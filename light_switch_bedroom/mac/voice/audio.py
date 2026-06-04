"""Audio I/O -- microphone capture, speech-to-text (Whisper), speech (macOS say).

Heavy imports (whisper, sounddevice) are done lazily so that lightweight uses
of the assistant -- text mode, the self-test -- don't pay the cost or require a
microphone to be present.
"""
import subprocess

import config

_whisper_model = None


def load_stt():
    """Load the Whisper model once (the first call is slow)."""
    global _whisper_model
    if _whisper_model is None:
        import whisper

        print(f"  [stt] loading Whisper '{config.WHISPER_MODEL}' model...")
        _whisper_model = whisper.load_model(config.WHISPER_MODEL)
        print("  [stt] ready.")
    return _whisper_model


def record(seconds: float | None = None):
    """Record from the default microphone and return a mono float32 array."""
    import numpy as np  # noqa: F401  (sounddevice needs numpy available)
    import sounddevice as sd

    seconds = seconds or config.RECORD_SECONDS
    audio = sd.rec(
        int(seconds * config.SAMPLE_RATE),
        samplerate=config.SAMPLE_RATE,
        channels=1,
        dtype="float32",
    )
    sd.wait()
    return audio.flatten()


def prepare() -> None:
    """Warm up whatever STT engine we'll use, so the first command isn't slow."""
    if config.STT_PROVIDER == "groq" and config.GROQ_API_KEY:
        return  # Groq is remote; nothing to preload
    load_stt()


# Stock phrases Whisper invents from silence / non-speech audio.
_HALLUCINATIONS = {
    "", ".", "you", "thank you", "thanks", "thank you very much",
    "thanks for watching", "thank you for watching", "thanks for watching!",
    "please subscribe", "bye", "goodbye", "okay", "ok", "so", "uh", "um",
    "hmm", "you're welcome", "i'm sorry", "subtitles by the amara.org community",
}


def _looks_like_speech(audio) -> bool:
    """Conservative gate: reject near-silent clips so the transcriber can't
    invent phantom phrases. Real speech (peak ~0.15) passes easily."""
    import numpy as np
    if audio.size < int(0.3 * config.SAMPLE_RATE):
        return False
    return float(np.max(np.abs(audio))) >= 0.02


def _is_hallucination(text) -> bool:
    """True for the stock phrases Whisper emits on silence/non-speech audio."""
    t = text.strip().lower().strip(" .!?,\"'")
    return t in _HALLUCINATIONS or len(t) <= 1


def transcribe(audio) -> str:
    """Turn a recorded clip into text. Returns '' for non-speech (silence,
    echo, faint noise) so callers ignore it. Uses Groq's hosted Whisper-large
    when configured, else local Whisper; Groq failures fall back to local."""
    if not _looks_like_speech(audio):
        return ""
    if config.STT_PROVIDER == "groq" and config.GROQ_API_KEY:
        text = _transcribe_groq(audio)
        if text is not None:
            return "" if _is_hallucination(text) else text
    text = _transcribe_local(audio)
    return "" if _is_hallucination(text) else text


def _transcribe_local(audio) -> str:
    model = load_stt()
    result = model.transcribe(audio, fp16=False, language="en")
    return result["text"].strip()


def _groq_stt_params():
    params = {"model": config.GROQ_STT_MODEL, "language": "en",
              "response_format": "json", "temperature": "0"}
    if config.STT_PROMPT:  # optional; off by default since priming can echo
        params["prompt"] = config.STT_PROMPT
    return params


def _transcribe_groq(audio):
    """Send the clip to Groq's hosted Whisper-large. Returns text, or None on
    failure so the caller can fall back to the local model."""
    import io
    import wave

    import numpy as np
    import requests

    buf = io.BytesIO()
    pcm = (np.clip(audio, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    with wave.open(buf, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(config.SAMPLE_RATE)
        wav.writeframes(pcm)
    buf.seek(0)
    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {config.GROQ_API_KEY}"},
            files={"file": ("speech.wav", buf, "audio/wav")},
            data=_groq_stt_params(),
            timeout=30,
        )
    except Exception as exc:
        print(f"  [stt] Groq request failed ({exc}); using local Whisper.")
        return None
    if resp.status_code != 200:
        print(f"  [stt] Groq STT error {resp.status_code}: {resp.text[:140]}; "
              "using local Whisper.")
        return None
    return resp.json().get("text", "").strip()


def speak(text: str) -> None:
    """Speak text aloud via the macOS ``say`` command (free, built-in).

    Falls back to the system default voice if the configured one isn't
    installed, and stays silent (rather than crashing) on non-macOS systems.
    """
    if not text:
        return
    base = ["say", "-r", str(config.TTS_RATE)]
    try:
        if config.TTS_VOICE:
            result = subprocess.run(base + ["-v", config.TTS_VOICE, text])
            if result.returncode == 0:
                return
        subprocess.run(base + [text])
    except FileNotFoundError:
        pass  # `say` only exists on macOS


def chime() -> None:
    """Play a short, non-blocking 'I'm listening' cue (macOS system sound)."""
    try:
        subprocess.Popen(
            ["afplay", "/System/Library/Sounds/Tink.aiff"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass
