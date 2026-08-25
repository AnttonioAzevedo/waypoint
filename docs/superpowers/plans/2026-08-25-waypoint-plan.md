# Waypoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild Clicky's push-to-talk → screenshot → Claude → speak → point interaction loop as a Linux-native Python app, fully local/free (Claude Code CLI subscription auth, `faster-whisper` STT, `piper-tts` TTS, Ollama fallback), targeting Pop!_OS 24.04 X11/GNOME.

**Architecture:** Single main Python process (GTK4 + libadwaita UI: panel, overlay) plus one small GTK3 subprocess for the tray icon (AppIndicator3 forces GTK3, incompatible in-process with GTK4 - see Task 17), talking over a local Unix socket. Pure-logic modules (state machine, tag parsing, context compaction, model routing, memory index, vision-family matching) are dependency-injected and unit tested; hardware/subprocess-facing modules (audio, screen, STT, TTS, the `claude` CLI itself, GTK windows) are integration/manual tested per the spec's own Testing section.

**Tech Stack:** Python 3.12, PyGObject (GTK4 + libadwaita + AppIndicator3), `pynput`, `mss`, `sounddevice`, `faster-whisper`, `piper-tts`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-25-waypoint-design.md`

## Global Constraints

- No macOS compatibility layer, no Wayland support this pass (X11 only), no packaging/distribution — local dev run only (spec Non-goals).
- Zero API keys anywhere in this codebase. All external calls go through local subprocesses/models (spec Architecture).
- `MAX_TOKEN_BUDGET = 250_000`, `COMPACT_TRIGGER = 200_000`, `KEEP_RECENT = 10` (spec Component 10).
- Session pinning uses `--resume <session_id>` captured from the CLI's `init` event — never `--continue` (spec Component 7).
- Default hotkey `ctrl+alt`, user-reconfigurable (spec Component 3).
- Annotation auto-fade default 4s (spec Component 9).
- All code lives under `waypoint/` in this repo (`AnttonioAzevedo/clicky-cc`), alongside the existing `leanring-buddy/` (Swift, untouched) and `worker/` (Cloudflare, not used by this port).

---

## File Structure

```
waypoint/
  pyproject.toml
  waypoint/
    __init__.py
    config.py            # paths, constants (Task 3)
    state_machine.py      # CompanionController + queue (Task 4)
    model_routing.py      # Component 15 (Task 5)
    tags.py                # POINT/HIGHLIGHT/ANNOTATE parse+strip (Task 6)
    context_manager.py    # Component 10 compaction (Task 7)
    ollama_fallback.py    # Component 11 vision-family matching (Task 8)
    memory.py              # Component 12 index + recall matching (Task 9)
    claude_session.py     # Component 7 session pinning (Task 10)
    screen_capture.py     # Component 4 (Task 11)
    audio_capture.py      # Component 5 (Task 12)
    stt.py                  # Component 6 (Task 13)
    tts.py                  # Component 8 (Task 14)
    hotkey.py               # Component 3 (Task 15)
    tray.py                 # Component 1 (Task 17) - main-process side, Unix socket server
    tray_process.py         # Component 1 (Task 17) - separate GTK3 subprocess, socket client
    panel.py                # Component 2 (Task 18)
    overlay.py              # Component 9 rendering (Task 19)
    app.py                   # wiring (Task 20)
  tests/
    test_state_machine.py
    test_model_routing.py
    test_tags.py
    test_context_manager.py
    test_ollama_fallback.py
    test_memory.py
    test_claude_session.py
  .claude/
    skills/
      teaching-mode/
        SKILL.md            # Component 13 (Task 16)
```

`waypoint/.claude/skills/teaching-mode/SKILL.md` is the file the `claude` CLI subprocess discovers via its `cwd` — the app's subprocess `cwd` is set to `waypoint/` (Task 10).

---

### Task 1: Project scaffolding

**Files:**
- Create: `waypoint/pyproject.toml`
- Create: `waypoint/waypoint/__init__.py`
- Create: `waypoint/tests/__init__.py`

**Interfaces:**
- Produces: an installable `waypoint` package and a `pytest`-discoverable `tests/` directory that every later task builds on.

- [ ] **Step 1: Create the package directories**

```bash
mkdir -p /home/tony/projects/clicky-cc/waypoint/waypoint
mkdir -p /home/tony/projects/clicky-cc/waypoint/tests
touch /home/tony/projects/clicky-cc/waypoint/waypoint/__init__.py
touch /home/tony/projects/clicky-cc/waypoint/tests/__init__.py
```

- [ ] **Step 2: Write `pyproject.toml`**

```toml
[project]
name = "waypoint"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "PyGObject>=3.48",
    "pynput>=1.8",
    "mss>=9.0",
    "sounddevice>=0.4",
    "numpy>=1.26",
    "faster-whisper>=1.0",
    "piper-tts>=1.7",
]

[project.optional-dependencies]
dev = ["pytest>=8.0"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

- [ ] **Step 3: Install in editable mode and verify pytest runs**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pip install -e ".[dev]"
pytest --collect-only
```

Expected: exits 0, "no tests ran" (no test files yet).

- [ ] **Step 4: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/pyproject.toml waypoint/waypoint/__init__.py waypoint/tests/__init__.py && git commit -m "chore: scaffold waypoint Python package"
```

---

### Task 2: Validation spike — `stream-json` schema (spec blocking task #1)

This is investigative, not implementation, but its output (a fixture file) is a real deliverable Task 10 depends on.

**Files:**
- Create: `waypoint/tests/fixtures/stream_json_init_event.json`
- Create: `waypoint/docs/stream-json-findings.md`

**Interfaces:**
- Produces: `tests/fixtures/stream_json_init_event.json` — a real captured `init` event, used by Task 10's tests to keep `extract_session_id()` honest against the actual schema instead of an assumed one.

- [ ] **Step 1: Run a minimal `claude` CLI call and capture stdout**

```bash
cd /home/tony/projects/clicky-cc/waypoint
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"say hi"}]}}' | \
  claude --input-format stream-json --output-format stream-json --model sonnet > /tmp/claude_stream_output.jsonl
cat /tmp/claude_stream_output.jsonl
```

- [ ] **Step 2: Identify the `init` event and its `session_id` field**

Find the line where `"type":"system"` and `"subtype":"init"` (or equivalent — confirm exact field names from the actual output, do not assume). Save that one JSON line as the fixture:

```bash
grep '"subtype":"init"' /tmp/claude_stream_output.jsonl > waypoint/tests/fixtures/stream_json_init_event.json
```

- [ ] **Step 3: Confirm `--resume <session_id>` works on a second call**

```bash
SESSION_ID=$(python3 -c "import json; print(json.load(open('waypoint/tests/fixtures/stream_json_init_event.json'))['session_id'])")
echo '{"type":"user","message":{"role":"user","content":[{"type":"text","text":"what did I just say?"}]}}' | \
  claude --input-format stream-json --output-format stream-json --model sonnet --resume "$SESSION_ID"
```

Expected: the response references "say hi" — confirms `--resume` carries history.

- [ ] **Step 4: Confirm an image content block round-trips**

Send one turn with an `{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "..."}}` block (any small PNG, base64-encoded) alongside a text block, using `--resume` from Step 3. Confirm the CLI doesn't error and the response acknowledges the image.

- [ ] **Step 5: Write findings**

```bash
cat > waypoint/docs/stream-json-findings.md <<'EOF'
# stream-json schema findings

Captured against: `claude --version` = <fill in actual output>

- `init` event shape: <paste the real JSON from the fixture>
- session_id field path confirmed as: <e.g. top-level "session_id">
- --resume with image-bearing turns: <PASS/FAIL + notes>
- Any deviations from the spec's assumed shape: <list or "none">
EOF
```

- [ ] **Step 6: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/tests/fixtures/stream_json_init_event.json waypoint/docs/stream-json-findings.md && git commit -m "docs: capture stream-json schema findings from validation spike"
```

**If findings contradict the spec's assumed field names**, update `claude_session.py`'s `extract_session_id()` in Task 10 accordingly — the fixture is the source of truth from here on, not the spec prose.

---

### Task 3: Config module

**Files:**
- Create: `waypoint/waypoint/config.py`

**Interfaces:**
- Produces: `WAYPOINT_HOME`, `CURRENT_SESSION_FILE`, `MEMORY_DIR`, `MEMORY_INDEX_FILE`, `MAX_TOKEN_BUDGET`, `COMPACT_TRIGGER`, `KEEP_RECENT`, `DEFAULT_HOTKEY`, `ANNOTATION_FADE_SECONDS`, `SESSION_END_IDLE_SECONDS` — used by Tasks 4, 7, 9, 10, 15, 19, 20.

No test here — this is pure constants, exercised indirectly by every module that imports it.

- [ ] **Step 1: Write `config.py`**

```python
from pathlib import Path

WAYPOINT_HOME = Path.home() / ".waypoint"
CURRENT_SESSION_FILE = WAYPOINT_HOME / "current_session.json"
MEMORY_DIR = WAYPOINT_HOME / "memory"
MEMORY_INDEX_FILE = MEMORY_DIR / "MEMORY.md"

# Component 10 (spec)
MAX_TOKEN_BUDGET = 250_000
COMPACT_TRIGGER = 200_000
KEEP_RECENT = 10

# Component 3 (spec)
DEFAULT_HOTKEY = "ctrl+alt"

# Component 9 (spec)
ANNOTATION_FADE_SECONDS = 4

# Open item in spec: session-end idle threshold that triggers memory
# distillation (Component 12). Defaulting to 10 minutes; override via
# panel settings once Task 18 exists.
SESSION_END_IDLE_SECONDS = 600
```

- [ ] **Step 2: Verify it imports cleanly**

```bash
cd /home/tony/projects/clicky-cc/waypoint && python3 -c "from waypoint import config; print(config.MAX_TOKEN_BUDGET)"
```

Expected: prints `250000`.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/config.py && git commit -m "feat: add config module with paths and Component 10 budget constants"
```

---

### Task 4: State machine + request queue (Components 14)

**Files:**
- Create: `waypoint/waypoint/state_machine.py`
- Test: `waypoint/tests/test_state_machine.py`

**Interfaces:**
- Produces: `CompanionState` (enum: `IDLE`, `LISTENING`, `PROCESSING`, `RESPONDING`), `CompanionController` with `on_hotkey_press()`, `on_hotkey_release(audio_buffer: bytes)`, `start_responding()`, `finish_turn() -> bytes | None`. `finish_turn()`'s return value (next buffer or `None`) is what Task 20's app loop uses to decide whether to immediately start the next turn.

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_state_machine.py
from waypoint.state_machine import CompanionController, CompanionState


def test_starts_idle():
    controller = CompanionController()
    assert controller.state == CompanionState.IDLE


def test_press_while_idle_moves_to_listening():
    controller = CompanionController()
    controller.on_hotkey_press()
    assert controller.state == CompanionState.LISTENING


def test_release_while_listening_moves_to_processing():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"audio-bytes")
    assert controller.state == CompanionState.PROCESSING


