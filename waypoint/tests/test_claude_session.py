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
