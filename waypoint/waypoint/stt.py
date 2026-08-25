import numpy as np
from faster_whisper import WhisperModel


class Transcriber:
    """Component 6: transcribes the full push-to-talk buffer on
    key-up (no partial/streaming transcript, unlike the original app's
    AssemblyAI websocket)."""

    def __init__(self, model_size: str = "small", device: str = "cpu"):
        self.model = WhisperModel(model_size, device=device, compute_type="int8")

    def transcribe_pcm16(self, pcm16_bytes: bytes, samplerate: int = 16000) -> str:
        audio = np.frombuffer(pcm16_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        segments, _ = self.model.transcribe(audio, language="pt")
        return " ".join(segment.text.strip() for segment in segments)
