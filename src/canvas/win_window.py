"""
src.canvas.win_window
=====================
Native Windows transparent layered desktop HUD overlay window powered by PyQt5 and PyCairo.

Creates a borderless, click-through, per-pixel alpha blended window using
Qt.WA_TranslucentBackground and Qt.WA_TransparentForMouseEvents.
Draws the active 26 Cairo themes at 30 FPS and supports interactive drag-and-drop
repositioning when edit mode is unlocked.
"""

from __future__ import annotations

import ctypes
import logging
import time
from typing import Any, Optional

import cairo
import numpy as np
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint
from PyQt5.QtGui import QPainter, QImage

from src.core.diagnostics import get_rate_limiter
from src.core.fonts import register_bundled_fonts
from src.themes.base import TimeData
from src.canvas.drag_controller import DragController

log = logging.getLogger(__name__)

# Ensure bundled fonts are registered with Windows GDI
register_bundled_fonts()


class WinDesktopCanvasWindow(QWidget):
    """
    Hardware-composited, click-through transparent desktop HUD overlay window.
    """

    def __init__(
        self,
        cfg_manager: Any,
        theme: Any,
        audio_stream: Optional[Any] = None,
        wallpaper_engine: Optional[Any] = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg_manager
        self.theme = theme
        self.audio = audio_stream
        self.engine = wallpaper_engine

        self.drag = DragController(self.cfg)
        self._edit_mode = False

        # Configure borderless, transparent, non-activating desktop overlay
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnBottomHint |
            Qt.Tool |
            Qt.NoFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setWindowTitle("DesktopSuite Canvas Overlay")

        # Full screen coverage
        screen = QApplication.primaryScreen()
        geo = screen.geometry() if screen else None
        self.width = geo.width() if geo else 1920
        self.height = geo.height() if geo else 1080
        self.setGeometry(0, 0, self.width, self.height)

        # Cairo rendering surface & context (FreeType proxy on Windows 7)
        from src.core.win7_font_engine import SharedCairoQtSurface, get_font_registry
        self._font_registry = get_font_registry()
        self._shared_surface = SharedCairoQtSurface(self.width, self.height, self._font_registry)
        self._ctx = self._shared_surface.create_context()
        self._surface = self._shared_surface.cairo_surface

        self._time_data = TimeData.now(is_24h=False)
        self._last_sec = -1
        self._render_bars = np.zeros(27, dtype=np.float32)
        self._paint_count = 0
        self._last_canvas_hb = time.monotonic()
        self._rate_limiter = get_rate_limiter()
        self._stopping = False

        # 30 FPS animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.update)
        self._timer.start(33)

        log.info(
            "WinDesktopCanvasWindow initialised (%dx%d, hwnd=0x%X, theme=%r, positions=%s)",
            self.width, self.height, int(self.winId()), getattr(self.theme, "name", "?"), self.drag.components,
        )

    def start(self) -> None:
        log.info("WinDesktopCanvasWindow.start()")
        self.show()
        self.lower_to_desktop()

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        log.info("WinDesktopCanvasWindow.stop() after %d paints", self._paint_count)
        try:
            self._timer.stop()
        except Exception:
            pass
        self.hide()
        self.close()
        self._ctx = None
        self._surface = None
        if self._shared_surface is not None:
            self._shared_surface.dispose()
            self._shared_surface = None
        self.deleteLater()

    def set_theme(self, theme: Any) -> None:
        log.info("WinDesktopCanvasWindow.set_theme(%r)", getattr(theme, "name", "?"))
        self.theme = theme
        if self._shared_surface is not None:
            self._shared_surface.clear_transparent()
        self.update()

    def reload_config(self) -> None:
        self.drag._load_positions()
        self.update()

    def lower_to_desktop(self) -> None:
        """Position the canvas window at the desktop layer below application windows."""
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            hwnd = int(self.winId())
            # HWND_BOTTOM = 1, SWP_NOMOVE = 2, SWP_NOSIZE = 1, SWP_NOACTIVATE = 0x0010
            ok = user32.SetWindowPos(hwnd, 1, 0, 0, 0, 0, 0x0013)
            log.info("lower_to_desktop(hwnd=0x%X): ok=%s err=%d", hwnd, bool(ok), kernel32.GetLastError())
        except Exception as exc:
            log.warning("lower_to_desktop exception: %s", exc, exc_info=True)

    def toggle_edit_mode(self) -> bool:
        self._edit_mode = not self._edit_mode
        self.drag.set_edit_mode(self._edit_mode)

        # In edit mode, allow mouse events; in normal mode, pass-through
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self._edit_mode)

        if self._edit_mode:
            # Raise temporarily so user can easily interact with anchor boxes
            self.raise_()
            self.activateWindow()
        else:
            self.lower_to_desktop()

        log.info("WinDesktopCanvasWindow.toggle_edit_mode -> edit_mode=%s", self._edit_mode)
        self.update()
        return self._edit_mode

    def _log_paint_error(self, stage: str, exc: Exception) -> None:
        allowed, suppressed = self._rate_limiter.check(f"canvas:{stage}", interval=5.0)
        if allowed:
            suffix = f" [suppressed {suppressed}]" if suppressed else ""
            log.error("Canvas %s exception: %s%s", stage, exc, suffix, exc_info=True)

    def paintEvent(self, event) -> None:
        if self._stopping or self._shared_surface is None or self._ctx is None or self._surface is None:
            return
        self._paint_count += 1
        # 1. Update time snapshot once per second
        now_sec = int(time.time())
        if now_sec != self._last_sec:
            self._time_data = TimeData.now(is_24h=False)
            self._last_sec = now_sec

        # 2. Smooth audio visualizer bars
        max_audio_bar = 0.0
        if self.audio:
            with self.audio.lock:
                target_bars = self.audio.bars.copy()
            max_audio_bar = float(np.max(target_bars))
            self._render_bars += 0.46 * (target_bars - self._render_bars)
        else:
            self._render_bars *= 0.85

        # 3. Clear shared surface (wipe RAM buffer to 0x00000000)
        self._shared_surface.clear_transparent()
        if self._surface is not self._shared_surface.cairo_surface:
            self._surface = self._shared_surface.cairo_surface
            self._ctx = self._shared_surface.create_context()
        self._ctx.set_operator(cairo.OPERATOR_OVER)

        # 4. Extract configuration snapshot
        independent_scales = bool(self.cfg.get("canvas.independent_scales"))
        cfg = {
            "scale": float(self.cfg.get("canvas.scale") or 1.0),
            "independent_scales": independent_scales,
            "clock_scale": float(self.cfg.get("canvas.clock_scale") or 1.0),
            "date_scale": float(self.cfg.get("canvas.date_scale") or 1.0),
            "visualizer_scale": float(self.cfg.get("canvas.visualizer_scale") or 1.0),
            "clock_color": self.cfg.get("canvas.clock_color") or "#FFFFFF",
            "date_color": self.cfg.get("canvas.date_color") or "#D0D0D0",
            "visualizer_color": self.cfg.get("canvas.visualizer_color") or "#FFFFFF",
            "visualizer_intensity": float(self.cfg.get("canvas.visualizer_intensity") or 0.65),
            "background_opacity": float(self.cfg.get("canvas.background_opacity") or 0.0),
            "clock_enabled": bool(self.cfg.get("canvas.clock_enabled", True)),
            "date_enabled": bool(self.cfg.get("canvas.date_enabled", True)),
            "visualizer_enabled": bool(self.cfg.get("canvas.visualizer_enabled", True)),
        }

        # 5. Background layer
        if cfg["background_opacity"] > 0:
            try:
                self.theme.draw_background(self._ctx, self.width, self.height, cfg)
            except Exception as exc:
                self._log_paint_error("draw_background", exc)

        # 6. Clock component
        if cfg["clock_enabled"]:
            pos_clk = self.drag.components.get("clock", {"x": 468, "y": 260})
            self._ctx.save()
            self._ctx.translate(pos_clk["x"], pos_clk["y"])
            scale_mult = cfg["scale"] * (cfg["clock_scale"] if independent_scales else 1.0)
            clk_w = int(float(getattr(self.theme, "clock_base_width", 430.0)) * scale_mult)
            clk_h = int(float(getattr(self.theme, "clock_base_height", 100.0)) * scale_mult)
            try:
                self.theme.draw_clock(self._ctx, clk_w, clk_h, cfg, self._time_data)
            except Exception as exc:
                self._log_paint_error("draw_clock", exc)
            self._ctx.restore()
            self.drag.update_bbox("clock", float(clk_w), float(clk_h))

        # 7. Date component
        if cfg["date_enabled"]:
            pos_dt = self.drag.components.get("date", {"x": 468, "y": 370})
            self._ctx.save()
            self._ctx.translate(pos_dt["x"], pos_dt["y"])
            scale_mult = cfg["scale"] * (cfg["date_scale"] if independent_scales else 1.0)
            dt_w = int(float(getattr(self.theme, "date_base_width", 430.0)) * scale_mult)
            dt_h = int(float(getattr(self.theme, "date_base_height", 95.0)) * scale_mult)
            try:
                self.theme.draw_date(self._ctx, dt_w, dt_h, cfg, self._time_data)
            except Exception as exc:
                self._log_paint_error("draw_date", exc)
            self._ctx.restore()
            self.drag.update_bbox("date", float(dt_w), float(dt_h))

        # 8. Visualizer component
        if cfg["visualizer_enabled"]:
            pos_vis = self.drag.components.get("visualizer", {"x": 468, "y": 410})
            self._ctx.save()
            self._ctx.translate(pos_vis["x"], pos_vis["y"])
            scale_mult = cfg["scale"] * (cfg["visualizer_scale"] if independent_scales else 1.0)
            base_vis_w = float(getattr(self.theme, "vis_base_width", getattr(self.theme, "visualizer_base_width", 430.0)))
            base_vis_h = getattr(self.theme, "vis_base_height", getattr(self.theme, "visualizer_base_height", 60.0))
            vis_w = int(base_vis_w * scale_mult)
            vis_h = int(float(base_vis_h) * scale_mult)
            try:
                self.theme.draw_visualizer(self._ctx, vis_w, vis_h, cfg, self._render_bars)
            except Exception as exc:
                self._log_paint_error("draw_visualizer", exc)
            self._ctx.restore()
            self.drag.update_bbox("visualizer", float(vis_w), float(vis_h))

        # 9. Drag overlay in edit mode
        if self._edit_mode:
            try:
                self.drag.draw_overlay(self._ctx)
            except Exception as exc:
                self._log_paint_error("draw_overlay", exc)

        self._surface.flush()

        # 10. Blit Cairo memory buffer into QPainter (zero-copy shared surface)
        try:
            painter = QPainter(self)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            blit_img = self._shared_surface.get_blit_qimage()
            painter.drawImage(0, 0, blit_img)
            painter.end()
            del blit_img
        except Exception as exc:
            self._log_paint_error("paintEvent_drawImage", exc)

        now = time.monotonic()
        if now - self._last_canvas_hb >= 5.0:
            self._last_canvas_hb = now
            log.info(
                "Canvas heartbeat (5s): paints=%d, theme=%r, visible=%s, vis_en=%s, "
                "max_audio_bar=%.4f, max_render_bar=%.4f",
                self._paint_count, getattr(self.theme, "name", "?"), self.isVisible(),
                cfg["visualizer_enabled"], max_audio_bar, float(np.max(self._render_bars)),
            )

    def mousePressEvent(self, event) -> None:
        if self._edit_mode and event.button() == Qt.LeftButton:
            x = float(event.x())
            y = float(event.y())
            self.drag.on_press(None, type("Event", (), {"x": x, "y": y, "button": 1})())
            self.update()

    def mouseMoveEvent(self, event) -> None:
        if self._edit_mode:
            x = float(event.x())
            y = float(event.y())
            self.drag.on_motion(None, type("Event", (), {"x": x, "y": y})())
            self.update()

    def mouseReleaseEvent(self, event) -> None:
        if self._edit_mode:
            self.drag.on_release(None, None)
            self.update()
