#!/usr/bin/env python3
# ======================================================
# Voice + Text Conversational Assistant with Smart Task Flow (Gemini + n8n)
# Segregated into 4 layers: LISTENS, THINKS, TALKS, ACTS
# ======================================================

# --- Patch: Fix Gradio "bool schema" bug (prevents APIInfoParseError / TypeError in 4.41.x) ---
import importlib.util
def _apply_gradio_schema_patch():
    try:
        spec = importlib.util.find_spec("gradio_client.utils")
        if spec is None:
            return
        import gradio_client.utils as _gu

        if hasattr(_gu, "get_type"):
            _orig = _gu.get_type
            def _safe_get_type(schema):
                if isinstance(schema, bool):
                    return "Any"
                try:
                    return _orig(schema)
                except Exception:
                    return "Any"
            _gu.get_type = _safe_get_type

        if hasattr(_gu, "_json_schema_to_python_type"):
            _orig_json_to_type = _gu._json_schema_to_python_type
            def _safe_json_to_type(schema, defs=None):
                if isinstance(schema, bool):
                    return "Any"
                try:
                    return _orig_json_to_type(schema, defs)
                except Exception:
                    return "Any"
            _gu._json_schema_to_python_type = _safe_json_to_type
    except Exception as e:
        print("⚠️ Gradio schema patch failed:", e)
_apply_gradio_schema_patch()


# ======================================================
# Imports & Config
# ======================================================
import os
import io
import re
import json
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import List, Dict, Tuple, Optional

import gradio as gr
import requests
from dotenv import load_dotenv

load_dotenv()

# -------- App Config --------
TZ_NAME = os.getenv("TZ_NAME", "Asia/Kolkata")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
N8N_TASKS_WEBHOOK = os.getenv("N8N_TASKS_WEBHOOK", "")

# -------- Optional deps (STT / TTS / Gemini) --------
try:
    import speech_recognition as sr
    HAVE_SR = True
except Exception:
    HAVE_SR = False

try:
    from gtts import gTTS
    HAVE_TTS = True
except Exception:
    HAVE_TTS = False

try:
    import google.generativeai as genai
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
    HAVE_GEMINI = bool(GEMINI_API_KEY)
except Exception:
    HAVE_GEMINI = False


# ======================================================
# Shared small utils
# ======================================================
def now_tz() -> datetime:
    return datetime.now(ZoneInfo(TZ_NAME))

def format_iso_date(d: datetime) -> str:
    return d.strftime("%Y-%m-%d")

def parse_due_date_from_text(text: str, ref: Optional[datetime] = None) -> Optional[str]:
    """
    Focused, high-precision date catcher for common phrases:
    - today, tomorrow
    - explicit YYYY-MM-DD
    - month-name + day (e.g., Oct 26), returns current/next year sensibly
    - 'next <weekday>' or '<weekday>' (this/next)
    Returns ISO 'YYYY-MM-DD' or None.
    """
    if not text:
        return None
    t = text.lower().strip()
    ref = ref or now_tz()
    today = ref.date()
    tomorrow = (ref + timedelta(days=1)).date()

    # 1) direct
    if re.search(r"\btoday\b", t):
        return str(today)
    if re.search(r"\btomorrow\b", t):
        return str(tomorrow)

    # 2) ISO YYYY-MM-DD
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", t)
    if m:
        y, mo, d = m.groups()
        try:
            return str(datetime(int(y), int(mo), int(d)).date())
        except Exception:
            pass

    # 3) Month-name Day (e.g., Oct 26, October 5)
    months = {
        "jan":1,"january":1,"feb":2,"february":2,"mar":3,"march":3,"apr":4,"april":4,
        "may":5,"jun":6,"june":6,"jul":7,"july":7,"aug":8,"august":8,"sep":9,"sept":9,
        "september":9,"oct":10,"october":10,"nov":11,"november":11,"dec":12,"december":12
    }
    m2 = re.search(r"\b([a-z]{3,9})\s+(\d{1,2})\b", t)
    if m2:
        mon_name, day = m2.groups()
        mon = months.get(mon_name[:3], None) or months.get(mon_name, None)
        if mon:
            year = ref.year
            try:
                cand = datetime(year, mon, int(day)).date()
            except Exception:
                cand = None
            if cand:
                if cand < today:
                    try:
                        cand_next = datetime(year + 1, mon, int(day)).date()
                        return str(cand_next)
                    except Exception:
                        return str(cand)
                return str(cand)

    # 4) Weekdays: <weekday> or next <weekday>
    weekdays = ["monday","tuesday","wednesday","thursday","friday","saturday","sunday"]
    wd_index = {w:i for i,w in enumerate(weekdays)}
    m3 = re.search(r"\b(next\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", t)
    if m3:
        nxt, wd = m3.groups()
        target = wd_index[wd]
        today_idx = today.weekday()  # Monday=0
        delta = (target - today_idx) % 7
        if delta == 0:
            delta = 7  # same weekday => next week
        if nxt:
            # force next week
            if delta <= 7:
                delta += 7 if delta == 0 else 7
        due = today + timedelta(days=delta)
        return str(due)

    return None

