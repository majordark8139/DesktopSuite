"""
src.canvas.win_window
=====================
Native Win32 transparent layered desktop HUD overlay window.

Creates a borderless, click-through, per-pixel alpha blended window using
standard Win32 Layered Windows (WS_EX_LAYERED | WS_EX_TRANSPARENT).
Draws the active theme (clock, date, visualizer) using PyCairo and presents
frames at 30 FPS via UpdateLayeredWindow.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import math
import sys
import threading
import time
from typing import Any, Optional

import cairo
import numpy as np

from src.core.fonts import register_bundled_fonts
from src.themes.base import TimeData
from src.canvas.drag_controller import DragController

log = logging.getLogger(__name__)

# Ensure bundled fonts are available to Windows GDI / Cairo
register_bundled_fonts()

# Win32 Constants
WS_POPUP = 0x80000000
WS_VISIBLE = 0x10000000
WS_EX_LAYERED = 0x00080000
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000

GWL_EXSTYLE = -20
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0

SM_CXSCREEN = 0
SM_CYSCREEN = 1

WM_DESTROY = 0x0002
WM_TIMER = 0x0113
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOUSEMOVE = 0x0200


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class WinDesktopCanvasWindow:
    """
    Win32 Layered Window overlay that renders PyCairo themes at 30 FPS.
    """

    def __init__(
        self,
        cfg_manager: Any,
        theme: Any,
        audio_stream: Optional[Any] = None,
        wallpaper_engine: Optional[Any] = None,
    ) -> None:
        self.cfg = cfg_manager
        self.theme = theme
        self.audio = audio_stream
        self.engine = wallpaper_engine

        self.drag = DragController(self.cfg)
        self._edit_mode = False

        self._user32 = ctypes.windll.user32
        self._gdi32 = ctypes.windll.gdi32
        self._kernel32 = ctypes.windll.kernel32

        self.width = self._user32.GetSystemMetrics(SM_CXSCREEN)
        self.height = self._user32.GetSystemMetrics(SM_CYSCREEN)

        self._hwnd: Optional[int] = None
        self._hdc_mem: Optional[int] = None
        self._hbitmap: Optional[int] = None
        self._bitmap_bits = ctypes.c_void_p()

        self._surface: Optional[cairo.ImageSurface] = None
        self._ctx: Optional[cairo.Context] = None

        self._time_data = TimeData.now(is_24h=False)
        self._last_sec = -1

        # Smooth visualizer bars for rendering
        self._render_bars = np.zeros(27, dtype=np.float32)

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_window, daemon=True, name="win-canvas")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._hwnd:
            self._user32.PostMessageW(self._hwnd, WM_DESTROY, 0, 0)
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def set_theme(self, theme: Any) -> None:
        self.theme = theme

    def reload_config(self) -> None:
        self.drag._load_positions()

    def toggle_edit_mode(self) -> bool:
        self._edit_mode = not self._edit_mode
        self.drag.set_edit_mode(self._edit_mode)
        if self._hwnd:
            ex_style = self._user32.GetWindowLongW(self._hwnd, GWL_EXSTYLE)
            if self._edit_mode:
                # Remove transparent flag to receive mouse input
                ex_style &= ~WS_EX_TRANSPARENT
            else:
                # Re-enable click-through
                ex_style |= WS_EX_TRANSPARENT
            self._user32.SetWindowLongW(self._hwnd, GWL_EXSTYLE, ex_style)
        return self._edit_mode

    def _setup_surface(self) -> None:
        hdc_screen = self._user32.GetDC(0)
        self._hdc_mem = self._gdi32.CreateCompatibleDC(hdc_screen)

        bmi = BITMAPINFOHEADER()
        bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.biWidth = self.width
        bmi.biHeight = -self.height  # Top-down DIB matches Cairo
        bmi.biPlanes = 1
        bmi.biBitCount = 32
        bmi.biCompression = BI_RGB

        self._hbitmap = self._gdi32.CreateDIBSection(
            self._hdc_mem,
            ctypes.byref(bmi),
            0,
            ctypes.byref(self._bitmap_bits),
            None,
            0,
        )
        self._gdi32.SelectObject(self._hdc_mem, self._hbitmap)
        self._user32.ReleaseDC(0, hdc_screen)

        self._surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, self.width, self.height)
        self._ctx = cairo.Context(self._surface)

    def _render_frame(self) -> None:
        if not self._ctx or not self._surface or not self._hwnd:
            return

        # Snapshot current time once per second
        now_sec = int(time.time())
        if now_sec != self._last_sec:
            self._time_data = TimeData.now(is_24h=False)
            self._last_sec = now_sec

        # Smooth visualizer data towards target audio bars
        if self.audio:
            with self.audio.lock:
                target_bars = self.audio.bars
            self._render_bars += 0.46 * (target_bars - self._render_bars)
        else:
            self._render_bars *= 0.85

        # Clear Cairo surface
        self._ctx.set_operator(cairo.OPERATOR_CLEAR)
        self._ctx.paint()
        self._ctx.set_operator(cairo.OPERATOR_OVER)

        # Build config view dict expected by theme draw methods
        cfg = {
            "scale": float(self.cfg.get("canvas.scale") or 1.0),
            "independent_scales": bool(self.cfg.get("canvas.independent_scales")),
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

        # 1. Background layer
        if cfg["background_opacity"] > 0:
            self.theme.draw_background(self._ctx, self.width, self.height, cfg)

        # 2. Clock component
        if cfg["clock_enabled"]:
            pos_clk = self.drag.components.get("clock", {"x": 468, "y": 260})
            self._ctx.save()
            self._ctx.translate(pos_clk["x"], pos_clk["y"])
            clk_w = int(float(getattr(self.theme, "clock_base_width", 430.0)) * cfg["scale"] * cfg["clock_scale"])
            clk_h = int(float(getattr(self.theme, "clock_base_height", 100.0)) * cfg["scale"] * cfg["clock_scale"])
            self.theme.draw_clock(self._ctx, clk_w, clk_h, cfg, self._time_data)
            self._ctx.restore()

        # 3. Date component
        if cfg["date_enabled"]:
            pos_dt = self.drag.components.get("date", {"x": 468, "y": 370})
            self._ctx.save()
            self._ctx.translate(pos_dt["x"], pos_dt["y"])
            dt_w = int(float(getattr(self.theme, "date_base_width", 430.0)) * cfg["scale"] * cfg["date_scale"])
            dt_h = int(float(getattr(self.theme, "date_base_height", 95.0)) * cfg["scale"] * cfg["date_scale"])
            self.theme.draw_date(self._ctx, dt_w, dt_h, cfg, self._time_data)
            self._ctx.restore()

        # 4. Visualizer component
        if cfg["visualizer_enabled"]:
            pos_vis = self.drag.components.get("visualizer", {"x": 468, "y": 410})
            self._ctx.save()
            self._ctx.translate(pos_vis["x"], pos_vis["y"])
            vis_w = int(float(getattr(self.theme, "visualizer_base_width", 430.0)) * cfg["scale"] * cfg["visualizer_scale"])
            vis_h = int(float(getattr(self.theme, "visualizer_base_height", 60.0)) * cfg["scale"] * cfg["visualizer_scale"])
            self.theme.draw_visualizer(self._ctx, vis_w, vis_h, cfg, self._render_bars)
            self._ctx.restore()

        # 5. Drag overlay in edit mode
        if self._edit_mode:
            self.drag.draw_overlay(self._ctx)

        self._surface.flush()

        # Blit Cairo ARGB32 memory into GDI DIB
        src_bytes = self._surface.get_data()
        ctypes.memmove(self._bitmap_bits, bytes(src_bytes), len(src_bytes))

        # Push to Win32 Layered Window
        hdc_screen = self._user32.GetDC(0)
        pt_dest = POINT(0, 0)
        pt_src = POINT(0, 0)
        size = SIZE(self.width, self.height)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)

        self._user32.UpdateLayeredWindow(
            self._hwnd,
            hdc_screen,
            ctypes.byref(pt_dest),
            ctypes.byref(size),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        self._user32.ReleaseDC(0, hdc_screen)

    def _run_window(self) -> None:
        WNDPROC = ctypes.WINFUNCTYPE(wintypes.LPARAM, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

        def wnd_proc(hwnd, msg, wparam, lparam):
            if msg == WM_DESTROY:
                self._user32.PostQuitMessage(0)
                return 0
            elif msg == WM_LBUTTONDOWN and self._edit_mode:
                x = float(lparam & 0xFFFF)
                y = float((lparam >> 16) & 0xFFFF)
                self.drag.on_press(None, type("Event", (), {"x": x, "y": y, "button": 1})())
                return 0
            elif msg == WM_MOUSEMOVE and self._edit_mode:
                x = float(lparam & 0xFFFF)
                y = float((lparam >> 16) & 0xFFFF)
                self.drag.on_motion(None, type("Event", (), {"x": x, "y": y})())
                return 0
            elif msg == WM_LBUTTONUP and self._edit_mode:
                self.drag.on_release(None, None)
                return 0
            return self._user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        wnd_proc_cb = WNDPROC(wnd_proc)

        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [
                ("cbSize", wintypes.UINT),
                ("style", wintypes.UINT),
                ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int),
                ("cbWndExtra", ctypes.c_int),
                ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON),
                ("hCursor", wintypes.HCURSOR),
                ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR),
                ("lpszClassName", wintypes.LPCWSTR),
                ("hIconSm", wintypes.HICON),
            ]

        hinst = self._kernel32.GetModuleHandleW(None)
        class_name = "DesktopSuiteCanvas"

        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = wnd_proc_cb
        wc.hInstance = hinst
        wc.lpszClassName = class_name
        wc.hCursor = self._user32.LoadCursorW(0, 32512)  # IDC_ARROW

        self._user32.RegisterClassExW(ctypes.byref(wc))

        ex_style = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE | WS_EX_TOPMOST
        self._hwnd = self._user32.CreateWindowExW(
            ex_style,
            class_name,
            "DesktopSuite Canvas",
            WS_POPUP | WS_VISIBLE,
            0,
            0,
            self.width,
            self.height,
            0,
            0,
            hinst,
            0,
        )

        self._setup_surface()

        # Render loop at ~30 FPS
        msg = wintypes.MSG()
        while not self._stop_event.is_set():
            while self._user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, 1):  # PM_REMOVE
                if msg.message == 0x0012:  # WM_QUIT
                    return
                self._user32.TranslateMessage(ctypes.byref(msg))
                self._user32.DispatchMessageW(ctypes.byref(msg))

            self._render_frame()
            time.sleep(0.033)

        if self._hbitmap:
            self._gdi32.DeleteObject(self._hbitmap)
        if self._hdc_mem:
            self._gdi32.DeleteDC(self._hdc_mem)
