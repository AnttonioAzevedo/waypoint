# Clicky Linux Port — Design Spec

## Context

Clicky ([farzaa/clicky](https://github.com/farzaa/clicky), MIT) is a native macOS menu bar
companion: push-to-talk voice input, screen-aware Claude vision chat, TTS response, and a
blue cursor overlay that points at UI elements. The original stack is 100% Apple-native
(SwiftUI/AppKit, ScreenCaptureKit, AVAudioEngine, CGEvent) and does not run on Linux.

This fork (`AnttonioAzevedo/clicky-cc`) targets **Pop!_OS 24.04, X11 session, GNOME desktop**
(confirmed via `$XDG_SESSION_TYPE` / `lsb_release`). Goal: rebuild the same interaction loop
—hotkey → listen → screenshot → Claude → speak → point— fully local and free, reusing the
original Swift code only as behavioral reference, not as source to port.

## Non-goals

- No macOS compatibility layer — this is a Linux-only rewrite, not a cross-platform abstraction.
- No Wayland support in this pass — X11 only, matching the confirmed session type. Revisit if
  the user moves to COSMIC/Wayland later.
- No packaging/distribution (`.deb`, Flatpak) — local dev run is enough for v1.

## Architecture

Single Python process, GTK4 + libadwaita for UI. No client-server split, no Cloudflare Worker,
no API keys — every external call in the current app is replaced by either a local model or a
local CLI subprocess.

```
┌─────────────────────────────────────────────────────────────┐
│  clicky-linux (Python process)                                │
│                                                                 │
│  ┌────────────┐   ┌──────────────┐   ┌────────────────────┐ │
│  │ Tray icon  │   │ Hotkey        │   │ Companion panel     │ │
│  │ (AppIndi-  │   │ listener      │   │ (Gtk.Window,         │ │
│  │  cator3)   │   │ (python-xlib) │   │  libadwaita styled)  │ │
│  └─────┬──────┘   └──────┬───────┘   └──────────┬──────────┘ │
│        │                 │                       │            │
│        └────────────┬────┴───────────────────────┘            │
│                      ▼                                        │
│              CompanionController (state machine)              │
│              idle → listening → processing → responding       │
│                      │                                        │
│      ┌───────────────┼────────────────┬─────────────────┐    │
│      ▼               ▼                ▼                 ▼    │
│  Mic capture    Screen capture   Claude Code CLI     Piper TTS │
│  (sounddevice)  (mss, X11)       subprocess          subprocess│
│      │                                │                   │    │
│      ▼                                ▼                   ▼    │
│  faster-whisper                 stream-json NDJSON   audio out │
│  (local STT)                    parsed → text chunks (pipewire)│
│                                                                 │
│                      ▼                                        │
│              Cursor overlay (Gtk.Window, override_redirect,    │
│              always-above, click-through, bezier animation)    │
└─────────────────────────────────────────────────────────────┘
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

### 3. Hotkey — `python-xlib`
Global key-grab for ctrl+option (Linux: ctrl+alt, since "option" is a Mac-ism — confirm
keybinding with user before implementation) via `XGrabKey` on the root window. Press/release
tracked the same way `GlobalPushToTalkShortcutMonitor.swift` does — a state transition, not a
toggle.

### 4. Screen capture — `mss`
`mss` grabs X11 frame buffers directly, no portal negotiation needed on X11 (unlike Wayland).
Multi-monitor: `mss` enumerates displays natively, matching the labeled multi-display capture
`CompanionScreenCaptureUtility.swift` does today.

### 5. Mic capture — `sounddevice` (PortAustio/ALSA/PipeWire backend)
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
constructs (`{"type": "image", "source": {"type": "base64", "media_type": ..., "data": ...}}`
+ text block), fed over stdin as NDJSON. Output NDJSON parsed for token deltas, re-emitted as
progressive text chunks to the UI — replicating the `onTextChunk` streaming callback contract.
Stateless: full conversation history resent each call, matching current behavior, not using
the CLI's own session/resume file.

**Validation spike required before implementation**: confirm the exact current `stream-json`
schema for image content blocks and the token-delta event shape against the installed `claude`
CLI version — do not assume the schema from memory. First task of the implementation plan.

### 8. TTS — `piper-tts` (local, subprocess)
Piper over ElevenLabs — meaningfully better quality than `espeak`/`festival`, fully offline,
real PT-BR voices available. Audio played via `sounddevice`/PipeWire. Exposes an
`is_playing` property mirroring `ElevenLabsTTSClient.swift`'s contract, so the "speaking"
state UI logic doesn't need to be redesigned.

### 9. Cursor overlay — `Gtk.Window`, `override_redirect`, click-through
Full-screen transparent window per monitor, `set_accept_focus(False)`, input shape mask so
clicks pass through except on the cursor widget itself. `[POINT:x,y:label:screenN]` tag
parsing from the original `OverlayWindow.swift` carries over as pure logic — bezier arc
animation reimplemented with GTK's frame clock / `Gtk.Snapshot` instead of SwiftUI animation.

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

## Data flow (one interaction)

1. Hotkey press → state → `listening`, mic capture starts, waveform begins drawing.
2. Hotkey release → mic buffer closed → `faster-whisper` transcribes → text.
3. Screenshot(s) captured (`mss`) for all connected monitors.
4. `claude` CLI spawned with image(s) + transcript + conversation history + system prompt →
   state → `processing`.
5. Streamed text deltas → panel/overlay bubble updates progressively → state → `responding`.
6. On completion: `[POINT:...]` tags parsed → overlay cursor animates if present.
7. Full response text → `piper-tts` → audio playback → `is_playing` drives waveform/cursor
   state until done.
8. Idle timeout (transient mode) → overlay fades out.

## Error handling

- `claude` CLI non-zero exit or malformed NDJSON → surfaced as an error bubble in the panel,
  mirroring the `NSError` throw path in the original `ClaudeAPI.swift` — fail loud, no silent
  swallow.
- Missing tray extension / X11 grab failure at startup → explicit dialog telling the user what
  to enable, not a silent no-op.
- Whisper/Piper model not yet downloaded → first-run blocking prompt with progress, not a
  crash on first hotkey press.

## Testing

- Unit: NDJSON parsing (chat deltas), `[POINT:...]` tag parsing, audio buffer conversion —
  pure functions, easy to isolate.
- Integration: mock `claude`/`piper` subprocesses to test the state machine transitions without
  needing the real CLI/model each run.
- Manual: full push-to-talk round trip on the actual Pop!_OS X11 session before calling any
  phase done — this is a desktop app, type-checking isn't proof it works.

## Open items carried into the implementation plan

- Exact `stream-json` schema validation (blocking task #1).
- Confirm AppIndicator GNOME extension is active on this machine before building tray code.
- Confirm hotkey remap (ctrl+option → ctrl+alt) with user.
- Whisper/Piper model size vs. quality trade-off — pick default, document override.