# ======================================================
# 🎧 LISTENS — capture & transcribe input
# ======================================================
def transcribe_if_needed(mic_path: Optional[str]) -> str:
    """
    Gradio Microphone(type='filepath') returns a path to an audio file.
    Guard: ensure it's a file (not a dir), else return "".
    """
    if not (HAVE_SR and mic_path):
        return ""
    try:
        if not os.path.isfile(mic_path):  # avoid IsADirectoryError
            return ""
        rec = sr.Recognizer()
        with sr.AudioFile(mic_path) as src:
            audio = rec.record(src)
        return rec.recognize_google(audio)
    except Exception:
        return ""


# ======================================================
# 🧠 THINKS — parse dates & reason with Gemini
# ======================================================


GEMINI_MODEL_CANDIDATES = [
    "gemini-1.5-flash",
    "gemini-1.5-flash-8b",
    "gemini-2.0-flash-exp",
]

SMART_NOTES_STYLE = """
- Write what the user needs to do or remember. Be specific and helpful.
- Examples: 
  - "Prepare ingredients and cook Biryani. Include marination, rice boiling, and final layering."
  - "Restock essentials: milk, eggs, vegetables, fruits. Check spice inventory."
  - "Draft 5 slides for Monday meeting: agenda, metrics, highlights, blockers, next steps."
"""

def _conversation_text(turns):
    out = []
    for t in turns[-12:]:
        role = "User" if t["role"] == "user" else "Assistant"
        out.append(f"{role}: {t['content']}")
    return "\n".join(out)

def ask_gemini(turns: List[Dict[str, str]]) -> Dict[str, any]:
    """
    Chats with Gemini. If a task should be created, it returns a JSON with task fields.
    Now produces SMART, CONTEXTUAL notes for the task using the conversation.
    """
    if not HAVE_GEMINI:
        return {
            "response": "Gemini is not configured. Set GEMINI_API_KEY.",
            "task": {"enabled": False, "title": "", "due": "", "notes": ""}
        }

    now = datetime.now(ZoneInfo(TZ_NAME))
    today_iso = now.strftime("%Y-%m-%d")
    tomorrow_iso = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    convo_text = _conversation_text(turns)

    system = f"""
You are a warm, concise assistant. You chat naturally AND also detect when a task should be created.

WHEN to create a task:
- The user clearly wants to remember, schedule, or follow up on something (e.g., “remind me”, “schedule”, “I should”, “let’s do tomorrow”, “add to list”).
- Or there’s an obvious next step that helps them (but avoid being too eager).

DUE DATE INTERPRETATION (local tz={TZ_NAME}, today={today_iso}, tomorrow={tomorrow_iso}):
- “today” => {today_iso}
- “tomorrow” => {tomorrow_iso}
- “this <weekday>” => next occurrence this calendar week (if passed, next week)
- “next <weekday>” => weekday in the next week
- explicit dates (“Oct 26”, “2025-10-26”) => normalize to YYYY-MM-DD
- If not clear, leave due="" and ask ONE brief follow-up question for the date.

NOTES:
- Generate intelligent, actionable notes using the following style:
{SMART_NOTES_STYLE}

OUTPUT: Return STRICT JSON with keys: response (string), task (object).
Schema:
{{
  "response": "assistant chat reply",
  "task": {{
      "enabled": bool,
      "title": "≤ 8 words, imperative or short noun phrase",
      "due": "YYYY-MM-DD or empty string",
      "notes": "smart notes text per the style"
  }}
}}
Only output JSON. No markdown fences.
If a task is ready to be created but not yet confirmed,
say something like:
"I’ve prepared this task — [Title] due [Date]. Here’s what I plan to include in the notes: [short summary].
Should I save it?"
Always include a concise preview of the generated notes when confirming.
Keep confirmations natural and friendly, suitable for TTS.
"""

    user_instruction = """
Based on the latest user intent in the conversation, decide:
- response: a friendly assistant reply that continues the chat.
- task: If a task is appropriate, set enabled=true, craft a helpful title, parse due date from the chat if present,
        and generate SMART notes (see style). If date uncertain, due="".

If user says things like “revise maths tomorrow focus on algebra -> title could be “Revise algebra – maths,
due=tomorrow, and notes should include top algebra topics + 5-7 practice questions and a short checklist.
"""

    prompt = system + "\n\nCONVERSATION:\n" + convo_text + "\n\n" + user_instruction

    model = genai.GenerativeModel("models/gemini-2.0-flash-exp")
    result = model.generate_content(
        prompt,
        generation_config={"response_mime_type": "application/json"}
    )
    raw = (result.text or "").strip()

    # Be tolerant of minor formatting issues
    try:
        data = json.loads(raw)
    except Exception:
        try:
            start = raw.find("{")
            end = raw.rfind("}")
            data = json.loads(raw[start:end+1]) if start != -1 and end != -1 else {
                "response": raw,
                "task": {"enabled": False, "title": "", "due": "", "notes": ""}
            }
        except Exception:
            data = {"response": raw, "task": {"enabled": False, "title": "", "due": "", "notes": ""}}

    # enforce shape
    data.setdefault("response", "")
    data.setdefault("task", {})
    data["task"].setdefault("enabled", False)
    data["task"].setdefault("title", "")
    data["task"].setdefault("due", "")
    data["task"].setdefault("notes", "")
    return data


