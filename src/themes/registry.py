"""
src.themes.registry
===================
Theme registry and the built-in **Mond Clean** default theme.

Theme registry
--------------
:class:`ThemeRegistry` is a simple name → instance dictionary.  The
``register`` decorator wires a theme class in automatically::

    registry = ThemeRegistry()

    @registry.register
    class MyTheme(BaseTheme):
        name = "My Theme"
        ...

    theme = registry.get("My Theme")   # returns the singleton instance

The registry is a module-level singleton :data:`REGISTRY` so that
``window.py`` and the settings GUI can share the same object.

Mond Clean (default theme)
--------------------------
A clean, minimal "Mondrian-inspired" white-on-transparent style derived
from the **Horizon Bold** / **Mountain Minimal** looks in the reference
clock:

* Clock: large white ``Montserrat Bold`` or ``Sans Bold`` time string.
* Date:  small light-grey date line below.
* Visualizer: white rounded bar graph (reference ``on_draw_visualizer``).
* Background: full-transparent (opacity = 0).

All geometry is computed once in ``_precompute`` and cached; the per-frame
path only calls ``ctx.show_text`` and ``ctx.stroke``.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Type

import cairo
import numpy as np

from .base import BaseTheme, TimeData

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ThemeRegistry:
    """
    A name-keyed store of :class:`~src.themes.base.BaseTheme` instances.

    Usage
    -----
    ::

        registry = ThemeRegistry()

        @registry.register
        class MyTheme(BaseTheme):
            name = "My Theme"

        theme = registry.get("My Theme")
        theme = registry.get_default()          # first registered theme
    """

    def __init__(self) -> None:
        self._themes: Dict[str, BaseTheme] = {}
        self._default_name: Optional[str] = None

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, cls: Type[BaseTheme]) -> Type[BaseTheme]:
        """
        Register *cls* (a :class:`BaseTheme` subclass) and return it.

        Can be used as a plain decorator::

            @registry.register
            class MyTheme(BaseTheme): ...

        Or called directly::

            registry.register(MyTheme)
        """
        instance = cls()
        name = instance.name
        if name in self._themes:
            log.warning("ThemeRegistry: overwriting theme %r", name)
        self._themes[name] = instance
        if self._default_name is None:
            self._default_name = name
        log.debug("ThemeRegistry: registered %r", name)
        return cls

    def add(self, instance: BaseTheme) -> None:
        """Register a pre-constructed theme *instance*."""
        name = instance.name
        self._themes[name] = instance
        if self._default_name is None:
            self._default_name = name

    # ------------------------------------------------------------------
    # Retrieval
    # ------------------------------------------------------------------

    def get(self, name: str) -> Optional[BaseTheme]:
        """
        Return the theme registered under *name*, or ``None`` if not found.
        """
        theme = self._themes.get(name)
        if theme is None:
            log.warning("ThemeRegistry: unknown theme %r; falling back to default", name)
            return self.get_default()
        return theme

    def get_default(self) -> Optional[BaseTheme]:
        """Return the first-registered theme, or ``None`` if empty."""
        if self._default_name:
            return self._themes.get(self._default_name)
        return None

    def names(self) -> list[str]:
        """Return a sorted list of all registered theme names."""
        return sorted(self._themes.keys())

    def __contains__(self, name: str) -> bool:
        return name in self._themes

    def __len__(self) -> int:
        return len(self._themes)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ThemeRegistry({self.names()})"


# ---------------------------------------------------------------------------
# Built-in theme: Original Cursive (Silhouette & Script)
# ---------------------------------------------------------------------------

class OriginalCursiveTheme(BaseTheme):
    """
    **Original Cursive** — the signature Silhouette & Script theme ported
    directly from ~/.config/desktop-clock.py.

    Layout (desktop-clock.py 'silhouette_overlap'):
    * Clock:
      - Translucent condensed time digits in Bebas Neue (size 98 pt, alpha 32%)
      - Interlaced cursive day name in Great Vibes (size 44 pt, white)
        centered directly over the time digits with a rich drop-shadow glow
        matching CSS text-shadow: 0px 3px 12px rgba(0,0,0,0.95).
    * Date:
      - Uppercase spaced date in Bebas Neue (size 13 pt, #D0D0D0)
        with subtle drop-shadow glow matching CSS text-shadow: 0px 2px 10px rgba(0,0,0,0.85).
        Format: "2  1     O  C  T  O  B  E  R     2  0  2  6".
    * Visualizer:
      - 27-bar symmetrical audio visualizer (bar_w=4.0, gap=5.2) centered
        horizontally at width 430, matching the exact geometry from
        desktop-clock.py on_draw_visualizer.
    """

    name: str = "Original Cursive"

    _TIME_FONT_SIZE   = 98.0    # pt — Bebas Neue size 98
    _SCRIPT_FONT_SIZE = 44.0    # pt — Great Vibes size 44
    _DATE_FONT_SIZE   = 13.0    # pt — Bebas Neue size 13
    _VIS_BAR_WIDTH    = 4.0     # px — reference: bar_w = 4.0 * sc
    _VIS_BAR_GAP      = 5.2     # px — reference: gap = 5.2 * sc
    _BLOCK_WIDTH      = 430.0   # px — reference window width

    def _precompute(self) -> None:
        self.cache["time_font_size"]   = self._TIME_FONT_SIZE
        self.cache["script_font_size"] = self._SCRIPT_FONT_SIZE
        self.cache["date_font_size"]   = self._DATE_FONT_SIZE
        self.cache["bar_width"]        = self._VIS_BAR_WIDTH
        self.cache["bar_gap"]          = self._VIS_BAR_GAP
        self.cache["block_width"]      = self._BLOCK_WIDTH

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0))
        if opacity <= 0.0:
            return
        ctx.rectangle(0, 0, width, height)
        ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
        ctx.fill()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """
        Render the silhouette & script overlay:
        Translucent condensed digits in Bebas Neue 98pt (alpha 32%),
        with cursive day name in Great Vibes 44pt centered on top with drop shadow.
        Scale is applied to font sizes and layout metrics.
        """
        color = cfg.get("clock_color", "#FFFFFF")
        scale = float(cfg.get("scale", 1.0) or 1.0)
        t_sz = self.cache["time_font_size"] * scale
        s_sz = self.cache["script_font_size"] * scale
        bw = self.cache["block_width"] * scale
        cx = bw / 2.0
        cy = 50.0 * scale

        # 1. Base time: Bebas Neue, alpha ~32%
        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(t_sz)
        t_ext = ctx.text_extents(time_data.time_str)
        tx = cx - t_ext.width / 2.0 - t_ext.x_bearing
        ty = cy - t_ext.height / 2.0 - t_ext.y_bearing

        self.set_hex_color(ctx, color, alpha=0.32)
        ctx.move_to(tx, ty)
        ctx.show_text(time_data.time_str)

        # 2. Cursive script day: Great Vibes with drop-shadow glow
        ctx.select_font_face("Great Vibes", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(s_sz)
        d_ext = ctx.text_extents(time_data.day_str)
        dx = cx - d_ext.width / 2.0 - d_ext.x_bearing
        dy = cy - d_ext.height / 2.0 - d_ext.y_bearing

        # Multi-pass shadow simulating CSS text-shadow: 0px 3px 12px rgba(0,0,0,0.95)
        for ox, oy, alpha in [
            (0, 3 * scale, 0.40),
            (0, 4 * scale, 0.30),
            (0, 2 * scale, 0.30),
            (-1 * scale, 3 * scale, 0.25),
            (1 * scale, 3 * scale, 0.25),
            (-2 * scale, 3 * scale, 0.15),
            (2 * scale, 3 * scale, 0.15),
            (0, 5 * scale, 0.15),
            (0, 1 * scale, 0.15),
            (-1 * scale, 2 * scale, 0.20),
            (1 * scale, 2 * scale, 0.20),
            (-1 * scale, 4 * scale, 0.20),
            (1 * scale, 4 * scale, 0.20),
        ]:
            ctx.move_to(dx + ox, dy + oy)
            ctx.set_source_rgba(0.0, 0.0, 0.0, alpha)
            ctx.show_text(time_data.day_str)

        # Cursive foreground text
        self.set_hex_color(ctx, color, alpha=1.0)
        ctx.move_to(dx, dy)
        ctx.show_text(time_data.day_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """
        Render spaced uppercase date in Bebas Neue
        with subtle drop-shadow glow (0px 2px 10px rgba(0,0,0,0.85)).
        """
        color = cfg.get("date_color", "#D0D0D0")
        scale = float(cfg.get("scale", 1.0) or 1.0)
        sz = self.cache["date_font_size"] * scale
        bw = self.cache["block_width"] * scale
        cx = bw / 2.0

        spaced_date = "  ".join(list(time_data.date_str))

        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(sz)
        ext = ctx.text_extents(spaced_date)

        x = cx - ext.width / 2.0 - ext.x_bearing
        y = (12.0 * scale) - ext.height / 2.0 - ext.y_bearing

        # Subtle shadow: text-shadow: 0px 2px 10px rgba(0,0,0,0.85)
        for ox, oy, alpha in [
            (0, 2 * scale, 0.35),
            (0, 1 * scale, 0.25),
            (-1 * scale, 2 * scale, 0.20),
            (1 * scale, 2 * scale, 0.20),
            (0, 3 * scale, 0.15),
        ]:
            ctx.move_to(x + ox, y + oy)
            ctx.set_source_rgba(0.0, 0.0, 0.0, alpha)
            ctx.show_text(spaced_date)

        # Foreground
        self.set_hex_color(ctx, color, alpha=0.92)
        ctx.move_to(x, y)
        ctx.show_text(spaced_date)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        """
        Render the 27-bar symmetrical spectrum visualizer scaled by canvas.scale
        and canvas.visualizer_intensity.
        """
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        intensity = float(cfg.get("visualizer_intensity", 0.65) or 0.65)

        total_bars = len(audio_bars)
        bar_w = self.cache["bar_width"] * scale
        gap   = self.cache["bar_gap"] * scale
        bw    = self.cache["block_width"] * scale

        total_w = total_bars * (bar_w + gap) - gap
        start_x = (bw - total_w) / 2.0
        base_y  = float(height) - (4.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)

        # Spectrum color: visualizer_color
        vis_color = cfg.get("visualizer_color", "#FFFFFF")
        self.set_hex_color(ctx, vis_color, alpha=0.82)

        # Intensity ratio relative to reference 0.65
        intensity_mult = intensity / 0.65

        for i in range(total_bars):
            h = float(audio_bars[i]) * (height - 8.0 * scale) * intensity_mult
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 1.5 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ---------------------------------------------------------------------------
# Built-in theme: Mond Clean
# ---------------------------------------------------------------------------

class MondCleanTheme(BaseTheme):
    """
    **Mond Clean** — the minimal default theme.

    Inspired by the "Horizon Bold" and "Mountain Minimal" layouts from the
    reference ``desktop-clock.py``.

    Layout (all positions relative to widget origin)
    ------------------------------------------------
    * Clock   — large bold time string, left-aligned at (0, font_size).
    * Date    — small light-grey string 8 px below the clock baseline.
    * Visualizer — centred horizontal bar graph (identical to reference
                   ``on_draw_visualizer``), bars are 4 px wide, 5.2 px gap,
                   rounded line caps.
    """

    name: str = "Mond Clean"

    # Visual constants (easily tweakable).
    _CLOCK_FONT_SIZE  = 72.0    # pt — reference: time_size = 74
    _DATE_FONT_SIZE   = 14.0    # pt — reference: date_size = 11 (slightly larger)
    _VIS_BAR_WIDTH    = 4.0     # px — reference: bar_w = 4.0 * sc
    _VIS_BAR_GAP      = 5.2     # px — reference: gap = 5.2 * sc

    def _precompute(self) -> None:
        """Cache static values that don't change per frame."""
        self.cache["clock_font_size"] = self._CLOCK_FONT_SIZE
        self.cache["date_font_size"]  = self._DATE_FONT_SIZE
        self.cache["bar_width"]       = self._VIS_BAR_WIDTH
        self.cache["bar_gap"]         = self._VIS_BAR_GAP

    # ------------------------------------------------------------------
    # draw_background
    # ------------------------------------------------------------------

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        """Draw a translucent dark rectangle if background_opacity > 0."""
        opacity = float(cfg.get("background_opacity", 0.0))
        if opacity <= 0.0:
            return
        ctx.rectangle(0, 0, width, height)
        ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
        ctx.fill()

    # ------------------------------------------------------------------
    # draw_clock
    # ------------------------------------------------------------------

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """
        Render the time string.

        Font preference order: cfg font_family → ``Sans``.
        Weight: Bold (mirrors ``Montserrat Black`` weight in reference).
        """
        scale  = float(cfg.get("scale", 1.0) or 1.0)
        font   = cfg.get("font_family", "Sans")
        color  = cfg.get("clock_color", "#FFFFFF")
        size   = self.cache["clock_font_size"] * scale

        ctx.select_font_face(font, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(size)
        self.set_hex_color(ctx, color, alpha=1.0)

        # Subtle text shadow: draw the same text slightly offset in black/50%.
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.5)
        ctx.move_to(2 * scale, size + 2 * scale)
        ctx.show_text(time_data.time_str)

        # Main text.
        self.set_hex_color(ctx, color, alpha=1.0)
        ctx.move_to(0, size)
        ctx.show_text(time_data.time_str)

    # ------------------------------------------------------------------
    # draw_date
    # ------------------------------------------------------------------

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """
        Render a two-line date: weekday on line 1, full date on line 2.

        Mirrors the "horizon_bold" layout from the reference:
        ``lbl_l3 → date_font date_size date_color``.
        """
        scale = float(cfg.get("scale", 1.0) or 1.0)
        font  = cfg.get("font_family", "Sans")
        size  = self.cache["date_font_size"] * scale
        color = cfg.get("date_color", "#D0D0D0")

        ctx.select_font_face(font, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(size)
        self.set_hex_color(ctx, color, alpha=0.85)

        line1 = time_data.day_str.upper()
        line2 = time_data.date_str

        ctx.move_to(0, size)
        ctx.show_text(line1)
        ctx.move_to(0, size * 2 + 4 * scale)
        ctx.show_text(line2)

    # ------------------------------------------------------------------
    # draw_visualizer
    # ------------------------------------------------------------------

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        """
        Render the symmetric spectrum bar graph.

        Pixel-perfect port of ``on_draw_visualizer`` from the reference
        (lines 362–388) — same bar_w, gap, start_x centering, line-cap,
        and colour logic.

        The incoming *audio_bars* are 0.0–1.0; we scale by ``height``
        to get pixel heights.
        """
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        intensity = float(cfg.get("visualizer_intensity", 0.65) or 0.65)

        total_bars = len(audio_bars)
        bar_w = self.cache["bar_width"] * scale
        gap   = self.cache["bar_gap"] * scale

        total_w = total_bars * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y  = float(height) - (4.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)

        vis_color = cfg.get("visualizer_color", "#FFFFFF")
        self.set_hex_color(ctx, vis_color, alpha=0.82)

        intensity_mult = intensity / 0.65

        for i in range(total_bars):
            h = float(audio_bars[i]) * (height - 8.0 * scale) * intensity_mult
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 1.5 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ---------------------------------------------------------------------------
# Module-level singleton registry — pre-populated with built-in & community themes
# ---------------------------------------------------------------------------

from .collection import (
    MondMinimalTheme,
    EleganceTwoToneTheme,
    SonderAxisTheme,
    WildYouthTheme,
    ChronoBlockTheme,
    VerticalOverlapTheme,
)

REGISTRY = ThemeRegistry()
REGISTRY.add(OriginalCursiveTheme())
REGISTRY.add(MondCleanTheme())
REGISTRY.add(MondMinimalTheme())
REGISTRY.add(EleganceTwoToneTheme())
REGISTRY.add(SonderAxisTheme())
REGISTRY.add(WildYouthTheme())
REGISTRY.add(ChronoBlockTheme())
REGISTRY.add(VerticalOverlapTheme())

