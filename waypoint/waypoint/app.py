import threading
import time
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

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

    Threading model (not in the original plan draft - added during
    implementation): HotkeyListener.start() blocks in its own X11 event
    loop, so it runs on a background thread, calling back into
    on_hotkey_press/on_hotkey_release. A full turn (network call to
    Claude, TTS playback) must NOT block that thread, or a second
    hotkey press during a turn would never be detected - so
    _run_turn() itself runs on its own worker thread, spawned per
    turn (and tail-called on the same worker thread when the request
    queue, Component 14, has a next buffer waiting). Any call that
    touches GTK widgets (panel, overlay) from off the main thread is
    marshaled via GLib.idle_add(), since GTK is not thread-safe.
    """

    def __init__(self):
        self.controller = CompanionController()
        self.mic = MicRecorder()
        self.transcriber = Transcriber()
        self.session_store = SessionStore(CURRENT_SESSION_FILE)
        self.claude_client = ClaudeSessionClient(self.session_store, system_prompt=self._build_system_prompt())
        self.context_manager = ContextManager()
        self.tts = PiperTTS(model_path=str(Path.home() / ".waypoint" / "models" / "pt_BR-faber-medium.onnx"))
        self.panel = CompanionPanel(on_hotkey_rebind=self._on_hotkey_rebind)
        self.overlays: list[AnnotationOverlay] = [
            AnnotationOverlay(screen_index=s.screen_index) for s in capture_all_screens()
        ]
        self.hotkey = HotkeyListener(binding=DEFAULT_HOTKEY)
        self.tray = TrayIcon(on_click=self._on_tray_click)
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

    def _on_tray_click(self) -> None:
        GLib.idle_add(self.panel.show_near_tray)

    def _on_hotkey_rebind(self, binding: str) -> None:
        self.hotkey.set_binding(binding)

    def on_hotkey_press(self) -> None:
        # Called from the hotkey listener thread (see class docstring).
        self.controller.on_hotkey_press()
        if self.controller.state.name == "LISTENING":
            self.mic.start()
            GLib.idle_add(self.panel.set_status_text, "Ouvindo...")

    def on_hotkey_release(self) -> None:
        # Called from the hotkey listener thread. Spawns a worker
        # thread for the turn itself so this thread keeps polling for
        # the next hotkey event immediately (Component 14's queue only
        # helps if presses are still being detected while busy).
        audio_buffer = self.mic.stop()
        self.controller.on_hotkey_release(audio_buffer)
        if self.controller.state.name == "PROCESSING":
            threading.Thread(target=self._run_turn, args=(audio_buffer,), daemon=True).start()

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

        GLib.idle_add(self.panel.set_status_text, "Pensando...")

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
                    GLib.idle_add(overlay.draw_tag, tag)
        clean_text = strip_tags(response_text)
        self.context_manager.record_exchange(transcript, clean_text)

        # Data flow step 9
        self.controller.start_responding()
        GLib.idle_add(self.panel.set_status_text, clean_text)
        self.tts.speak(clean_text)

        # Data flow step 10
        self._last_activity = time.monotonic()
        next_buffer = self.controller.finish_turn()
        if next_buffer is not None:
            self._run_turn(next_buffer)
        else:
            GLib.idle_add(self.panel.set_status_text, "Segure Ctrl+Alt para falar")

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
    app.tray.run()  # non-blocking: spawns the GTK3 tray subprocess + listener thread

    threading.Thread(
        target=app.hotkey.start,
        kwargs={"on_press": app.on_hotkey_press, "on_release": app.on_hotkey_release},
        daemon=True,
    ).start()

    gtk_app = Gtk.Application(application_id="dev.waypoint.linux")

    def on_activate(gtk_app):
        gtk_app.add_window(app.panel)
        for overlay in app.overlays:
            gtk_app.add_window(overlay)

    gtk_app.connect("activate", on_activate)
    gtk_app.run(None)


if __name__ == "__main__":
    run_app()
