"""Live 'tools' that give Jarvis real-world data the frozen LLM can't know:
current weather, the current date/time, and web search.

Every source here is free and needs NO API key:
  - Weather   : Open-Meteo (open-meteo.com)
  - Geocoding : Open-Meteo geocoding
  - Location  : ip-api.com (when no city is given)
  - Web search: DuckDuckGo via the `ddgs` package

The brain (brain.py) passes these to the model as callable tools, so the model
decides when to use them and we run them and feed the result back.
"""
import datetime
import json
import urllib.parse
import urllib.request

import config

_UA = {"User-Agent": "JarvisVoice/1.0"}

# The latest user request, so the weather tool can reject a city the model
# invented (small models sometimes pass a location the user never mentioned).
_USER_CONTEXT = ""


def set_user_context(text):
    global _USER_CONTEXT
    _USER_CONTEXT = text or ""

# Open-Meteo "WMO weather code" -> plain English
_WMO = {
    0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast",
    45: "fog", 48: "freezing fog", 51: "light drizzle", 53: "drizzle",
    55: "heavy drizzle", 56: "freezing drizzle", 57: "freezing drizzle",
    61: "light rain", 63: "rain", 65: "heavy rain", 66: "freezing rain",
    67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow",
    77: "snow grains", 80: "light showers", 81: "showers", 82: "violent showers",
    85: "snow showers", 86: "snow showers", 95: "thunderstorms",
    96: "thunderstorms with hail", 99: "thunderstorms with hail",
}


def _get_json(url, timeout=10):
    req = urllib.request.Request(url, headers=_UA)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _ip_city():
    """Best-effort current city from public IP (no key)."""
    try:
        d = _get_json("http://ip-api.com/json/?fields=status,city,lat,lon", timeout=5)
        if d.get("status") == "success":
            return d.get("city") or f"{d.get('lat')},{d.get('lon')}"
    except Exception:
        pass
    return None


def get_current_datetime(**kwargs):
    """Current local date and time."""
    return datetime.datetime.now().strftime(
        "It is %A, %B %-d, %Y, and the time is %-I:%M %p."
    )


def get_weather(**kwargs):
    """Current weather + today's forecast for a city (or the user's location)."""
    location = (kwargs.get("location") or kwargs.get("city")
                or kwargs.get("place") or "").strip()
    # Guard against the model inventing a city the user never said: only trust a
    # location that actually appears in the user's request; otherwise fall back
    # to the configured city or IP-based location.
    if location and _USER_CONTEXT and location.lower() not in _USER_CONTEXT.lower():
        location = ""
    if not location:
        location = (config.DEFAULT_CITY or _ip_city() or "").strip()
    if not location:
        return "I'm not sure which city you mean -- tell me a place and I'll check."

    fahrenheit = config.WEATHER_UNITS.lower().startswith("f")
    unit = "fahrenheit" if fahrenheit else "celsius"
    sym = "°F" if fahrenheit else "°C"

    try:
        geo = _get_json(
            "https://geocoding-api.open-meteo.com/v1/search?count=1&name="
            + urllib.parse.quote(location)
        )
    except Exception as exc:
        return f"I couldn't reach the weather service ({exc})."
    if not geo.get("results"):
        return f"I couldn't find a place called {location}."
    g = geo["results"][0]
    name = g["name"]
    country = g.get("country", "")
    try:
        wx = _get_json(
            f"https://api.open-meteo.com/v1/forecast?latitude={g['latitude']}"
            f"&longitude={g['longitude']}&timezone=auto&forecast_days=1"
            f"&temperature_unit={unit}"
            "&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
            "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        )
    except Exception as exc:
        return f"I couldn't reach the weather service ({exc})."

    cur = wx["current"]
    day = wx["daily"]
    desc = _WMO.get(cur.get("weather_code"), "unclear skies")
    where = f"{name}, {country}" if country else name
    return (
        f"In {where} it's {round(cur['temperature_2m'])}{sym} and {desc}, "
        f"feels like {round(cur['apparent_temperature'])}{sym}, "
        f"wind {round(cur['wind_speed_10m'])} kilometers per hour. "
        f"Today's high is {round(day['temperature_2m_max'][0])}{sym}, "
        f"low {round(day['temperature_2m_min'][0])}{sym}, with a "
        f"{day['precipitation_probability_max'][0]} percent chance of rain."
    )


def web_search(**kwargs):
    """Search the live web and return the top results to summarize."""
    query = (kwargs.get("query") or kwargs.get("q") or kwargs.get("search") or "").strip()
    if not query:
        return "I need something to search for."
    try:
        from ddgs import DDGS
    except ImportError:
        try:
            from duckduckgo_search import DDGS
        except ImportError:
            return "Web search isn't set up (the ddgs package isn't installed)."
    try:
        results = list(DDGS().text(query, max_results=5))
    except Exception as exc:
        return f"My web search failed ({exc})."
    if not results:
        return f"I found nothing online for '{query}'."
    lines = [f"Top web results for '{query}':"]
    for r in results[:5]:
        title = r.get("title", "").strip()
        body = r.get("body", "").strip()
        lines.append(f"- {title}: {body}")
    return "\n".join(lines)


# --- Tool schemas (OpenAI / Ollama format) ---------------------------------
SCHEMAS = [
    {"type": "function", "function": {
        "name": "get_weather",
        "description": ("Get the current weather and today's forecast for a city. "
                        "Use for any question about weather, temperature, rain, "
                        "wind, or how hot or cold it is."),
        "parameters": {"type": "object", "properties": {
            "location": {"type": "string",
                         "description": "City name, e.g. 'Toronto'. Omit to use the user's current location."}},
            "required": []}}},
    {"type": "function", "function": {
        "name": "web_search",
        "description": ("Search the live internet for current or recent information: "
                        "news, sports scores, prices, events, or anything that "
                        "changes over time or happened after your training data. "
                        "Summarize the results for the user."),
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "The search query."}},
            "required": ["query"]}}},
    {"type": "function", "function": {
        "name": "get_current_datetime",
        "description": ("Get the current local date and time. Use for any question "
                        "about what time it is, what day or date it is."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
]

_DISPATCH = {
    "get_weather": get_weather,
    "web_search": web_search,
    "get_current_datetime": get_current_datetime,
}


def run(name, args):
    """Execute a tool by name with a dict of arguments; always returns a string."""
    fn = _DISPATCH.get(name)
    if fn is None:
        return f"Unknown tool: {name}"
    try:
        return fn(**(args or {}))
    except Exception as exc:
        return f"The {name} tool failed: {exc}"
