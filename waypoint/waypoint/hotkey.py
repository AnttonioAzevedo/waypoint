"""Component 3: global push-to-talk hotkey.

**Revised during implementation**: the original design used raw
`python-xlib` `XGrabKey`. Verified live on a real GNOME/Pop!_OS 24.04
session that this doesn't reliably work: even after fixing a real
`owner_events` bug and confirming no GNOME shortcut conflict (checked
via `gsettings`), neither a real physical key press nor a synthetic
XTest key event ever reached the grab - only a spurious
`MappingNotify`, never `KeyPress`/`KeyRelease`. Root cause not fully
isolated, but `XGrabKey`-based global hotkeys are a known-fragile area
across Linux desktop environments. Switched to `pynput`, a
battle-tested library for exactly this: verified live that its
listener (backed by the X `RECORD` extension, a passive monitoring
mechanism rather than an exclusive grab - it doesn't compete with the
window manager's own shortcuts the way `XGrabKey` does) correctly
receives both real and XTest-synthetic key events.
"""
from typing import Callable, Optional

from pynput import keyboard

# Modifier name -> the set of pynput Key values that count as "this
# modifier", since pynput reports left/right variants separately
# (e.g. Key.ctrl_l vs Key.ctrl_r) but a binding like "ctrl+alt" should
# match either side.
_MODIFIER_KEYS: dict[str, set] = {
    "ctrl": {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r},
    "alt": {keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r},
    "shift": {keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r},
    "super": {keyboard.Key.cmd, keyboard.Key.cmd_l, keyboard.Key.cmd_r},
}


def _parse_binding(binding: str) -> list[set]:
    """'ctrl+alt' -> [{ctrl_l, ctrl_r, ctrl}, {alt_l, alt_r, alt}] -
    one set of acceptable keys per required modifier."""
    return [_MODIFIER_KEYS[part] for part in binding.lower().split("+")]


class HotkeyListener:
    """Fires on_press() once every required modifier in the binding is
    held simultaneously (regardless of press order), and on_release()
    as soon as any of them is released. start() blocks - run it on a
    background thread (see app.py)."""

    def __init__(self, binding: str):
        self.binding = binding
        self._required = _parse_binding(binding)
        self._pressed: set = set()
        self._active = False
        self._listener: Optional[keyboard.Listener] = None
        self._on_press: Optional[Callable[[], None]] = None
        self._on_release: Optional[Callable[[], None]] = None

    def set_binding(self, binding: str) -> None:
        self.binding = binding
        self._required = _parse_binding(binding)

    def start(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._listener = keyboard.Listener(on_press=self._handle_press, on_release=self._handle_release)
        self._listener.start()
        self._listener.join()

    def _all_required_held(self) -> bool:
        return all(any(key in self._pressed for key in group) for group in self._required)

    def _handle_press(self, key) -> None:
        self._pressed.add(key)
        if not self._active and self._all_required_held():
            self._active = True
            self._on_press()

    def _handle_release(self, key) -> None:
        self._pressed.discard(key)
        if self._active and not self._all_required_held():
            self._active = False
            self._on_release()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
