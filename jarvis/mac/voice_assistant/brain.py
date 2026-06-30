"""The 'brain' -- answers any general question, with a swappable LLM provider
and live tools (weather, web search, clock) so it can reach the real world.

The provider is chosen by ``config.LLM_PROVIDER``:
    "ollama"  -> a model running locally via Ollama (free, no account, offline*)
    "groq"    -> Groq cloud API (free key, very fast, high quality)
    "gemini"  -> Google Gemini (free key)

(* offline except for the live tools, which need the internet by definition.)

Ollama and Groq get tool-calling: the model can ask to run get_weather /
web_search / get_current_datetime, we execute it, feed the result back, and let
the model phrase the spoken answer. All providers keep a rolling conversation.
"""
import datetime
import json
import re
import time
import urllib.request

import requests

import config
import tools

SYSTEM_INSTRUCTION = (
    f"You are {config.ASSISTANT_NAME}, a witty, capable voice assistant modeled "
    "on Tony Stark's AI. Your replies are spoken out loud, so they MUST be short "
    "and precise: answer in ONE sentence whenever possible, never more than two. "
    "Use plain, exact wording -- no filler, no hedging, no preamble, no sign-off, "
    "and don't restate the question. Give the answer directly, then stop. Never "
    "use markdown, bullet points, headings, code fences, or emoji; just speak plainly. "
    "Answer almost everything directly from your own knowledge. You have several "
    "tools, but use one ONLY when the user clearly and explicitly asks for that "
    "exact thing: call get_weather ONLY if they mention weather, temperature, "
    "rain, or forecast; call get_current_datetime ONLY if they ask the time or "
    "date; call web_search ONLY if they ask about news, current events, or to "
    "look something up. For reminders: call set_reminder when the user asks to "
    "be reminded of something AND gives a specific date and time -- convert any "
    "relative time (like 'tomorrow at 8pm' or 'in two hours') into an absolute "
    "ISO 8601 datetime using the current local time provided below; but if they "
    "ask for a reminder WITHOUT a clear date and time, do NOT guess -- ask them "
    "exactly when. For RECURRING reminders ('every day', 'every Monday', 'every "
    "Saturday and Sunday', 'weekdays', 'every week', etc.) pass 'when' as the "
    "FIRST occurrence (absolute ISO 8601) and 'recurrence' as a plain English "
    "string like 'daily', 'every monday', 'every saturday and sunday', 'weekdays', "
    "'weekends'. The reminder nags every few minutes until the user says done, then "
    "auto-reschedules for the next occurrence -- forever. "
    "Call list_reminders when they ask what reminders they have. "
    "Call cancel_reminder when they want to remove or delete any reminder -- "
    "even if they don't say which one; pass no text argument and the tool will "
    "list them and ask. "
    "Call get_prayer_times for ANY question about salah / athan / adhan times: "
    "'when is the next athan', 'what time is Maghrib', 'متى الأذان', today's full "
    "prayer schedule, how long until a prayer, etc. Pass prayer='Fajr' (or the "
    "specific prayer they asked about), all=true for the full schedule, or nothing "
    "for the next upcoming prayer. "
    "For the Quran: call play_quran when the user asks "
    "to play/recite the Quran or a surah (pass the surah name or number, and a "
    "reciter only if they named one); call stop_quran, pause_quran, resume_quran, "
    "next_surah, or previous_surah for playback control while it's playing. "
    "For lights: call set_light to turn a room's light ON or OFF -- including "
    "when the user just says 'off', 'on', 'turn them off', etc. referring to "
    "lights mentioned earlier; use the conversation so far to choose the room "
    "(bedroom, front_door, desk, living_room, kitchen, or 'all'). If you truly "
    "can't tell which room they mean, ask instead of guessing. "
    "For anything else, do NOT call any tool -- just answer "
    "normally. Never default to the weather. If you can't tell what the user "
    "said or meant, briefly ask them to repeat instead of guessing. You may "
    "occasionally address the user as 'sir'."
)