# ======================================================
# 💬 TALKS — chat messages & speech output
# ======================================================
def tts_to_tempfile(text: str) -> Optional[str]:
    if not (HAVE_TTS and text and text.strip()):
        return None
    try:
        mp3 = io.BytesIO()
        gTTS(text=text, lang="en").write_to_fp(mp3)
        mp3.seek(0)
        fd, tmp = tempfile.mkstemp(suffix=".mp3")
        with os.fdopen(fd, "wb") as f:
            f.write(mp3.read())
        return tmp
    except Exception:
        return None

def build_thinking_message() -> Dict[str, str]:
    return {"role": "assistant", "content": "…thinking…"}

def replace_last_assistant_with(text: str, messages: List[Dict[str, str]]) -> List[Dict[str, str]]:
    # Replace last assistant message (the thinking placeholder) with final text.
    for i in range(len(messages)-1, -1, -1):
        if messages[i]["role"] == "assistant":
            messages[i]["content"] = text
            return messages
    messages.append({"role": "assistant", "content": text})
    return messages

def normalize_affirmative(s: str) -> bool:
    return bool(re.search(r"\b(yes|yep|yeah|sure|do it|please|go ahead|sounds good|ok|okay)\b", s.strip().lower()))

def normalize_negative(s: str) -> bool:
    return bool(re.search(r"\b(no|nah|don’t|dont|stop|cancel|not now)\b", s.strip().lower()))


# ======================================================
# ⚙️ ACTS — perform actions (n8n / Google Tasks)
# ======================================================
def push_task_to_n8n(title: str, due_iso: str, notes: str) -> Tuple[bool, str]:
    """
    Flat JSON body:
    {
      "title": "...",
      "due": "YYYY-MM-DD",
      "notes": "...",
      "timestamp": ISO8601
    }
    """
    payload = {
        "title": title.strip(),
        "due": due_iso.strip(),
        "notes": notes.strip(),
        "timestamp": datetime.utcnow().isoformat()
    }
    if not N8N_TASKS_WEBHOOK:
        return False, f"(mock) Would POST to n8n with: {json.dumps(payload, ensure_ascii=False)}"
    try:
        r = requests.post(N8N_TASKS_WEBHOOK, json=payload, timeout=10)
        ok = r.status_code >= 200 and r.status_code < 300
        return ok, (r.text or "")
    except Exception as e:
        return False, f"Request failed: {e}"


