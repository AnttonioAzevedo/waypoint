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
