"""
src.canvas.window
=================
Borderless RGBA GTK3 desktop overlay window — the visual canvas for the
clock, date label, and audio visualizer.

X11 / EWMH layering strategy
-----------------------------
The goal is a window that:

* Sits at the desktop layer (below all app windows, above the wallpaper).
* Is fully transparent to mouse clicks in normal mode.
* Never steals keyboard focus.
* Survives Alt+F4 on an empty desktop.
* Does not appear in the taskbar or window switcher.

Implementation (mirrors ``~/.config/desktop-clock.py`` lines 57–75):

1. ``set_decorated(False)``
2. ``set_skip_taskbar_hint(True)`` / ``set_skip_pager_hint(True)``
3. ``set_keep_below(True)``
4. ``screen.get_rgba_visual()`` → ``set_visual()`` for per-pixel alpha.
5. GTK type hint: ``Gdk.WindowTypeHint.DESKTOP`` (falls back to DOCK).
6. ``set_accept_focus(False)`` + ``set_focus_on_map(False)``.
7. ``connect("delete-event", lambda w, e: True)`` — swallow all close requests.
8. In normal mode: ``input_shape_combine_region(cairo.Region())`` makes the
   window fully click-through.

Draw loop
---------
Two GLib timers run concurrently:

* **30 FPS** (≈33 ms) — ``animate_tick``: advances visualizer bar
  animation (attack / decay), triggers a ``queue_draw``.
* **1 Hz** — ``clock_tick``: refreshes the :class:`TimeData` snapshot
  so the clock label updates once per second.

All theme drawing happens inside the ``"draw"`` signal callback which Cairo
calls exactly when GTK decides to repaint, minimising redundant work.
"""

from __future__ import annotations

import logging
import sys
import os
import subprocess
from typing import Any, Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib
import ctypes
import ctypes.util
import cairo
import numpy as np

from src.core.fonts import register_bundled_fonts
register_bundled_fonts()

log = logging.getLogger(__name__)


def _raise_x11_window(xid: int) -> bool:
    """Raise the window to the top of its current stack layer in X11."""
    try:
        lib_name = ctypes.util.find_library("X11") or "libX11.so.6"
        x11 = ctypes.CDLL(lib_name)
        x11.XOpenDisplay.restype = ctypes.c_void_p
        x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
        x11.XRaiseWindow.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        x11.XFlush.argtypes = [ctypes.c_void_p]

        disp = x11.XOpenDisplay(None)
        if not disp:
            return False
        x11.XRaiseWindow(disp, ctypes.c_ulong(xid))
        x11.XFlush(disp)
        x11.XCloseDisplay(disp)
        return True
    except Exception as exc:
        log.debug("XRaiseWindow failed for xid %s: %s", xid, exc)
        return False


# Frame period for the visualizer animation loop (~30 FPS).
_ANIM_INTERVAL_MS: int = 33

# Visualizer animation smoothing constants (ported from reference animate_visualizer).
_ATTACK_COEFF: float = 0.46    # reference: += (target - current) * 0.46
_DECAY_COEFF:  float = 0.83    # reference: current * 0.83
_DECAY_FLOOR:  float = 0.25    # reference: - 0.25


