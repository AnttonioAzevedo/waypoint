import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gtk, Adw, GLib  # noqa: E402

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

        # Task 21 (UI polish): waveform view driven by MicRecorder's
        # level_callback while LISTENING, matching
        # CompanionResponseOverlay.swift's waveform purpose.
        self._waveform_area = Gtk.DrawingArea()
        self._waveform_area.set_content_height(40)
        self._waveform_area.set_draw_func(self._on_draw_waveform)
        self._levels: list[float] = [0.0] * 24

        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        box.append(self._status_label)
        box.append(self._waveform_area)

        # Task 21: crossfade the whole panel body in/out instead of
        # popping, matching the original app's "Transient Cursor Mode"
        # fade-out-after-1s-idle behavior (spec UI polish section).
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self._revealer.set_transition_duration(300)
        self._revealer.set_child(box)
        self._revealer.set_reveal_child(True)
        self.set_child(self._revealer)

        self._on_hotkey_rebind = on_hotkey_rebind
        self._fade_timeout_id: int | None = None

    def show_near_tray(self) -> None:
        self._revealer.set_reveal_child(True)
        self.present()

    def hide_panel(self) -> None:
        self._revealer.set_reveal_child(False)
        # Give the 300ms crossfade time to finish before actually
        # hiding the window, or the fade never gets seen.
        GLib.timeout_add(320, self._finish_hide)

    def _finish_hide(self) -> bool:
        self.set_visible(False)
        return GLib.SOURCE_REMOVE

    def set_status_text(self, text: str) -> None:
        self._status_label.set_label(text)

    def push_level(self, level: float) -> None:
        """Called (via GLib.idle_add from MicRecorder's level_callback,
        since this touches a GTK widget) once per audio frame while
        LISTENING. Keeps a rolling window of recent levels and redraws
        the waveform bars."""
        self._levels.pop(0)
        self._levels.append(max(0.0, min(1.0, level)))
        self._waveform_area.queue_draw()

    def reset_waveform(self) -> None:
        self._levels = [0.0] * len(self._levels)
        self._waveform_area.queue_draw()

    def _on_draw_waveform(self, area, cr, width, height) -> None:
        if not self._levels:
            return
        bar_width = width / len(self._levels)
        cr.set_source_rgb(0.1, 0.5, 1.0)
        for i, level in enumerate(self._levels):
            bar_height = max(2, level * height)
            x = i * bar_width
            y = (height - bar_height) / 2
            cr.rectangle(x + 1, y, max(1, bar_width - 2), bar_height)
        cr.fill()