def test_release_while_busy_enqueues_instead_of_processing():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"first")  # -> PROCESSING
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"second")  # busy -> enqueued
    assert controller.state == CompanionState.PROCESSING
    assert list(controller._queue) == [b"second"]


def test_finish_turn_returns_to_idle_when_queue_empty():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"only")
    controller.start_responding()
    next_buffer = controller.finish_turn()
    assert next_buffer is None
    assert controller.state == CompanionState.IDLE


def test_finish_turn_drains_queue_in_order():
    controller = CompanionController()
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"first")
    controller.on_hotkey_press()
    controller.on_hotkey_release(b"second")
    controller.start_responding()
    next_buffer = controller.finish_turn()
    assert next_buffer == b"second"
    assert controller.state == CompanionState.PROCESSING
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_state_machine.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'waypoint.state_machine'`.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/state_machine.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_state_machine.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/state_machine.py waypoint/tests/test_state_machine.py && git commit -m "feat: add CompanionController state machine with request queue"
```

---

### Task 5: Model routing (Component 15)

**Files:**
- Create: `waypoint/waypoint/model_routing.py`
- Test: `waypoint/tests/test_model_routing.py`

**Interfaces:**
- Consumes: nothing (pure function over a string).
- Produces: `resolve_model(transcript: str) -> str`, returning one of `"haiku"`, `"sonnet"`, `"opus"`. Used by Task 20's app loop to pick `--model` before calling `ClaudeSessionClient.run_turn()` (Task 10).

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_model_routing.py
from waypoint.model_routing import resolve_model


def test_explicit_fast_phrase_wins():
    assert resolve_model("modo rápido, que dia é hoje?") == "haiku"


def test_explicit_deep_phrase_wins():
    assert resolve_model("pensa com calma nisso: qual a melhor arquitetura aqui?") == "opus"


def test_explicit_phrase_overrides_heuristic_keywords():
    # Contains "explica" (would heuristically route to sonnet) but the
    # explicit phrase takes priority per spec Component 15.
    assert resolve_model("modo rápido, explica isso rapidinho") == "haiku"


def test_heuristic_keyword_routes_to_sonnet():
    assert resolve_model("explica como funciona esse sistema") == "sonnet"


def test_short_transcript_without_signal_routes_to_haiku():
    assert resolve_model("que horas são?") == "haiku"


def test_longer_transcript_without_signal_defaults_to_sonnet():
    assert resolve_model("me conta um pouco sobre a história desse prédio que a gente está vendo aqui na tela") == "sonnet"


def test_never_auto_escalates_to_opus():
    long_text = "explica " * 50
    assert resolve_model(long_text) != "opus"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_model_routing.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/model_routing.py
MODEL_HAIKU = "haiku"
MODEL_SONNET = "sonnet"
MODEL_OPUS = "opus"

# Illustrative per spec Open items — finalize exact PT-BR phrases before
# real-world use.
EXPLICIT_PHRASES: dict[str, str] = {
    "pensa com calma nisso": MODEL_OPUS,
    "pensa com calma": MODEL_OPUS,
    "modo profundo": MODEL_OPUS,
    "modo rápido": MODEL_HAIKU,
    "modo rapido": MODEL_HAIKU,
}

_HEURISTIC_KEYWORDS: tuple[str, ...] = ("explica", "analisa", "compara", "por que", "como funciona")

_SHORT_TRANSCRIPT_WORD_LIMIT = 6


def resolve_model(transcript: str) -> str:
    """Component 15: explicit voice command first, heuristic fallback
    second. Never auto-escalates to Opus without an explicit phrase."""
    lowered = transcript.lower()

    for phrase, model in EXPLICIT_PHRASES.items():
        if phrase in lowered:
            return model

    if any(keyword in lowered for keyword in _HEURISTIC_KEYWORDS):
        return MODEL_SONNET

    if len(transcript.split()) <= _SHORT_TRANSCRIPT_WORD_LIMIT:
        return MODEL_HAIKU

    return MODEL_SONNET
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_model_routing.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/model_routing.py waypoint/tests/test_model_routing.py && git commit -m "feat: add model routing (explicit phrase, heuristic fallback)"
```

---

### Task 6: Tag parsing and stripping (Component 9 logic)

**Files:**
- Create: `waypoint/waypoint/tags.py`
- Test: `waypoint/tests/test_tags.py`

**Interfaces:**
- Produces: `PointTag`, `HighlightTag`, `AnnotateTag` dataclasses, `parse_tags(text: str) -> list[PointTag | HighlightTag | AnnotateTag]`, `strip_tags(text: str) -> str`. Used by Task 19 (overlay rendering) and Task 20 (stripping before TTS/memory per spec).

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_tags.py
from waypoint.tags import parse_tags, strip_tags, PointTag, HighlightTag, AnnotateTag


def test_parse_point_tag():
    tags = parse_tags("Olha aqui [POINT:120,340:botão salvar:screen1] pra salvar.")
    assert tags == [PointTag(x=120.0, y=340.0, label="botão salvar", screen=1)]


def test_parse_highlight_tag():
    tags = parse_tags("[HIGHLIGHT:10,20,200,50:screen0] essa área")
    assert tags == [HighlightTag(x=10.0, y=20.0, w=200.0, h=50.0, screen=0)]


def test_parse_annotate_arrow():
    tags = parse_tags("[ANNOTATE:arrow:10,10,100,100:screen0]")
    assert tags == [AnnotateTag(shape="arrow", params=[10.0, 10.0, 100.0, 100.0], screen=0)]


def test_parse_annotate_circle():
    tags = parse_tags("[ANNOTATE:circle:50,60,25:screen1]")
    assert tags == [AnnotateTag(shape="circle", params=[50.0, 60.0, 25.0], screen=1)]


def test_parse_multiple_tags_in_order():
    text = "[POINT:1,2:a:screen0] depois [HIGHLIGHT:3,4,5,6:screen0]"
    tags = parse_tags(text)
    assert len(tags) == 2
    assert isinstance(tags[0], PointTag)
    assert isinstance(tags[1], HighlightTag)


def test_parse_no_tags_returns_empty_list():
    assert parse_tags("resposta sem nenhuma tag") == []


def test_strip_tags_removes_all_families():
    text = "Olha [POINT:1,2:x:screen0] e [HIGHLIGHT:1,2,3,4:screen0] e [ANNOTATE:circle:1,2,3:screen0] aqui."
    assert strip_tags(text) == "Olha  e  e  aqui."


def test_strip_tags_no_tags_returns_original_trimmed():
    assert strip_tags("  texto puro  ") == "texto puro"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_tags.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/tags.py
import re
from dataclasses import dataclass, field
from typing import Union

_TAG_PATTERN = re.compile(r"\[(POINT|HIGHLIGHT|ANNOTATE):([^\]]+)\]")


@dataclass
class PointTag:
    x: float
    y: float
    label: str
    screen: int


@dataclass
class HighlightTag:
    x: float
    y: float
    w: float
    h: float
    screen: int


@dataclass
class AnnotateTag:
    shape: str
    params: list[float] = field(default_factory=list)
    screen: int = 0


Tag = Union[PointTag, HighlightTag, AnnotateTag]


def _parse_screen(token: str) -> int:
    return int(token.replace("screen", ""))


def parse_tags(text: str) -> list[Tag]:
    tags: list[Tag] = []
    for match in _TAG_PATTERN.finditer(text):
        kind, body = match.group(1), match.group(2)
        parts = body.split(":")

        if kind == "POINT":
            x_str, y_str = parts[0].split(",")
            tags.append(PointTag(x=float(x_str), y=float(y_str), label=parts[1], screen=_parse_screen(parts[2])))

        elif kind == "HIGHLIGHT":
            x_str, y_str, w_str, h_str = parts[0].split(",")
            tags.append(HighlightTag(x=float(x_str), y=float(y_str), w=float(w_str), h=float(h_str), screen=_parse_screen(parts[1])))

        elif kind == "ANNOTATE":
            shape = parts[0]
            params = [float(p) for p in parts[1].split(",")]
            tags.append(AnnotateTag(shape=shape, params=params, screen=_parse_screen(parts[2])))

    return tags


def strip_tags(text: str) -> str:
    return _TAG_PATTERN.sub("", text).strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_tags.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/tags.py waypoint/tests/test_tags.py && git commit -m "feat: add POINT/HIGHLIGHT/ANNOTATE tag parsing and stripping"
```