class DesktopCanvasWindow(Gtk.Window):
    """
    Borderless full-screen RGBA desktop overlay window.

    Parameters
    ----------
    cfg_manager:
        :class:`~src.core.config.ConfigManager` instance.
    theme:
        A :class:`~src.themes.base.BaseTheme` instance to use for drawing.
    audio_stream:
        Optional pre-started :class:`~src.canvas.audio.AudioStream`.
        If ``None``, the visualizer is skipped.
    wallpaper_engine:
        Optional :class:`~src.wallpaper.engine.WallpaperEngine` instance
        to coordinate Z-order stacking with.
    """

    def __init__(
        self,
        cfg_manager: Any,
        theme: Any,
        audio_stream: Optional[Any] = None,
        wallpaper_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self._cfg      = cfg_manager
        self._theme    = theme
        self._audio    = audio_stream
        self._wallpaper_engine = wallpaper_engine

        # Canvas config shortcut.
        self._ccfg: dict = self._cfg.get("canvas") or {}

        # Time snapshot updated by the 1 Hz timer.
        from src.themes.base import TimeData
        self._time_data = TimeData.now()

        # Animated bar heights for the visualizer (smooth interpolation layer).
        # These are pixel-space values; AudioStream provides 0–1 normalised floats.
        from src.canvas.audio import NUM_BANDS
        total_bars = (NUM_BANDS * 2) - 1
        self._bar_heights: np.ndarray = np.zeros(total_bars, dtype=np.float32)

        # Drag controller.
        from src.canvas.drag_controller import DragController
        self._drag = DragController(cfg_manager)

        # ----------------------------------------------------------
        # GTK window properties
        # ----------------------------------------------------------
        self.set_decorated(False)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)
        self.set_keep_below(True)
        self.set_accept_focus(False)
        self.set_focus_on_map(False)
        self.set_app_paintable(True)

        # Type hint: NORMAL with keep_below(True) places the window in the
        # _NET_WM_STATE_BELOW layer, immediately above the root/xwinwrap desktop plane.
        # Fall back to DESKTOP if needed.
        try:
            self.set_type_hint(Gdk.WindowTypeHint.NORMAL)
            self.set_keep_below(True)
        except Exception:
            self.set_type_hint(Gdk.WindowTypeHint.DESKTOP)
            self.set_keep_below(True)

        # RGBA visual for per-pixel alpha transparency.
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        else:
            log.warning(
                "DesktopCanvasWindow: compositor not running — "
                "transparency will not work"
            )

        # Transparent GTK background.
        css = Gtk.CssProvider()
        css.load_from_data(b"window { background-color: rgba(0,0,0,0); }")
        Gtk.StyleContext.add_provider_for_screen(
            screen, css, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

        # Swallow close requests so Alt+F4 on the empty desktop never kills us.
        self.connect("delete-event", lambda w, e: True)

        # Full-screen size — use Gdk.Display/Monitor API (GDK 3.22+).
        display  = Gdk.Display.get_default()
        monitor  = display.get_primary_monitor() or display.get_monitor(0)
        rect     = monitor.get_geometry()
        self.set_default_size(rect.width, rect.height)
        self.move(rect.x, rect.y)

        # ----------------------------------------------------------
        # Drawing area
        # ----------------------------------------------------------
        self._darea = Gtk.DrawingArea()
        self._darea.connect("draw", self._on_draw)
        self.add(self._darea)

        # ----------------------------------------------------------
        # Event masks — needed for drag mode
        # ----------------------------------------------------------
        self.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
        )
        self.connect("button-press-event",   self._drag.on_press)
        self.connect("button-release-event", self._drag.on_release)
        self.connect("motion-notify-event",  self._drag.on_motion)

        # ----------------------------------------------------------
        # Apply click-through in normal mode & raise above wallpaper
        # ----------------------------------------------------------
        self.connect("realize", lambda w: (self._apply_input_shape(), self._raise_above_wallpaper()))
        self.connect("map-event", lambda w, e: (self._apply_input_shape(), self._raise_above_wallpaper(), False)[2])
        self._apply_input_shape()

        # Connect to wallpaper engine if supplied
        if self._wallpaper_engine is not None:
            self.connect_wallpaper_engine(self._wallpaper_engine)

        # ----------------------------------------------------------
        # GLib timers
        # ----------------------------------------------------------
        # 30 FPS animation + draw tick.
        GLib.timeout_add(_ANIM_INTERVAL_MS, self._animate_tick)
        # 1 Hz clock update.
        GLib.timeout_add_seconds(1, self._clock_tick)

    # ------------------------------------------------------------------
    # Timer callbacks
    # ------------------------------------------------------------------

    def _animate_tick(self) -> bool:
        """
        ~30 FPS timer: advance visualizer bar animation and queue a redraw.

        Attack/decay logic is a direct port of ``animate_visualizer``
        from ``desktop-clock.py`` lines 347–355.

        Returns ``True`` to keep the timer firing.
        """
        if self._audio is not None and self._cfg.get("canvas.visualizer_enabled"):
            with self._audio.lock:
                target_bars = self._audio.bars.copy()

            vis_h = self._get_visualizer_height()
            for i in range(len(self._bar_heights)):
                target = float(target_bars[i]) * vis_h if i < len(target_bars) else 0.0
                current = float(self._bar_heights[i])
                if target > current:
                    self._bar_heights[i] = current + (target - current) * _ATTACK_COEFF
                else:
                    self._bar_heights[i] = max(0.0, current * _DECAY_COEFF - _DECAY_FLOOR)

        self._darea.queue_draw()
        return True   # keep timer alive

    def _clock_tick(self) -> bool:
        """
        1 Hz timer: refresh the TimeData snapshot.

        Returns ``True`` to keep the timer firing.
        """
        from src.themes.base import TimeData
        self._time_data = TimeData.now()
        return True

    # ------------------------------------------------------------------
    # Main draw callback
    # ------------------------------------------------------------------

    def _on_draw(self, widget: Gtk.DrawingArea, ctx: cairo.Context) -> None:
        """
        GTK ``"draw"`` signal handler — the entire canvas is painted here.

        Sequence:
        1. Clear to transparent.
        2. draw_background (optional dim layer).
        3. draw_clock (if enabled).
        4. draw_date (if enabled).
        5. draw_visualizer (if enabled and audio running).
        6. draw_overlay (bounding boxes when in edit mode).
        """
        alloc = widget.get_allocation()
        w, h  = alloc.width, alloc.height

        # 1 — Clear to fully transparent.
        ctx.save()
        ctx.set_operator(cairo.OPERATOR_CLEAR)
        ctx.paint()
        ctx.restore()
        ctx.set_operator(cairo.OPERATOR_OVER)

        ccfg = self._ccfg

        # 2 — Background dim layer.
        self._theme.draw_background(ctx, w, h, ccfg)

        master_scale = float(ccfg.get("scale", 1.0) or 1.0)
        independent = bool(ccfg.get("independent_scales", False))

        if independent:
            clock_scale = master_scale * float(ccfg.get("clock_scale", 1.0) or 1.0)
            date_scale = master_scale * float(ccfg.get("date_scale", 1.0) or 1.0)
            vis_scale = master_scale * float(ccfg.get("visualizer_scale", 1.0) or 1.0)
        else:
            clock_scale = master_scale
            date_scale = master_scale
            vis_scale = master_scale

        # 3 — Clock.
        if ccfg.get("clock_enabled", True):
            clock_cfg = {**ccfg, "scale": clock_scale}
            pos = self._drag.components.get("clock", {"x": 468, "y": 260})
            base_clk_w = float(getattr(self._theme, "clock_base_width", 430.0))
            base_clk_h = float(getattr(self._theme, "clock_base_height", 100.0))
            clk_w = int(base_clk_w * clock_scale)
            clk_h = int(base_clk_h * clock_scale)
            ctx.save()
            ctx.translate(pos["x"], pos["y"])
            self._theme.draw_clock(ctx, clk_w, clk_h, clock_cfg, self._time_data)
            ctx.restore()
            self._drag.update_bbox("clock", float(clk_w), float(clk_h))

        # 4 — Date.
        if ccfg.get("date_enabled", True):
            date_cfg = {**ccfg, "scale": date_scale}
            pos = self._drag.components.get("date", {"x": 468, "y": 370})
            base_dt_w = float(getattr(self._theme, "date_base_width", 430.0))
            base_dt_h = float(getattr(self._theme, "date_base_height", 95.0))
            dt_w = int(base_dt_w * date_scale)
            dt_h = int(base_dt_h * date_scale)
            ctx.save()
            ctx.translate(pos["x"], pos["y"])
            self._theme.draw_date(ctx, dt_w, dt_h, date_cfg, self._time_data)
            ctx.restore()
            self._drag.update_bbox("date", float(dt_w), float(dt_h))

        # 5 — Visualizer.
        if ccfg.get("visualizer_enabled", True) and self._audio is not None:
            vis_cfg = {**ccfg, "scale": vis_scale}
            pos = self._drag.components.get("visualizer", {"x": 468, "y": 410})
            base_vis_w = float(getattr(self._theme, "vis_base_width", 430.0))
            base_vis_h = getattr(self._theme, "vis_base_height", None)
            vis_w = int(base_vis_w * vis_scale)
            vis_h = int(float(base_vis_h) * vis_scale) if base_vis_h is not None else self._get_visualizer_height(vis_scale)

            ctx.save()
            ctx.translate(pos["x"], pos["y"])
            # Normalise pixel bar heights back to [0,1] for the theme.
            norm_bars = (
                self._bar_heights / vis_h if vis_h > 0
                else np.zeros_like(self._bar_heights)
            )
            self._theme.draw_visualizer(ctx, vis_w, vis_h, vis_cfg, norm_bars)
            ctx.restore()

            # Update bounding box so DragController hit-testing is accurate.
            self._drag.update_bbox("visualizer", float(vis_w), float(vis_h))

        # 6 — Edit-mode overlay.
        self._drag.draw_overlay(ctx)

    # ------------------------------------------------------------------
    # Edit mode toggle (public API for the settings GUI)
    # ------------------------------------------------------------------

    def toggle_edit_mode(self) -> bool:
        """
        Toggle drag/edit mode on or off.

        In normal mode the window becomes click-through via
        ``input_shape_combine_region``.

        Returns the new edit-mode state.
        """
        new_state = self._drag.toggle_edit_mode()
        self._apply_input_shape()
        self._darea.queue_draw()
        return new_state

    # ------------------------------------------------------------------
    # Theme and config hot-swap (public API)
    # ------------------------------------------------------------------

    def set_theme(self, theme: Any) -> None:
        """Replace the active theme at runtime."""
        self._theme = theme
        self._darea.queue_draw()

    def reload_config(self) -> None:
        """Re-read the canvas section from ConfigManager after a settings change."""
        self._ccfg = self._cfg.get("canvas") or {}
        if self._theme:
            self._theme.invalidate()
        self._darea.queue_draw()

    # ------------------------------------------------------------------
    # Wallpaper coordination & Z-order stacking (public API)
    # ------------------------------------------------------------------

    def connect_wallpaper_engine(self, engine: Any) -> None:
        """Connect to the wallpaper engine's state changes to raise canvas when wallpaper starts."""
        self._wallpaper_engine = engine
        if hasattr(engine, "add_state_callback"):
            engine.add_state_callback(self._on_wallpaper_state_change)

    def _on_wallpaper_state_change(self, state: str) -> None:
        """Called whenever the wallpaper engine transitions state."""
        if state in ("started", "active", "resumed", "running"):
            GLib.idle_add(self._raise_above_wallpaper)

    def raise_above_wallpaper(self) -> None:
        """Public API: raise the canvas window above the desktop wallpaper stack without stealing focus."""
        self._raise_above_wallpaper()

    def _raise_above_wallpaper(self) -> None:
        """Raise the GDK window above the wallpaper while maintaining keep_below and no focus."""
        gdk_win = self.get_window()
        if gdk_win:
            gdk_win.raise_()
            self.set_keep_below(True)
            try:
                xid = gdk_win.get_xid()
                if xid:
                    _raise_x11_window(xid)
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _apply_input_shape(self) -> None:
        """
        Apply or clear the input shape region.

        Normal mode → empty region → fully click-through.
        Edit mode   → full region → receives all events.
        """
        gdkwin = self.get_window()
        if gdkwin is None:
            return   # window not yet realized
        if self._drag.is_edit_mode():
            alloc = self.get_allocation()
            w = max(alloc.width, 4096)
            h = max(alloc.height, 4096)
            full_region = cairo.Region(cairo.RectangleInt(0, 0, w, h))
            gdkwin.input_shape_combine_region(full_region, 0, 0)
        else:
            # Empty cairo.Region() → no hit area → click-through.
            empty = cairo.Region()
            gdkwin.input_shape_combine_region(empty, 0, 0)

    def _get_visualizer_height(self, scale_override: Optional[float] = None) -> int:
        """Return the visualizer panel height in pixels."""
        if scale_override is not None:
            scale = scale_override
        else:
            scale = float(self._cfg.get("canvas.scale") or 1.0)
        return max(10, int(54 * scale))

    def __repr__(self) -> str:  # pragma: no cover
        return f"DesktopCanvasWindow(theme={self._theme!r})"


