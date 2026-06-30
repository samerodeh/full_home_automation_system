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
from reminders import reminders
from media import quran_player

_UA = {"User-Agent": "JarvisVoice/1.0"}  # some endpoints reject a blank UA

# Spoken day names (and common abbreviations) -> Python weekday() index, Mon=0.
# Used to turn "every tuesday and thursday" into concrete weekday numbers.
_DAY_MAP = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}


def _parse_recurrence(text, due_dt=None):
    """Convert a recurrence description string into a {days, time} dict, or None."""
    if not text:
        return None
    t = text.lower().strip()
    # Recurrence reuses the first occurrence's clock time; default to 09:00 if
    # we somehow have no due datetime to copy it from.
    time_str = f"{due_dt.hour:02d}:{due_dt.minute:02d}" if due_dt else "09:00"
    if t in ("daily", "every day", "everyday", "each day"):
        return {"days": list(range(7)), "time": time_str}
    if t in ("weekdays", "every weekday", "workdays", "work days"):
        return {"days": [0, 1, 2, 3, 4], "time": time_str}
    if t in ("weekends", "every weekend", "weekend"):
        return {"days": [5, 6], "time": time_str}
    if t in ("weekly", "every week"):
        day = due_dt.weekday() if due_dt else 0
        return {"days": [day], "time": time_str}
    # Otherwise collect any explicit day names present in the text. Substring
    # matching means "tuesday" also trips the "tue"/"tues" aliases, so dedupe
    # with set() before sorting.
    days = []
    for name, num in _DAY_MAP.items():
        if name in t:
            days.append(num)
    if days:
        return {"days": sorted(set(days)), "time": time_str}
    return None  # unrecognised phrasing -> treat as a one-time reminder

# The latest user request, so the weather tool can reject a city the model
# invented (small models sometimes pass a location the user never mentioned).
_USER_CONTEXT = ""


def set_user_context(text):
    """Record the latest user utterance so tools can sanity-check model args."""
    global _USER_CONTEXT
    _USER_CONTEXT = text or ""


# -- deferred action ---------------------------------------------------------
# Action tools (lights, Quran) generate their reply text immediately but
# register the physical side-effect here. jarvis.py calls pop_pending() after
# audio.speak() so the user always hears the confirmation before anything moves
# or sounds.
_pending = [None]


def defer(fn):
    """Register one callable to run after Jarvis finishes speaking."""
    _pending[0] = fn


def pop_pending():
    """Pop and return the pending action (or None). Clears the slot."""
    fn = _pending[0]
    _pending[0] = None
    return fn


# -- light control -----------------------------------------------------------
# The LightController lives in jarvis.py and is registered here at startup, so
# the brain can actuate lights for CONTEXTUAL follow-ups the fast keyword router
# (home_control.py) doesn't catch -- e.g. a bare "off" after "bedroom lights on".
_LIGHTS = [None]

_ROOM_ALIASES = {
    "all": "all", "everything": "all", "every": "all", "house": "all",
    "all lights": "all", "the lights": "all",
    "front door": "front_door", "front_door": "front_door", "door": "front_door",
    "bedroom": "bedroom", "bed room": "bedroom", "bed": "bedroom",
    "living room": "living_room", "living_room": "living_room", "lounge": "living_room",
    "desk": "desk", "kitchen": "kitchen",
}


def set_light_controller(controller):
    """Register the LightController so set_light() can publish."""
    _LIGHTS[0] = controller

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
    """GET a URL and parse the JSON body. Raises on network/HTTP/JSON errors;
    callers wrap this in try/except and turn failures into a spoken apology."""
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

    # Step 1: geocode the place name -> latitude/longitude (Open-Meteo's
    # forecast API takes coordinates, not names). count=1 keeps the top hit.
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
    # Step 2: fetch current conditions + today's daily summary for those coords.
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
    # The package was renamed `duckduckgo_search` -> `ddgs`; import the new name
    # first and fall back to the old one so either installed version works.
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


def set_reminder(**kwargs):
    """Store a reminder the assistant will announce out loud when it's due."""
    text = (kwargs.get("text") or kwargs.get("task")
            or kwargs.get("reminder") or kwargs.get("what") or "").strip()
    when = (kwargs.get("when") or kwargs.get("datetime")
            or kwargs.get("time") or kwargs.get("date") or "").strip()
    recurrence_str = (kwargs.get("recurrence") or "").strip()
    if not text:
        return "I need to know what to remind you about -- ask the user."
    if not when:
        return ("No date and time was given. Do NOT guess -- ask the user when "
                "they want to be reminded.")
    due_dt = reminders.parse_due(when)
    recurrence = _parse_recurrence(recurrence_str, due_dt) if recurrence_str else None
    rem = reminders.add(text, when, recurrence=recurrence)
    due = reminders.parse_due(rem.get("due"))
    if due is None:
        return ("That date and time wasn't clear. Ask the user for a specific "
                "day and time.")
    if recurrence:
        label = reminders.recurrence_label(recurrence)
        return f"Done — I'll remind you to {text} {label}, starting {reminders.speak_due(due)}."
    return f"Reminder set for {reminders.speak_due(due)}: {text}."


