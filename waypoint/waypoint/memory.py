import re
from dataclasses import dataclass
from pathlib import Path

_ENTRY_PATTERN = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] session_id=(\S+) — (.+)$")


@dataclass
class MemoryEntry:
    date: str
    session_id: str
    summary: str


def format_entry(entry: MemoryEntry) -> str:
    return f"- [{entry.date}] session_id={entry.session_id} — {entry.summary}"


def parse_memory_index(index_text: str) -> list[MemoryEntry]:
    entries: list[MemoryEntry] = []
    for line in index_text.splitlines():
        match = _ENTRY_PATTERN.match(line.strip())
        if match:
            entries.append(MemoryEntry(date=match.group(1), session_id=match.group(2), summary=match.group(3)))
    return entries


def append_entry(index_path: Path, entry: MemoryEntry) -> None:
    index_path.parent.mkdir(parents=True, exist_ok=True)
    with index_path.open("a", encoding="utf-8") as f:
        f.write(format_entry(entry) + "\n")


def find_best_match(entries: list[MemoryEntry], query: str) -> MemoryEntry | None:
    """Simple word-overlap scoring - good enough for a short index of
    session summaries. Component 12's alternative (asking the current
    Claude turn to pick) is the app-level fallback when this returns
    None or the caller wants a smarter match."""
    query_words = set(query.lower().split())
    best_entry: MemoryEntry | None = None
    best_score = 0
    for entry in entries:
        summary_words = set(entry.summary.lower().split())
        score = len(query_words & summary_words)
        if score > best_score:
            best_score = score
            best_entry = entry
    return best_entry
