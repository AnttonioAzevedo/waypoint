from typing import Callable, Optional

from Xlib import X, XK
from Xlib.display import Display

# Modifier name -> Xlib modifier mask
_MODIFIER_MASKS = {
    "ctrl": X.ControlMask,
    "alt": X.Mod1Mask,
    "shift": X.ShiftMask,
    "super": X.Mod4Mask,
}

# Modifier name -> the keysym of its own physical key, used when the
# whole binding is modifier-only (e.g. "ctrl+alt" has no letter key).
_MODIFIER_OWN_KEYSYMS = {
    "ctrl": XK.XK_Control_L,
    "alt": XK.XK_Alt_L,
    "shift": XK.XK_Shift_L,
    "super": XK.XK_Super_L,
}


class HotkeyGrabError(RuntimeError):
    """Raised when XGrabKey fails - most commonly because another
    client (the window manager, another app) already holds a grab on
    the same keycode+modifier combination. python-xlib delivers this as
    an async X protocol error (BadAccess), not a Python exception, so
    start() installs an error handler to catch and raise it explicitly
    instead of silently doing nothing (a real failure mode found during
    manual verification against a live GNOME session)."""


def _parse_binding(display: Display, binding: str) -> tuple[int, int]:
    """'ctrl+alt' -> (keycode of the *last* modifier's own key, combined
    mask of every modifier *except* the last one). Grabbing X.AnyKey
    with the full combined mask looks equivalent but isn't: it fails
    with BadAccess the moment any other client has grabbed *any single*
    keycode under that same modifier mask (e.g. GNOME's own Ctrl+Alt+T
    or Ctrl+Alt+Left/Right bindings) - a real failure observed against a
    live GNOME session that a synthetic AnyKey grab is far more likely
    to collide with than a real physical key."""
    parts = binding.lower().split("+")
    *other_parts, last_part = parts
    mask = 0
    for part in other_parts:
        mask |= _MODIFIER_MASKS[part]
    keysym = _MODIFIER_OWN_KEYSYMS[last_part]
    keycode = display.keysym_to_keycode(keysym)
    return keycode, mask


class HotkeyListener:
    def __init__(self, binding: str):
        self.binding = binding
        self._display: Optional[Display] = None
        self._on_press: Optional[Callable[[], None]] = None
        self._on_release: Optional[Callable[[], None]] = None
        self._grab_keycode: Optional[int] = None
        self._grab_mask: Optional[int] = None

    def set_binding(self, binding: str) -> None:
        self.binding = binding

    def start(self, on_press: Callable[[], None], on_release: Callable[[], None]) -> None:
        self._on_press = on_press
        self._on_release = on_release
        self._display = Display()
        root = self._display.screen().root

        errors: list[Exception] = []
        self._display.set_error_handler(lambda err, req=None: errors.append(err))

        keycode, mask = _parse_binding(self._display, self.binding)
        self._grab_keycode, self._grab_mask = keycode, mask
        root.grab_key(keycode, mask, True, X.GrabModeAsync, X.GrabModeAsync)
        self._display.sync()

        if errors:
            self._display.close()
            self._display = None
            raise HotkeyGrabError(
                f"Failed to grab hotkey '{self.binding}' - it's likely already bound by "
                f"another application (e.g. the window manager). Try a different binding."
            )

        pressed = False
        while True:
            event = self._display.next_event()
            if event.type == X.KeyPress and not pressed:
                pressed = True
                self._on_press()
            elif event.type == X.KeyRelease and pressed:
                pressed = False
                self._on_release()

    def stop(self) -> None:
        if self._display:
            root = self._display.screen().root
            if self._grab_keycode is not None:
                root.ungrab_key(self._grab_keycode, self._grab_mask)
            self._display.close()
            self._display = None