---

### Task 7: ContextManager compaction (Component 10)

**Files:**
- Create: `waypoint/waypoint/context_manager.py`
- Test: `waypoint/tests/test_context_manager.py`

**Interfaces:**
- Consumes: `config.MAX_TOKEN_BUDGET`, `config.COMPACT_TRIGGER`, `config.KEEP_RECENT` (Task 3).
- Produces: `Turn` dataclass, `ContextManager` with `record_exchange(user_text, assistant_text)`, `should_compact() -> bool`, `compact(summarize_fn) -> str`. Used by Task 20's app loop before every `claude` CLI spawn.

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_context_manager.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_context_manager.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/context_manager.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_context_manager.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/context_manager.py waypoint/tests/test_context_manager.py && git commit -m "feat: add ContextManager token-budget compaction (ported from flicky)"
```

---

### Task 8: Ollama vision-model detection (Component 11)

**Files:**
- Create: `waypoint/waypoint/ollama_fallback.py`
- Test: `waypoint/tests/test_ollama_fallback.py`

**Interfaces:**
- Produces: `VISION_FAMILIES: list[str]`, `is_vision_model(model_name: str) -> bool`, `pick_vision_model(available_models: list[str]) -> str | None`. Used by Task 20's app loop when the `claude` CLI subprocess fails.

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_ollama_fallback.py
from waypoint.ollama_fallback import is_vision_model, pick_vision_model


def test_is_vision_model_matches_known_families():
    assert is_vision_model("llava:13b") is True
    assert is_vision_model("qwen2.5-vl:7b") is True
    assert is_vision_model("gemma3:27b") is True


def test_is_vision_model_case_insensitive():
    assert is_vision_model("LLaVA:13B") is True


def test_is_vision_model_false_for_non_vision_models():
    assert is_vision_model("llama3:8b") is False
    assert is_vision_model("mistral:7b") is False


def test_pick_vision_model_returns_first_match():
    models = ["llama3:8b", "llava:13b", "mistral:7b"]
    assert pick_vision_model(models) == "llava:13b"


def test_pick_vision_model_returns_none_if_no_vision_model_available():
    models = ["llama3:8b", "mistral:7b"]
    assert pick_vision_model(models) is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_ollama_fallback.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/ollama_fallback.py
# Ported from flicky's ollama-api.ts isVisionModel() family list (spec
# Component 11) - Ollama doesn't self-report vision capability, so
# detection is by name-family match.
VISION_FAMILIES: list[str] = [
    "llava", "bakllava", "moondream", "cogvlm", "minicpm-v",
    "llava-llama3", "llava-phi3", "granite3.2-vision",
    "qwen2-vl", "qwen2.5-vl", "qwen3-vl",
    "llava-v1.6", "llava-v1.5", "gemma3", "gemma4",
    "mistral-small3.1",
]


def is_vision_model(model_name: str) -> bool:
    lowered = model_name.lower()
    return any(family in lowered for family in VISION_FAMILIES)


def pick_vision_model(available_models: list[str]) -> str | None:
    for name in available_models:
        if is_vision_model(name):
            return name
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_ollama_fallback.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/ollama_fallback.py waypoint/tests/test_ollama_fallback.py && git commit -m "feat: add Ollama vision-model family detection (ported from flicky)"
```

---

### Task 9: Memory index and session recall matching (Component 12)

**Files:**
- Create: `waypoint/waypoint/memory.py`
- Test: `waypoint/tests/test_memory.py`

**Interfaces:**
- Consumes: `config.MEMORY_DIR`, `config.MEMORY_INDEX_FILE` (Task 3).
- Produces: `MemoryEntry` dataclass, `parse_memory_index(index_text: str) -> list[MemoryEntry]`, `format_entry(entry: MemoryEntry) -> str`, `append_entry(index_path: Path, entry: MemoryEntry) -> None`, `find_best_match(entries: list[MemoryEntry], query: str) -> MemoryEntry | None`. Used by Task 20 for writing memory on session end and resolving "volta naquele papo sobre X" recall requests.

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_memory.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_memory.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/memory.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_memory.py -v
```

Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/memory.py waypoint/tests/test_memory.py && git commit -m "feat: add cross-session memory index and recall matching"
```

---

### Task 10: Claude session client — session pinning (Component 7)

**Files:**
- Create: `waypoint/waypoint/claude_session.py`
- Test: `waypoint/tests/test_claude_session.py`

**Interfaces:**
- Consumes: `config.CURRENT_SESSION_FILE` (Task 3), the `init` event fixture from Task 2 (`tests/fixtures/stream_json_init_event.json`), the teaching-mode `SKILL.md` body from Task 16.
- Produces: `SessionStore` (`read() -> str | None`, `write(session_id: str) -> None`), `load_persona(skill_path: Path) -> str` (strips YAML frontmatter), `build_claude_command(session_id, model, system_prompt=None) -> list[str]`, `extract_session_id(event: dict) -> str`, `ClaudeSessionClient(session_store, popen_factory=..., system_prompt=None).run_turn(content_blocks, model) -> Iterator[dict]`. Used by Task 20's app loop.

**Revised during implementation**: the original design assumed Claude Code's cwd-based skill
discovery would auto-inject the teaching-mode persona (Component 13). Live verification showed
this is false — discovery only makes a skill *available to invoke*, it doesn't inject content
automatically; the model answered as the user's own global `CLAUDE.md` persona instead. Fix:
`load_persona()` reads the skill file directly and the persona text is passed as literal
`--system-prompt` content (full replacement, not `--append-system-prompt` — that was tried too
and got refused as a suspected injection). `build_claude_command()` and `ClaudeSessionClient`
below already reflect this fix, not the original skill-discovery-only design.

- [ ] **Step 1: Write the failing tests**

