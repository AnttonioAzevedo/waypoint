import gi

gi.require_version("Gtk", "4.0")
from gi.repository import Gtk, GLib  # noqa: E402

from waypoint.config import ANNOTATION_FADE_SECONDS
from waypoint.tags import PointTag, HighlightTag, AnnotateTag, Tag


class AnnotationOverlay(Gtk.Window):
    """Component 9: full-screen transparent, click-through overlay for
    one monitor. Renders POINT/HIGHLIGHT/ANNOTATE tags with Cairo via a
    Gtk.DrawingArea. Non-activating, click-through except the cursor
    widget itself - achieved via an input shape mask (set at the
    windowing-system level; confirm the exact GTK4/X11 call available
    on the installed GTK version when wiring this up for real)."""

    def __init__(self, screen_index: int):
        super().__init__()
        self.screen_index = screen_index
        self.set_decorated(False)

        self._drawing_area = Gtk.DrawingArea()
        self._drawing_area.set_draw_func(self._on_draw)

        # Task 21 (UI polish): crossfade the whole overlay in when the
        # first tag of a response appears, and out once the last one
        # is gone - annotation marks read as part of the same visual
        # system as the panel, not a bolted-on layer (spec UI polish).
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.CROSSFADE)
        self._revealer.set_transition_duration(300)
        self._revealer.set_child(self._drawing_area)
        self._revealer.set_reveal_child(False)
        self.set_child(self._revealer)

        self._active_tags: list[Tag] = []

    def draw_tag(self, tag: Tag) -> None:
        self._active_tags.append(tag)
        self._revealer.set_reveal_child(True)
        self._drawing_area.queue_draw()

        if isinstance(tag, (HighlightTag, AnnotateTag)):
            GLib.timeout_add_seconds(ANNOTATION_FADE_SECONDS, self._fade_out, tag)

    def clear(self) -> None:
        self._active_tags = []
        self._revealer.set_reveal_child(False)
        self._drawing_area.queue_draw()

    def _fade_out(self, tag: Tag) -> bool:
        if tag in self._active_tags:
            self._active_tags.remove(tag)
            self._drawing_area.queue_draw()
            if not self._active_tags:
                self._revealer.set_reveal_child(False)
        return GLib.SOURCE_REMOVE

    def _on_draw(self, area, cr, width, height) -> None:
        for tag in self._active_tags:
            if isinstance(tag, PointTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.arc(tag.x, tag.y, 12, 0, 2 * 3.14159)
                cr.fill()
            elif isinstance(tag, HighlightTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.set_line_width(3)
                cr.rectangle(tag.x, tag.y, tag.w, tag.h)
                cr.stroke()
            elif isinstance(tag, AnnotateTag):
                cr.set_source_rgb(0.1, 0.5, 1.0)
                cr.set_line_width(3)
                if tag.shape == "arrow":
                    x1, y1, x2, y2 = tag.params
                    cr.move_to(x1, y1)
                    cr.line_to(x2, y2)
                    cr.stroke()
                elif tag.shape == "circle":
                    x, y, radius = tag.params
                    cr.arc(x, y, radius, 0, 2 * 3.14159)
                    cr.stroke()
                elif tag.shape == "underline":
                    x1, y, x2 = tag.params
                    cr.move_to(x1, y)
                    cr.line_to(x2, y)
                    cr.stroke()
