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


def register_bundled_fonts() -> bool:
    """
    Register all TrueType fonts located in ``assets/fonts/`` with Fontconfig (Linux)
    or GDI32 AddFontResourceExW (Windows).

    Idempotent — runs only once per process.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return True

    proj_root = Path(__file__).resolve().parent.parent.parent
    font_dir = proj_root / "assets" / "fonts"

    if not font_dir.is_dir():
        log.warning("Bundled font directory not found: %s", font_dir)
        return False

    success = False

    # Windows GDI private font registration
    if sys.platform == "win32":
        try:
            gdi32 = ctypes.windll.gdi32
            FR_PRIVATE = 0x10
            count = 0
            for ext_pattern in ("*.ttf", "*.otf"):
                for font_file in font_dir.glob(ext_pattern):
                    res = gdi32.AddFontResourceExW(str(font_file), FR_PRIVATE, 0)
                    if res > 0:
                        count += 1
            if count > 0:
                _FONTS_REGISTERED = True
                log.info("Registered %d bundled fonts with Windows GDI from %s", count, font_dir)
                success = True
        except Exception as exc:
            log.warning("Failed to register bundled fonts with Windows GDI: %s", exc)

    # Fontconfig registration (Linux or Windows with fontconfig available)
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