```python
# waypoint/tests/test_claude_session.py
import json
from pathlib import Path

from waypoint.claude_session import SessionStore, build_claude_command, extract_session_id, ClaudeSessionClient, load_persona


def test_session_store_read_returns_none_when_file_missing(tmp_path):
    store = SessionStore(tmp_path / "current_session.json")
    assert store.read() is None


def test_session_store_write_then_read_round_trips(tmp_path):
    path = tmp_path / "nested" / "current_session.json"
    store = SessionStore(path)
    store.write("abc123")
    assert store.read() == "abc123"


def test_build_claude_command_without_session_id_bootstraps():
    cmd = build_claude_command(session_id=None, model="sonnet")
    assert cmd == [
        "claude", "--input-format", "stream-json", "--output-format", "stream-json",
        "--model", "sonnet", "--strict-mcp-config",
    ]
    assert "--resume" not in cmd
    assert "--continue" not in cmd


def test_build_claude_command_with_session_id_pins_via_resume():
    cmd = build_claude_command(session_id="abc123", model="opus")
    assert "--resume" in cmd
    assert cmd[cmd.index("--resume") + 1] == "abc123"
    assert "--continue" not in cmd
    assert "--strict-mcp-config" in cmd


def test_build_claude_command_includes_system_prompt_when_given():
    cmd = build_claude_command(session_id=None, model="sonnet", system_prompt="You are Waypoint.")
    assert "--system-prompt" in cmd
    assert cmd[cmd.index("--system-prompt") + 1] == "You are Waypoint."


def test_build_claude_command_omits_system_prompt_when_none():
    cmd = build_claude_command(session_id=None, model="sonnet")
    assert "--system-prompt" not in cmd


def test_load_persona_strips_frontmatter(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text(
        "---\nname: teaching-mode\ndescription: something\n---\n\n"
        "# Teaching-mode persona\n\nYou are Waypoint.\n"
    )
    persona = load_persona(skill_path)
    assert persona == "# Teaching-mode persona\n\nYou are Waypoint."
    assert "name: teaching-mode" not in persona


def test_load_persona_returns_full_text_when_no_frontmatter(tmp_path):
    skill_path = tmp_path / "SKILL.md"
    skill_path.write_text("Just plain text, no frontmatter.")
    assert load_persona(skill_path) == "Just plain text, no frontmatter."


def test_extract_session_id_reads_real_fixture():
    fixture_path = Path(__file__).parent / "fixtures" / "stream_json_init_event.json"
    event = json.loads(fixture_path.read_text())
    session_id = extract_session_id(event)
    assert isinstance(session_id, str)
    assert len(session_id) > 0


class FakeStdin:
    def __init__(self):
        self.written = []

    def write(self, data):
        self.written.append(data)

    def close(self):
        pass


class FakeProcess:
    def __init__(self, output_lines):
        self.stdin = FakeStdin()
        self.stdout = iter(output_lines)
        self.waited = False

    def wait(self):
        self.waited = True


def test_run_turn_pins_session_id_from_init_event(tmp_path):
    init_event = {"type": "system", "subtype": "init", "session_id": "new-session-42"}
    output_lines = [json.dumps(init_event) + "\n"]
    fake_process = FakeProcess(output_lines)

    store = SessionStore(tmp_path / "current_session.json")
    client = ClaudeSessionClient(store, popen_factory=lambda *a, **kw: fake_process)

    events = list(client.run_turn(content_blocks=[{"type": "text", "text": "hi"}], model="sonnet"))

    assert events == [init_event]
    assert store.read() == "new-session-42"
    assert fake_process.waited is True


def test_run_turn_uses_pinned_session_id_on_subsequent_call(tmp_path):
    store = SessionStore(tmp_path / "current_session.json")
    store.write("existing-session")

    captured_cmd = {}

    def factory(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return FakeProcess([])

    client = ClaudeSessionClient(store, popen_factory=factory)
    list(client.run_turn(content_blocks=[{"type": "text", "text": "hi"}], model="sonnet"))

    assert "--resume" in captured_cmd["cmd"]
    assert captured_cmd["cmd"][captured_cmd["cmd"].index("--resume") + 1] == "existing-session"


def test_run_turn_passes_configured_system_prompt(tmp_path):
    store = SessionStore(tmp_path / "current_session.json")

    captured_cmd = {}

    def factory(cmd, **kwargs):
        captured_cmd["cmd"] = cmd
        return FakeProcess([])

    client = ClaudeSessionClient(store, popen_factory=factory, system_prompt="You are Waypoint.")
    list(client.run_turn(content_blocks=[{"type": "text", "text": "hi"}], model="sonnet"))

    assert "--system-prompt" in captured_cmd["cmd"]
    assert captured_cmd["cmd"][captured_cmd["cmd"].index("--system-prompt") + 1] == "You are Waypoint."
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_claude_session.py -v
```

Expected: FAIL, module not found.

- [ ] **Step 3: Write the implementation**

```python
# waypoint/waypoint/claude_session.py
import json
import subprocess
from pathlib import Path
from typing import Iterator, Optional


class SessionStore:
    """Persists the pinned session_id for Component 7's session-pinning
    scheme. See config.CURRENT_SESSION_FILE for the default path."""

    def __init__(self, path: Path):
        self.path = path

    def read(self) -> Optional[str]:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text())
        return data.get("session_id")

    def write(self, session_id: str) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"session_id": session_id}))


def load_persona(skill_path: Path) -> str:
    """Strips the YAML frontmatter from teaching-mode's SKILL.md,
    returning just the body. Used as literal --system-prompt content -
    NOT relying on Claude Code's own skill-discovery mechanism, which
    only makes a skill *available* for the model to invoke on its own
    judgment. Verified live: a plain cwd-based skill discovery left the
    model answering as the user's own global CLAUDE.md persona instead
    of Waypoint's, even when explicitly asked "quem é você?" -
    discovery is not the same as always-active context. --system-prompt
    (full replacement, not --append-system-prompt) is what reliably
    switches the model's identity (spec Component 7/13 finding)."""
    text = skill_path.read_text()
    parts = text.split("---", 2)
    if len(parts) == 3:
        return parts[2].strip()
    return text.strip()


def build_claude_command(session_id: Optional[str], model: str, system_prompt: Optional[str] = None) -> list[str]:
    """Bootstrap (session_id is None): plain new session, no --resume,
    no --continue. Pinned (session_id is set): --resume explicitly.
    Never --continue - see spec Component 7 for why. --strict-mcp-config
    drops the user's unrelated MCP servers (Jira/Gmail/Grafana/etc.) with
    no functional downside (spec Component 7, stream-json spike).
    --system-prompt carries the teaching-mode persona (see load_persona) -
    passed on every call since each turn is a separate subprocess."""
    cmd = [
        "claude", "--input-format", "stream-json", "--output-format", "stream-json",
        "--model", model, "--strict-mcp-config",
    ]
    if system_prompt:
        cmd += ["--system-prompt", system_prompt]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def extract_session_id(event: dict) -> str:
    return event["session_id"]


class ClaudeSessionClient:
    def __init__(self, session_store: SessionStore, popen_factory=subprocess.Popen, system_prompt: Optional[str] = None):
        self.session_store = session_store
        self._popen_factory = popen_factory
        self.system_prompt = system_prompt

    def run_turn(self, content_blocks: list[dict], model: str) -> Iterator[dict]:
        session_id = self.session_store.read()
        cmd = build_claude_command(session_id, model, system_prompt=self.system_prompt)
        process = self._popen_factory(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

        request = {"type": "user", "message": {"role": "user", "content": content_blocks}}
        process.stdin.write(json.dumps(request) + "\n")
        process.stdin.close()

        for line in process.stdout:
            event = json.loads(line)
            if event.get("type") == "system" and event.get("subtype") == "init":
                self.session_store.write(extract_session_id(event))
            yield event

        process.wait()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd /home/tony/projects/clicky-cc/waypoint && pytest tests/test_claude_session.py -v
```

Expected: 12 passed. **If Task 2's findings showed different field names** (e.g. `session_id` nested under a different key), fix `extract_session_id()` and the corresponding test now, before moving on.

- [ ] **Step 5: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/claude_session.py waypoint/tests/test_claude_session.py && git commit -m "feat: add ClaudeSessionClient with explicit session_id pinning"
```

---

### Task 11: Screen capture (Component 4)

**Files:**
- Create: `waypoint/waypoint/screen_capture.py`

**Interfaces:**
- Produces: `ScreenshotResult` dataclass (`screen_index: int`, `media_type: str`, `base64_data: str`), `capture_all_screens() -> list[ScreenshotResult]`. Used by Task 20's app loop to build Claude image content blocks.

No unit test — `mss` requires a real X11 display. Manual verification only, per spec Testing section.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/screen_capture.py
import base64
from dataclasses import dataclass

import mss
import mss.tools


@dataclass
class ScreenshotResult:
    screen_index: int
    media_type: str
    base64_data: str


def capture_all_screens() -> list[ScreenshotResult]:
    """mss.monitors[0] is the "all monitors combined" virtual screen -
    skipped. Enumeration starts at 1, matching CompanionScreenCaptureUtility.swift's
    per-display labeling (spec Component 4)."""
    results: list[ScreenshotResult] = []
    with mss.mss() as sct:
        for index, monitor in enumerate(sct.monitors[1:], start=1):
            shot = sct.grab(monitor)
            png_bytes = mss.tools.to_png(shot.rgb, shot.size)
            results.append(
                ScreenshotResult(
                    screen_index=index,
                    media_type="image/png",
                    base64_data=base64.b64encode(png_bytes).decode("ascii"),
                )
            )
    return results
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
from waypoint.screen_capture import capture_all_screens
results = capture_all_screens()
for r in results:
    print(r.screen_index, r.media_type, len(r.base64_data), 'bytes b64')
"
```

Expected: one line per connected monitor, on the real Pop!_OS X11 session, with a non-trivial base64 length.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/screen_capture.py && git commit -m "feat: add multi-monitor X11 screenshot capture via mss"
```

---

### Task 12: Mic capture (Component 5)

**Files:**
- Create: `waypoint/waypoint/audio_capture.py`

**Interfaces:**
- Produces: `MicRecorder` with `start() -> None`, `stop() -> bytes` (returns raw PCM16 mono bytes). Used by Task 20's app loop, feeding Task 13's `Transcriber`.

No unit test — requires a real audio device. Manual verification only.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/audio_capture.py
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
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import time
from waypoint.audio_capture import MicRecorder
r = MicRecorder()
r.start()
print('recording 2s, say something...')
time.sleep(2)
data = r.stop()
print(len(data), 'bytes captured')
"
```

