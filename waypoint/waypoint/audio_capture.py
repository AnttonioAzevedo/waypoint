from typing import Callable, Optional

import numpy as np
import sounddevice as sd


class MicRecorder:
    """Push-to-talk buffer capture (spec Component 5), converted to
    PCM16 mono for faster-whisper (Task 13). Optional level_callback
    reports a 0.0-1.0 RMS level per audio frame, driving the panel's
    waveform view (Task 21 - UI polish)."""

    def __init__(self, samplerate: int = 16000, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None
        self._level_callback: Optional[Callable[[float], None]] = None

    def _callback(self, indata, frames, time_info, status) -> None:
        self._frames.append(indata.copy())
        if self._level_callback is not None:
            rms = float(np.sqrt(np.mean(indata.astype(np.float32) ** 2)))
            normalized = min(1.0, rms / 32768.0 * 8.0)  # empirical scale for typical mic levels
            self._level_callback(normalized)

    def start(self, level_callback: Optional[Callable[[float], None]] = None) -> None:
        self._frames = []
        self._level_callback = level_callback
        self._stream = sd.InputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="int16",
            callback=self._callback,
        )
        self._stream.start()

    def stop(self) -> bytes:
        if self._stream is None:
            return b""
        self._stream.stop()
        self._stream.close()
        self._stream = None
        if not self._frames:
            return b""
        audio = np.concatenate(self._frames, axis=0)
        return audio.tobytes()
