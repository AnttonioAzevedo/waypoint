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


def build_claude_command(session_id: Optional[str], model: str) -> list[str]:
    """Bootstrap (session_id is None): plain new session, no --resume,
    no --continue. Pinned (session_id is set): --resume explicitly.
    Never --continue - see spec Component 7 for why. --strict-mcp-config
    drops the user's unrelated MCP servers (Jira/Gmail/Grafana/etc.) with
    no functional downside (spec Component 7, stream-json spike)."""
    cmd = [
        "claude", "--input-format", "stream-json", "--output-format", "stream-json",
        "--model", model, "--strict-mcp-config",
    ]
    if session_id:
        cmd += ["--resume", session_id]
    return cmd


def extract_session_id(event: dict) -> str:
    return event["session_id"]


class ClaudeSessionClient:
    def __init__(self, session_store: SessionStore, popen_factory=subprocess.Popen):
        self.session_store = session_store
        self._popen_factory = popen_factory

    def run_turn(self, content_blocks: list[dict], model: str) -> Iterator[dict]:
        session_id = self.session_store.read()
        cmd = build_claude_command(session_id, model)
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
