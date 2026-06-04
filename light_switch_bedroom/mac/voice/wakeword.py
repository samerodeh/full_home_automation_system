"""Local wake-word detection with openWakeWord (free, offline, no account).

Listens for a wake phrase (default "Hey Jarvis") with a tiny pretrained model,
so the assistant can ignore all other sound WITHOUT transcribing it -- no flood
of speaker/TV audio, no wasted speech-to-text calls, far fewer false triggers.
"""
import collections

import numpy as np

import config


class WakeWord:
    def __init__(self):
        import openwakeword
        from openwakeword.model import Model

        # Downloads the small pretrained models on first run (no-op afterward).
        try:
            openwakeword.utils.download_models()
        except Exception:
            pass

        self.threshold = config.WAKE_THRESHOLD
        kwargs = dict(wakeword_models=[config.WAKE_MODEL], inference_framework="onnx")
        if config.WAKE_VAD_THRESHOLD > 0:
            # Silero VAD gating: suppresses wake scores unless real speech is present.
            kwargs["vad_threshold"] = config.WAKE_VAD_THRESHOLD
        self._model = Model(**kwargs)
        self._recent = collections.deque(maxlen=8)  # ~0.6 s of recent peaks
        self.last_score = 0.0

    def reset(self):
        try:
            self._model.reset()
        except Exception:
            pass
        self._recent.clear()

    def detect(self, frame_float32) -> bool:
        """Feed a frame (float32 in [-1, 1]); True if the wake word just fired.

        Guards against openWakeWord spuriously activating on digital silence /
        zeros: a hit only counts if there was real audio in the last ~0.6 s."""
        pcm16 = (np.clip(frame_float32, -1.0, 1.0) * 32767).astype(np.int16)
        scores = self._model.predict(pcm16)  # always feed, to keep its buffer continuous
        self.last_score = max(scores.values(), default=0.0)
        self._recent.append(float(np.max(np.abs(frame_float32))))
        if max(self._recent, default=0.0) < config.WAKE_MIN_PEAK:
            return False
        return self.last_score >= self.threshold