_HTTP_TIMEOUT = 120
_MAX_TOOL_ROUNDS = 5
# Max user+assistant turns kept in the rolling context. Older turns are dropped
# so Groq API calls stay fast regardless of session length. 20 turns (~40
# messages) gives plenty of short-term memory without accumulating forever.
_MAX_HISTORY_TURNS = 20


def _system_message():
    """The system prompt, refreshed with the current local time so the model can
    resolve relative reminder times into absolute datetimes."""
    now = datetime.datetime.now()
    return {"role": "system", "content": (
        SYSTEM_INSTRUCTION
        + f"\n\nThe current local date and time is {now:%A, %B %-d, %Y at %-I:%M %p} "
        + f"(ISO 8601: {now.isoformat(timespec='minutes')})."
    )}


def _http_post(url, payload, headers=None):
    # Uses requests (not urllib): Groq's endpoint sits behind Cloudflare, which
    # blocks urllib's signature (403 code 1010) but allows requests.
    resp = requests.post(url, json=payload, headers=headers or {}, timeout=_HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code} {resp.text[:200]}")
    return resp.json()


def _parse_args(raw):
    """Normalize a tool call's arguments to a dict. Providers return them either
    as a ready dict (Ollama) or a JSON string (Groq/OpenAI); bad JSON -> {}."""
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


def _is_per_minute_limit(err: str) -> bool:
    """True if a 429 is a transient per-minute limit (TPM/RPM), not the daily
    cap (TPD). The per-minute kind clears in seconds, so it's worth a short wait."""
    e = err.lower()
    return ("per minute" in e or "tokens per minute" in e
            or "requests per minute" in e or "tpm" in e or "rpm" in e)


def _retry_after_seconds(err: str, default=3.0, cap=8.0) -> float:
    """Seconds to wait before retrying, from Groq's 'try again in Xs' hint
    (with a small buffer, capped so the assistant never hangs for long)."""
    m = re.search(r"try again in ([\d.]+)\s*s", err.lower())
    secs = float(m.group(1)) if m else default
    return min(max(secs + 0.5, 1.0), cap)


def _groq_chat(messages, tries=3):
    """POST a chat completion to Groq, with three layers of resilience:

    1. tool_use_failed (400): llama-3.3-70b occasionally formats a tool call
       wrong; re-rolling the same request almost always fixes it.
    2. Per-minute rate limit (429 TPM/RPM): transient -- wait the suggested time
       (capped) and retry the SAME model before falling back.
    3. Daily cap (429 TPD): switch to the fallback model so Jarvis keeps working
       for the rest of the day without any manual action.
    """
    headers = {"Authorization": f"Bearer {config.GROQ_API_KEY}"}
    # Build the list of models to try: primary first, then fallback (if different).
    models = [config.GROQ_MODEL]
    if config.GROQ_FALLBACK_MODEL and config.GROQ_FALLBACK_MODEL != config.GROQ_MODEL:
        models.append(config.GROQ_FALLBACK_MODEL)

    last_exc = None
    for model in models:
        payload = {"model": model, "messages": messages,
                   "tools": tools.SCHEMAS, "tool_choice": "auto"}
        waited = False
        for attempt in range(tries):
            try:
                return _http_post(
                    "https://api.groq.com/openai/v1/chat/completions", payload, headers)
            except RuntimeError as exc:
                err = str(exc)
                if "tool_use_failed" in err and attempt < tries - 1:
                    continue  # re-roll same model
                if err.startswith("429"):
                    last_exc = exc
                    # Transient per-minute limit: wait once, then retry this model.
                    if _is_per_minute_limit(err) and not waited and attempt < tries - 1:
                        wait = _retry_after_seconds(err)
                        print(f"  [brain] {model} hit a per-minute limit; "
                              f"waiting {wait:.0f}s and retrying...")
                        time.sleep(wait)
                        waited = True
                        continue
                    # Daily cap (or out of per-minute retries): fall back.
                    nxt = (models[models.index(model) + 1]
                           if model != models[-1] else "no more fallbacks")
                    print(f"  [brain] {model} rate-limited; switching to {nxt}...")
                    break  # try next model in outer loop
                raise  # any other error bubbles up immediately
    raise last_exc or RuntimeError("All Groq models are rate-limited.")


