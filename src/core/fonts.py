"""
src.core.fonts
==============
Registers fonts bundled in assets/fonts/ with Fontconfig so Cairo and Pango
can resolve them by family name across the desktop suite.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import logging
import sys
from pathlib import Path

log = logging.getLogger(__name__)

_FONTS_REGISTERED = False


def get_font_dir() -> Path:
    """Locate the bundled font directory in both source and frozen PyInstaller environments."""
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.append(exe_dir / "assets" / "fonts")
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
    1. Windows GDI32 (AddFontResourceExW)
    2. Qt QFontDatabase (if PyQt5 is available)
    3. Fontconfig (Linux)

    Idempotent — runs only once per process.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return True

    font_dir = get_font_dir()

    if not font_dir.is_dir():
        log.warning("Bundled font directory not found: %s", font_dir)
        return False

    success = False

    # 1. Windows GDI private font registration
    if sys.platform == "win32":
        try:
            gdi32 = ctypes.windll.gdi32
            gdi32.AddFontResourceExW.argtypes = [ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_void_p]
            gdi32.AddFontResourceExW.restype = ctypes.c_int
            FR_PRIVATE = 0x10
            count = 0
            for ext_pattern in ("*.ttf", "*.otf"):
                for font_file in font_dir.glob(ext_pattern):
                    res = gdi32.AddFontResourceExW(str(font_file.resolve()), FR_PRIVATE, 0)
                    if res > 0:
                        count += 1
            if count > 0:
                _FONTS_REGISTERED = True
                log.info("Registered %d bundled fonts with Windows GDI from %s", count, font_dir)
                success = True
                try:
                    user32 = ctypes.windll.user32
                    user32.PostMessageW(0xFFFF, 0x001D, 0, 0)  # HWND_BROADCAST, WM_FONTCHANGE
                except Exception:
                    pass
        except Exception as exc:
            log.warning("Failed to register bundled fonts with Windows GDI: %s", exc)

    # 2. Register with Qt QFontDatabase if PyQt5 is loaded
    try:
        from PyQt5.QtGui import QFontDatabase
        qt_count = 0
        for ext_pattern in ("*.ttf", "*.otf"):
            for font_file in font_dir.glob(ext_pattern):
                fid = QFontDatabase.addApplicationFont(str(font_file.resolve()))
                if fid >= 0:
                    qt_count += 1
        if qt_count > 0:
            log.info("Registered %d bundled fonts with Qt QFontDatabase", qt_count)
            success = True
    except Exception:
        pass

    # 3. Fontconfig registration (Linux or Windows with fontconfig available)
    try:
        fc_lib = ctypes.util.find_library("fontconfig")
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

    return success or _FONTS_REGISTERED
