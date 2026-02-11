## AI Chatbot UI (Flask + Gemini + Live Weather)

Simple chat UI with a Flask backend that supports streaming responses.
For time/weather questions, the backend injects live data:
- Time: Europe/Dublin
- Weather: Open-Meteo (Galway coordinates), cached for 60 seconds

### Run locally
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

export GEMINI_API_KEY="YOUR_KEY"
python3 server/app.py