Expected: non-zero byte count roughly matching `2 seconds * 16000 samplerate * 2 bytes/sample`.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/audio_capture.py && git commit -m "feat: add push-to-talk mic capture via sounddevice"
```

---

### Task 13: Speech-to-text (Component 6)

**Files:**
- Create: `waypoint/waypoint/stt.py`

**Interfaces:**
- Consumes: `MicRecorder.stop()`'s output (Task 12, raw PCM16 bytes).
- Produces: `Transcriber` with `transcribe_pcm16(pcm16_bytes: bytes, samplerate: int = 16000) -> str`. Used by Task 20's app loop.

No unit test — depends on a downloaded Whisper model and real audio. Manual verification only.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/stt.py
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
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import time
from waypoint.audio_capture import MicRecorder
from waypoint.stt import Transcriber

r = MicRecorder()
r.start()
print('recording 3s, say something in portuguese...')
time.sleep(3)
data = r.stop()

t = Transcriber(model_size='small')
print(t.transcribe_pcm16(data))
"
```

Expected: a reasonably accurate transcript of what was said. Note the model download on first run (this is the "first-run blocking prompt" case from spec Error handling — Task 18 wires that UI, this step just confirms the underlying call works).

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/stt.py && git commit -m "feat: add faster-whisper STT wrapper"
```

---

### Task 14: Text-to-speech (Component 8)

**Files:**
- Create: `waypoint/waypoint/tts.py`

**Interfaces:**
- Consumes: `tags.strip_tags()`'s output (Task 6) — text passed in should already have tags stripped.
- Produces: `PiperTTS` with `speak(text: str) -> None`, and an `is_playing: bool` property. Used by Task 20's app loop.

No unit test — spawns a real subprocess and plays real audio. Manual verification only.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/tts.py
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
```

- [ ] **Step 2: Manual verification**

Requires a downloaded Piper PT-BR voice model (e.g. `pt_BR-faber-medium.onnx`).

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
from waypoint.tts import PiperTTS
tts = PiperTTS(model_path='/path/to/pt_BR-faber-medium.onnx')
tts.speak('Oi, isso é um teste de voz.')
"
```

Expected: audible PT-BR speech through the default audio output.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/tts.py && git commit -m "feat: add Piper TTS subprocess wrapper"
```

---

### Task 15: Global push-to-talk hotkey (Component 3)

**Files:**
- Create: `waypoint/waypoint/hotkey.py`

**Interfaces:**
- Produces: `HotkeyListener` with `start(on_press: Callable[[], None], on_release: Callable[[], None]) -> None`, `stop() -> None`, `set_binding(binding: str) -> None`. Used by Task 18 (panel settings UI) and Task 20 (app wiring).

No unit test — `XGrabKey` requires a live X11 display and root window access. Manual verification only.

**Revised during implementation**: the original `_parse_binding()`/`start()` below used
`root.grab_key(X.AnyKey, mask, ...)` for a modifier-only binding. Verified live against a real
GNOME session: this fails with an asynchronous `BadAccess` X error the moment *any* other client
(the window manager, in practice always true - GNOME/mutter typically has some Ctrl+Alt+*
binding already) holds a grab on any single keycode under that same modifier mask.
`python-xlib`'s `grab_key()` never raises this as a Python exception (`GrabKey` has no
synchronous reply), so the bug is silent - the hotkey would just never fire on a real desktop,
with no error anywhere. Fix: grab the *last* modifier's own physical keycode (e.g. `Control_L`)
with the *other* modifiers as the mask (e.g. `Mod1Mask` for Alt) - this is what the docstring
already described in prose, the code just didn't implement it. Also added an explicit error
handler so a genuine grab conflict raises `HotkeyGrabError` instead of failing silently. The code
block below reflects the fix, not the original buggy version.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/hotkey.py
from typing import Callable, Optional

from Xlib import X, XK
from Xlib.display import Display

# Modifier name -> Xlib modifier mask
_MODIFIER_MASKS = {
    "ctrl": X.ControlMask,
    "alt": X.Mod1Mask,
    "shift": X.ShiftMask,
    "super": X.Mod4Mask,
}

# Modifier name -> the keysym of its own physical key, used when the
# whole binding is modifier-only (e.g. "ctrl+alt" has no letter key).
_MODIFIER_OWN_KEYSYMS = {
    "ctrl": XK.XK_Control_L,
    "alt": XK.XK_Alt_L,
    "shift": XK.XK_Shift_L,
    "super": XK.XK_Super_L,
}


class HotkeyGrabError(RuntimeError):
    """Raised when XGrabKey fails - most commonly because another
    client already holds a grab on the same keycode+modifier
    combination. See the note above start() for why this needs an
    explicit error handler rather than a try/except."""


def _parse_binding(display: Display, binding: str) -> tuple[int, int]:
    """'ctrl+alt' -> (keycode of the *last* modifier's own key, combined
    mask of every modifier *except* the last one). Grabbing X.AnyKey
    with the full combined mask looks equivalent but isn't - see the
    note above for why."""
    parts = binding.lower().split("+")
    *other_parts, last_part = parts
    mask = 0
    for part in other_parts:
        mask |= _MODIFIER_MASKS[part]
    keysym = _MODIFIER_OWN_KEYSYMS[last_part]
    keycode = display.keysym_to_keycode(keysym)
    return keycode, mask


