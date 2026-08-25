from collections import deque
from enum import Enum, auto
from typing import Optional


class CompanionState(Enum):
    IDLE = auto()
    LISTENING = auto()
    PROCESSING = auto()
    RESPONDING = auto()


class CompanionController:
    """Single-turn push-to-talk state machine with a FIFO queue for
    hotkey releases that land while a previous turn is still in flight
    (spec Component 14)."""

    def __init__(self) -> None:
        self.state = CompanionState.IDLE
        self._queue: deque[bytes] = deque()

    def on_hotkey_press(self) -> None:
        if self.state == CompanionState.IDLE:
            self.state = CompanionState.LISTENING

    def on_hotkey_release(self, audio_buffer: bytes) -> None:
        if self.state == CompanionState.LISTENING:
            self.state = CompanionState.PROCESSING
        else:
            self._queue.append(audio_buffer)

    def start_responding(self) -> None:
        assert self.state == CompanionState.PROCESSING
        self.state = CompanionState.RESPONDING

    def finish_turn(self) -> Optional[bytes]:
        """Call once a turn's TTS playback finishes. Returns the next
        queued audio buffer to process immediately (state advances to
        PROCESSING for it), or None if the queue was empty (state
        returns to IDLE)."""
        if self._queue:
            next_buffer = self._queue.popleft()
            self.state = CompanionState.PROCESSING
            return next_buffer
        self.state = CompanionState.IDLE
        return None