class _OllamaBrain:
    """Local Ollama server, with tool-calling."""

    def __init__(self):
        self.error = None
        self._messages = [_system_message()]
        want = config.OLLAMA_MODEL
        try:
            req = urllib.request.Request(config.OLLAMA_HOST + "/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                names = [m.get("name", "")
                         for m in json.loads(resp.read().decode("utf-8")).get("models", [])]
            if not (want in names or (want + ":latest") in names):
                self.error = f"the model '{want}' isn't downloaded yet -- run: ollama pull {want}"
        except Exception:
            self.error = (
                f"can't reach Ollama at {config.OLLAMA_HOST} -- is it running? "
                "start it with `open -a Ollama` (or `ollama serve`)"
            )

    @property
    def ready(self):
        return self.error is None

    def _trim(self):
        """Keep only the most recent _MAX_HISTORY_TURNS exchanges (system msg + last N pairs)."""
        # messages[0] is always the system message; rest are alternating user/assistant
        if len(self._messages) > 1 + _MAX_HISTORY_TURNS * 2:
            # Replace everything after the system message with just the last N
            # pairs. The negative slice start (1 - N*2) counts back from the end,
            # so we always keep the system message + the tail of the conversation.
            self._messages[1:] = self._messages[1 - _MAX_HISTORY_TURNS * 2:]

    def remember(self, user_text, assistant_text):
        """Record an exchange handled outside the LLM (e.g. a light command) so
        later follow-ups like 'off' have the context."""
        self._messages.append({"role": "user", "content": user_text})
        self._messages.append({"role": "assistant", "content": assistant_text})
        self._trim()

    def ask(self, question):
        if not self.ready:
            return f"I can't answer questions yet because {self.error}."
        tools.set_user_context(question)
        self._messages[0] = _system_message()  # refresh "current time" for reminders
        self._trim()
        # Remember where this turn starts so we can roll the whole turn back out
        # of history if the request fails partway through (see except below).
        start = len(self._messages)
        self._messages.append({"role": "user", "content": question})
        try:
            # Tool-calling loop: the model may ask for a tool, we run it and feed
            # the result back, and it gets another turn -- repeating until it
            # returns a plain answer (no tool_calls) or we hit the round cap.
            for _ in range(_MAX_TOOL_ROUNDS):
                data = _http_post(config.OLLAMA_HOST + "/api/chat", {
                    "model": config.OLLAMA_MODEL,
                    "messages": self._messages,
                    "stream": False,
                    "tools": tools.SCHEMAS,
                })
                msg = data.get("message", {})
                self._messages.append(msg)
                calls = msg.get("tool_calls") or []
                if not calls:
                    # No tool requested -> this is the final spoken answer.
                    return (msg.get("content") or "").strip() or "I'm not sure, sir."
                # Run each requested tool and append its output as a "tool" message
                # so the model can read the result on the next round.
                for call in calls:
                    fn = call.get("function", {})
                    result = tools.run(fn.get("name", ""), _parse_args(fn.get("arguments")))
                    self._messages.append(
                        {"role": "tool", "tool_name": fn.get("name", ""), "content": result}
                    )
            # Model kept asking for tools past the cap -- bail rather than loop forever.
            return "I got a little tangled up working that out, sir."
        except Exception as exc:
            # Drop the partial turn so a failed request doesn't poison history.
            del self._messages[start:]
            if "tool_use_failed" in str(exc):
                return "I had trouble with that one, sir -- could you say it again?"
            return f"I ran into a problem reaching my brain: {exc}"