# ---------------------------------------------------------------------------
# Self-test block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import os

    # ── Path setup ───────────────────────────────────────────────────────
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(os.path.dirname(_here))
    if _root not in sys.path:
        sys.path.insert(0, _root)

    logging.basicConfig(level=logging.DEBUG, format="%(name)s %(levelname)s %(message)s")

    print("=" * 60)
    print("DesktopCanvasWindow — self-test (5-second display)")
    print("=" * 60)

    # ── 1. Load ConfigManager ────────────────────────────────────────────
    print("\n[1] Loading ConfigManager …")
    from src.core.config import ConfigManager
    cfg = ConfigManager()
    print(f"    canvas.clock_enabled    = {cfg.get('canvas.clock_enabled')}")
    print(f"    canvas.visualizer_enabled = {cfg.get('canvas.visualizer_enabled')}")
    print("    ConfigManager OK ✓")

    # ── 2. Get default theme from registry ──────────────────────────────
    print("\n[2] Loading theme registry …")
    from src.themes.registry import REGISTRY
    theme = REGISTRY.get_default()
    assert theme is not None, "No default theme registered!"
    print(f"    Active theme: {theme.name!r} ✓")

    # ── 3. Start audio (optional — skip gracefully if parec unavailable) ─
    print("\n[3] Starting audio stream …")
    from src.canvas.audio import AudioStream
    audio = AudioStream()
    audio.start()
    if audio.is_running:
        print("    AudioStream running ✓")
    else:
        print("    AudioStream could not start (no audio device?) — continuing")
        audio = None

    # ── 4. Instantiate and show the canvas window ────────────────────────
    print("\n[4] Creating DesktopCanvasWindow …")
    win = DesktopCanvasWindow(cfg_manager=cfg, theme=theme, audio_stream=audio)
    win.show_all()
    print("    Window shown ✓")
    print("    (visible for 5 seconds — check desktop for the canvas overlay)")

    # ── 5. Auto-quit after 5 seconds ────────────────────────────────────
    def _quit_after_delay():
        print("\n[5] 5 s elapsed — cleaning up …")
        if audio:
            audio.stop()
            print("    AudioStream stopped ✓")
        Gtk.main_quit()
        return False   # don't repeat

    GLib.timeout_add(5000, _quit_after_delay)

    Gtk.main()

    print("\n" + "=" * 60)
    print("Self-test complete.")
    print("=" * 60)
    sys.exit(0)
