# 🎙️ AI Voice Assistant

A simple yet powerful **voice + text conversational assistant** built using **Gemini AI** and **n8n**.  
It listens to your voice, understands your intent, and automatically creates tasks — all from a beautiful chat interface.

This project helps you learn how to connect **AI reasoning**, **automation workflows**, and **voice interaction** in one real-world use case.

---

## 🧩 Features

- 🎤 **Voice Recording** – Record your voice directly in the browser  
- 🗣️ **Speech-to-Text** – Converts speech to text using Google Speech Recognition  
- 🤖 **Gemini AI Integration** – Understands your intent and creates contextual tasks  
- ⚡ **n8n Integration** – Executes task automation workflows  
- 🔊 **Text-to-Speech** – Speaks responses using gTTS  
- 💬 **Conversational UI** – Chat-style interface with both mic and text input  
- ✅ **Smart Confirmation** – Asks before performing any real action  



---
# ⚙️ Setup Guide  

Follow these simple steps to set up and run the **AI Voice Assistant** project locally on your system — whether you’re on **Windows**, **macOS**, or **Linux**.

---

## 🧩 1️⃣ Install Git (If Not Already Installed)  

Before cloning the project, make sure **Git** is installed on your system.

### 🪟 For Windows:  
- Visit [https://git-scm.com/downloads](https://git-scm.com/downloads)  
- Download and install Git using the setup wizard (keep default settings).  

### 🍎 For macOS/Linux:  
Open **Terminal** and type:  
```bash
git --version
```

If Git isn’t found, install it using:

```bash
# macOS
brew install git

# Ubuntu/Linux
sudo apt install git
```
## 💻 2️⃣ Open Your IDE & Terminal

Open your preferred IDE (e.g., VS Code, PyCharm, or any other code editor).

Inside your IDE, open the Terminal or Command Prompt window.

### Clone the Repository

Open your terminal and run:

```bash
git clone https://github.com/yourusername/ai-voice-assistant.git
cd ai-voice-assistant
```


This downloads the project folder to your system.

---

### 3️⃣ Set Up Gemini API Key

To use the assistant, you’ll need to connect it with **Google Gemini AI** using an API key.


#### 🔹 Steps to get your API key:

1. Visit <a href="https://aistudio.google.com/api-keys" target="_blank">**Google AI Studio**</a>  
2. Sign in with your Google account  
3. Click **“Create API Key”**  
4. Copy the generated API key — you’ll need to add it to your environment file in the next step  

🎥 Need help? Watch this short setup guide:  
<a href="https://www.loom.com/share/81f9cef408c449ccbc5977fd06bff818" target="_blank">**Video Guidelines**</a>

💡 **Keep your API key private.**  
Never share it publicly or upload it to GitHub repositories.

---

### Add Your Gemini Key to the `.env.example` File

Your `.env.example` file includes placeholders for all required environment variables.  
You’ll **copy this file** (don’t move it) and then update the fields.

#### 🧩 Copy the example file:
```bash
cp .env.example .env
```


---

### Configure n8n (Google Tasks Workflow Only)

You’ll create a simple **n8n workflow** that receives tasks from the AI Assistant and adds them to your **Google Tasks** account.

---

#### ✅ Google Tasks Workflow

**🎯 Goal:**  
Add or list tasks when you say something like:  
> “Remind me to call John tomorrow.”

---

#### 🪜 Steps to Create the Workflow

1. **Create a new Webhook node**
   - Set the **Path** to:
     ```
     /webhook/tasks
     ```

2. **Add a Google Tasks node**
   - Set the **Operation** to:
     ```
     Create Task
     ```

3. **Map these fields in the Google Tasks node:**
   ```json
   Title: {{ $json.parameters.title }}
   Due: {{ $json.parameters.due_date }}T00:00:00.000Z
   Notes: {{ $json.parameters.notes }}
    ```
🌐 Add Production Webhook URL to .env.example
Once your workflow is created and deployed, copy the Production Webhook URL from n8n and add it to your .env.example file as shown below:
 ```
bash
Copy code
N8N_TASKS_WEBHOOK=https://your-n8n-instance-url/webhook/tasks
 ```
💡 Tip: Keep your .env.example file updated so new developers know which environment variables are required.

---

### 4️⃣ Copy and Update the `.env.example` File

We’ve included an example environment file to make setup easier.  
You just need to **copy** it (not move it) and then update it with your actual keys and links.

#### 🪜 Steps:

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```
---

2. **Run the App**

Use the included **`run.sh`** script to set up and launch the assistant in one simple step.

#### 🧩 Run the command:
```bash
bash run.sh
```

---

## 🚀 Getting Started

Once the application starts, open the link shown in your terminal (usually):
👉 [http://127.0.0.1:7890](http://127.0.0.1:7890)

Open it in your browser to access the chat interface where you can speak or type messages.

## 🎯 Example Commands

### 📝 Tasks
- "Remind me to call John tomorrow."
- "Add a task to review the project report."

### 💬 General Conversation
- "Hello, how are you?"
- "Tell me a joke."

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Mic not recording | Allow microphone access in your browser |
| Speech not recognized | Ensure your internet is working and speak clearly |
| Gemini not responding | Check your API key and internet connection |
| n8n error | Verify webhook URLs and workflow status |
| Wrong timezone | Update `TZ_NAME` in `.env` file |

## 🛠️ Tech Stack

| Feature | Technology |
|---------|------------|
| Frontend | Gradio |
| Reasoning & Chat | Gemini AI |
| Voice Input | Google SpeechRecognition |
| Voice Output | gTTS |
| Task Automation | n8n Webhooks |
| Environment | Python 3.9+ |
