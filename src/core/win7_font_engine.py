"""
src.core.win7_font_engine
=========================
High-performance FreeType font rendering engine and zero-copy shared memory buffer
for DesktopSuite on Windows 7 SP1 x64 (Intel Core i3-4005U / Intel HD Graphics 4400).

Bypasses Windows 7 GDI limitations (CFF .otf rejection in memory DCs, Name ID 16 mismatch,
and missing font weights) by using Qt's internal FreeType 2 rasterizer.
Provides a drop-in Win7CairoContext proxy that forwards vector graphics to C Cairo
while rendering text via QPainter + FreeType on the exact same zero-copy shared memory buffer.
"""

from __future__ import annotations

import ctypes
import logging
import os
import sys
from pathlib import Path
from typing import Any, NamedTuple, Optional

import cairo

log = logging.getLogger(__name__)


def enable_qt_freetype_on_win7() -> None:
    """
    Forces PyQt5 on Windows to use its built-in FreeType 2 font engine
    instead of Windows GDI / DirectWrite.
    Must be called BEFORE QApplication is instantiated.
    """
    if sys.platform == "win32":
        os.environ["QT_QPA_PLATFORM"] = "windows:fontengine=freetype"
        log.info("Enabled Qt FreeType font engine on Windows (QT_QPA_PLATFORM=windows:fontengine=freetype)")


class CairoTextExtents(NamedTuple):
    x_bearing: float
    y_bearing: float
    width: float
    height: float
    x_advance: float
    y_advance: float = 0.0


class CairoFontExtents(NamedTuple):
    ascent: float
    descent: float
    height: float
    max_x_advance: float
    max_y_advance: float = 0.0


