"""Component 1: tray icon, running in a separate GTK3 process.

**Revised during implementation**: AppIndicator3's typelib forces GTK3 to
load in-process - verified live that this collides fatally with the app's
GTK4 panel/overlay (`gi.RepositoryError: Requiring namespace 'Gtk' version
'4.0', but '3.0' is already loaded`). No GTK4-native tray indicator library
is available on this system - even the Ayatana fork's typelib is packaged
GTK-3-only (`gir1.2-ayatanaappindicator3-0.1` is explicitly labeled "GTK-3+
version"). Fix: the tray icon runs as its own tiny subprocess (GTK3 +
AppIndicator3 only, see tray_process.py), talking to the main GTK4 process
over a local Unix domain socket - one "click" message whenever the tray
menu's "Open Companion" item is activated.
"""
import socket
import subprocess
import sys
import threading
from typing import Callable, Optional

from waypoint.config import WAYPOINT_HOME

TRAY_SOCKET_PATH = WAYPOINT_HOME / "tray.sock"


class TrayIcon:
    """Spawns the GTK3/AppIndicator3 tray subprocess and invokes
    on_click() in THIS process whenever it's clicked, via a local Unix
    socket. run() is non-blocking - it starts the subprocess and a
    background listener thread, then returns, so the caller's own GTK4
    main loop (panel/overlay) can run in this process afterward."""

    def __init__(self, on_click: Callable[[], None]):
        self._on_click = on_click
        self._process: Optional[subprocess.Popen] = None
        self._server: Optional[socket.socket] = None

    def run(self) -> None:
        TRAY_SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        if TRAY_SOCKET_PATH.exists():
            TRAY_SOCKET_PATH.unlink()

        self._server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._server.bind(str(TRAY_SOCKET_PATH))
        self._server.listen(1)

        threading.Thread(target=self._listen, daemon=True).start()

        self._process = subprocess.Popen(
            [sys.executable, "-m", "waypoint.tray_process", str(TRAY_SOCKET_PATH)]
        )

    def _listen(self) -> None:
        while True:
            conn, _ = self._server.accept()
            with conn:
                data = conn.recv(1024)
                if data == b"click":
                    self._on_click()

    def stop(self) -> None:
        if self._process:
            self._process.terminate()
        if self._server:
            self._server.close()
