from pathlib import Path

from waypoint.memory import MemoryEntry, parse_memory_index, format_entry, append_entry, find_best_match


def test_format_entry_matches_spec_format():
    entry = MemoryEntry(date="2026-08-25", session_id="def456", summary="Design do port Linux")
    assert format_entry(entry) == "- [2026-08-25] session_id=def456 — Design do port Linux"


def test_parse_memory_index_round_trips_with_format_entry():
    index_text = (
        "- [2026-08-20] session_id=abc123 — Discutindo migração do worker Cloudflare\n"
        "- [2026-08-25] session_id=def456 — Design do port Linux\n"
    )
    entries = parse_memory_index(index_text)
    assert entries == [
        MemoryEntry(date="2026-08-20", session_id="abc123", summary="Discutindo migração do worker Cloudflare"),
        MemoryEntry(date="2026-08-25", session_id="def456", summary="Design do port Linux"),
    ]


def test_parse_memory_index_ignores_malformed_lines():
    index_text = "not a valid entry\n- [2026-08-25] session_id=def456 — Design do port Linux\n"
    entries = parse_memory_index(index_text)
    assert len(entries) == 1


def test_append_entry_writes_and_creates_parent_dir(tmp_path):
    index_path = tmp_path / "memory" / "MEMORY.md"
    entry = MemoryEntry(date="2026-08-25", session_id="def456", summary="Design do port Linux")

    append_entry(index_path, entry)

    assert index_path.exists()
    assert format_entry(entry) in index_path.read_text()


def test_append_entry_appends_without_overwriting(tmp_path):
    index_path = tmp_path / "MEMORY.md"
    append_entry(index_path, MemoryEntry("2026-08-20", "abc123", "Primeiro papo"))
    append_entry(index_path, MemoryEntry("2026-08-25", "def456", "Segundo papo"))

    lines = index_path.read_text().splitlines()
    assert len(lines) == 2


def test_find_best_match_picks_highest_word_overlap():
    entries = [
        MemoryEntry("2026-08-20", "abc123", "Discutindo migração do worker Cloudflare"),
        MemoryEntry("2026-08-25", "def456", "Design do port Linux com GTK"),
    ]
    match = find_best_match(entries, "volta naquele papo sobre o port Linux")
    assert match.session_id == "def456"


def test_find_best_match_returns_none_when_no_overlap():
    entries = [MemoryEntry("2026-08-20", "abc123", "Discutindo migração do worker Cloudflare")]
    assert find_best_match(entries, "vamos falar de receitas de bolo") is None
