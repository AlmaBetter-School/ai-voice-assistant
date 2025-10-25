#!/bin/bash
# Simple runner for AI Voice Assistant

python3 -m venv .venv
source .venv/bin/activate

pip install -r requirements.txt --quiet

python app.py
