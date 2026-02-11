from __future__ import annotations

import os
from datetime import datetime

import pytz
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai

# Serve UI from repo root (index.html, script.js, style.css)
app = Flask(__name__, static_folder="..", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})

_client = None

def get_gemini_client() -> genai.Client:
    """
    Create Gemini client lazily so imports don't fail in CI.
    Requires GEMINI_API_KEY in environment.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("Missing GEMINI_API_KEY environment variable")

    _client = genai.Client(api_key=api_key)
    return _client


# --- Simple weather helper (Open-Meteo is free) ---
_weather_cache = {"ts": 0.0, "value": None}

def get_galway_time_and_weather() -> dict:
    tz = pytz.timezone("Europe/Dublin")
    now = datetime.now(tz)

    # Galway coordinates
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": 53.2707,
        "longitude": -9.0568,
        "current": "temperature_2m,precipitation,wind_speed_10m",
        "timezone": "Europe/Dublin",
    }

    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current") or {}
        return {
            "time": now.strftime("%A, %d %B %Y %H:%M (%Z)"),
            "temperature_c": cur.get("temperature_2m"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "precip_mm": cur.get("precipitation"),
        }
    except Exception:
        # Still return time even if weather fails
        return {
            "time": now.strftime("%A, %d %B %Y %H:%M (%Z)"),
            "temperature_c": None,
            "wind_kmh": None,
            "precip_mm": None,
        }


@app.get("/api/health")
def health():
    # Always works even with no key (important for CI)
    return jsonify({"status": "ok"})


@app.get("/")
def root():
    return send_from_directory("..", "index.html")


@app.post("/api/chat")
def chat():
    payload = request.get_json(silent=True) or {}
    user_msg = (payload.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Missing 'message'"}), 400

    # Add your “Galway time/weather” tool info into prompt
    tw = get_galway_time_and_weather()
    tool_context = (
        f"Galway time now: {tw['time']}\n"
        f"Weather: temp={tw['temperature_c']}C wind={tw['wind_kmh']}km/h precip={tw['precip_mm']}mm\n"
    )

    try:
        client = get_gemini_client()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

    prompt = f"{tool_context}\nUser: {user_msg}\nAssistant:"

    resp = client.models.generate_content(model=model, contents=prompt)
    text = getattr(resp, "text", None) or str(resp)

    return jsonify({"reply": text})


@app.post("/api/chat/stream")
def chat_stream():
    payload = request.get_json(silent=True) or {}
    user_msg = (payload.get("message") or "").strip()
    if not user_msg:
        return jsonify({"error": "Missing 'message'"}), 400

    tw = get_galway_time_and_weather()
    tool_context = (
        f"Galway time now: {tw['time']}\n"
        f"Weather: temp={tw['temperature_c']}C wind={tw['wind_kmh']}km/h precip={tw['precip_mm']}mm\n"
    )

    try:
        client = get_gemini_client()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 500

    model = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")
    prompt = f"{tool_context}\nUser: {user_msg}\nAssistant:"

    def generate():
        # SSE (Server-Sent Events)
        try:
            stream = client.models.generate_content_stream(model=model, contents=prompt)
            for chunk in stream:
                t = getattr(chunk, "text", "")
                if t:
                    yield f"data: {t}\n\n"
        except Exception as e:
            yield f"data: [ERROR] {str(e)}\n\n"

    return Response(generate(), mimetype="text/event-stream")