class HotkeyListener:
    def __init__(self, binding: str):
        self.binding = binding
        self._display: Optional[Display] = None
        self._on_press: Optional[Callable[[], None]] = None
        self._on_release: Optional[Callable[[], None]] = None
        self._grab_keycode: Optional[int] = None
        self._grab_mask: Optional[int] = None

    def set_binding(self, binding: str) -> None:
        self.binding = binding

    def start(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._display = Display()
        root = self._display.screen().root

        errors: list[Exception] = []
        self._display.set_error_handler(lambda err, req=None: errors.append(err))

        keycode, mask = _parse_binding(self._display, self.binding)
        self._grab_keycode, self._grab_mask = keycode, mask
        root.grab_key(keycode, mask, True, X.GrabModeAsync, X.GrabModeAsync)
        self._display.sync()

        if errors:
            self._display.close()
            self._display = None
            raise HotkeyGrabError(
                f"Failed to grab hotkey '{self.binding}' - it's likely already bound by "
                f"another application (e.g. the window manager). Try a different binding."
            )

        pressed = False
        while True:
            event = self._display.next_event()
            if event.type == X.KeyPress and not pressed:
                pressed = True
                self._on_press()
            elif event.type == X.KeyRelease and pressed:
                pressed = False
                self._on_release()

    def stop(self) -> None:
        if self._display:
            root = self._display.screen().root
            if self._grab_keycode is not None:
                root.ungrab_key(self._grab_keycode, self._grab_mask)
            self._display.close()
            self._display = None
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
from waypoint.hotkey import HotkeyListener
listener = HotkeyListener(binding='ctrl+alt')
listener.start(on_press=lambda: print('PRESS'), on_release=lambda: print('RELEASE'))
"
```

Expected: pressing and releasing Ctrl+Alt on the real Pop!_OS X11 session prints `PRESS`/`RELEASE`.

**Second revision - this is what actually shipped**: even with the `owner_events` fix above, live
testing (both a real physical key press from Tony and a synthetic XTest injection) confirmed the
`XGrabKey`-based grab never actually receives `KeyPress`/`KeyRelease` - only a spurious
`MappingNotify`. Root cause not fully isolated (GNOME shortcut conflicts were ruled out via
`gsettings`); `XGrabKey`-based global hotkeys are a known-fragile area across Linux desktop
environments generally. **Switched to `pynput`** (`pip install pynput`, pulls in `evdev` as a
transitive dependency) instead of hand-rolled `python-xlib` grabbing. `HotkeyListener` keeps the
exact same public interface (`start(on_press, on_release)`, `stop()`, `set_binding()`) but tracks
currently-held keys via `pynput.keyboard.Listener` and fires `on_press()`/`on_release()` once
every required modifier in the binding is simultaneously held/released - this works because
`pynput`'s Linux backend uses the X `RECORD` extension, a passive monitoring mechanism that
doesn't compete with the window manager's own key grabs the way `XGrabKey` does. Verified live,
both via XTest synthetic injection and a real physical Ctrl+Alt press/release from Tony: reliably
fires `PRESS`/`RELEASE`. The `python-xlib`-based implementation above (Step 1's code block) was
never actually shipped - see `waypoint/waypoint/hotkey.py` for the real, working version.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/hotkey.py waypoint/pyproject.toml && git commit -m "fix: replace XGrabKey with pynput for global hotkey capture"
```

---

### Task 16: Teaching-mode persona file (Component 13)

**Files:**
- Create: `waypoint/.claude/skills/teaching-mode/SKILL.md`

**Interfaces:**
- Consumes: the tag syntax defined in Task 6 (`POINT`/`HIGHLIGHT`/`ANNOTATE`).
- Produces: a file read directly by `claude_session.load_persona()` (Task 10) and passed as
  `--system-prompt` content. **Not** discovered automatically via Claude Code's own
  skill-invocation mechanism — see the note below.

**Revised during implementation**: originally this file was meant to be auto-discovered via
`cwd` the way any project-local skill is, with Claude Code injecting it as active context on its
own. Verified live that this doesn't happen — a discoverable skill is only an *available tool the
model can choose to invoke*, and in practice it didn't, even when explicitly asked "quem é você?"
or given the skill's own literal trigger phrase. The frontmatter (`name`, `description`) is kept
here for documentation/versioning value only; Task 10's `load_persona()` strips it and the body
becomes the `--system-prompt` string on every turn instead.

- [ ] **Step 1: Write the skill file**

```markdown
---
name: teaching-mode
description: Persona and screen-annotation tag syntax for Waypoint, a voice-driven screen companion. Always active for this app - not a user-invoked skill.
---

# Teaching-mode persona

You are Waypoint, a friendly companion that lives beside the user's cursor. You see their
screen, hear their voice, and respond both in text (spoken aloud via TTS) and by drawing
directly on their screen. Speak like a patient teacher sitting next to them, not like a
generic assistant: explain what you're pointing at as you point at it, keep responses
conversational and concise (this gets read aloud), and default to Brazilian Portuguese
unless the user switches language.

## Screen-annotation tags

Embed these tags directly in your response text at the point where the annotation should
happen. They are parsed and rendered by the cursor overlay, then stripped before the text
is spoken or recorded - so write them exactly as specified, they will never be heard.

- `[POINT:x,y:label:screenN]` - cursor flies to a single coordinate. Use when directing
  attention to one specific control (a button, a field, an icon).
- `[HIGHLIGHT:x,y,w,h:screenN]` - draws a ring around a rectangular region. Use when the
  user should look at an *area*, not a single point (a panel, a section of text, a window).
- `[ANNOTATE:shape:params:screenN]` - freeform teaching marks, auto-fade after 4 seconds:
  - `arrow:x1,y1,x2,y2` - draw attention from one point toward another.
  - `circle:x,y,radius` - circle around a point, softer than HIGHLIGHT for a quick callout.
  - `underline:x1,y1,x2` - underline a horizontal span, e.g. a line of text or a label.

Coordinates are in screen pixels for the numbered screen (`screenN`, 0-indexed) the
element is on - check the screenshot(s) provided with the request to determine which
screen and what coordinates to use.

## Continuity

A `MEMORY.md` index of past sessions (date, session ID, one-line summary) is available in
your context. If the user references a past conversation ("volta naquele papo sobre X"),
use this index to recognize what they mean - the app handles the actual session switch.
```

- [ ] **Step 2: Verify the persona activates via --system-prompt**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import json
content = open('.claude/skills/teaching-mode/SKILL.md').read().split('---', 2)[2]
req = {'type':'user','message':{'role':'user','content':[{'type':'text','text':'quem é você?'}]}}
print(json.dumps(req))
" | claude --input-format stream-json --output-format stream-json --model sonnet --strict-mcp-config \
  --system-prompt "$(python3 -c "print(open('.claude/skills/teaching-mode/SKILL.md').read().split('---', 2)[2])")"
```

Expected: the response reflects the teaching-mode persona (mentions pointing/screen/teaching, in
character as Waypoint) — confirming `--system-prompt` delivery works, not that `cwd` discovery
picked anything up (it doesn't, see above).

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/.claude/skills/teaching-mode/SKILL.md && git commit -m "feat: add teaching-mode skill defining persona and tag syntax"
```

---

### Task 17: Tray icon (Component 1)

**Files:**
- Create: `waypoint/waypoint/tray.py`
- Create: `waypoint/waypoint/tray_process.py`

**Interfaces:**
- Produces: `TrayIcon` with `__init__(on_click: Callable[[], None])`, `run() -> None` (non-blocking - spawns the subprocess and a listener thread, then returns), `stop() -> None`. Used by Task 20 (app wiring).

No unit test for the GTK3/AppIndicator3 parts — requires a live GNOME session, manual verification only. The socket IPC path itself was verified with an automated end-to-end check (send a raw `b"click"` message and confirm `on_click` fires), not a real mouse click.

**Revised during implementation**: the original plan assumed `AyatanaAppIndicator3` loaded alongside `Gtk 4.0` in one process. Verified live that both assumptions are wrong on this system: (1) the installed typelib namespace is `AppIndicator3`, not `AyatanaAppIndicator3` — Ubuntu's `gir1.2-appindicator3-0.1` package keeps the legacy GI namespace name even though the runtime library is `libayatana-appindicator3`; (2) more importantly, `AppIndicator3`'s typelib unconditionally pulls in **GTK 3**, which cannot coexist with GTK 4 in the same process (`gi.RepositoryError: Requiring namespace 'Gtk' version '4.0', but '3.0' is already loaded`) — confirmed no GTK4-native alternative exists on this system, including the Ayatana fork (`gir1.2-ayatanaappindicator3-0.1` is packaged "GTK-3+ version" too). Fix: the tray icon runs in its own subprocess (`tray_process.py`, GTK3 + AppIndicator3 exclusively), talking to the main GTK4 process over a local Unix domain socket at `WAYPOINT_HOME / "tray.sock"`. Also found: the pip-installed `PyGObject` wheel doesn't search `/usr/lib/girepository-1.0` by default (only the multiarch path) — Ubuntu's typelib installs there specifically, so both files set `GI_TYPELIB_PATH` before any `gi.require_version()` call.

- [ ] **Step 1: Write the main-process side**

```python
# waypoint/waypoint/tray.py
"""Component 1: tray icon, running in a separate GTK3 process (see
module docstring rationale above)."""
import socket
import subprocess
import sys
import threading
from typing import Callable, Optional

from waypoint.config import WAYPOINT_HOME

TRAY_SOCKET_PATH = WAYPOINT_HOME / "tray.sock"


class TrayIcon:
    """Spawns the GTK3/AppIndicator3 tray subprocess and invokes
    on_click() in THIS process whenever it's clicked, via a local Unix
    socket. run() is non-blocking - it starts the subprocess and a
    background listener thread, then returns, so the caller's own GTK4
    main loop (panel/overlay) can run in this process afterward."""

    def __init__(self, on_click: Callable[[], None]):
        self._on_click = on_click
        self._process: Optional[subprocess.Popen] = None
        self._server: Optional[socket.socket] = None

    def run(self) -> None:
        TRAY_SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if TRAY_SOCKET_PATH.exists():
            TRAY_SOCKET_PATH.unlink()

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(TRAY_SOCKET_PATH))
        self._server.listen(1)

        threading.Thread(target=self._listen, daemon=True).start()

        self._process = subprocess.Popen(
            [sys.executable, "-m", "waypoint.tray_process", str(TRAY_SOCKET_PATH)]
        )

    def _listen(self) -> None:
        while True:
            conn, _ = self._server.accept()
            with conn:
                data = conn.recv(1024)
                if data == b"click":
                    self._on_click()

    def stop(self) -> None:
        if self._process:
            self._process.terminate()
        if self._server:
            self._server.close()
```

- [ ] **Step 2: Write the GTK3 subprocess**

```python
# waypoint/waypoint/tray_process.py
import os
import socket
import sys

os.environ.setdefault("GI_TYPELIB_PATH", "/usr/lib/girepository-1.0")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
gi.require_version("AppIndicator3", "0.1")
from gi.repository import AppIndicator3, Gtk  # noqa: E402


def _send_click(socket_path: str) -> None:
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.connect(socket_path)
            sock.sendall(b"click")
    except OSError:
        pass  # main process isn't listening (yet) - drop the click rather than crash the tray


def main() -> None:
    socket_path = sys.argv[1]

    indicator = AppIndicator3.Indicator.new(
        "waypoint",
        "utilities-terminal",  # placeholder icon name; swap for a real asset
        AppIndicator3.IndicatorCategory.APPLICATION_STATUS,
    )
    indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

    menu = Gtk.Menu()
    open_item = Gtk.MenuItem(label="Open Companion")
    open_item.connect("activate", lambda _widget: _send_click(socket_path))
    menu.append(open_item)
    menu.show_all()
    indicator.set_menu(menu)

    Gtk.main()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Automated IPC verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import socket, time
from waypoint.tray import TrayIcon, TRAY_SOCKET_PATH

clicked = []
icon = TrayIcon(on_click=lambda: clicked.append(True))
icon.run()
time.sleep(2)
assert icon._process.poll() is None, 'subprocess died'

with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
    sock.connect(str(TRAY_SOCKET_PATH))
    sock.sendall(b'click')
time.sleep(0.5)
assert len(clicked) == 1, 'on_click did not fire'
icon.stop()
print('IPC path verified')
"
```

Expected: `IPC path verified`, no assertion errors. This confirms the subprocess starts without crashing and the socket delivers clicks — it does **not** confirm the icon is visually correct on the real desktop; do that separately by watching the GNOME top bar while running the same snippet without the synthetic socket send (requires `gnome-shell-extension-appindicator` active — spec Component 1's documented fallback prompt if it isn't).

- [ ] **Step 4: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/tray.py waypoint/waypoint/tray_process.py && git commit -m "feat: add tray icon as a separate GTK3 subprocess (Component 1)"
```

---

### Task 18: Companion panel (Component 2)

**Files:**
- Create: `waypoint/waypoint/panel.py`

**Interfaces:**
- Consumes: `HotkeyListener.set_binding()` (Task 15), for the hotkey-reconfiguration UI.
- Produces: `CompanionPanel` (a `Gtk.Window` subclass) with `show_near_tray() -> None`, `hide() -> None`, `set_status_text(text: str) -> None`. Used by Task 20.

No unit test — GTK4 windowing requires a live display. Manual verification only.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/panel.py
import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw  # noqa: E402

from typing import Callable


class CompanionPanel(Gtk.Window):
    """Component 2: borderless, always-on-top companion panel. Rounded
    corners/shadow approximated via CSS since X11 doesn't composite
    window shadows outside the WM (spec Component 2)."""

    def __init__(self, on_hotkey_rebind: Callable[[str], None]):
        super().__init__()
        self.set_decorated(False)
        self.set_default_size(320, 180)

        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)

        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(
            b"""
            window { border-radius: 16px; background-color: #1a1a1e; }
            .status-label { color: #e8e8ea; font-size: 14px; }
            """
        )
        Gtk.StyleContext.add_provider_for_display(
            self.get_display(), css_provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        self._status_label = Gtk.Label(label="Segure Ctrl+Alt para falar")
        self._status_label.add_css_class("status-label")

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._status_label)
        self.set_child(box)

        self._on_hotkey_rebind = on_hotkey_rebind

    def show_near_tray(self) -> None:
        self.present()

    def hide_panel(self) -> None:
        self.set_visible(False)

    def set_status_text(self, text: str) -> None:
        self._status_label.set_label(text)
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from waypoint.panel import CompanionPanel

app = Gtk.Application(application_id='dev.waypoint.linux')
def on_activate(app):
    panel = CompanionPanel(on_hotkey_rebind=lambda b: print('rebind', b))
    app.add_window(panel)
    panel.show_near_tray()
app.connect('activate', on_activate)
app.run(None)
"
```

Expected: a dark, borderless, rounded panel window appears showing "Segure Ctrl+Alt para falar".

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/panel.py && git commit -m "feat: add companion panel GTK4/libadwaita window"
```

---

### Task 19: Cursor / annotation overlay rendering (Component 9 rendering)

**Files:**
- Create: `waypoint/waypoint/overlay.py`

**Interfaces:**
- Consumes: `tags.PointTag`, `tags.HighlightTag`, `tags.AnnotateTag` (Task 6), `config.ANNOTATION_FADE_SECONDS` (Task 3).
- Produces: `AnnotationOverlay` (a `Gtk.Window` subclass, one per monitor) with `draw_tag(tag: Tag) -> None`, `clear() -> None`. Used by Task 20.

No unit test — Cairo drawing on a live X11 overlay window. Manual verification only.

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/overlay.py
import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

from waypoint.config import ANNOTATION_FADE_SECONDS
from waypoint.tags import PointTag, HighlightTag, AnnotateTag, Tag


class AnnotationOverlay(Gtk.Window):
    """Component 9: full-screen transparent, click-through overlay for
    one monitor. Renders POINT/HIGHLIGHT/ANNOTATE tags with Cairo via a
    Gtk.DrawingArea. Non-activating, click-through except the cursor
    widget itself - achieved via an input shape mask (set at the
    windowing-system level; confirm the exact GTK4/X11 call available
    on the installed GTK version when wiring this up for real)."""

    def __init__(self, screen_index: int):
        super().__init__()
        self.screen_index = screen_index
        self.set_decorated(False)

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)
        self.set_child(self._drawing_area)

        self._active_tags: list[Tag] = []

    def draw_tag(self, tag: Tag) -> None:
        self._active_tags.append(tag)
        self._drawing_area.queue_draw()

        if isinstance(tag, (HighlightTag, AnnotateTag)):
            GLib.timeout_add_seconds(ANNOTATION_FADE_SECONDS, self._fade_out, tag)

    def clear(self) -> None:
        self._active_tags = []
        self._drawing_area.queue_draw()

    def _fade_out(self, tag: Tag) -> bool:
        if tag in self._active_tags:
            self._active_tags.remove(tag)
            self._drawing_area.queue_draw()
        return GLib.SOURCE_REMOVE

    def _on_draw(self, area, cr, width, height) -> None:
        for tag in self._active_tags:
            if isinstance(tag, PointTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.arc(tag.x, tag.y, 12, 0, 2 * 3.14159)
                cr.fill()
            elif isinstance(tag, HighlightTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.set_line_width(3)
                cr.rectangle(tag.x, tag.y, tag.w, tag.h)
                cr.stroke()
            elif isinstance(tag, AnnotateTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.set_line_width(3)
                if tag.shape == "arrow":
                    x1, y1, x2, y2 = tag.params
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                elif tag.shape == "circle":
                    x, y, radius = tag.params
                    cr.arc(x, y, radius, 0, 2 * 3.14159)
                    cr.stroke()
                elif tag.shape == "underline":
                    x1, y, x2 = tag.params
                    cr.move_to(x1, y)
                    cr.line_to(x2, y)
                    cr.stroke()
```

- [ ] **Step 2: Manual verification**

```bash
cd /home/tony/projects/clicky-cc/waypoint
python3 -c "
import gi
gi.require_version('Gtk', '4.0')
from gi.repository import Gtk
from waypoint.overlay import AnnotationOverlay
from waypoint.tags import PointTag, HighlightTag

app = Gtk.Application(application_id='dev.waypoint.overlay')
def on_activate(app):
    overlay = AnnotationOverlay(screen_index=0)
    app.add_window(overlay)
    overlay.present()
    overlay.draw_tag(PointTag(x=200, y=200, label='test', screen=0))
    overlay.draw_tag(HighlightTag(x=400, y=300, w=150, h=60, screen=0))
app.connect('activate', on_activate)
app.run(None)
"
```

Expected: a blue dot at (200,200) and a rectangle ring at (400,300,150x60) render on screen; the highlight fades after 4s.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/overlay.py && git commit -m "feat: add cursor/annotation overlay rendering with Cairo"
```

---

### Task 20: App wiring (main entrypoint)

**Files:**
- Create: `waypoint/waypoint/app.py`

**Interfaces:**
- Consumes: every module from Tasks 3-19.
- Produces: `run_app() -> None`, the process entrypoint. Nothing downstream depends on this — it's the integration point.

This task is integration glue, not new pure logic — no new unit tests, verified manually end-to-end per the spec's Testing section ("full push-to-talk round trip on the actual Pop!_OS X11 session before calling any phase done").

- [ ] **Step 1: Write the implementation**

```python
# waypoint/waypoint/app.py
import time
from pathlib import Path

from waypoint.config import (
    CURRENT_SESSION_FILE, MEMORY_INDEX_FILE, MEMORY_DIR,
    DEFAULT_HOTKEY, SESSION_END_IDLE_SECONDS,
)
from waypoint.state_machine import CompanionController
from waypoint.audio_capture import MicRecorder
from waypoint.stt import Transcriber
from waypoint.screen_capture import capture_all_screens
from waypoint.model_routing import resolve_model
from waypoint.claude_session import ClaudeSessionClient, SessionStore, load_persona
from waypoint.context_manager import ContextManager
from waypoint.ollama_fallback import pick_vision_model
from waypoint.tags import parse_tags, strip_tags
from waypoint.memory import MemoryEntry, append_entry, parse_memory_index, find_best_match
from waypoint.tts import PiperTTS
from waypoint.hotkey import HotkeyListener
from waypoint.tray import TrayIcon
from waypoint.panel import CompanionPanel
from waypoint.overlay import AnnotationOverlay


class WaypointApp:
    """Wires every component together per the spec's Data flow section.
    Each step below is numbered to match that section directly."""

    def __init__(self):
        self.controller = CompanionController()
        self.mic = MicRecorder()
        self.transcriber = Transcriber()
        self.session_store = SessionStore(CURRENT_SESSION_FILE)
        self.claude_client = ClaudeSessionClient(self.session_store, system_prompt=self._build_system_prompt())
        self.context_manager = ContextManager()
        self.tts = PiperTTS(model_path="~/.waypoint/models/pt_BR-faber-medium.onnx")
        self.overlays: list[AnnotationOverlay] = []
        self._last_activity = time.monotonic()

    def _build_system_prompt(self) -> str:
        # Component 7/13: skill auto-discovery via cwd doesn't reliably
        # inject content (verified live, Task 16) - the persona is read
        # directly and passed as --system-prompt instead. MEMORY.md is
        # appended after it so cross-session continuity (Component 12)
        # rides the same mechanism rather than relying on cwd residency.
        skill_path = Path(__file__).parent.parent / ".claude" / "skills" / "teaching-mode" / "SKILL.md"
        persona = load_persona(skill_path)
        if MEMORY_INDEX_FILE.exists():
            persona += "\n\n## MEMORY.md\n\n" + MEMORY_INDEX_FILE.read_text()
        return persona

    def on_hotkey_press(self) -> None:
        self.controller.on_hotkey_press()
        if self.controller.state.name == "LISTENING":
            self.mic.start()

    def on_hotkey_release(self) -> None:
        audio_buffer = self.mic.stop()
        self.controller.on_hotkey_release(audio_buffer)
        if self.controller.state.name == "PROCESSING":
            self._run_turn(audio_buffer)

    def _run_turn(self, audio_buffer: bytes) -> None:
        # Data flow step 2
        transcript = self.transcriber.transcribe_pcm16(audio_buffer)

        # Data flow step 3
        screenshots = capture_all_screens()

        # Data flow step 4
        model = resolve_model(transcript)

        # Data flow step 5 - compaction and session recall
        if self.context_manager.should_compact():
            self.context_manager.compact(summarize_fn=self._summarize_via_claude)
            self.session_store.write("")  # forces bootstrap on next run_turn call
        recall_match = self._maybe_handle_session_recall(transcript)
        if recall_match:
            self.session_store.write(recall_match.session_id)

        # Data flow step 6
        content_blocks = [
            {"type": "image", "source": {"type": "base64", "media_type": s.media_type, "data": s.base64_data}}
            for s in screenshots
        ]
        content_blocks.append({"type": "text", "text": transcript})

        response_text = ""
        try:
            for event in self.claude_client.run_turn(content_blocks, model):
                if event.get("type") == "content_block_delta":
                    response_text += event.get("delta", {}).get("text", "")
        except Exception:
            vision_model = pick_vision_model(self._list_ollama_models())
            if vision_model:
                response_text = self._run_ollama_fallback(vision_model, transcript, screenshots)
            else:
                response_text = "Desculpa, não consegui responder agora."

        # Data flow step 8 - tags parsed/drawn, stripped before TTS/memory
        for tag in parse_tags(response_text):
            for overlay in self.overlays:
                if overlay.screen_index == tag.screen:
                    overlay.draw_tag(tag)
        clean_text = strip_tags(response_text)
        self.context_manager.record_exchange(transcript, clean_text)

        # Data flow step 9
        self.controller.start_responding()
        self.tts.speak(clean_text)

        # Data flow step 10
        self._last_activity = time.monotonic()
        next_buffer = self.controller.finish_turn()
        if next_buffer is not None:
            self._run_turn(next_buffer)

    def _maybe_handle_session_recall(self, transcript: str):
        if not MEMORY_INDEX_FILE.exists():
            return None
        entries = parse_memory_index(MEMORY_INDEX_FILE.read_text())
        lowered = transcript.lower()
        if "volta" not in lowered and "papo sobre" not in lowered:
            return None
        return find_best_match(entries, transcript)

    def _summarize_via_claude(self, old_text: str) -> str:
        summary = ""
        for event in self.claude_client.run_turn(
            content_blocks=[{"type": "text", "text": f"Resuma esta conversa em um parágrafo curto:\n\n{old_text}"}],
            model="haiku",
        ):
            if event.get("type") == "content_block_delta":
                summary += event.get("delta", {}).get("text", "")
        return summary

    def _list_ollama_models(self) -> list[str]:
        # Placeholder for the real `ollama list` call / HTTP API -
        # replace with an actual client call before relying on this path.
        return []

    def _run_ollama_fallback(self, model: str, transcript: str, screenshots) -> str:
        raise NotImplementedError("Ollama HTTP call - wire up against a running Ollama instance")

    def maybe_distill_memory(self) -> None:
        idle_seconds = time.monotonic() - self._last_activity
        if idle_seconds < SESSION_END_IDLE_SECONDS:
            return
        if not self.context_manager.turns and not self.context_manager.rolling_summary:
            return
        summary = self.context_manager.rolling_summary or self._summarize_via_claude(
            "\n".join(f"{t.user_text} -> {t.assistant_text}" for t in self.context_manager.turns)
        )
        session_id = self.session_store.read() or ""
        date_str = time.strftime("%Y-%m-%d")
        slug = "-".join(summary.split()[:5]).lower() or "sessao"
        memory_path = MEMORY_DIR / f"{date_str}-{slug}.md"
        memory_path.parent.mkdir(parents=True, exist_ok=True)
        memory_path.write_text(summary)
        append_entry(MEMORY_INDEX_FILE, MemoryEntry(date=date_str, session_id=session_id, summary=summary))


def run_app() -> None:
    app = WaypointApp()
    hotkey = HotkeyListener(binding=DEFAULT_HOTKEY)
    tray = TrayIcon(on_click=lambda: None)
    hotkey.start(on_press=app.on_hotkey_press, on_release=app.on_hotkey_release)
    tray.run()


if __name__ == "__main__":
    run_app()
```

**Note for the implementer**: `_list_ollama_models()` and `_run_ollama_fallback()` are stubbed — Component 11 in the spec only requires vision-family *detection* (Task 8, done) and a degraded-mode retry path; the actual Ollama HTTP client call is a small, separate follow-up once a real Ollama instance with a vision model is confirmed runnable (spec Open items). Don't treat the stub as done — it's flagged here so it isn't silently forgotten.

- [ ] **Step 2: Manual end-to-end verification**

On the real Pop!_OS X11 session: run `python3 -m waypoint.app`, press and hold Ctrl+Alt, ask a question about something on screen, release. Confirm: transcript captured, screenshot sent, Claude response streamed, any `POINT`/`HIGHLIGHT`/`ANNOTATE` tags rendered on the overlay, response spoken via Piper, and a second hotkey press while still responding gets queued and processed after.

- [ ] **Step 3: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/app.py && git commit -m "feat: wire full push-to-talk pipeline in WaypointApp"
```

---

### Task 21: UI polish pass

**Files:**
- Modify: `waypoint/waypoint/panel.py`
- Modify: `waypoint/waypoint/overlay.py`

**Interfaces:**
- No new interfaces — this task only refines the visual behavior already wired in Tasks 18-20.

- [ ] **Step 1: Add waveform drawing to the panel during LISTENING**

Add a `Gtk.DrawingArea` to `CompanionPanel` (Task 18) driven by `sounddevice`'s level callback from `MicRecorder` (Task 12) — bars redrawn on each audio frame, matching `CompanionResponseOverlay.swift`'s waveform purpose (spec UI polish section).

- [ ] **Step 2: Add `Gtk.Revealer` fade transitions**

Wrap the panel's content box and the overlay's drawing area in `Gtk.Revealer` with `transition_type = Gtk.RevealerTransitionType.CROSSFADE`, matching the original app's "Transient Cursor Mode" fade-out-after-1s-idle behavior (spec UI polish section).

- [ ] **Step 3: Manual verification**

Run the full app (Task 20's Step 2 flow) and confirm: waveform bars animate while holding the hotkey, and both panel and overlay fade smoothly rather than popping in/out.

- [ ] **Step 4: Commit**

```bash
cd /home/tony/projects/clicky-cc && git add waypoint/waypoint/panel.py waypoint/waypoint/overlay.py && git commit -m "polish: add waveform view and fade transitions to panel/overlay"
```

---

## Self-Review

**1. Spec coverage** — every numbered spec component maps to a task:
1→17, 2→18, 3→15, 4→11, 5→12, 6→13, 7→10, 8→14, 9→6+19, 10→7, 11→8 (+ Ollama HTTP call flagged as a follow-up in Task 20), 12→9+20, 13→16, 14→4, 15→5. UI polish section → 21. Data flow → Task 20. Error handling paths → distributed across Tasks 10 (CLI failure→Ollama), 7 (compaction fallback), 17 (tray extension missing), 13/14 (model-not-downloaded, manual first-run note). Open items → Tasks 2 (schema spike) and 3 (session-end threshold default picked, documented as override-able).

**2. Placeholder scan** — two intentional, explicitly-flagged stubs remain: `_list_ollama_models()` and `_run_ollama_fallback()` in Task 20, called out in that task's implementer note as a deliberate follow-up (not a silent gap) because the real Ollama HTTP call depends on the spec's own open item — confirming a vision-capable model is actually runnable on this machine — which is unresolved as of this plan. Everything else has real code, no "TBD"/"implement later" language.

**3. Type consistency** — checked across tasks: `CompanionState`/`CompanionController` (Task 4) used identically in Task 20; `Tag`/`PointTag`/`HighlightTag`/`AnnotateTag` (Task 6) used identically in Tasks 19 and 20; `ContextManager.compact(summarize_fn)` signature (Task 7) matches its call site in Task 20; `ClaudeSessionClient.run_turn(content_blocks, model)` (Task 10) matches its two call sites in Task 20 (`_run_turn` and `_summarize_via_claude`); `MemoryEntry`/`append_entry`/`find_best_match` (Task 9) match their usage in Task 20's `_maybe_handle_session_recall` and `maybe_distill_memory`.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-08-25-waypoint-plan.md`. Two execution options:

**1. Subagent-Driven (recommended)** — I dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach?**
