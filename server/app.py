from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, Generator, Optional

import pytz
import requests
from flask import Flask, Response, jsonify, request, send_from_directory
from flask_cors import CORS
from google import genai

# -----------------------------
# Flask setup
# -----------------------------
# Repo layout:
# repo/
#   index.html
#   script.js
#   style.css
#   server/
#     __init__.py
#     app.py
#
# Serve UI files from repo root ("..")
app = Flask(__name__, static_folder="..", static_url_path="")
CORS(app, resources={r"/api/*": {"origins": "*"}})

# -----------------------------
# Config
# -----------------------------
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.0-flash")
GALWAY_LAT = 53.2707
GALWAY_LON = -9.0568
GALWAY_TZ = "Europe/Dublin"

# -----------------------------
# Lazy Gemini client (IMPORTANT for CI)
# -----------------------------
_client: Optional[genai.Client] = None


def get_gemini_client() -> genai.Client:
    """
    Create Gemini client lazily. This prevents CI from failing on `import server.app`
    when no API key exists in the environment.
    """
    global _client
    if _client is not None:
        return _client

    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        # Don't crash on import; only raise when an endpoint actually needs Gemini.
        raise RuntimeError("Missing GEMINI_API_KEY environment variable.")

    _client = genai.Client(api_key=api_key)
    return _client


# -----------------------------
# Weather helper (Open-Meteo) with tiny cache
# -----------------------------
_weather_cache: Dict[str, Any] = {"ts": 0.0, "value": None}


def get_galway_time_weather() -> Dict[str, Any]:
    """
    Returns Galway local time + current weather via Open-Meteo.
    Cached for 60s to reduce calls.
    """
    now = time.time()
    if _weather_cache["value"] is not None and (now - _weather_cache["ts"] < 60):
        return _weather_cache["value"]

    tz = pytz.timezone(GALWAY_TZ)
    local_now = datetime.now(tz)

    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": GALWAY_LAT,
        "longitude": GALWAY_LON,
        "current": "temperature_2m,precipitation,wind_speed_10m",
        "timezone": GALWAY_TZ,
    }

    weather: Dict[str, Any] = {}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()
        cur = data.get("current") or {}
        weather = {
            "temperature_c": cur.get("temperature_2m"),
            "precip_mm": cur.get("precipitation"),
            "wind_kmh": cur.get("wind_speed_10m"),
            "obs_time": cur.get("time"),
        }
    except Exception:
        weather = {"error": "weather_fetch_failed"}

    result = {
        "city": "Galway",
        "timezone": GALWAY_TZ,
        "local_time": local_now.strftime("%A, %d %B %Y %H:%M (%Z)"),
        "weather": weather,
    }

    _weather_cache["ts"] = now
    _weather_cache["value"] = result
    return result


def maybe_handle_time_weather(user_text: str) -> Optional[str]:
    """
    If user asks about Galway time/weather, answer directly (no Gemini call).
    """
    t = user_text.lower()
    if "galway" in t and ("weather" in t or "time" in t):
        info = get_galway_time_weather()
        w = info["weather"]
        if "error" in w:
            return (
                f"The time in Galway is {info['local_time']}. "
                f"I couldn’t fetch live weather right now."
            )

        return (
            f"The time in Galway is {info['local_time']}. "
            f"Current weather: {w.get('temperature_c')}°C, "
            f"wind {w.get('wind_kmh')} km/h, precipitation {w.get('precip_mm')} mm."
        )
    return None


# -----------------------------
# Routes: UI
# -----------------------------
@app.get("/")
def index() -> Any:
    return send_from_directory("..", "index.html")


@app.get("/<path:path>")
def static_files(path: str) -> Any:
    return send_from_directory("..", path)


# -----------------------------
# Routes: API
# -----------------------------
@app.get("/api/health")
def health() -> Any:
    return jsonify({"status": "ok"})


@app.post("/api/chat")
def chat() -> Any:
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return jsonify({"reply": "Send a message, genius."}), 400

    # Fast-path: Galway time/weather
    direct = maybe_handle_time_weather(message)
    if direct is not None:
        return jsonify({"reply": direct})

    try:
        client = get_gemini_client()
    except RuntimeError as e:
        return jsonify({"reply": str(e)}), 500

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=message,
    )
    return jsonify({"reply": response.text or ""})


@app.post("/api/chat/stream")
def chat_stream() -> Response:
    payload = request.get_json(silent=True) or {}
    message = (payload.get("message") or "").strip()
    if not message:
        return Response("data: Missing message\n\n", mimetype="text/event-stream")

    # Fast-path: Galway time/weather (still streamed so UI behaves)
    direct = maybe_handle_time_weather(message)
    if direct is not None:

        def _direct_stream() -> Generator[str, None, None]:
            yield f"data: {direct}\n\n"
            yield "data: [DONE]\n\n"

        return Response(_direct_stream(), mimetype="text/event-stream")

    def _stream() -> Generator[str, None, None]:
        # If key missing, stream the error nicely.
        try:
            client = get_gemini_client()
        except RuntimeError as e:
            yield f"data: {str(e)}\n\n"
            yield "data: [DONE]\n\n"
            return

        # Gemini streaming
        for chunk in client.models.generate_content_stream(
            model=GEMINI_MODEL,
            contents=message,
        ):
            if chunk.text:
                # Keep it simple: plain text SSE chunks
                yield f"data: {chunk.text}\n\n"

        yield "data: [DONE]\n\n"

    return Response(_stream(), mimetype="text/event-stream")


if __name__ == "__main__":
    # Run dev server
    app.run(host="0.0.0.0", port=5000, debug=True)