# ======================================================
# Orchestrator — ties LISTENS, THINKS, TALKS, ACTS
# ======================================================
def handle_interaction(user_text: str, mic_path: str,
                       history: List[Dict[str, str]],
                       auto_tts: bool,
                       pending: Dict) -> Tuple[List[Dict[str, str]], Optional[str], Dict]:
    """
    Returns: new_history (messages list[{'role','content'}]), tts_path, new_pending_state
    pending state fields:
      - awaiting_due: bool
      - awaiting_confirm: bool
      - topic_key: str (hash of title)
      - draft_task: {'title','notes','due'}  (due may be '')
    """
    tts_path = None
    ref_now = now_tz()

    # 1) LISTENS - Input routing (voice first if text empty)
    msg = (user_text or "").strip()
    voice_used = False
    if not msg and mic_path:
        transcript = transcribe_if_needed(mic_path)
        if transcript:
            msg = transcript
            voice_used = True

    if not msg:
        return history, None, pending

    # 2) THINKS - due-date follow-up (awaiting date only)
    if pending.get("awaiting_due") and not pending.get("awaiting_confirm"):
        guessed = parse_due_date_from_text(msg, ref_now)
        if not guessed:
            history += [{"role": "user", "content": msg},
                        {"role": "assistant", "content": "What date should I set for this?"}]
            if auto_tts:
                tts_path = tts_to_tempfile("What date should I set for this?")
            return history, tts_path, pending

        pending["draft_task"]["due"] = guessed
        pending["awaiting_due"] = False
        pending["awaiting_confirm"] = True

        title = pending["draft_task"]["title"]
        notes = pending["draft_task"]["notes"]

        # TALKS - confirmation (with notes preview)
        prompt = (
            f"I can add **{title}** for {guessed}.\n\n"
            f"🧠 **Notes Preview:**\n{(notes or '(none)')[:300]}...\n\n"
            "Should I save it?"
        )
        history += [{"role": "user", "content": msg},
                    {"role": "assistant", "content": prompt}]
        if auto_tts:
            tts_path = tts_to_tempfile(
                f"I can add {title} for {guessed}. Here’s a quick summary of the notes: "
                f"{notes[:200] if notes else 'no notes'}. Should I save it?"
            )
        return history, tts_path, pending

    # 3) THINKS/ACTS - confirmation stage
    if pending.get("awaiting_confirm"):
        title = pending["draft_task"]["title"].strip()
        notes = pending["draft_task"]["notes"].strip()
        due = pending["draft_task"]["due"]

        if normalize_negative(msg):
            history += [{"role": "user", "content": msg},
                        {"role": "assistant", "content": "Okay, I won’t add it."}]
            pending.clear()
            return history, tts_to_tempfile("Okay, I won’t add it.") if auto_tts else None, pending

        if normalize_affirmative(msg):
            ok, resp = push_task_to_n8n(title, due, notes)
            if ok:
                say = (
                    f"✅ Done! I’ve added **{title}** for {due or 'upcoming days'}.\n"
                    f"🧠 Notes saved:\n{notes[:300]}..."
                )
                if auto_tts:
                    tts_text = (
                        f"I've added your task {title}, due {due or 'soon'}. "
                        f"It includes notes like: {notes[:150]}."
                    )
                    tts_path = tts_to_tempfile(tts_text)
            else:
                say = f"Hmm, I couldn’t save it right now. {resp if resp else ''}".strip()
                if auto_tts:
                    tts_path = tts_to_tempfile(say)

            history += [{"role": "user", "content": msg},
                        {"role": "assistant", "content": say}]
            pending.clear()
            return history, tts_path, pending
        # else: fall through to normal chat

    # 4) THINKS - regular chat (LLM)
    history.append({"role": "user", "content": msg})
    history.append(build_thinking_message())

    gem = ask_gemini(history)

    task = gem.get("task", {})
    task_enabled = bool(task.get("enabled", False))
    due_raw = task.get("due_raw", "") or ""
    title = (task.get("title", "") or "").strip()
    notes = (task.get("notes", "") or "").strip()

    due_iso = parse_due_date_from_text(due_raw, ref_now) if due_raw else None
    needs_due = bool(gem.get("needs_due", False)) or (task_enabled and not due_iso)

    reply_text = (gem.get("response") or "").strip()
    history = replace_last_assistant_with(reply_text or "Okay.", history)

    # 5) ACTS - propose task if helpful
    if task_enabled and title and notes:
        pending = pending or {}
        pending["draft_task"] = {"title": title, "notes": notes, "due": due_iso or ""}
        pending["topic_key"] = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")

        if needs_due:
            ask = f"When should I set **{title}**?"
            history.append({"role": "assistant", "content": ask})
            pending["awaiting_due"] = True
            pending["awaiting_confirm"] = False
            if HAVE_TTS and auto_tts:
                tts_path = tts_to_tempfile(f"When should I set {title}?")
        else:
            ask = (
                f"I can add **{title}** for {pending['draft_task']['due']}.\n\n"
                f"🧠 **Notes Preview:**\n{(notes or '(none)')[:300]}...\n\n"
                "Should I save it?"
            )
            history.append({"role": "assistant", "content": ask})
            pending["awaiting_due"] = False
            pending["awaiting_confirm"] = True
            if HAVE_TTS and auto_tts:
                tts_path = tts_to_tempfile(
                    f"I can add {title} for {pending['draft_task']['due']}. "
                    f"Here’s a quick summary of the notes: {notes[:200]}. Should I save it?"
                )
    else:
        if HAVE_TTS and auto_tts and reply_text:
            tts_path = tts_to_tempfile(reply_text)

    return history, tts_path, pending


