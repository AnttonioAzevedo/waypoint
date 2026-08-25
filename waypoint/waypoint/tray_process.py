"""Standalone GTK3 + AppIndicator3 process for the tray icon (spec
Component 1). Launched by tray.py's TrayIcon as a subprocess, kept
separate from the main GTK4 process because AppIndicator3's typelib
forces GTK3 to load, which cannot coexist with GTK4 in one process
(verified live: `gi.RepositoryError: Requiring namespace 'Gtk' version
'4.0', but '3.0' is already loaded`). Sends a one-word message over a
local Unix socket to the main process whenever the tray menu's "Open
Companion" item is clicked.
"""
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
