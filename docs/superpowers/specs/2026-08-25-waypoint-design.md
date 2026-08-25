# Waypoint — Design Spec

## Context

Clicky ([farzaa/clicky](https://github.com/farzaa/clicky), MIT) is a native macOS menu bar
companion: push-to-talk voice input, screen-aware Claude vision chat, TTS response, and a
blue cursor overlay that points at UI elements. The original stack is 100% Apple-native
(SwiftUI/AppKit, ScreenCaptureKit, AVAudioEngine, CGEvent) and does not run on Linux.

This fork (`AnttonioAzevedo/clicky-cc`) targets **Pop!_OS 24.04, X11 session, GNOME desktop**
(confirmed via `$XDG_SESSION_TYPE` / `lsb_release`). Goal: rebuild the same interaction loop
—hotkey → listen → screenshot → Claude → speak → point— fully local and free, reusing the
original Swift code only as behavioral reference, not as source to port.

**Naming**: the resulting app is called **Waypoint**. It started as a straight Linux port and
stayed a fork of Clicky in fact — MIT license, credited above, behavioral reference throughout
this doc — but diverged enough in scope (cross-session memory with recall, a request queue,
model routing, an Ollama resilience fallback — none of which exist in the original) that calling
it "Clicky for Linux" undersells what it does. Fork lineage stays visible in this Context
section and in the repo's README credit; the product name doesn't need to carry it.

A parallel project, [pango07/flicky](https://github.com/pango07/flicky), reimplements Clicky
as a cross-platform Electron app with paid multi-provider API keys (Anthropic/OpenAI +
ElevenLabs + Groq). It solves a different problem (cross-platform, provider flexibility) than
ours (zero API cost via Claude Pro/Max subscription auth, fully local STT/TTS) and its stack
(TypeScript/Electron) doesn't transfer — it's referenced here only for two algorithms worth
reusing (see Components 10 and 11), not as a dependency or fork target.

## Non-goals

- No macOS compatibility layer — this is a Linux-only rewrite, not a cross-platform abstraction.
- No Wayland support in this pass — X11 only, matching the confirmed session type. Revisit if
  the user moves to COSMIC/Wayland later.
- No packaging/distribution (`.deb`, Flatpak) — local dev run is enough for v1.
- No multi-provider key management (Flicky's core feature) — this app has zero API keys by
  design; Ollama (Component 11) is a local resilience fallback, not a provider picker.
- No full-duplex/continuous voice mode (ChatGPT-app-style always-listening + barge-in
  interruption of TTS) in this pass — v1 stays push-to-talk with a request queue (Component 14).
  Full-duplex is a materially different interaction model (VAD, continuous mic capture,
  TTS-interrupt-on-speech) and belongs in its own spec once v1 is running, not folded in here.

## Architecture

Single Python process, GTK4 + libadwaita for UI. No client-server split, no Cloudflare Worker,
no API keys — every external call in the current app is replaced by either a local model or a
local CLI subprocess.

```
┌───────────────────────────────────────────────────────────────────┐
│  waypoint (Python process)                                      │
│                                                                       │
│  ┌────────────┐  ┌──────────────┐  ┌────────────────────┐          │
│  │ Tray icon  │  │ Hotkey        │  │ Companion panel     │          │
│  │ (AppIndi-  │  │ listener      │  │ (Gtk.Window,         │          │
│  │  cator3)   │  │ (python-xlib, │  │  libadwaita styled)  │          │
│  │            │  │  configurable)│  │                       │          │
│  └─────┬──────┘  └──────┬───────┘  └──────────┬──────────┘          │
│        │                │                     │                     │
│        └───────────┬────┴─────────────────────┘                     │
│                     ▼                                                │
│             CompanionController (state machine)                     │
│             idle → listening → processing → responding              │
│                     │                                                │
│     ┌───────────────┼─────────────┬──────────────┬───────────────┐ │
│     ▼               ▼             ▼              ▼               ▼ │
│ Mic capture   Screen capture  Claude Code CLI  ContextManager  Piper │
│ (sounddevice) (mss, X11)      subprocess       (compaction +   TTS  │
│     │                              │ ▲          memory .md)    sub- │
│     ▼                              │ └── Ollama fallback       proc │
│ faster-whisper              stream-json NDJSON  (if CLI down)   │   │
│ (local STT)                 → text chunks                       ▼   │
│                                                              audio   │
│                     ▼                                     (pipewire)│
│             Cursor / annotation overlay (Gtk.Window,                │
│             override_redirect, always-above, click-through,         │
│             POINT / HIGHLIGHT / ANNOTATE tag rendering)              │
└───────────────────────────────────────────────────────────────────┘

.claude/skills/teaching-mode/SKILL.md ─── discovered by the CLI via cwd,
defines tone + exact tag syntax the model should emit (Component 13).

Hotkey press while non-idle → Request queue (Component 14, deque), drained on return to idle.
Transcript → Model routing (Component 15) resolves --model before the CLI spawn.
CLI spawn always uses --resume <pinned session_id> (Component 7), never --continue.
```

## Components

### 1. Tray icon — `AppIndicator3` (via `PyGObject`)
Standard libappindicator, GNOME on Pop!_OS 24.04 ships the AppIndicator/KStatusNotifierItem
extension by default. Click opens the companion panel positioned near the tray. Fallback: if
the extension isn't active, detect at startup and prompt the user to enable
`gnome-shell-extension-appindicator` (one-time setup note, not code we ship).

### 2. Companion panel — `Gtk.Window` + libadwaita
Borderless, `set_decorated(False)`, `set_keep_above(True)`. Styled with a custom
`Adw.StyleManager` dark theme + CSS (rounded corners via `border-radius` on the root box,
custom shadow via `Gtk.Overlay` trick since X11 doesn't composite window shadows outside the
WM) to approximate the original `DesignSystem.swift` dark aesthetic. Click-outside-to-dismiss
via a global X11 button-press grab while the panel is open.

### 3. Hotkey — `python-xlib`, user-configurable
Global key-grab via `XGrabKey` on the root window. Default binding is `ctrl+alt` (Linux
equivalent of the original `ctrl+option`), but the combination is captured and re-registered
live from the panel settings UI — same idea as Flicky's customizable shortcut capture, applied
here to close the "confirm keybinding with user" open item from the previous draft: instead of
hardcoding it, the user picks it once in the UI. Press/release tracked the same way
`GlobalPushToTalkShortcutMonitor.swift` does — a state transition, not a toggle.

### 4. Screen capture — `mss`
`mss` grabs X11 frame buffers directly, no portal negotiation needed on X11 (unlike Wayland).
Multi-monitor: `mss` enumerates displays natively, matching the labeled multi-display capture
`CompanionScreenCaptureUtility.swift` does today.

### 5. Mic capture — `sounddevice` (PortAudio/ALSA/PipeWire backend)
Push-to-talk buffer capture, converted to PCM16 mono for `faster-whisper`, mirroring
`BuddyAudioConversionSupport.swift`'s conversion role.

### 6. STT — `faster-whisper` (local, CTranslate2-backed Whisper)
Runs `base` or `small` model on CPU (GPU/CUDA optional if available). No streaming
partial-transcript UX like AssemblyAI's turn-based websocket — v1 transcribes the full
push-to-talk buffer on key-up, same finalize-on-release behavior the app already has as its
functional contract (`OpenAIAudioTranscriptionProvider.swift` is the closest existing
precedent: buffer-then-upload, except now buffer-then-local-transcribe).

### 7. Chat — `claude` CLI subprocess (Claude Code, user's Pro/Max subscription)
Spawned via `subprocess.Popen` with `--input-format stream-json --output-format stream-json`.
Content blocks (image + text) built in the same shape the original `ClaudeAPI.swift` already
constructs (`{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}` +
text block), fed over stdin as NDJSON. Output NDJSON parsed for token deltas, re-emitted as
progressive text chunks to the UI — replicating the `onTextChunk` streaming callback contract.

**Session pinning, not `--continue`**: `--continue` resumes "the most recent session for this
cwd" — a heuristic that breaks the moment the user also runs `claude` interactively in the same
project directory (which this app's `cwd` necessarily is, for Component 13's skill discovery).
Two sessions would fight over the "most recent" slot. Instead: the `init` event on the first
`stream-json` response of any session carries a `session_id`. The app captures and persists it
to `~/.waypoint/current_session.json`, and every subsequent call passes `--resume <session_id>`
explicitly. This pins the app to its own session regardless of what else runs `claude` in that
directory — no separate `cwd`, no symlink, no duplication. See Component 12 for how this
`session_id` is also used for session recall and Component 10 for how it's replaced on
compaction.

**Bootstrap**: if `~/.waypoint/current_session.json` doesn't exist yet (first-ever run, or right
after a compaction/session-end reset it, per Component 10), the CLI is spawned with neither
`--resume` nor `--continue` — a plain new session. Its `init` event's `session_id` is what gets
written to `current_session.json` for the first time, and every call after that pins to it as
described above.

**Validation spike required before implementation**: confirm the exact current `stream-json`
schema for image content blocks, the `init` event's `session_id` field, and the token-delta
event shape, and confirm `--resume` behavior with image-bearing turns, against the installed
`claude` CLI version — do not assume the schema from memory. First task of the implementation
plan.

### 8. TTS — `piper-tts` (local, subprocess)
Piper over ElevenLabs — meaningfully better quality than `espeak`/`festival`, fully offline,
real PT-BR voices available. Audio played via `sounddevice`/PipeWire. Exposes an
`is_playing` property mirroring `ElevenLabsTTSClient.swift`'s contract, so the "speaking"
state UI logic doesn't need to be redesigned.

### 9. Cursor / annotation overlay — `Gtk.Window`, `override_redirect`, click-through
Full-screen transparent window per monitor, `set_accept_focus(False)`, input shape mask so
clicks pass through except on the cursor widget itself. Parses a family of tags the model can
embed in its response, drawn with Cairo:

- `[POINT:x,y:label:screenN]` — cursor flies to the coordinate (original behavior, from
  `OverlayWindow.swift`), bezier arc animation via GTK's frame clock.
- `[HIGHLIGHT:x,y,w,h:screenN]` — draws a ring around a rectangular region (the "it points,
  explains, and teaches" effect), fades out with the response bubble.
- `[ANNOTATE:shape:params:screenN]` — freeform teaching marks, `shape` ∈:
  - `arrow:x1,y1,x2,y2` — arrow from origin to target
  - `circle:x,y,radius` — circle around a point
  - `underline:x1,y1,x2` — horizontal underline
  - all annotations **auto-fade after 4s** (configurable), matching the "annotations fade
    automatically" behavior.

All three tag families are stripped from the text before it's spoken by TTS or stored in
conversation memory (same rule the original app already applies to `[POINT:...]`, confirmed
still followed in Flicky's `companion-manager.ts`).

### 10. ContextManager — token-budget compaction (within a live session)
Session pinning via `--resume` (Component 7) means the CLI holds history across turns, but a
long-running session can still grow past a usable context size. Ported as an **algorithm**, not
code, from Flicky's
`context-manager.ts` (TypeScript, not reusable directly, but the design is sound):

- `MAX_TOKEN_BUDGET = 250_000`, `COMPACT_TRIGGER = 200_000`, `KEEP_RECENT = 10` exchanges.
- Approximate token count via `len(text) // 4` unless the CLI reports exact usage.
- On crossing the trigger: everything older than the recent window gets summarized in one call
  (folding in any prior summary — a rolling summary, never summary-of-summary chains). The
  current session is then closed out — distilled to a memory `.md` file and indexed in
  `MEMORY.md` (Component 12), same as any session end — and a genuinely **new** session is
  started (no `--resume`, no `--continue`; we don't control the CLI's internal session file
  directly, so "fresh" has to mean an actual new session, not a resumed one), seeded with the
  summary as its first turn. Its new `session_id` (Component 7) replaces the pinned one in
  `~/.waypoint/current_session.json`. The old session's full history isn't lost — it stays
  resumable by ID via the recall mechanism in Component 12.
- **Fallback if summarization itself fails**: don't block the interaction — drop the oldest
  half of the non-recent turns verbatim and continue. Never let a compaction failure block a
  response the user is waiting on.

### 11. Ollama fallback — local resilience, not a provider picker
If the `claude` CLI subprocess is unreachable (non-zero exit, missing binary, subscription
auth expired) **and** a local Ollama instance with a vision-capable model is available, retry
the same request against it instead of failing the interaction outright. Vision-model detection
by name-family match (`llava`, `qwen2-vl`, `gemma3`, etc. — ported from Flicky's
`isVisionModel()` family list, same reasoning: Ollama doesn't self-report vision support).
This is a **degraded-mode fallback**, not a configuration option the user picks day-to-day —
Claude via subscription is always the primary path. Detected and logged, never silent: the
panel shows "using local fallback model" so response-quality differences aren't a mystery.

### 12. Cross-session memory — `.md` files + session index, injected via skill/system prompt
Solves "Clicky forgets everything when the app closes" — true of the original app
(`CompanionManager.swift` caps `conversationHistory` at 10 in-memory exchanges, lost on
restart) and not something we're inheriting on purpose.

- On session end (idle timeout, app shutdown, or compaction per Component 10), the
  `ContextManager`'s current summary (or a fresh summarize call if the session was short) is
  written to `~/.waypoint/memory/YYYY-MM-DD-<topic-slug>.md`.
- A `~/.waypoint/memory/MEMORY.md` index is updated alongside it, **one line per session,
  including that session's `session_id`** so it can be resumed later, e.g.:
  ```
  - [2026-08-20] session_id=abc123 — Discutindo migração do worker Cloudflare
  - [2026-08-25] session_id=def456 — Design do port Linux
  ```
  Kept short on purpose — this is what gets loaded every session start, not the full memory
  files.
- On next app start, `MEMORY.md`'s content is prepended to the `claude` CLI's system prompt (or
  read via the teaching-mode skill, Component 13) so the model has continuity across restarts
  without resending full transcripts or images from prior days.

**Session recall ("volta naquele papo sobre X")**: since the model sees the `MEMORY.md` index
every session, it can recognize when the user is asking to return to a past topic. This is
handled as an app-level intent, not left to prose — a recognized recall request triggers the
app to match the request against `MEMORY.md` entries (fuzzy match, or asking the current Claude
turn to pick the matching entry) and, on a match, swap `~/.waypoint/current_session.json`'s
pinned `session_id` (Component 7) to that entry's ID. The old session's full history is intact
in the CLI's own session store — nothing was deleted, only which ID is currently pinned
changes. Switching back later is the same mechanism in reverse.

### 13. Teaching-mode skill — `.claude/skills/teaching-mode/SKILL.md`
Since the app's `claude` CLI subprocess always runs with its `cwd` set to the app's working
directory, Claude Code's own skill-discovery mechanism picks up a project-level
`.claude/skills/teaching-mode/SKILL.md` automatically — no custom loading code needed. This
file documents, in the format Claude Code already understands:

- Tone/persona for the "teaches like a real teacher beside you" behavior.
- The exact tag syntax and when to use `POINT` vs `HIGHLIGHT` vs `ANNOTATE` (e.g. point at a
  single control, highlight a region being discussed, annotate to draw attention mid-explanation).
- Pointer to `MEMORY.md` for continuity context.

This replaces a large hardcoded system-prompt string in Python with a versioned, human-editable
file — the natural place to tune "teacher personality" without touching application code.

### 14. Request queue — handling a hotkey press mid-turn
The state machine (`idle → listening → processing → responding → idle`) is a single-turn cycle;
it doesn't say what happens if the hotkey is pressed again before returning to `idle`. Rather
than ignore the press or cancel the in-flight turn, it's enqueued: a `collections.deque` holds
pending push-to-talk buffers, drained one at a time as the controller returns to `idle`. Keeps
push-to-talk strictly turn-based (see the full-duplex non-goal above) while still capturing
everything the user says, in order — no dropped input, no overlapping audio/overlay state.

### 15. Model routing — explicit command, heuristic fallback
`claude` CLI's `--model` flag lets each spawn (Component 7) pick Sonnet/Opus/Haiku per turn.
Priority order:
1. **Explicit voice command** — the transcribed text is checked for a routing phrase first
   (e.g. "modo rápido" → Haiku, "pensa com calma nisso" → Opus) before anything else runs. A
   small fixed phrase table, not a model call — cheap and unambiguous.
2. **Heuristic fallback** — if no explicit phrase is present, a lightweight rule set picks the
   model from the request shape (short/factual → Haiku, "explica"/"analisa"/"compara" → Sonnet
   default, nothing auto-escalates to Opus without the explicit phrase — it's the expensive
   tier, opt-in only).

Both layers are pure functions over the transcript text, easy to unit test in isolation
(Testing section already covers this class of logic).

## UI polish

Given the ask to keep it visually nice, not just functional:
- libadwaita for native GNOME look-and-feel (respects system light/dark, but default to the
  dark aesthetic the original app has).
- Custom CSS provider for the companion panel and overlay bubble — rounded corners, subtle
  border, accent color matching original `DS.Colors`.
- `Gtk.Revealer`/CSS transitions for panel show/hide and overlay fade in/out, approximating
  the fade timing described in the original overlay ("Transient Cursor Mode" — fade out after
  1s idle).
- Waveform view during listening: simple `Gtk.DrawingArea` with live audio-level bars, driven
  by `sounddevice` level callback — same purpose as `CompanionResponseOverlay.swift`'s
  waveform, redrawn with Cairo instead of SwiftUI Canvas.
- Annotation/highlight strokes (Component 9) use the same accent color and fade curve as the
  panel, so teaching marks read as part of the same visual system, not a bolted-on layer.

## Data flow (one interaction)

1. Hotkey press (user-configured binding) → if controller isn't `idle`, buffer is enqueued
   (Component 14) instead of starting a new turn. Otherwise: state → `listening`, mic capture
   starts, waveform begins drawing.
2. Hotkey release → mic buffer closed → `faster-whisper` transcribes → text.
3. Screenshot(s) captured (`mss`) for all connected monitors.
4. Transcript checked for a model-routing phrase (Component 15) → resolves which `--model` this
   turn uses.
5. `ContextManager` checks token budget; compacts if over `COMPACT_TRIGGER` (Component 10, which
   also handles session-recall requests by swapping the pinned `session_id`).
6. `claude` CLI spawned with `--resume <pinned session_id>` (Component 7), image(s) + transcript
   + system prompt (teaching-mode skill + `MEMORY.md` context already resident via cwd) → state
   → `processing`. On subprocess failure, Ollama fallback (Component 11) is attempted before
   surfacing an error.
7. Streamed text deltas → panel/overlay bubble updates progressively → state → `responding`.
8. On completion: `[POINT:...]` / `[HIGHLIGHT:...]` / `[ANNOTATE:...]` tags parsed → overlay
   draws/animates accordingly; tags stripped before TTS and before the turn is recorded.
9. Full response text → `piper-tts` → audio playback → `is_playing` drives waveform/cursor
   state until done.
10. Controller returns to `idle`; if the queue (Component 14) has pending buffers, the next one
    starts immediately from step 4. Otherwise: idle timeout (transient mode) → overlay fades
    out; if idle crosses the session-end threshold, Component 12's memory distillation runs in
    the background.

## Error handling

- `claude` CLI non-zero exit or malformed NDJSON → Ollama fallback attempted first (Component
  11); if that also fails, surfaced as an error bubble in the panel, mirroring the `NSError`
  throw path in the original `ClaudeAPI.swift` — fail loud, no silent swallow.
- Context compaction failure → non-blocking fallback (drop oldest turns verbatim), logged but
  never surfaced as a user-facing error — the interaction still completes.
- Missing tray extension / X11 grab failure at startup → explicit dialog telling the user what
  to enable, not a silent no-op.
- Whisper/Piper model not yet downloaded → first-run blocking prompt with progress, not a
  crash on first hotkey press.
- Memory write failure (disk full, permissions) → logged, interaction still completes; the app
  degrades to session-only memory rather than blocking on a filesystem error.

## Testing

- Unit: NDJSON parsing (chat deltas), tag parsing (`POINT`/`HIGHLIGHT`/`ANNOTATE`), audio buffer
  conversion, `ContextManager` compaction trigger/fallback logic, vision-model family matching,
  model-routing phrase/heuristic resolution (Component 15), request queue drain order
  (Component 14) — all pure functions, easy to isolate.
- Integration: mock `claude`/`ollama`/`piper` subprocesses to test the state machine transitions
  and the CLI→Ollama fallback path without needing the real CLI/model each run.
- Manual: full push-to-talk round trip on the actual Pop!_OS X11 session before calling any
  phase done — this is a desktop app, type-checking isn't proof it works.

## Open items carried into the implementation plan

- Exact `stream-json` schema validation, including the `init` event's `session_id` field and
  `--resume` behavior with image-bearing turns (blocking task #1).
- Confirm AppIndicator GNOME extension is active on this machine before building tray code.
  Pop!_OS 24.04 ships COSMIC (Rust, not GNOME-based) as its **default** session — GNOME is an
  optional session you select at the login screen. Re-confirm `$XDG_SESSION_TYPE` and
  `echo $XDG_CURRENT_DESKTOP` right before starting Task 17 (tray), since AppIndicator3,
  `set_keep_above`, `override_redirect`, and the X11 click-outside grab (Component 2/9) all
  assume a GNOME/mutter session specifically, not COSMIC's own compositor.
- Whisper/Piper model size vs. quality trade-off — pick default, document override.
- Confirm at least one vision-capable Ollama model is realistically runnable on this machine
  before treating Component 11 as anything but a documented no-op fallback.
- Model-routing phrase table (Component 15) — finalize the exact PT-BR trigger phrases and
  their model mapping before implementation; the ones in this spec are illustrative.
- Full-duplex/continuous voice mode (see Non-goals) — separate future spec, not scoped here.
- Session-end idle threshold (Component 12, Data flow step 10) — the value that triggers memory
  distillation isn't picked yet. Distinct from the 1s overlay-fade timing (UI polish), which is
  already specified; this one is presumably minutes, not seconds — pick a default and document
  it before implementation.
