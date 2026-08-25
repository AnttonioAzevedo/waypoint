# stream-json schema findings

Captured against: `claude --version` = `2.1.245 (Claude Code)`

## Schema — confirmed, matches spec assumptions

- `init` event: `{"type":"system","subtype":"init","session_id":"<uuid>", "cwd": ..., "tools": [...], "model": ..., ...}`.
  `session_id` is a **top-level string field** — `extract_session_id(event) -> event["session_id"]` is correct as written.
- `--resume <session_id>` carries prior turn history correctly (confirmed: a follow-up turn correctly referenced the first turn's content).
- Image content blocks (`{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": ...}}`) round-trip correctly through `--resume` and are answered correctly by the model. **Caveat**: a trivially small image (1x1 px) is rejected by the API ("could not be processed and was removed") — not a schema problem, a content-validation floor. Irrelevant for this app (real screenshots are never 1x1), noted only so nobody re-discovers this by accident.
- Full fixture saved at `tests/fixtures/stream_json_init_event.json`, captured from a real call in this repo's `cwd`.

## New finding not anticipated by the spec — subprocess environment inheritance

A plain `claude --input-format stream-json --output-format stream-json` call in this `cwd`
inherits the **full interactive user environment**: all global hooks (`~/.claude/settings.json`),
all installed plugins (including `superpowers`, which injects a large "you have superpowers"
reminder via a `SessionStart` hook), all configured MCP servers (~15: Jira, Gmail, Calendar,
Grafana, GitHub, Supabase, etc.), and the user's global `CLAUDE.md` persona. Confirmed via a live
call: the model responded in character as the user's personal assistant persona, in Portuguese,
unprompted.

**Cost impact, measured**: first call in a fresh session (cache miss) — **$0.159**, ~39k tokens of
cache-creation, almost entirely from hook-injected skill content and the full MCP tool list.
Second call in the **same session** via `--resume` (cache hit) — **$0.027**, ~52k tokens read from
cache instead of recreated. **This cost is paid once per pinned session, not once per voice turn**
— Component 7's `--resume` pinning means the expensive part only happens at session bootstrap or
after a Component 10 compaction resets the session, not on every push-to-talk interaction.

**What was tried to suppress it, and why it didn't work:**
- `--safe-mode`: cuts cost to $0.025 and removes the noise, but disables **all** skill discovery
  (confirmed via a live probe skill that stopped being recognized) — breaks Component 13's core
  mechanism, which depends on `.claude/skills/teaching-mode/SKILL.md` being auto-discovered.
- `--bare`: same trade-off, plus it disables OAuth/keychain auth entirely (`ANTHROPIC_API_KEY`
  only) — incompatible with the whole point of this app (zero API keys, Pro/Max subscription
  auth). Ruled out immediately.
- `CLAUDE_CONFIG_DIR` pointed at an empty directory: isolates hooks/CLAUDE.md, and confirmed
  project-local skill discovery still works via `cwd` independent of the config dir — but it also
  breaks OAuth login ("Not logged in"), since the subscription token lives under the real config
  dir. Ruled out for the same reason as `--bare`.
- Overriding `hooks` to `{}` — via a project-local `.claude/settings.json`, an inline
  `--settings '{"hooks":{}}'` JSON string, and a `--settings /path/to/file.json` file — all three
  had **zero effect**; hook count and cost were identical to the unmodified baseline. Hooks
  accumulate across the settings scope hierarchy (managed/user/project) rather than being
  override-able per scope; there is currently no CLI-exposed way to selectively suppress them.
- `--append-system-prompt` to try to substitute a custom persona instead of relying on
  skill-discovery: the model treated the appended content as an untrusted injection attempt and
  explicitly refused to adopt it (visible refusal text, not silent failure) — not usable as a
  skill-discovery replacement.

**Decision (Tony, 2026-08-25)**: accept hooks/plugins/skills staying active. Tony explicitly wants
Waypoint to inherit his user-scope skills, not run in an isolated bubble — the cost finding above
(one-time per session, not per turn) makes this an acceptable trade-off rather than a blocker.
**Only change adopted**: add `--strict-mcp-config` (no `--mcp-config` passed) to
`build_claude_command()` — this drops the ~15 irrelevant MCP servers (Jira/Gmail/Grafana/etc.)
from the tool list with no functional downside, since Waypoint never uses any of them. No change
to Component 13 — skill auto-discovery via `cwd` is confirmed working and stays as originally
designed.

## Deviations from the spec's assumed shape

None in the JSON schema itself. The one real deviation is environmental (see above), not a field
name or type — it changes one line of `build_claude_command()` (add `--strict-mcp-config`) and
adds a documented, accepted cost trade-off to Component 7. No changes needed to
`extract_session_id()` or the tag/content-block shapes assumed elsewhere in the spec.