def list_reminders(**kwargs):
    """List the user's current (unacknowledged) reminders."""
    items = reminders.pending()
    if not items:
        return "You have no reminders set."
    parts = []
    for r in items:
        due = reminders.parse_due(r.get("due"))
        when = reminders.speak_due(due) if due else "no set time"
        rec = r.get("recurrence")
        if rec:
            label = reminders.recurrence_label(rec)
            parts.append(f"{r['text']} — {label}, next on {when}")
        else:
            parts.append(f"{r['text']} on {when}")
    return "Your reminders: " + "; ".join(parts) + "."


def cancel_reminder(**kwargs):
    """Cancel a reminder the user no longer wants."""
    query = (kwargs.get("text") or kwargs.get("query")
             or kwargs.get("reminder") or "").strip()
    if not query:
        # Nothing specified -- list what's pending and ask which to remove.
        # The 10-second follow-up window will catch the user's answer.
        items = reminders.pending()
        if not items:
            return "You have no reminders set, sir."
        parts = []
        for r in items:
            due = reminders.parse_due(r.get("due"))
            when = reminders.speak_due(due) if due else "no set time"
            parts.append(f"{r['text']}, due {when}")
        listing = "; ".join(parts)
        return (f"You have {len(items)} reminder{'s' if len(items) != 1 else ''}: "
                f"{listing}. Which one should I remove? Just say part of it.")
    n = reminders.cancel(query)
    if not n:
        return f"I couldn't find a reminder matching '{query}', sir."
    return f"Removed{' it' if n == 1 else f' {n} reminders'}, sir."


def cancel_all_reminders(**kwargs):
    """Cancel every pending reminder at once (local store + macOS Reminders app)."""
    local_n = reminders.cancel_all()
    mac_n = reminders.clear_mac_reminders()
    total = local_n + max(mac_n, 0)
    if total == 0:
        return "You have no reminders to clear, sir."
    return f"Cleared {total} reminder{'s' if total != 1 else ''}, sir."


def get_prayer_times(**kwargs):
    """Return today's prayer times or the next/specific upcoming salah."""
    from media import athan as _athan
    prayer_filter = (kwargs.get("prayer") or "").strip()
    show_all      = bool(kwargs.get("all") or kwargs.get("show_all"))

    times = _athan.all_prayer_times()
    if not times:
        return "I couldn't load today's prayer times, sir."

    now_dt = datetime.datetime.now()

    # Specific prayer requested -----------------------------------------------
    if prayer_filter:
        pfl = prayer_filter.lower()
        # Match the spoken name to a canonical prayer, allowing a 3-letter prefix
        # so "fajr"/"faj" and STT near-misses still resolve.
        canonical = None
        for p in _athan._PRAYERS:
            if p.lower() == pfl or p.lower().startswith(pfl[:3]):
                canonical = p
                break
        if not canonical:
            return f"I don't recognise '{prayer_filter}' as a prayer name, sir."
        t_str = times.get(canonical)
        if not t_str:
            return f"I don't have the {canonical} time for today, sir."
        # Minutes from now until that prayer (negative = already passed today).
        h, m = map(int, t_str.split(":"))
        diff_min = int((now_dt.replace(hour=h, minute=m, second=0, microsecond=0) - now_dt).total_seconds() / 60)
        if diff_min < -1:
            return f"{canonical} was at {t_str} today, sir -- it has already passed."
        elif diff_min < 2:
            return f"The {canonical} athan is right now, sir."
        h_p, m_p = divmod(diff_min, 60)
        tl = (f"{h_p} hour{'s' if h_p != 1 else ''} and {m_p} min" if h_p else
              f"{m_p} minute{'s' if m_p != 1 else ''}")
        return f"{canonical} is at {t_str} today, in {tl}, sir."

    # All times requested -----------------------------------------------------
    if show_all:
        parts = []
        for p in _athan._PRAYERS:
            t_str = times.get(p, "?")
            if ":" in t_str:
                h, m = map(int, t_str.split(":"))
                passed = (now_dt - now_dt.replace(hour=h, minute=m, second=0, microsecond=0)).total_seconds() > 90
            else:
                passed = False
            parts.append(f"{p} {t_str}" + (" (passed)" if passed else ""))
        return "Today's prayers: " + ", ".join(parts) + "."

    # Default: next upcoming prayer -------------------------------------------
    result = _athan.next_prayer()
    if result is None:
        parts = [f"{p} at {times[p]}" for p in _athan._PRAYERS if p in times]
        return f"All five prayers for today have passed, sir. They were: {', '.join(parts)}."
    name, t_str, mins = result
    h_p, m_p = divmod(mins, 60)
    if h_p and m_p:
        tl = f"{h_p} hour{'s' if h_p != 1 else ''} and {m_p} minute{'s' if m_p != 1 else ''}"
    elif h_p:
        tl = f"{h_p} hour{'s' if h_p != 1 else ''}"
    else:
        tl = f"{m_p} minute{'s' if m_p != 1 else ''}"
    return f"The next athan is {name} at {t_str}, in {tl}, sir."


