import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    """Local STT via faster-whisper (spec Component 6). Model size is a
    documented open item - defaulting to "base" here, override via
    constructor for a quality/speed trade-off."""

    def __init__(self, model_size: str = "base"):
        self._model = WhisperModel(model_size, device="cpu", compute_type="int8")

    def transcribe_pcm16(self, pcm16_bytes: bytes, samplerate: int = 16000) -> str:
        audio = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _info = self._model.transcribe(audio, language="pt")
        return " ".join(segment.text.strip() for segment in segments).strip()
