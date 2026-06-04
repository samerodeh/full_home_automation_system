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
import json
import urllib.request

import requests

import config
import tools

SYSTEM_INSTRUCTION = (
    f"You are {config.ASSISTANT_NAME}, a witty, capable voice assistant modeled "
    "on Tony Stark's AI. Your replies are spoken out loud, so keep them short, "
    "clear, and conversational -- usually one to three sentences. Never use "
    "markdown, bullet points, headings, code fences, or emoji; just speak plainly. "
    "Answer almost everything directly from your own knowledge. You have three "
    "tools, but use one ONLY when the user clearly and explicitly asks for that "
    "exact thing: call get_weather ONLY if they mention weather, temperature, "
    "rain, or forecast; call get_current_datetime ONLY if they ask the time or "
    "date; call web_search ONLY if they ask about news, current events, or to "
    "look something up. For anything else, do NOT call any tool -- just answer "
    "normally. Never default to the weather. If you can't tell what the user "
    "said or meant, briefly ask them to repeat instead of guessing. You may "
    "occasionally address the user as 'sir'."
)

_HTTP_TIMEOUT = 120
_MAX_TOOL_ROUNDS = 5


def _http_post(url, payload, headers=None):
    # Uses requests (not urllib): Groq's endpoint sits behind Cloudflare, which
    # blocks urllib's signature (403 code 1010) but allows requests.
    resp = requests.post(url, json=payload, headers=headers or {}, timeout=_HTTP_TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"{resp.status_code} {resp.text[:200]}")
    return resp.json()


def _parse_args(raw):
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


class _OllamaBrain:
    """Local Ollama server, with tool-calling."""

    def __init__(self):
        self.error = None
        self._messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
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

    def ask(self, question):
        if not self.ready:
            return f"I can't answer questions yet because {self.error}."
        tools.set_user_context(question)
        start = len(self._messages)
        self._messages.append({"role": "user", "content": question})
        try:
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
                    return (msg.get("content") or "").strip() or "I'm not sure, sir."
                for call in calls:
                    fn = call.get("function", {})
                    result = tools.run(fn.get("name", ""), _parse_args(fn.get("arguments")))
                    self._messages.append(
                        {"role": "tool", "tool_name": fn.get("name", ""), "content": result}
                    )
            return "I got a little tangled up working that out, sir."
        except Exception as exc:
            del self._messages[start:]
            return f"I ran into a problem reaching my brain: {exc}"


class _GroqBrain:
    """Groq's OpenAI-compatible cloud API, with tool-calling."""

    def __init__(self):
        self.error = None
        self._messages = [{"role": "system", "content": SYSTEM_INSTRUCTION}]
        if not config.GROQ_API_KEY:
            self.error = "no Groq API key is set (free one at console.groq.com/keys)"

    @property
    def ready(self):
        return self.error is None

    def ask(self, question):
        if not self.ready:
            return f"I can't answer questions yet because {self.error}."
        tools.set_user_context(question)
        start = len(self._messages)
        self._messages.append({"role": "user", "content": question})
        try:
            for _ in range(_MAX_TOOL_ROUNDS):
                data = _http_post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    {"model": config.GROQ_MODEL, "messages": self._messages,
                     "tools": tools.SCHEMAS, "tool_choice": "auto"},
                    headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
                )
                msg = data["choices"][0]["message"]
                self._messages.append(msg)
                calls = msg.get("tool_calls") or []
                if not calls:
                    return (msg.get("content") or "").strip() or "I'm not sure, sir."
                for call in calls:
                    fn = call.get("function", {})
                    result = tools.run(fn.get("name", ""), _parse_args(fn.get("arguments")))
                    self._messages.append({
                        "role": "tool", "tool_call_id": call.get("id", ""),
                        "name": fn.get("name", ""), "content": result,
                    })
            return "I got a little tangled up working that out, sir."
        except Exception as exc:
            del self._messages[start:]
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