class BundledFontRegistry:
    """
    Loads bundled .ttf and .otf fonts via QFontDatabase and maintains a
    case-insensitive lookup table with automatic weight fallback synthesis.
    """

    # Standard explicit family mappings for all DesktopSuite themes
    KNOWN_ALIASES: dict[str, str] = {
        "anurati": "Anurati",
        "anurati-regular": "Anurati",
        "montserrat": "Montserrat",
        "montserrat light": "Montserrat",
        "montserrat bold": "Montserrat",
        "bebas neue": "Bebas Neue",
        "bebasneue": "Bebas Neue",
        "bebasneue-regular": "Bebas Neue",
        "shojumaru": "Shojumaru",
        "shojumaru-regular": "Shojumaru",
        "wild youth": "Wild Youth",
        "wildyouth": "Wild Youth",
        "caveat": "Caveat",
        "caveat-bold": "Caveat",
        "sf sports night": "SF Sports Night",
        "sfsportsnight": "SF Sports Night",
        "anton": "Anton",
        "anton-regular": "Anton",
        "orbitron": "Orbitron",
        "orbitron-bold": "Orbitron",
        "share tech mono": "Share Tech Mono",
        "sharetechmono": "Share Tech Mono",
        "sharetechmono-regular": "Share Tech Mono",
        "press start 2p": "Press Start 2P",
        "pressstart2p": "Press Start 2P",
        "pressstart2p-regular": "Press Start 2P",
        "vt323": "VT323",
        "vt323-regular": "VT323",
        "cinzel": "Cinzel",
        "cinzel-bold": "Cinzel",
        "comfortaa": "Comfortaa",
        "comfortaa-bold": "Comfortaa",
    }

    def __init__(self) -> None:
        self.family_map: dict[str, str] = dict(self.KNOWN_ALIASES)
        self.available_weights: dict[str, list[int]] = {}
        self._loaded = False

    def load_fonts_from_directory(self, fonts_dir: str | Path) -> int:
        """Register all font files in fonts_dir with QFontDatabase."""
        fonts_path = Path(fonts_dir).resolve()
        if not fonts_path.is_dir():
            log.warning("Bundled font directory not found: %s", fonts_path)
            return 0

        try:
            from PyQt5.QtGui import QFontDatabase
        except ImportError:
            log.warning("PyQt5 not available; cannot load bundled fonts into QFontDatabase")
            return 0

        db = QFontDatabase()
        count = 0

        for ext in ("*.ttf", "*.otf"):
            for font_file in sorted(fonts_path.glob(ext)):
                full_path = str(font_file.resolve())
                font_id = QFontDatabase.addApplicationFont(full_path)
                if font_id == -1:
                    log.warning("QFontDatabase failed to load: %s", font_file.name)
                    continue

                families = QFontDatabase.applicationFontFamilies(font_id)
                for fam in families:
                    clean_key = fam.strip().lower()
                    self.family_map[clean_key] = fam

                    # Map without spaces (e.g. "bebasneue")
                    self.family_map[clean_key.replace(" ", "")] = fam

                    # Map without style suffixes (" regular", " bold", " light", etc.)
                    for suffix in (" regular", " bold", " light", " medium", " thin", " black"):
                        if clean_key.endswith(suffix):
                            base_key = clean_key[:-len(suffix)].strip()
                            self.family_map.setdefault(base_key, fam)
                            self.family_map.setdefault(base_key.replace(" ", ""), fam)

                    # Record available weights
                    styles = db.styles(fam)
                    weights = [db.weight(fam, s) for s in styles if db.weight(fam, s) > 0]
                    self.available_weights[fam] = sorted(set(weights))

                # Map filename stem (e.g. "Wild Youth.otf" -> "wild youth", "wildyouth")
                stem_raw = font_file.stem.lower()
                self.family_map.setdefault(stem_raw, families[0] if families else stem_raw)
                self.family_map.setdefault(stem_raw.replace(" ", ""), families[0] if families else stem_raw)
                stem_base = stem_raw.split("-")[0].strip()
                if families:
                    self.family_map.setdefault(stem_base, families[0])
                    self.family_map.setdefault(stem_base.replace(" ", ""), families[0])

                count += 1

        self._loaded = True
        log.info("BundledFontRegistry loaded %d fonts (%d families mapped)", count, len(self.family_map))
        return count

    def resolve_qfont(
        self,
        requested_family: str,
        cairo_slant: int,
        cairo_weight: int,
        pixel_size: float,
    ) -> Any:
        """Resolve a requested font family, slant, and weight to a configured QFont."""
        from PyQt5.QtGui import QFont

        raw_key = requested_family.strip().lower()
        no_space_key = raw_key.replace(" ", "").replace("-", "")

        # Lookup in family map
        actual_family = self.family_map.get(
            raw_key,
            self.family_map.get(no_space_key, self.KNOWN_ALIASES.get(raw_key, requested_family))
        )

        font = QFont(actual_family)
        font.setPixelSize(max(1, int(round(pixel_size))))

        # Map Cairo slant -> QFont style
        if cairo_slant == cairo.FontSlant.ITALIC:
            font.setStyle(QFont.StyleItalic)
        elif cairo_slant == cairo.FontSlant.OBLIQUE:
            font.setStyle(QFont.StyleOblique)
        else:
            font.setStyle(QFont.StyleNormal)

        # Map Cairo weight -> QFont weight (Qt scale: 50 = Normal, 75 = Bold)
        target_qt_weight = QFont.Bold if cairo_weight == cairo.FontWeight.BOLD else QFont.Normal

        # Synthesize closest weight if exact weight not bundled
        avail = self.available_weights.get(actual_family)
        if avail and target_qt_weight not in avail:
            closest_weight = min(avail, key=lambda w: abs(w - target_qt_weight))
            font.setWeight(closest_weight)
        else:
            font.setWeight(target_qt_weight)

        font.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        return font


