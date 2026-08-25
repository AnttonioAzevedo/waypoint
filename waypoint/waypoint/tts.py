import subprocess

import numpy as np
import sounddevice as sd


class PiperTTS:
    """Component 8: piper-tts subprocess, played via
    sounddevice/PipeWire. is_playing mirrors ElevenLabsTTSClient.swift's
    contract so downstream "speaking" state UI logic doesn't change."""

    def __init__(self, model_path: str, piper_binary: str = "piper"):
        self.model_path = model_path
        self.piper_binary = piper_binary
        self.is_playing = False

    def speak(self, text: str) -> None:
        self.is_playing = True
        try:
            result = subprocess.run(
                [self.piper_binary, "--model", self.model_path, "--output-raw"],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                check=True,
            )
            audio = np.frombuffer(result.stdout, dtype=np.int16)
            sd.play(audio, samplerate=22050)
            sd.wait()
        finally:
            self.is_playing = False
