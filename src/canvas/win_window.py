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
from ctypes import wintypes
import logging
import math
import sys
import time
from typing import Any, Optional

import cairo
import numpy as np
from PyQt5.QtWidgets import QWidget, QApplication
from PyQt5.QtCore import Qt, QTimer, QPoint, QRect
from PyQt5.QtGui import QPainter, QImage

from src.core.diagnostics import get_rate_limiter
from src.themes.base import TimeData
from src.canvas.drag_controller import DragController

log = logging.getLogger(__name__)


_SECOND_PRECISION_THEMES = frozenset({"Circular Orbit", "Matrix CLI"})

_GWL_EXSTYLE = -20
_GW_HWNDNEXT = 2
_GW_HWNDPREV = 3

_WS_EX_TRANSPARENT = 0x00000020
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_LAYERED = 0x00080000
_WS_EX_NOACTIVATE = 0x08000000

_HWND_TOP = 0
_HWND_BOTTOM = 1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_NOZORDER = 0x0004
_SWP_NOACTIVATE = 0x0010
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_SWP_HIDEWINDOW = 0x0080

_SW_SHOWNA = 8
_WM_SIZE = 0x0005
_SIZE_MINIMIZED = 1
_WM_MOUSEACTIVATE = 0x0021
_MA_NOACTIVATE = 3
_WM_WINDOWPOSCHANGING = 0x0046
_WM_WINDOWPOSCHANGED = 0x0047
_WM_NCHITTEST = 0x0084
_HTTRANSPARENT = -1
_WM_SYSCOMMAND = 0x0112
_SC_MINIMIZE = 0xF020

_DWMWA_FLIP3D_POLICY = 8
_DWMFLIP3D_EXCLUDEBELOW = 1
_DWMWA_EXCLUDED_FROM_PEEK = 12

_WINEVENT_OUTOFCONTEXT = 0x0000
_EVENT_SYSTEM_FOREGROUND = 0x0003
_EVENT_SYSTEM_MINIMIZESTART = 0x0016
_EVENT_SYSTEM_MINIMIZEEND = 0x0017

if sys.platform == "win32":
    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    try:
        _dwmapi = ctypes.windll.dwmapi
    except Exception:
        _dwmapi = None

    class _WINDOWPOS(ctypes.Structure):
        _fields_ = [
            ("hwnd", wintypes.HWND),
            ("hwndInsertAfter", wintypes.HWND),
            ("x", ctypes.c_int),
            ("y", ctypes.c_int),
            ("cx", ctypes.c_int),
            ("cy", ctypes.c_int),
            ("flags", wintypes.UINT),
        ]

    _WINEVENTPROC = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )

    _user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    _user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
    _user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowW.restype = wintypes.HWND
    _user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    _user32.FindWindowExW.restype = wintypes.HWND
    _user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    _user32.GetWindow.restype = wintypes.HWND
    _user32.IsWindow.argtypes = [wintypes.HWND]
    _user32.IsWindow.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsIconic.argtypes = [wintypes.HWND]
    _user32.IsIconic.restype = wintypes.BOOL
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT
    ]
    _user32.SetWindowPos.restype = wintypes.BOOL
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.SetWinEventHook.argtypes = [
        wintypes.DWORD, wintypes.DWORD, wintypes.HMODULE, _WINEVENTPROC,
        wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    ]
    _user32.SetWinEventHook.restype = wintypes.HANDLE
    _user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
    _user32.UnhookWinEvent.restype = wintypes.BOOL

    if _dwmapi is not None:
        _dwmapi.DwmSetWindowAttribute.argtypes = [
            wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD
        ]
        _dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long
else:
    _user32 = None
    _kernel32 = None
    _dwmapi = None
    _WINDOWPOS = None
    _WINEVENTPROC = None


def _find_desktop_anchor_hwnd(user32_lib: Any = None) -> int:
    """Return WorkerW hosting SHELLDLL_DefView on Windows, falling back to Progman."""
    u32 = user32_lib or _user32
    if u32 is None:
        return 0
    cur = u32.FindWindowExW(0, 0, "WorkerW", None)
    while cur:
        if u32.FindWindowExW(cur, 0, "SHELLDLL_DefView", None):
            return int(cur)
        cur = u32.FindWindowExW(0, cur, "WorkerW", None)
    progman = u32.FindWindowW("Progman", None)
    return int(progman or 0)