def play_quran(**kwargs):
    """Stream a surah of the Quran by a reciter."""
    surah = (kwargs.get("surah") or kwargs.get("surah_name") or kwargs.get("name")
             or kwargs.get("chapter") or kwargs.get("number") or "").strip()
    reciter = (kwargs.get("reciter") or kwargs.get("qari") or kwargs.get("by") or "").strip()
    if not surah:
        return "Which surah should I play? Ask the user for a surah name or number."
    reply, action = quran_player.plan_play(surah, reciter)
    if action:
        defer(action)  # mpg123 starts AFTER Jarvis finishes speaking
    return reply


def stop_quran(**kwargs):
    had = quran_player._P.playing
    reply = "Stopped the Quran." if had else "Nothing is playing, sir."
    if had:
        defer(quran_player.stop)  # kill mpg123 AFTER confirmation is spoken
    return reply


def pause_quran(**kwargs):
    p = quran_player._P
    if not p.playing:
        return "Nothing is playing, sir."
    if p.paused:
        return "It's already paused, sir."
    defer(quran_player.pause)  # SIGSTOP AFTER "Paused." is spoken
    return "Paused."


def resume_quran(**kwargs):
    p = quran_player._P
    if p._proc is None or not p.paused:
        return "Nothing is paused, sir."
    defer(quran_player.resume)  # SIGCONT AFTER "Resuming." is spoken
    return "Resuming."


def next_surah(**kwargs):
    reply, action = quran_player.plan_step(1)
    if action:
        defer(action)
    return reply


def previous_surah(**kwargs):
    reply, action = quran_player.plan_step(-1)
    if action:
        defer(action)
    return reply


