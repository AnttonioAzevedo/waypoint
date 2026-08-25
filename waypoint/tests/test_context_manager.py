import pytest
from waypoint.context_manager import ContextManager, Turn


def test_should_compact_false_when_under_trigger():
    cm = ContextManager(compact_trigger=1000)
    cm.record_exchange("oi", "olá")
    assert cm.should_compact() is False


def test_should_compact_true_when_over_trigger():
    cm = ContextManager(compact_trigger=10)
    cm.record_exchange("x" * 100, "y" * 100)
    assert cm.should_compact() is True


def test_compact_keeps_recent_turns_verbatim():
    cm = ContextManager(keep_recent=2)
    for i in range(5):
        cm.record_exchange(f"user{i}", f"assistant{i}")

    cm.compact(summarize_fn=lambda old_text: "SUMMARY")

    assert len(cm.turns) == 2
    assert cm.turns[0].user_text == "user3"
    assert cm.turns[1].user_text == "user4"
    assert cm.rolling_summary == "SUMMARY"


def test_compact_folds_prior_summary_into_next_call():
    cm = ContextManager(keep_recent=1)
    cm.record_exchange("a", "b")
    cm.record_exchange("c", "d")
    cm.compact(summarize_fn=lambda old_text: "FIRST SUMMARY")

    cm.record_exchange("e", "f")
    cm.record_exchange("g", "h")

    captured_old_text = {}

    def capture(old_text):
        captured_old_text["value"] = old_text
        return "SECOND SUMMARY"

    cm.compact(summarize_fn=capture)

    assert "FIRST SUMMARY" in captured_old_text["value"]
    assert cm.rolling_summary == "SECOND SUMMARY"


def test_compact_does_nothing_if_turns_fit_in_keep_recent():
    cm = ContextManager(keep_recent=10)
    cm.record_exchange("a", "b")
    result = cm.compact(summarize_fn=lambda old_text: "SHOULD NOT BE CALLED")
    assert result == ""
    assert len(cm.turns) == 1


def test_compact_falls_back_to_dropping_oldest_half_on_summarize_failure():
    cm = ContextManager(keep_recent=1)
    for i in range(5):
        cm.record_exchange(f"user{i}", f"assistant{i}")
    # 4 old turns (user0..user3) + 1 recent (user4)

    def failing_summarize(old_text):
        raise RuntimeError("summarize call failed")

    cm.compact(summarize_fn=failing_summarize)

    # oldest half of the 4 old turns (2) dropped, remaining 2 old + 1 recent kept
    assert len(cm.turns) == 3
    assert cm.turns[0].user_text == "user2"
    assert cm.turns[-1].user_text == "user4"


def test_compact_fallback_never_raises():
    cm = ContextManager(keep_recent=1)
    for i in range(3):
        cm.record_exchange(f"user{i}", f"assistant{i}")

    def failing_summarize(old_text):
        raise RuntimeError("boom")

    # Must not raise - never block the interaction (spec requirement).
    cm.compact(summarize_fn=failing_summarize)
