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
from pathlib import Path

log = logging.getLogger(__name__)

_FONTS_REGISTERED = False


def register_bundled_fonts() -> bool:
    """
    Register all TrueType fonts located in ``assets/fonts/`` with Fontconfig.

    Calls ``FcConfigAppFontAddDir`` and ``FcConfigAppFontAddFile`` via ctypes.
    Idempotent — runs only once per process.
    """
    global _FONTS_REGISTERED
    if _FONTS_REGISTERED:
        return True

    try:
        fc_lib = ctypes.util.find_library("fontconfig")
        if not fc_lib:
            log.warning("fontconfig library not found; bundled fonts may not resolve")
            return False

        fc = ctypes.CDLL(fc_lib)

        # Locate assets/fonts relative to this module: src/core/fonts.py -> root/assets/fonts
        proj_root = Path(__file__).resolve().parent.parent.parent
        font_dir = proj_root / "assets" / "fonts"

        if not font_dir.is_dir():
            log.warning("Bundled font directory not found: %s", font_dir)
            return False

        # Add the directory to fontconfig app font search paths
        fc.FcConfigAppFontAddDir(None, str(font_dir).encode("utf-8"))

        # Explicitly register individual TTF and OTF font files
        count = 0
        for ext_pattern in ("*.ttf", "*.otf"):
            for font_file in font_dir.glob(ext_pattern):
                res = fc.FcConfigAppFontAddFile(None, str(font_file).encode("utf-8"))
                if res:
                    count += 1

        _FONTS_REGISTERED = True
        log.info("Registered %d bundled fonts from %s", count, font_dir)
        return True
    except Exception as exc:
        log.warning("Failed to register bundled fonts: %s", exc)
        return False