class SharedCairoQtSurface:
    """
    Zero-copy shared memory ARGB32 surface between PyCairo and PyQt5 QPainter.
    Qt's QImage owns a writable unshared buffer (ref=1, ro_data=False) and PyCairo
    draws directly into that scanline memory so QPainter never detaches onto a copy.
    """

    def __init__(self, width: int, height: int, font_registry: BundledFontRegistry) -> None:
        from PyQt5.QtGui import QImage

        self.width = max(1, width)
        self.height = max(1, height)
        self.font_registry = font_registry
        self._disposed = False

        # Qt allocates and owns its native aligned ARGB32_Premultiplied buffer (ro_data=False)
        self.qimage = QImage(self.width, self.height, QImage.Format_ARGB32_Premultiplied)
        self.qimage.fill(0)

        self.stride = self.qimage.bytesPerLine()
        self._buf_size = self.stride * self.height
        self._buf_addr = 0
        self._buffer: Any = None
        self.cairo_surface: Any = None
        self._bind_cairo_surface()

    def _bind_cairo_surface(self) -> None:
        """Bind (or rebind) Cairo's ImageSurface directly over self.qimage's writable buffer."""
        if self._disposed or self.qimage is None:
            return
        if self.cairo_surface is not None:
            try:
                self.cairo_surface.finish()
            except Exception:
                pass
            self.cairo_surface = None

        bits_ptr = self.qimage.bits()
        self._buf_addr = int(bits_ptr)
        self._buffer = (ctypes.c_ubyte * self._buf_size).from_address(self._buf_addr)
        self.cairo_surface = cairo.ImageSurface.create_for_data(
            self._buffer, cairo.FORMAT_ARGB32, self.width, self.height, self.stride
        )

        try:
            q_const_addr = int(self.qimage.constBits())
            if q_const_addr != self._buf_addr:
                log.warning(
                    "SharedCairoQtSurface address mismatch: qimage=0x%X vs buffer=0x%X",
                    q_const_addr, self._buf_addr,
                )
        except Exception:
            pass

    def clear_transparent(self) -> None:
        """
        Wipes the shared ARGB32 RAM buffer to 0x00000000 (fully transparent)
        and ensures Cairo remains bound to self.qimage's current scanline address.
        """
        if self._disposed or self.qimage is None:
            return
        if self.cairo_surface is not None:
            self.cairo_surface.flush()
        self.qimage.fill(0)
        cur_addr = int(self.qimage.constBits())
        if cur_addr != self._buf_addr:
            log.warning(
                "SharedCairoQtSurface rebound after QImage relocate: 0x%X -> 0x%X",
                self._buf_addr, cur_addr,
            )
            self._bind_cairo_surface()
        if self.cairo_surface is not None:
            self.cairo_surface.mark_dirty()

    def get_blit_qimage(self) -> Any:
        """Flush pending Cairo drawing and return the shared QImage for QPainter.drawImage()."""
        if self.cairo_surface is not None:
            self.cairo_surface.flush()
        return self.qimage

    def dispose(self) -> None:
        """Deterministically release Cairo handle before freeing QImage buffer."""
        if self._disposed:
            return
        self._disposed = True
        try:
            if self.cairo_surface is not None:
                self.cairo_surface.flush()
                self.cairo_surface.finish()
        except Exception:
            pass
        self.cairo_surface = None
        self._buffer = None
        self.qimage = None

    def create_context(self) -> Win7CairoContext:
        """Create a drop-in Win7CairoContext proxy operating on this surface."""
        return Win7CairoContext(self.cairo_surface, self.qimage, self.font_registry)


