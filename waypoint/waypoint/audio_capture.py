import numpy as np
import sounddevice as sd


class MicRecorder:
    """Push-to-talk buffer capture (spec Component 5), converted to
    PCM16 mono for faster-whisper (Task 13)."""

    def __init__(self, samplerate: int = 16000, channels: int = 1):
        self.samplerate = samplerate
        self.channels = channels
        self._frames: list[np.ndarray] = []
        self._stream: sd.InputStream | None = None

    def _callback(self, indata, frames, time_info, status) -> None:
        self._frames.append(indata.copy())

    def start(self) -> None:
        self._frames = []
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
