from dataclasses import dataclass, field
from typing import Callable, Optional

from waypoint.config import MAX_TOKEN_BUDGET, COMPACT_TRIGGER, KEEP_RECENT


@dataclass
class Turn:
    user_text: str
    assistant_text: str


@dataclass
class ContextManager:
    max_token_budget: int = MAX_TOKEN_BUDGET
    compact_trigger: int = COMPACT_TRIGGER
    keep_recent: int = KEEP_RECENT
    turns: list[Turn] = field(default_factory=list)
    rolling_summary: Optional[str] = None

    def _approx_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def total_tokens(self) -> int:
        total = sum(self._approx_tokens(t.user_text) + self._approx_tokens(t.assistant_text) for t in self.turns)
        if self.rolling_summary:
            total += self._approx_tokens(self.rolling_summary)
        return total

    def record_exchange(self, user_text: str, assistant_text: str) -> None:
        self.turns.append(Turn(user_text, assistant_text))

    def should_compact(self) -> bool:
        return self.total_tokens() >= self.compact_trigger

    def compact(self, summarize_fn: Callable[[str], str]) -> str:
        """Component 10: summarize everything older than keep_recent,
        folding in any prior rolling summary. On summarize_fn failure,
        falls back to dropping the oldest half of the non-recent turns
        verbatim rather than blocking the interaction."""
        if len(self.turns) <= self.keep_recent:
            return self.rolling_summary or ""

        recent = self.turns[-self.keep_recent:] if self.keep_recent > 0 else []
        old = self.turns[: len(self.turns) - self.keep_recent]

        old_text = "\n".join(f"User: {t.user_text}\nAssistant: {t.assistant_text}" for t in old)
        if self.rolling_summary:
            old_text = f"{self.rolling_summary}\n\n{old_text}"

        try:
            new_summary = summarize_fn(old_text)
            self.rolling_summary = new_summary
            self.turns = recent
            return new_summary
        except Exception:
            half = len(old) // 2
            self.turns = old[half:] + recent
            return self.rolling_summary or ""