class _GroqBrain:
    """Groq's OpenAI-compatible cloud API, with tool-calling."""

    def __init__(self):
        self.error = None
        self._messages = [_system_message()]
        if not config.GROQ_API_KEY:
            self.error = "no Groq API key is set (free one at console.groq.com/keys)"

    @property
    def ready(self):
        return self.error is None

    def _trim(self):
        """Keep only the most recent _MAX_HISTORY_TURNS exchanges (system msg + last N pairs)."""
        if len(self._messages) > 1 + _MAX_HISTORY_TURNS * 2:
            self._messages[1:] = self._messages[1 - _MAX_HISTORY_TURNS * 2:]

    def remember(self, user_text, assistant_text):
        """Record an exchange handled outside the LLM (e.g. a light command) so
        later follow-ups like 'off' have the context."""
        self._messages.append({"role": "user", "content": user_text})
        self._messages.append({"role": "assistant", "content": assistant_text})
        self._trim()

    def ask(self, question):
        if not self.ready:
            return f"I can't answer questions yet because {self.error}."
        tools.set_user_context(question)
        self._messages[0] = _system_message()  # refresh "current time" for reminders
        self._trim()
        # Roll-back marker for a failed turn (see except below).
        start = len(self._messages)
        self._messages.append({"role": "user", "content": question})
        try:
            # Same tool-calling loop as the Ollama brain; see _OllamaBrain.ask.
            for _ in range(_MAX_TOOL_ROUNDS):
                data = _groq_chat(self._messages)
                msg = data["choices"][0]["message"]
                self._messages.append(msg)
                calls = msg.get("tool_calls") or []
                if not calls:
                    return (msg.get("content") or "").strip() or "I'm not sure, sir."
                for call in calls:
                    fn = call.get("function", {})
                    result = tools.run(fn.get("name", ""), _parse_args(fn.get("arguments")))
                    # OpenAI/Groq tool replies must echo the call's id so the API
                    # can pair this result with the request that asked for it.
                    self._messages.append({
                        "role": "tool", "tool_call_id": call.get("id", ""),
                        "name": fn.get("name", ""), "content": result,
                    })
            return "I got a little tangled up working that out, sir."
        except Exception as exc:
            del self._messages[start:]
            if "tool_use_failed" in str(exc):
                return "I had trouble with that one, sir -- could you say it again?"
            return f"I ran into a problem reaching my brain: {exc}"


class _GeminiBrain:
    """Google Gemini via the google-genai SDK (no tools wired up)."""

    def __init__(self):
        self.error = None
        self._client = None  # kept alive so its HTTP session isn't GC'd
        self._chat = None
        try:
            from google import genai
            from google.genai import types
        except ImportError:
            self.error = "the google-genai package isn't installed"
            return
        if not config.GEMINI_API_KEY:
            self.error = "no Gemini API key is set"
            return
        try:
            self._client = genai.Client(api_key=config.GEMINI_API_KEY)
            self._chat = self._client.chats.create(
                model=config.GEMINI_MODEL,
                config=types.GenerateContentConfig(
                    system_instruction=SYSTEM_INSTRUCTION, temperature=0.7,
                ),
            )
        except Exception as exc:
            self.error = f"couldn't start the Gemini client ({exc})"

    @property
    def ready(self):
        return self._chat is not None

    def ask(self, question):
        if not self.ready:
            return f"I can't answer questions yet because {self.error}."
        try:
            response = self._chat.send_message(question)
            return (response.text or "").strip() or "I'm not sure, sir."
        except Exception as exc:
            return f"I ran into a problem reaching my brain: {exc}"


class Brain:
    """Picks an LLM provider from config.LLM_PROVIDER and delegates to it."""

    def __init__(self):
        self.provider = config.LLM_PROVIDER
        if self.provider == "gemini":
            self._impl = _GeminiBrain()
        elif self.provider == "groq":
            self._impl = _GroqBrain()
        else:
            self.provider = "ollama"
            self._impl = _OllamaBrain()

    @property
    def ready(self):
        return self._impl.ready

    @property
    def error(self):
        return self._impl.error

    def ask(self, question):
        return self._impl.ask(question)

    def remember(self, user_text, assistant_text):
        """Record a non-LLM exchange (e.g. a light command handled by the fast
        router) into history, if the active provider keeps message history."""
        fn = getattr(self._impl, "remember", None)
        if fn:
            fn(user_text, assistant_text)
