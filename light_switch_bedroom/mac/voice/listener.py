"""Always-on microphone listener with voice-activity detection (VAD).

Continuously reads the mic and returns one complete spoken utterance at a time:
capture starts when you begin speaking and ends once you've gone quiet for a
moment, so Jarvis acts only when you've *finished* talking.

Energy-based VAD with an adaptive ambient-noise baseline -- no dependencies
beyond sounddevice + numpy (both already required). For each 30 ms frame we
compare its loudness (RMS) to a threshold derived from the room's background
level; a run of quiet frames after speech marks the end of the utterance.
"""
import collections

import numpy as np

import config


class Listener:
    def __init__(self, frame_source=None):
        self.sr = config.SAMPLE_RATE
        self.frame_ms = 30
        self.frame_len = int(self.sr * self.frame_ms / 1000)
        self.sensitivity = config.VAD_SENSITIVITY
        self.abs_floor = 0.015            # never trust a threshold below this
        self.end_silence = config.END_SILENCE_SEC
        self.max_utt = config.MAX_UTTERANCE_SEC
        self.preroll = 0.30               # keep this much audio before speech onset
        self._baseline = 0.01
        self._stream = None
        self._frame_source = frame_source  # injectable for tests; None -> real mic

    # -- stream lifecycle ----------------------------------------------------
    def start(self):
        if self._frame_source is None:
            import sounddevice as sd
            self._stream = sd.InputStream(
                samplerate=self.sr, channels=1, dtype="float32",
                blocksize=self.frame_len,
            )
            self._stream.start()
        self._calibrate()
        return self

    def stop(self):
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None

    def flush(self):
        """Discard buffered audio (e.g. Jarvis's own TTS picked up by the mic)."""
        if self._stream is None:
            return
        try:
            while self._stream.read_available >= self.frame_len:
                self._stream.read(self.frame_len)
        except Exception:
            pass

    def wait_for_wake(self, detector):
        """Read mic frames and feed the wake-word detector until it fires.
        Unlike transcription, this sends audio nowhere -- it just listens locally
        for the wake phrase and ignores everything else."""
        chunk = 1280  # openWakeWord's preferred 80 ms frame at 16 kHz
        while True:
            if self._frame_source is not None:
                frame = self._frame_source()
            else:
                data, _ = self._stream.read(chunk)
                frame = data[:, 0]
            if detector.detect(frame):
                return

    # -- frame I/O -----------------------------------------------------------
    def _read_frame(self):
        if self._frame_source is not None:
            return self._frame_source()
        data, _ = self._stream.read(self.frame_len)
        return data[:, 0]

    @staticmethod
    def _rms(frame):
        if frame.size == 0:
            return 0.0
        return float(np.sqrt(np.mean(frame.astype(np.float64) ** 2)))

    def _calibrate(self, seconds=0.6):
        n = max(1, int(seconds * 1000 / self.frame_ms))
        vals = [v for v in (self._rms(self._read_frame()) for _ in range(n)) if v > 0]
        if vals:
            self._baseline = float(np.median(vals))

    # -- main entry point ----------------------------------------------------
    def listen_utterance(self, start_timeout_sec: float = 0):
        """Block until one complete utterance is captured; return float32 audio.

        start_timeout_sec: how long to wait for speech to *begin* before giving
        up and returning empty audio. 0 = wait forever (push-to-talk / passive
        mode). Set to e.g. 5.0 after a wake-word so the user has time to think.
        """
        preroll_frames = max(1, int(self.preroll * 1000 / self.frame_ms))
        hangover = max(1, int(self.end_silence * 1000 / self.frame_ms))
        max_frames = int(self.max_utt * 1000 / self.frame_ms)
        start_timeout_frames = int(start_timeout_sec * 1000 / self.frame_ms) if start_timeout_sec > 0 else 0
        ring = collections.deque(maxlen=preroll_frames)
        collected = []
        in_speech = False
        silence = 0
        spoken = 0
        waiting = 0   # frames elapsed waiting for speech to begin

        while True:
            frame = self._read_frame()
            rms = self._rms(frame)
            thresh = max(self._baseline * self.sensitivity, self.abs_floor)

            if not in_speech:
                ring.append(frame)
                waiting += 1
                if rms >= thresh:
                    in_speech = True
                    collected.extend(ring)
                    ring.clear()
                    silence = 0
                else:
                    self._baseline = 0.97 * self._baseline + 0.03 * rms
                    if start_timeout_frames and waiting >= start_timeout_frames:
                        break  # user didn't speak within the window
            else:
                collected.append(frame)
                spoken += 1
                if rms >= thresh:
                    silence = 0
                else:
                    silence += 1
                    if silence >= hangover:
                        break
                if spoken >= max_frames:
                    break

        if not collected:
            return np.zeros(0, dtype=np.float32)
        return np.concatenate(collected).astype(np.float32)