# ======================================================
# UI — minimal, ChatGPT-like
# ======================================================
CUSTOM_CSS = """
/* Keep classic neutral look similar to ChatGPT */
body { font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; }
.gradio-container { max-width: 820px !important; margin: auto !important; }
.gr-chatbot { border-radius: 14px !important; background: #fff !important; box-shadow: 0 2px 8px rgba(0,0,0,0.05); }
.gr-textbox textarea { font-size: 15px !important; border-radius: 10px !important; }
button { border-radius: 10px !important; }
.small-hint { font-size: 12px; color: #666; margin-top: -8px; margin-bottom: 6px; }
"""

with gr.Blocks(css=CUSTOM_CSS, title="AI Chat Assistant") as demo:
    gr.Markdown("<h3 style='text-align:center;margin-top:8px;'>💬 Chat with your AI Assistant</h3>")

    chatbot = gr.Chatbot(type="messages", height=520)
    history_state = gr.State(value=[])     # list[{'role','content'}]
    pending_state = gr.State(value={})     # {'awaiting_due','awaiting_confirm','topic_key','draft_task':{...}}

    auto_tts_toggle = gr.Checkbox(value=True, label="🔊 Speak replies automatically")

    # Row 1: Voice input
    gr.Markdown("<div class='small-hint'>Voice</div>")
    with gr.Row():
        mic = gr.Microphone(label="🎤 Record", type="filepath", show_label=False, interactive=True)

    # Row 2: Text input + Send button
    gr.Markdown("<div class='small-hint'>Text</div>")
    with gr.Row():
        user_input = gr.Textbox(placeholder="Type your message…", scale=5, show_label=False)
        send_btn = gr.Button("Send", variant="primary", scale=1)

    # Audio output (autoplay with controls)
    audio_out = gr.Audio(label="Voice", autoplay=True, interactive=False, show_download_button=False)

    # Event wiring
    def on_send(txt, mic_path, history, auto_tts, pending):
        try:
            new_history, tts_path, new_pending = handle_interaction(txt, mic_path, history, auto_tts, pending)
            return new_history, None if not tts_path else tts_path, new_history, new_pending, ""
        except Exception as e:
            err = f"Sorry—something broke: {type(e).__name__}: {e}"
            history = history + [{"role":"assistant","content": err}]
            tts_path = tts_to_tempfile("Sorry, something went wrong.") if auto_tts else None
            return history, tts_path, history, pending, ""

    user_input.submit(
        on_send,
        [user_input, mic, history_state, auto_tts_toggle, pending_state],
        [chatbot, audio_out, history_state, pending_state, user_input]
    )
    send_btn.click(
        on_send,
        [user_input, mic, history_state, auto_tts_toggle, pending_state],
        [chatbot, audio_out, history_state, pending_state, user_input]
    )

    mic.stop_recording(
        on_send,
        [user_input, mic, history_state, auto_tts_toggle, pending_state],
        [chatbot, audio_out, history_state, pending_state, user_input]
    )

if __name__ == "__main__":
    demo.launch(server_name="127.0.0.1", server_port=7890, share=True)