def set_light(**kwargs):
    """Turn a room's light(s) on or off.

    Used for contextual requests the fast keyword router missed -- e.g. the user
    said 'bedroom lights on' earlier and now just says 'off'. The brain reads the
    room from the conversation and passes room + state here. Publish is deferred
    so it fires AFTER Jarvis speaks the confirmation."""
    lights = _LIGHTS[0]
    raw_room  = (kwargs.get("room") or kwargs.get("location")
                 or kwargs.get("where") or "").strip().lower()
    raw_state = (kwargs.get("state") or kwargs.get("status")
                 or kwargs.get("value") or kwargs.get("power") or "").strip().lower()

    if raw_state in ("on", "true", "1", "open", "enable", "enabled"):
        state = "ON"
    elif raw_state in ("off", "false", "0", "close", "closed", "disable", "disabled"):
        state = "OFF"
    else:
        return "Should I turn the light on or off, sir?"

    room = (_ROOM_ALIASES.get(raw_room, raw_room.replace(" ", "_"))
            if raw_room else config.DEFAULT_LIGHT_ROOM)

    if lights is None or not getattr(lights, "connected", False):
        return "I can't reach the lights right now, sir -- the home hub looks offline."
    reply = lights.light_reply(room, state)
    defer(lambda r=room, s=state: lights.publish(r, s))
    return reply


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
    {"type": "function", "function": {
        "name": "set_reminder",
        "description": ("Set a reminder to tell the user about something at a later date/time. "
                        "Call this ONLY when the user asks to be reminded AND you have BOTH what "
                        "to remind them about AND a specific date and time. Convert relative "
                        "phrasing ('tomorrow at 8pm', 'in two hours', 'next Monday') into an "
                        "absolute ISO 8601 datetime using the current local time you were given. "
                        "If no clear date/time was provided, do NOT call this -- ask instead. "
                        "For recurring reminders ('every day', 'every Monday', 'every Saturday "
                        "and Sunday', 'weekdays', etc.) set 'when' to the FIRST occurrence and "
                        "pass 'recurrence' describing the cadence. The reminder will keep nagging "
                        "every few minutes until acknowledged, then auto-reschedule for next time."),
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "What to remind the user about, e.g. 'write the to-do list'."},
            "when": {"type": "string", "description": "First (or only) occurrence, ISO 8601 local, e.g. '2026-06-19T09:00'."},
            "recurrence": {"type": "string", "description": (
                "How often to repeat. Plain English: 'daily', 'weekdays', 'weekends', "
                "'every monday', 'every tuesday and thursday', 'every saturday', etc. "
                "Omit entirely for a one-time reminder."
            )}},
            "required": ["text", "when"]}}},
    {"type": "function", "function": {
        "name": "list_reminders",
        "description": "List the user's current reminders. Use when they ask what reminders they have.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "cancel_reminder",
        "description": "Cancel/remove a reminder the user no longer wants.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "Part of the reminder text to cancel, e.g. 'mom'."}},
            "required": ["text"]}}},
    {"type": "function", "function": {
        "name": "cancel_all_reminders",
        "description": ("Cancel ALL reminders at once. Use when the user says something like "
                        "'remove all reminders', 'clear all reminders', 'delete all reminders', "
                        "or 'cancel everything'."),
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "get_prayer_times",
        "description": (
            "Get today's Islamic prayer (salah/salat) times, or find out when the "
            "next athan is. Use for ANY question about: when is the next athan/adhan, "
            "what time is Fajr/Dhuhr/Asr/Maghrib/Isha, today's prayer schedule, "
            "how long until a prayer, متى الأذان, وقت الصلاة. Covers all five daily "
            "prayers for the user's city."
        ),
        "parameters": {"type": "object", "properties": {
            "prayer": {
                "type": "string",
                "description": (
                    "Specific prayer to ask about: Fajr, Dhuhr, Asr, Maghrib, or Isha. "
                    "Omit (or leave empty) to get the next upcoming prayer."
                )
            },
            "all": {
                "type": "boolean",
                "description": "Set true to list all five prayer times for today."
            }
        }, "required": []}}},
    {"type": "function", "function": {
        "name": "play_quran",
        "description": ("Play a surah (chapter) of the Quran out loud. Use when the "
                        "user asks to play/recite the Quran or a named surah. Pass "
                        "the surah name or number and, if the user named a reciter "
                        "(qari), pass that too; otherwise leave reciter empty for "
                        "the default."),
        "parameters": {"type": "object", "properties": {
            "surah": {"type": "string", "description": "Surah name or number, e.g. 'Al-Kahf', 'Ya-Sin', or '18'."},
            "reciter": {"type": "string", "description": "Reciter/qari name if specified, e.g. 'Mishary', 'Sudais'. Empty for default."}},
            "required": ["surah"]}}},
    {"type": "function", "function": {
        "name": "stop_quran",
        "description": "Stop the Quran playback entirely.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "pause_quran",
        "description": "Pause the Quran playback (can be resumed).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "resume_quran",
        "description": "Resume Quran playback after it was paused.",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "next_surah",
        "description": "Skip to the next surah (same reciter).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "previous_surah",
        "description": "Go back to the previous surah (same reciter).",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "set_light",
        "description": ("Turn a room's light or lamp ON or OFF. Use for any request "
                        "to switch lights on/off, INCLUDING a bare 'on' / 'off' / "
                        "'turn them off' that refers to lights mentioned earlier in "
                        "the conversation -- read the room from the context. If you "
                        "genuinely can't tell which room, ask instead of guessing."),
        "parameters": {"type": "object", "properties": {
            "room": {"type": "string",
                     "description": "Room: bedroom, front_door (front door / door), desk, living_room, kitchen, or 'all'. Infer from the conversation."},
            "state": {"type": "string", "enum": ["ON", "OFF"],
                      "description": "Whether to turn the light ON or OFF."}},
            "required": ["state"]}}},
]

# Maps each schema's tool name to the Python function that implements it. The
# model emits a name + args; run() looks the name up here and calls it.
_DISPATCH = {
    "get_weather": get_weather,
    "web_search": web_search,
    "get_current_datetime": get_current_datetime,
    "get_prayer_times": get_prayer_times,
    "set_reminder": set_reminder,
    "list_reminders": list_reminders,
    "cancel_reminder": cancel_reminder,
    "cancel_all_reminders": cancel_all_reminders,
    "play_quran": play_quran,
    "stop_quran": stop_quran,
    "pause_quran": pause_quran,
    "resume_quran": resume_quran,
    "next_surah": next_surah,
    "previous_surah": previous_surah,
    "set_light": set_light,
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
