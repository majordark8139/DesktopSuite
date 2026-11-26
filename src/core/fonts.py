"""
src.core.fonts
==============
Registers fonts bundled in assets/fonts/ with Windows GDI, Qt QFontDatabase, and Fontconfig
so Cairo, Uniscribe, and Pango can resolve them by family name across the desktop suite.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import logging
import os
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_FONTS_REGISTERED = False
_REGISTERED_PATHS: list[str] = []


def get_font_dir() -> Path:
    """Locate the bundled font directory in both source and frozen PyInstaller environments."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "assets" / "fonts")
        candidates.append(exe_dir / "_internal" / "assets" / "fonts")
        if hasattr(sys, "_MEIPASS"):
            candidates.append(Path(sys._MEIPASS) / "assets" / "fonts")
    candidates.append(Path(__file__).resolve().parent.parent.parent / "assets" / "fonts")
    candidates.append(Path.cwd() / "assets" / "fonts")
    for d in candidates:
        if d.is_dir():
            return d
    return candidates[0]


def register_bundled_fonts() -> bool:
    """
    Register all TrueType and OpenType fonts in ``assets/fonts/`` with:
    1. Windows GDI32:
       - Session-wide via AddFontResourceW
       - Process-private via AddFontResourceExW (FR_PRIVATE)
       - Broadcast WM_FONTCHANGE via SendMessageTimeoutW
    2. Qt QFontDatabase (if PyQt5 is available)
    3. Fontconfig (Linux)

    Idempotent — runs only once per process.
    """
    global _FONTS_REGISTERED, _REGISTERED_PATHS
    if _FONTS_REGISTERED:
        return True

    font_dir = get_font_dir()

    if not font_dir.is_dir():
        log.warning("Bundled font directory not found: %s", font_dir)
        return False

    success = False

    # 1. Windows GDI session-wide and private font registration
    if sys.platform == "win32":
        try:
            gdi32 = ctypes.windll.gdi32
            gdi32.AddFontResourceW.argtypes = [ctypes.c_wchar_p]
            gdi32.AddFontResourceW.restype = ctypes.c_int

            gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
            gdi32.AddFontResourceExW.restype = ctypes.c_int

            count = 0
            for ext_pattern in ("*.ttf", "*.otf"):
                for font_file in font_dir.glob(ext_pattern):
                    p_str = str(font_file.resolve())
                    r1 = gdi32.AddFontResourceW(p_str)
                    if r1 > 0:
                        count += 1
                        _REGISTERED_PATHS.append(p_str)

            if count > 0:
                log.info("Registered %d bundled fonts with Windows GDI from %s", count, font_dir)
                success = True
                try:
                    user32 = ctypes.windll.user32
                    user32.SendMessageTimeoutW.argtypes = [
                        wintypes.HWND, ctypes.c_uint, wintypes.WPARAM, wintypes.LPARAM,
                        ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_ulong)
                    ]
                    user32.SendMessageTimeoutW.restype = wintypes.LPARAM
                    res_val = ctypes.c_ulong(0)
                    user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 1000, ctypes.byref(res_val))
                except Exception as b_exc:
                    log.debug("WM_FONTCHANGE broadcast error: %s", b_exc)

            atexit.register(_cleanup_fonts)
        except Exception as exc:
            log.warning("Failed to register bundled fonts with Windows GDI: %s", exc)

    # 2. Register with Qt QFontDatabase if QApplication instance exists
    try:
        from PyQt5.QtGui import QGuiApplication
        if QGuiApplication.instance() is not None:
            from src.core.win7_font_engine import get_font_registry
            reg = get_font_registry()
            qt_count = reg.load_fonts_from_directory(font_dir)
            if qt_count > 0:
                log.info("Registered %d bundled fonts with Qt QFontDatabase", qt_count)
                success = True
    except Exception as q_exc:
        log.debug("Qt font registration skipped: %s", q_exc)

    # 3. Fontconfig registration (Linux or Windows with fontconfig available)
    try:
        from ctypes import util as ctypes_util
        fc_lib = ctypes_util.find_library("fontconfig")
        if fc_lib:
            fc = ctypes.CDLL(fc_lib)
            fc.FcConfigAppFontAddDir(None, str(font_dir).encode("utf-8"))
            count = 0
            for ext_pattern in ("*.ttf", "*.otf"):
                for font_file in font_dir.glob(ext_pattern):
                    res = fc.FcConfigAppFontAddFile(None, str(font_file).encode("utf-8"))
                    if res:
                        count += 1
            _FONTS_REGISTERED = True
            log.info("Registered %d bundled fonts with Fontconfig from %s", count, font_dir)
            success = True
    except Exception as exc:
        log.debug("Fontconfig registration skipped or failed: %s", exc)

    _FONTS_REGISTERED = True
    return True


def _cleanup_fonts() -> None:
    """Clean up session font resources on exit."""
    if sys.platform != "win32" or not _REGISTERED_PATHS:
        return
    try:
        gdi32 = ctypes.windll.gdi32
        for p_str in _REGISTERED_PATHS:
            try:
                gdi32.RemoveFontResourceW(p_str)
            except Exception:
                pass
        try:
            user32 = ctypes.windll.user32
            res_val = ctypes.c_ulong(0)
            user32.SendMessageTimeoutW(0xFFFF, 0x001D, 0, 0, 0x0002, 500, ctypes.byref(res_val))
        except Exception:
            pass
    except Exception:
        pass