class Win7CairoContext:
    """
    Drop-in proxy for cairo.Context.
    Forwards all vector operations to C cairo.Context while intercepting
    Cairo Toy Text API calls (select_font_face, set_font_size, text_extents, show_text)
    and rendering them directly onto the shared buffer via QPainter + FreeType.
    """

    def __init__(
        self,
        cairo_surface: cairo.ImageSurface,
        qimage: Any,
        font_registry: BundledFontRegistry,
    ) -> None:
        self._ctx = cairo.Context(cairo_surface)
        self._surface = cairo_surface
        self._qimage = qimage
        self._registry = font_registry

        self._font_family = "Sans"
        self._font_slant = cairo.FontSlant.NORMAL
        self._font_weight = cairo.FontWeight.NORMAL
        self._font_size = 12.0
        self._last_rgba = (1.0, 1.0, 1.0, 1.0)
        self._state_stack: list[tuple[str, int, int, float, tuple[float, float, float, float]]] = []

    # --- State Stack Tracking ---
    def save(self) -> None:
        self._state_stack.append((
            self._font_family, self._font_slant,
            self._font_weight, self._font_size, self._last_rgba
        ))
        self._ctx.save()

    def restore(self) -> None:
        if self._state_stack:
            (
                self._font_family, self._font_slant,
                self._font_weight, self._font_size, self._last_rgba
            ) = self._state_stack.pop()
        self._ctx.restore()

    # --- Source Color Tracking ---
    def set_source_rgb(self, r: float, g: float, b: float) -> None:
        self._last_rgba = (r, g, b, 1.0)
        self._ctx.set_source_rgb(r, g, b)

    def set_source_rgba(self, r: float, g: float, b: float, a: float) -> None:
        self._last_rgba = (r, g, b, a)
        self._ctx.set_source_rgba(r, g, b, a)

    # --- Toy Text API Interception ---
    def select_font_face(
        self,
        family: str,
        slant: int = cairo.FontSlant.NORMAL,
        weight: int = cairo.FontWeight.NORMAL,
    ) -> None:
        self._font_family = family
        self._font_slant = slant
        self._font_weight = weight

    def set_font_size(self, size: float) -> None:
        self._font_size = float(size)

    def _current_qfont(self) -> Any:
        return self._registry.resolve_qfont(
            self._font_family, self._font_slant, self._font_weight, self._font_size
        )

    def text_extents(self, text: str) -> Any:
        if not text:
            try:
                return cairo.TextExtents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
            except Exception:
                return CairoTextExtents(0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        from PyQt5.QtGui import QFontMetricsF
        qfont = self._current_qfont()
        fm = QFontMetricsF(qfont)
        rect = fm.tightBoundingRect(text)
        x_adv = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)

        xb = float(rect.x())
        yb = float(rect.y())
        w = float(rect.width())
        h = float(rect.height())
        xa = float(x_adv)
        ya = 0.0

        try:
            return cairo.TextExtents(xb, yb, w, h, xa, ya)
        except Exception:
            return CairoTextExtents(xb, yb, w, h, xa, ya)

    def font_extents(self) -> Any:
        from PyQt5.QtGui import QFontMetricsF
        qfont = self._current_qfont()
        fm = QFontMetricsF(qfont)
        ascent = float(fm.ascent())
        descent = float(fm.descent())
        height = float(fm.height())
        max_x = float(fm.maxWidth())
        try:
            return cairo.FontExtents(ascent, descent, height, max_x, 0.0)
        except Exception:
            return CairoFontExtents(ascent, descent, height, max_x, 0.0)

    def show_text(self, text: str) -> None:
        if not text:
            return

        has_current = self._ctx.has_current_point()
        cx, cy = self._ctx.get_current_point() if has_current else (0.0, 0.0)

        # 1. Flush pending Cairo vector commands to the shared buffer
        self._surface.flush()

        from PyQt5.QtCore import QPointF
        from PyQt5.QtGui import QPainter, QFontMetricsF, QTransform, QColor

        qfont = self._current_qfont()
        painter = QPainter(self._qimage)
        try:
            painter.setRenderHints(
                QPainter.Antialiasing | QPainter.TextAntialiasing | QPainter.SmoothPixmapTransform
            )

            # Sync Cairo Current Transformation Matrix (CTM) to QPainter
            m = self._ctx.get_matrix()
            painter.setTransform(QTransform(m.xx, m.yx, m.xy, m.yy, m.x0, m.y0))

            # Sync RGBA color
            r, g, b, a = self._last_rgba
            painter.setPen(QColor.fromRgbF(
                max(0.0, min(1.0, r)),
                max(0.0, min(1.0, g)),
                max(0.0, min(1.0, b)),
                max(0.0, min(1.0, a)),
            ))
            painter.setFont(qfont)
            painter.drawText(QPointF(cx, cy), text)

            fm = QFontMetricsF(qfont)
            x_adv = fm.horizontalAdvance(text) if hasattr(fm, "horizontalAdvance") else fm.width(text)
        finally:
            painter.end()

        # 2. Mark surface dirty for Cairo and advance the current point
        self._surface.mark_dirty()
        self._ctx.move_to(cx + x_adv, cy)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctx, name)


# ---------------------------------------------------------------------------
# Global Singleton Registry
# ---------------------------------------------------------------------------
_GLOBAL_FONT_REGISTRY: Optional[BundledFontRegistry] = None


def get_font_registry() -> BundledFontRegistry:
    """Return the application-wide BundledFontRegistry singleton."""
    global _GLOBAL_FONT_REGISTRY
    if _GLOBAL_FONT_REGISTRY is None:
        from src.core.fonts import get_font_dir
        _GLOBAL_FONT_REGISTRY = BundledFontRegistry()
        _GLOBAL_FONT_REGISTRY.load_fonts_from_directory(get_font_dir())
    return _GLOBAL_FONT_REGISTRY
