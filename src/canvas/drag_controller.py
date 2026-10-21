"""
src.canvas.drag_controller
==========================
Independent drag-and-drop position management for the three canvas
components: ``"clock"``, ``"date"``, and ``"visualizer"``.

Modes
-----
``DragController`` operates in two exclusive modes toggled by
:meth:`set_edit_mode`:

**Normal mode** (default)
    The canvas is fully click-through.  Mouse events are NOT connected
    and the overlay drawing is disabled.  The canvas window uses
    ``set_app_paintable(True)`` + ``input_shape_combine_region(cairo.Region())``.

**Edit / Drag mode**
    * Lightweight bounding boxes with corner grab-handles are painted around
      each component on every ``"draw"`` signal (via :meth:`draw_overlay`).
    * ``"button-press-event"``, ``"button-release-event"``, and
      ``"motion-notify-event"`` are connected to :meth:`on_press`,
      :meth:`on_release`, and :meth:`on_motion`.
    * Mouse-down inside a component's bbox begins a drag; motion updates
      the component's ``(x, y)`` in-memory.
    * Mouse-up saves the final coordinates back to
      :class:`~src.core.config.ConfigManager`.

Components
----------
Each component is a ``dict`` with:

* ``"x"``, ``"y"`` — current top-left corner (screen pixels).
* ``"w"``, ``"h"`` — bounding-box size (updated by the canvas on each frame).

These are kept in :attr:`components` which is a ``dict[str, dict]``.
The :attr:`components` dict is the *single source of truth* for the
positions used by :class:`~src.canvas.window.DesktopCanvasWindow` when
translating the Cairo context before each draw call.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import cairo

log = logging.getLogger(__name__)

# Names of the three draggable components.
COMPONENT_NAMES = ("clock", "date", "visualizer")

# Visual constants for the edit-mode overlay.
_HANDLE_RADIUS    = 6.0    # px — radius of corner grab handles
_BOX_LINE_WIDTH   = 1.5    # px
_BOX_COLOR        = (0.3, 0.8, 1.0, 0.9)   # RGBA — light-cyan bounding box
_HANDLE_COLOR     = (1.0, 1.0, 1.0, 1.0)   # RGBA — white handles
_LABEL_FONT_SIZE  = 11.0   # pt
_LABEL_COLOR      = (1.0, 1.0, 1.0, 0.9)


class DragController:
    """
    Manages drag-and-drop repositioning of the three canvas components.

    Parameters
    ----------
    cfg_manager:
        The running :class:`~src.core.config.ConfigManager` instance.
        ``get("positions.*")`` / ``set("positions.*")`` are called to
        read / persist coordinates.
    """

    def __init__(self, cfg_manager: Any) -> None:
        self._cfg = cfg_manager
        self._edit_mode: bool = False

        # Active drag state.
        self._dragging: Optional[str] = None   # component name being dragged
        self._drag_offset_x: float = 0.0
        self._drag_offset_y: float = 0.0

        # Live component state (populated by the canvas at startup).
        self.components: dict[str, dict[str, float]] = {}
        self._load_positions()

    # ------------------------------------------------------------------
    # Initialisation / persistence
    # ------------------------------------------------------------------

    def _load_positions(self) -> None:
        """
        Load positions from :class:`ConfigManager` into :attr:`components`.

        Missing components get a default bounding-box of 200×60.
        """
        for name in COMPONENT_NAMES:
            pos = self._cfg.get(f"positions.{name}") or {}
            self.components[name] = {
                "x": float(pos.get("x", 60)),
                "y": float(pos.get("y", 60)),
                "w": 200.0,   # placeholder — updated by the canvas on first draw
                "h":  60.0,
            }
        log.debug("DragController: loaded positions %s", self.components)

    def save_positions(self) -> None:
        """
        Persist all component positions back to :class:`ConfigManager`
        and flush to disk.
        """
        for name, state in self.components.items():
            self._cfg.set(f"positions.{name}.x", int(state["x"]))
            self._cfg.set(f"positions.{name}.y", int(state["y"]))
        self._cfg.save()
        log.debug("DragController: positions saved")

    def update_bbox(self, name: str, w: float, h: float) -> None:
        """
        Update the bounding-box dimensions of *name*.

        The canvas calls this after measuring a widget's drawn size so
        that hit-testing in drag mode is accurate.
        """
        if name in self.components:
            self.components[name]["w"] = w
            self.components[name]["h"] = h

    # ------------------------------------------------------------------
    # Mode switching
    # ------------------------------------------------------------------

    def is_edit_mode(self) -> bool:
        """Return ``True`` if edit/drag mode is active."""
        return self._edit_mode

    def set_edit_mode(self, enabled: bool) -> None:
        """
        Switch between normal and edit mode.

        In normal mode the canvas should call
        ``window.input_shape_combine_region(cairo.Region())``
        to make it click-through.
        In edit mode that region should be cleared so mouse events land.
        """
        self._edit_mode = enabled
        self._dragging = None
        log.info("DragController: edit_mode=%s", enabled)

    def toggle_edit_mode(self) -> bool:
        """Toggle edit mode and return the new state."""
        self.set_edit_mode(not self._edit_mode)
        return self._edit_mode

    # ------------------------------------------------------------------
    # Mouse event handlers (connected by the canvas in edit mode)
    # ------------------------------------------------------------------

    def on_press(self, widget: Any, event: Any) -> bool:
        """
        GTK ``"button-press-event"`` handler.

        Returns ``True`` (event consumed) if a component was hit.
        """
        if not self._edit_mode or event.button != 1:
            return False

        hit = self._hit_test(event.x, event.y)
        if hit:
            self._dragging = hit
            comp = self.components[hit]
            self._drag_offset_x = event.x - comp["x"]
            self._drag_offset_y = event.y - comp["y"]
            log.debug("DragController: drag start %r offset=(%.0f,%.0f)",
                      hit, self._drag_offset_x, self._drag_offset_y)
            return True
        return False

    def on_motion(self, widget: Any, event: Any) -> bool:
        """
        GTK ``"motion-notify-event"`` handler.

        Moves the active component as the mouse drags.
        """
        if not self._edit_mode or not self._dragging:
            return False

        comp = self.components[self._dragging]
        comp["x"] = event.x - self._drag_offset_x
        comp["y"] = event.y - self._drag_offset_y

        # Request a redraw so the overlay follows the mouse.
        if hasattr(widget, "queue_draw"):
            widget.queue_draw()
        return True

    def on_release(self, widget: Any, event: Any) -> bool:
        """
        GTK ``"button-release-event"`` handler.

        Finalises the drag and persists positions.
        """
        if not self._edit_mode or not self._dragging:
            return False

        log.debug(
            "DragController: drag end %r → (%.0f, %.0f)",
            self._dragging,
            self.components[self._dragging]["x"],
            self.components[self._dragging]["y"],
        )
        self._dragging = None
        self.save_positions()
        return True

    # ------------------------------------------------------------------
    # Overlay drawing (edit mode only)
    # ------------------------------------------------------------------

    def draw_overlay(self, ctx: cairo.Context) -> None:
        """
        Draw bounding boxes and grab-handles for all components.

        Call this from the canvas ``"draw"`` signal handler **after** all
        theme content has been painted, and **only** when in edit mode.
        """
        if not self._edit_mode:
            return

        ctx.save()
        for name, comp in self.components.items():
            self._draw_component_box(ctx, name, comp)
        ctx.restore()

    def _draw_component_box(
        self,
        ctx: cairo.Context,
        name: str,
        comp: dict,
    ) -> None:
        """Draw a single component's bounding box with corner handles."""
        x, y = comp["x"], comp["y"]
        w, h = comp["w"], comp["h"]

        is_active = (name == self._dragging)

        # Bounding box rectangle.
        ctx.set_line_width(_BOX_LINE_WIDTH)
        if is_active:
            ctx.set_source_rgba(1.0, 0.8, 0.2, 1.0)   # orange when dragging
        else:
            ctx.set_source_rgba(*_BOX_COLOR)
        ctx.rectangle(x, y, w, h)
        ctx.stroke()

        # Corner grab handles.
        ctx.set_source_rgba(*_HANDLE_COLOR)
        for hx, hy in [(x, y), (x + w, y), (x, y + h), (x + w, y + h)]:
            ctx.arc(hx, hy, _HANDLE_RADIUS, 0, 6.2832)
            ctx.fill()

        # Label (component name) inside the top-left corner.
        ctx.set_source_rgba(*_LABEL_COLOR)
        ctx.select_font_face("Sans", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(_LABEL_FONT_SIZE)
        ctx.move_to(x + _HANDLE_RADIUS + 2, y + _LABEL_FONT_SIZE + 2)
        ctx.show_text(name.upper())

    # ------------------------------------------------------------------
    # Hit testing
    # ------------------------------------------------------------------

    def _hit_test(self, mx: float, my: float) -> Optional[str]:
        """
        Return the name of the component whose bounding box contains
        ``(mx, my)``, or ``None`` if the point is outside all boxes.

        Iterates in reverse insertion order so the topmost-drawn component
        gets priority.
        """
        for name in reversed(list(self.components.keys())):
            comp = self.components[name]
            x, y, w, h = comp["x"], comp["y"], comp["w"], comp["h"]
            if x <= mx <= x + w and y <= my <= y + h:
                return name
        return None

    def __repr__(self) -> str:  # pragma: no cover
        mode = "EDIT" if self._edit_mode else "NORMAL"
        return f"DragController(mode={mode}, dragging={self._dragging!r})"