def _is_window_above(hwnd_a: int, hwnd_b: int, user32_lib: Any = None, max_steps: int = 512) -> bool:
    """Return True if top-level hwnd_a sits strictly above hwnd_b in the Win32 Z-order."""
    u32 = user32_lib or _user32
    if u32 is None or not hwnd_a or not hwnd_b or hwnd_a == hwnd_b:
        return False
    cur = u32.GetWindow(hwnd_a, _GW_HWNDNEXT)
    steps = 0
    while cur and steps < max_steps:
        if int(cur) == int(hwnd_b):
            return True
        cur = u32.GetWindow(cur, _GW_HWNDNEXT)
        steps += 1
    return False


def _compute_desktop_insert_after(canvas_hwnd: int, anchor_hwnd: int, user32_lib: Any = None) -> int:
    """
    Compute the HWND to pass to SetWindowPos(canvas_hwnd, insert_after, ...)
    so canvas_hwnd sits immediately ABOVE anchor_hwnd (WorkerW #1 / Progman)
    while remaining below open application windows.
    """
    u32 = user32_lib or _user32
    if u32 is None or not anchor_hwnd:
        return _HWND_BOTTOM
    prev = u32.GetWindow(anchor_hwnd, _GW_HWNDPREV)
    steps = 0
    while prev and int(prev) == int(canvas_hwnd) and steps < 32:
        prev = u32.GetWindow(prev, _GW_HWNDPREV)
        steps += 1
    return int(prev) if prev else _HWND_TOP


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

        # Dual Cairo-Qt zero-copy surfaces:
        #   _static_surface caches clock + date + background (rebuilt ~1x/min or 1x/sec)
        #   _shared_surface composites only the dirty region + live audio bars at 30 FPS
        from src.core.win7_font_engine import SharedCairoQtSurface, get_font_registry
        self._font_registry = get_font_registry()
        self._shared_surface = SharedCairoQtSurface(self.width, self.height, self._font_registry)
        self._static_surface = SharedCairoQtSurface(self.width, self.height, self._font_registry)
        self._ctx = self._shared_surface.create_context()
        self._surface = self._shared_surface.cairo_surface
        self._static_ctx = self._static_surface.create_context()
        self._static_cairo = self._static_surface.cairo_surface

        self._time_data = TimeData.now(is_24h=False)
        self._last_sec = -1
        self._render_bars = np.zeros(27, dtype=np.float32)
        self._static_key: Optional[tuple] = None
        self._vis_dirty_rect = QRect()
        self._prev_vis_rect = QRect()
        self._had_vis_bars = False
        self._force_full_repaint = True
        self._paint_count = 0
        self._tick_count = 0
        self._static_rebuilds = 0
        self._last_max_audio_bar = 0.0
        self._last_canvas_hb = time.monotonic()
        self._rate_limiter = get_rate_limiter()
        self._stopping = False
        self._z_order_guard = False
        self._win_event_hooks: list[int] = []
        self._win_event_cb = None
        self._z_check_counter = 0

        # 25 FPS smart animation tick (smooth bars, skips repaints when idle & silent)
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)
        self._timer.start(40)

        log.info(
            "WinDesktopCanvasWindow initialised (%dx%d, hwnd=0x%X, theme=%r, positions=%s)",
            self.width, self.height, int(self.winId()), getattr(self.theme, "name", "?"), self.drag.components,
        )

    def start(self) -> None:
        log.info("WinDesktopCanvasWindow.start()")
        self.show()
        self._configure_native_window_attrs()
        self._install_win_event_hooks()
        self.lower_to_desktop(force=True)

    def stop(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        log.info(
            "WinDesktopCanvasWindow.stop() after %d paints (%d ticks, %d static rebuilds)",
            self._paint_count, self._tick_count, self._static_rebuilds,
        )
        self._uninstall_win_event_hooks()
        try:
            self._timer.stop()
        except Exception:
            pass
        self.hide()
        self.close()
        self._ctx = None
        self._surface = None
        self._static_ctx = None
        self._static_cairo = None
        if self._shared_surface is not None:
            self._shared_surface.dispose()
            self._shared_surface = None
        if self._static_surface is not None:
            self._static_surface.dispose()
            self._static_surface = None
        self.deleteLater()

    def set_theme(self, theme: Any) -> None:
        log.info("WinDesktopCanvasWindow.set_theme(%r)", getattr(theme, "name", "?"))
        self.theme = theme
        self._static_key = None
        self._force_full_repaint = True
        if self._static_surface is not None:
            self._static_surface.clear_transparent()
        if self._shared_surface is not None:
            self._shared_surface.clear_transparent()
        self.update()

    def reload_config(self) -> None:
        self.drag._load_positions()
        self._static_key = None
        self._force_full_repaint = True
        self.update()

    def _configure_native_window_attrs(self) -> None:
        """Apply Windows 7 DWM Aero Peek exclusion and non-activating click-through ex-styles."""
        if sys.platform != "win32" or _user32 is None or self._stopping:
            return
        try:
            hwnd = int(self.winId())
            if not hwnd or not _user32.IsWindow(hwnd):
                return

            if _dwmapi is not None:
                excl = ctypes.c_int(1)
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, _DWMWA_EXCLUDED_FROM_PEEK, ctypes.byref(excl), ctypes.sizeof(excl)
                )
                flip_policy = ctypes.c_int(_DWMFLIP3D_EXCLUDEBELOW)
                _dwmapi.DwmSetWindowAttribute(
                    hwnd, _DWMWA_FLIP3D_POLICY, ctypes.byref(flip_policy), ctypes.sizeof(flip_policy)
                )

            exstyle = _user32.GetWindowLongPtrW(hwnd, _GWL_EXSTYLE)
            if self._edit_mode:
                desired = (exstyle & ~(_WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT)) | _WS_EX_TOOLWINDOW | _WS_EX_LAYERED
            else:
                desired = exstyle | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE | _WS_EX_TRANSPARENT | _WS_EX_LAYERED
            if desired != exstyle:
                _user32.SetWindowLongPtrW(hwnd, _GWL_EXSTYLE, desired)
                _user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOZORDER | _SWP_NOACTIVATE | _SWP_FRAMECHANGED,
                )
        except Exception as exc:
            log.debug("_configure_native_window_attrs error: %s", exc)

    def _install_win_event_hooks(self) -> None:
        """Hook Windows foreground & minimize/Show-Desktop transitions with zero polling cost."""
        if sys.platform != "win32" or _user32 is None or _WINEVENTPROC is None:
            return
        if self._win_event_hooks:
            return

        @_WINEVENTPROC
        def _on_win_event(_hook, event, hwnd, _id_obj, _id_child, _thread, _time_ms):
            try:
                if self._stopping or self._edit_mode:
                    return
                if event == _EVENT_SYSTEM_MINIMIZEEND:
                    # Windows finished restoring (e.g. second Win+D / Show Desktop toggle):
                    # tuck canvas right back above WorkerW #1 / Progman below restored apps.
                    QTimer.singleShot(25, lambda: self.lower_to_desktop(force=True))
                elif event in (_EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_MINIMIZESTART):
                    cls_name = ""
                    if hwnd and _user32.IsWindow(hwnd):
                        buf = ctypes.create_unicode_buffer(64)
                        _user32.GetClassNameW(hwnd, buf, 64)
                        cls_name = buf.value
                    # Recover immediately if desktop/Show-Desktop raised WorkerW or minimized canvas
                    if event == _EVENT_SYSTEM_MINIMIZESTART or cls_name in ("WorkerW", "Progman", "Shell_TrayWnd"):
                        QTimer.singleShot(25, lambda: self._ensure_desktop_layer(force=False))
            except Exception:
                pass

        self._win_event_cb = _on_win_event
        for ev_min, ev_max in (
            (_EVENT_SYSTEM_FOREGROUND, _EVENT_SYSTEM_FOREGROUND),
            (_EVENT_SYSTEM_MINIMIZESTART, _EVENT_SYSTEM_MINIMIZEEND),
        ):
            hook = _user32.SetWinEventHook(
                ev_min, ev_max, 0, self._win_event_cb, 0, 0, _WINEVENT_OUTOFCONTEXT
            )
            if hook:
                self._win_event_hooks.append(int(hook))
        log.debug("Installed %d WinEvent hooks for Show Desktop resilience", len(self._win_event_hooks))

    def _uninstall_win_event_hooks(self) -> None:
        if sys.platform == "win32" and _user32 is not None:
            for hook in self._win_event_hooks:
                try:
                    _user32.UnhookWinEvent(hook)
                except Exception:
                    pass
        self._win_event_hooks.clear()
        self._win_event_cb = None

    def _ensure_desktop_layer(self, force: bool = False) -> None:
        """
        Keep the overlay visible and positioned immediately above WorkerW #1 (SHELLDLL_DefView) /
        Progman so Windows 7 Aero Peek & Show Desktop never bury or minimize the clock while leaving
        open application windows in front of the overlay.
        """
        if sys.platform != "win32" or _user32 is None or self._stopping or self._z_order_guard:
            return
        if self._edit_mode and not force:
            return
        self._z_order_guard = True
        try:
            hwnd = int(self.winId())
            if not hwnd or not _user32.IsWindow(hwnd):
                return

            restored = False
            if _user32.IsIconic(hwnd) or not _user32.IsWindowVisible(hwnd):
                _user32.ShowWindow(hwnd, _SW_SHOWNA)
                restored = True

            anchor = _find_desktop_anchor_hwnd()
            if not force and not restored and (not anchor or _is_window_above(hwnd, anchor)):
                return

            insert_after = _compute_desktop_insert_after(hwnd, anchor) if anchor else _HWND_BOTTOM
            if (
                not force
                and not restored
                and _user32.GetWindow(anchor, _GW_HWNDPREV) == hwnd
            ):
                return

            swp_flags = _SWP_NOMOVE | _SWP_NOSIZE | _SWP_NOACTIVATE
            if restored:
                swp_flags |= _SWP_SHOWWINDOW
            ok = _user32.SetWindowPos(
                hwnd, insert_after, 0, 0, self.width, self.height, swp_flags,
            )
            err = _kernel32.GetLastError() if _kernel32 is not None else 0
            if force or restored:
                log.info(
                    "lower_to_desktop(hwnd=0x%X, anchor=0x%X, insert_after=0x%X, restored=%s): ok=%s err=%d",
                    hwnd, anchor, insert_after, restored, bool(ok), err,
                )
        except Exception as exc:
            log.warning("lower_to_desktop exception: %s", exc, exc_info=True)
        finally:
            self._z_order_guard = False

    def lower_to_desktop(self, force: bool = True) -> None:
        """Position the canvas window at the desktop layer immediately above WorkerW/Progman."""
        self._ensure_desktop_layer(force=force)

    def toggle_edit_mode(self) -> bool:
        self._edit_mode = not self._edit_mode
        self.drag.set_edit_mode(self._edit_mode)

        # In edit mode, allow mouse events; in normal mode, pass-through
        self.setAttribute(Qt.WA_TransparentForMouseEvents, not self._edit_mode)
        self._configure_native_window_attrs()

        if self._edit_mode:
            # Raise temporarily so user can easily interact with anchor boxes
            self.raise_()
            self.activateWindow()
        else:
            self.lower_to_desktop(force=True)

        self._static_key = None
        self._force_full_repaint = True
        log.info("WinDesktopCanvasWindow.toggle_edit_mode -> edit_mode=%s", self._edit_mode)
        self.update()
        return self._edit_mode

    def _log_paint_error(self, stage: str, exc: Exception) -> None:
        allowed, suppressed = self._rate_limiter.check(f"canvas:{stage}", interval=5.0)
        if allowed:
            suffix = f" [suppressed {suppressed}]" if suppressed else ""
            log.error("Canvas %s exception: %s%s", stage, exc, suffix, exc_info=True)

    def _snapshot_cfg(self) -> dict[str, Any]:
        independent_scales = bool(self.cfg.get("canvas.independent_scales"))
        return {
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

    def _compute_vis_geom(self, cfg: dict[str, Any]) -> tuple[dict[str, float], int, int, QRect]:
        pos_vis = self.drag.components.get("visualizer", {"x": 468.0, "y": 410.0})
        scale_mult = cfg["scale"] * (cfg["visualizer_scale"] if cfg["independent_scales"] else 1.0)
        base_vis_w = float(getattr(self.theme, "vis_base_width", getattr(self.theme, "visualizer_base_width", 430.0)))
        base_vis_h = float(getattr(self.theme, "vis_base_height", getattr(self.theme, "visualizer_base_height", 60.0)))
        vis_w = int(base_vis_w * scale_mult)
        vis_h = int(base_vis_h * scale_mult)
        theme_name = getattr(self.theme, "name", "")
        base_pad = 48.0 if theme_name == "Circular Orbit" else 12.0
        pad = int(math.ceil(base_pad * max(1.0, scale_mult)))
        dirty = QRect(
            int(math.floor(pos_vis["x"] - pad)),
            int(math.floor(pos_vis["y"] - pad)),
            int(math.ceil(vis_w + 2 * pad)),
            int(math.ceil(vis_h + 2 * pad)),
        ).intersected(self.rect())
        return pos_vis, vis_w, vis_h, dirty

    def _build_static_key(self, cfg: dict[str, Any]) -> tuple:
        theme_name = getattr(self.theme, "name", type(self.theme).__name__)
        uses_seconds = theme_name in _SECOND_PRECISION_THEMES or bool(getattr(self.theme, "uses_seconds", False))
        pos_clk = self.drag.components.get("clock", {"x": 468.0, "y": 260.0})
        pos_dt = self.drag.components.get("date", {"x": 468.0, "y": 370.0})
        pos_vis = self.drag.components.get("visualizer", {"x": 468.0, "y": 410.0})
        return (
            theme_name,
            self._time_data.time_str,
            self._time_data.date_str,
            self._time_data.day_str,
            self._time_data.second if uses_seconds else 0,
            cfg["scale"],
            cfg["independent_scales"],
            cfg["clock_scale"],
            cfg["date_scale"],
            cfg["clock_color"],
            cfg["date_color"],
            cfg["background_opacity"],
            cfg["clock_enabled"],
            cfg["date_enabled"],
            self._edit_mode,
            int(pos_clk["x"]),
            int(pos_clk["y"]),
            int(pos_dt["x"]),
            int(pos_dt["y"]),
            int(pos_vis["x"]) if self._edit_mode else 0,
            int(pos_vis["y"]) if self._edit_mode else 0,
        )

    def _rebuild_static_layer(self, cfg: dict[str, Any]) -> None:
        if self._static_surface is None:
            return
        self._static_surface.clear_transparent()
        if self._static_cairo is not self._static_surface.cairo_surface:
            self._static_cairo = self._static_surface.cairo_surface
            self._static_ctx = self._static_surface.create_context()

        ctx = self._static_ctx
        ctx.set_operator(cairo.OPERATOR_OVER)

        if cfg["background_opacity"] > 0:
            try:
                self.theme.draw_background(ctx, self.width, self.height, cfg)
            except Exception as exc:
                self._log_paint_error("draw_background", exc)

        independent_scales = cfg["independent_scales"]
        if cfg["clock_enabled"]:
            pos_clk = self.drag.components.get("clock", {"x": 468.0, "y": 260.0})
            ctx.save()
            ctx.translate(pos_clk["x"], pos_clk["y"])
            scale_mult = cfg["scale"] * (cfg["clock_scale"] if independent_scales else 1.0)
            clk_w = int(float(getattr(self.theme, "clock_base_width", 430.0)) * scale_mult)
            clk_h = int(float(getattr(self.theme, "clock_base_height", 100.0)) * scale_mult)
            try:
                self.theme.draw_clock(ctx, clk_w, clk_h, cfg, self._time_data)
            except Exception as exc:
                self._log_paint_error("draw_clock", exc)
            ctx.restore()
            self.drag.update_bbox("clock", float(clk_w), float(clk_h))

        if cfg["date_enabled"]:
            pos_dt = self.drag.components.get("date", {"x": 468.0, "y": 370.0})
            ctx.save()
            ctx.translate(pos_dt["x"], pos_dt["y"])
            scale_mult = cfg["scale"] * (cfg["date_scale"] if independent_scales else 1.0)
            dt_w = int(float(getattr(self.theme, "date_base_width", 430.0)) * scale_mult)
            dt_h = int(float(getattr(self.theme, "date_base_height", 95.0)) * scale_mult)
            try:
                self.theme.draw_date(ctx, dt_w, dt_h, cfg, self._time_data)
            except Exception as exc:
                self._log_paint_error("draw_date", exc)
            ctx.restore()
            self.drag.update_bbox("date", float(dt_w), float(dt_h))

        _pv, vis_w, vis_h, vis_dirty = self._compute_vis_geom(cfg)
        self.drag.update_bbox("visualizer", float(vis_w), float(vis_h))
        self._vis_dirty_rect = vis_dirty

        self._static_cairo.flush()
        self._static_key = self._build_static_key(cfg)
        self._static_rebuilds += 1

    def _on_tick(self) -> None:
        if self._stopping:
            return
        self._tick_count += 1
        self._z_check_counter += 1
        if self._z_check_counter >= 10:
            self._z_check_counter = 0
            if not self._edit_mode:
                self._ensure_desktop_layer(force=False)

        now_sec = int(time.time())
        if now_sec != self._last_sec:
            self._time_data = TimeData.now(is_24h=False)
            self._last_sec = now_sec

        cfg = self._snapshot_cfg()
        static_dirty = (self._build_static_key(cfg) != self._static_key)

        max_audio_bar = 0.0
        if cfg["visualizer_enabled"]:
            if self.audio:
                with self.audio.lock:
                    target_bars = self.audio.bars.copy()
                max_audio_bar = float(np.max(target_bars))
                self._render_bars += 0.46 * (target_bars - self._render_bars)
            else:
                self._render_bars *= 0.85
            self._render_bars[self._render_bars < 0.001] = 0.0
        else:
            self._render_bars.fill(0.0)

        self._last_max_audio_bar = max_audio_bar
        max_render_bar = float(np.max(self._render_bars))
        bars_active = cfg["visualizer_enabled"] and (max_audio_bar > 0.001 or max_render_bar > 0.001)

        if not static_dirty and not bars_active and not self._had_vis_bars and not self._force_full_repaint:
            return

        if static_dirty or self._force_full_repaint:
            self._rebuild_static_layer(cfg)
            self._force_full_repaint = False
            self._had_vis_bars = bars_active
            self._prev_vis_rect = self._vis_dirty_rect if bars_active else QRect()
            self.update()
        else:
            self._had_vis_bars = bars_active
            _pv, _vw, _vh, cur_vis = self._compute_vis_geom(cfg)
            self._vis_dirty_rect = cur_vis
            dirty = cur_vis.united(self._prev_vis_rect) if not self._prev_vis_rect.isEmpty() else cur_vis
            self._prev_vis_rect = cur_vis if bars_active else QRect()
            if not dirty.isEmpty():
                self.update(dirty)

    def paintEvent(self, event) -> None:
        if self._stopping or self._shared_surface is None or self._static_surface is None:
            return
        self._paint_count += 1

        cfg = self._snapshot_cfg()
        if self._static_key != self._build_static_key(cfg):
            self._rebuild_static_layer(cfg)

        dirty = event.rect().intersected(self.rect())
        if dirty.isEmpty():
            dirty = self.rect()

        # Copy static clock/date/background slice directly into shared buffer (no 17x FreeType redraw!)
        self._shared_surface.blit_from_surface_rect(
            self._static_surface, dirty.x(), dirty.y(), dirty.width(), dirty.height()
        )
        if self._surface is not self._shared_surface.cairo_surface:
            self._surface = self._shared_surface.cairo_surface
            self._ctx = self._shared_surface.create_context()

        # Draw live visualizer bars only when intersecting dirty region & active
        pos_vis, vis_w, vis_h, vis_dirty = self._compute_vis_geom(cfg)
        self._vis_dirty_rect = vis_dirty
        self.drag.update_bbox("visualizer", float(vis_w), float(vis_h))

        max_render_bar = float(np.max(self._render_bars))
        if cfg["visualizer_enabled"] and max_render_bar > 0.001 and dirty.intersects(vis_dirty):
            self._ctx.save()
            self._ctx.rectangle(dirty.x(), dirty.y(), dirty.width(), dirty.height())
            self._ctx.clip()
            self._ctx.translate(pos_vis["x"], pos_vis["y"])
            try:
                self.theme.draw_visualizer(self._ctx, vis_w, vis_h, cfg, self._render_bars)
            except Exception as exc:
                self._log_paint_error("draw_visualizer", exc)
            self._ctx.restore()

        # Drag overlay only when in edit mode
        if self._edit_mode:
            self._ctx.save()
            self._ctx.rectangle(dirty.x(), dirty.y(), dirty.width(), dirty.height())
            self._ctx.clip()
            try:
                self.drag.draw_overlay(self._ctx)
            except Exception as exc:
                self._log_paint_error("draw_overlay", exc)
            self._ctx.restore()

        # Blit only the dirty rectangle from shared buffer onto layered Qt backing store
        try:
            painter = QPainter(self)
            painter.setCompositionMode(QPainter.CompositionMode_Source)
            blit_img = self._shared_surface.get_blit_qimage()
            painter.drawImage(dirty, blit_img, dirty)
            painter.end()
            del blit_img
        except Exception as exc:
            self._log_paint_error("paintEvent_drawImage", exc)

        now = time.monotonic()
        if now - self._last_canvas_hb >= 5.0:
            self._last_canvas_hb = now
            log.info(
                "Canvas heartbeat (5s): paints=%d, ticks=%d, static_rebuilds=%d, theme=%r, visible=%s, vis_en=%s, "
                "last_dirty=(%d,%d %dx%d), max_audio_bar=%.4f, max_render_bar=%.4f",
                self._paint_count, self._tick_count, self._static_rebuilds,
                getattr(self.theme, "name", "?"), self.isVisible(),
                cfg["visualizer_enabled"], dirty.x(), dirty.y(), dirty.width(), dirty.height(),
                self._last_max_audio_bar, max_render_bar,
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

    def nativeEvent(self, eventType, message):
        """
        Defend against Show Desktop minimizing/hiding/lowering the desktop HUD overlay
        and keep mouse/hit-test/activation completely transparent outside edit mode.
        """
        if (
            sys.platform == "win32"
            and _WINDOWPOS is not None
            and not self._stopping
            and eventType == b"windows_generic_MSG"
        ):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if not self._edit_mode:
                    if msg.message == _WM_NCHITTEST:
                        return True, _HTTRANSPARENT
                    if msg.message == _WM_MOUSEACTIVATE:
                        return True, _MA_NOACTIVATE
                if msg.message == _WM_SYSCOMMAND and (msg.wParam & 0xFFF0) == _SC_MINIMIZE:
                    return True, 0
                if msg.message == _WM_WINDOWPOSCHANGING and msg.lParam:
                    wp = _WINDOWPOS.from_address(int(msg.lParam))
                    wp.flags &= ~_SWP_HIDEWINDOW
                    if (wp.flags & _SWP_NOMOVE) == 0 and (wp.x <= -10000 or wp.y <= -10000):
                        wp.x = 0
                        wp.y = 0
                        wp.cx = self.width
                        wp.cy = self.height
                elif msg.message == _WM_SIZE and msg.wParam == _SIZE_MINIMIZED:
                    QTimer.singleShot(0, lambda: self._ensure_desktop_layer(force=True))
                elif (
                    msg.message == _WM_WINDOWPOSCHANGED
                    and not self._edit_mode
                    and not self._z_order_guard
                ):
                    QTimer.singleShot(0, lambda: self._ensure_desktop_layer(force=False))
            except Exception:
                pass
        return super().nativeEvent(eventType, message)
