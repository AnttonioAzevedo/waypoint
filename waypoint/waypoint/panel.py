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
