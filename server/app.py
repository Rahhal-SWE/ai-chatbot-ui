from __future__ import annotations

import os
from datetime import datetime
from typing import Optional

import pytz
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai

# =========================
# Config
# =========================
MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")

# =========================
# Gemini client (lazy init)
# =========================
_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """
    Lazy-init Gemini client so importing this module doesn't require an API key.
    This fixes CI "smoke import" failures.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY (or GOOGLE_API_KEY). Set it in your environment.")

    _client = genai.Client(api_key=api_key)
    return _client


# =========================
# Live data helpers
# =========================
_weather_cache = {"ts": 0.0, "value": None}


def ireland_time_now() -> str:
    tz = pytz.timezone("Europe/Dublin")
    now = datetime.now(tz)
    return now.strftime("%A, %d %B %Y %H:%M (%Z)")


def galway_weather_now() -> str:
    import time

    # Galway city approx coordinates
    lat, lon = 53.2707, -9.0568

    now = time.time()
    if _weather_cache["value"] is not None and (now - _weather_cache["ts"] < 60):
        return _weather_cache["value"]

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,precipitation,wind_speed_10m",
        "timezone": "Europe/Dublin",
    }

    r = requests.get(url, params=params, timeout=10)
    r.raise_for_status()
    data = r.json()

    cur = data.get("current") or {}
    t = cur.get("temperature_2m")
    w = cur.get("wind_speed_10m")
    p = cur.get("precipitation")

    if t is None or w is None or p is None:
        raise RuntimeError(f"Missing fields in Open-Meteo response: {cur}")

    # round for clean output
    t = round(float(t), 1)
    w = round(float(w), 1)
    p = round(float(p), 2)

    result = f"location=Galway temperature_c={t} wind_kmh={w} precipitation_mm={p}"
    _weather_cache["ts"] = now
    _weather_cache["value"] = result
    return result


def build_prompt_with_live_data(user_msg: str) -> str:
    """
    Inject verified live data for time/weather questions.
    Strong prompt: do not hallucinate missing facts.
    """
    lower = user_msg.lower()
    tool_info = ""

    # time triggers
    if "time" in lower and ("galway" in lower or "ireland" in lower):
        tool_info += f"Ireland time now: {ireland_time_now()}\n"

    # weather triggers
    if "weather" in lower and ("galway" in lower or "ireland" in lower):
        try:
            tool_info += f"Live weather: {galway_weather_now()}\n"
        except Exception as e:
            tool_info += f"Live weather: (unavailable: {str(e).replace(chr(10), ' ')})\n"

    if not tool_info:
        return user_msg

    return (
        "You are a helpful assistant. "
        "You MUST use only the LIVE_DATA below for time/weather facts. "
        "If LIVE_DATA is missing something the user asked for, say you don't have it.\n\n"
        f"LIVE_DATA:\n{tool_info}\n"
        f"USER_QUESTION: {user_msg}\n"
        "Answer clearly in 1-4 sentences."
    )


# =========================
# Flask app
# =========================
# Serve the UI (index.html, script.js, style.css) from repo root:
# repo/
#   index.html
#   script.js
#   style.css
#   server/app.py
app = Flask(__name__, static_folder="..", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})


@app.get("/")
def index():
    return send_from_directory("..", "index.html")


@app.get("/api/health")
def health():
    return jsonify({"status": "ok"})


# Silence Chrome devtools probe spam
@app.get("/.well-known/appspecific/com.chrome.devtools.json")
def chrome_devtools_noise():
    return ("", 204)


@app.post("/api/chat")
def chat_once():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Missing 'message'"}), 400

    prompt = build_prompt_with_live_data(user_msg)

    try:
        client = get_gemini_client()
        resp = client.models.generate_content(model=MODEL, contents=prompt)
        return jsonify({"reply": resp.text or ""})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.post("/api/chat/stream")
def chat_stream():
    data = request.get_json(silent=True) or {}
    user_msg = (data.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Missing 'message'"}), 400

    prompt = build_prompt_with_live_data(user_msg)

    def sse():
        try:
            client = get_gemini_client()
            for chunk in client.models.generate_content_stream(model=MODEL, contents=prompt):
                text = getattr(chunk, "text", None)
                if text:
                    yield f"data: {text}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            msg = str(e).replace("\n", " ")
            yield f"data: [ERROR] {msg}\n\n"
            yield "data: [DONE]\n\n"

    return Response(sse(), mimetype="text/event-stream")


if __name__ == "__main__":
    # For local dev only (Render/production should use gunicorn)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=True)
