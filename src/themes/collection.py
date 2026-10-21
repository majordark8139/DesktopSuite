"""
src.themes.collection
=====================
Master collection of 6 iconic community Rainmeter themes.

Themes included:
1. Mond Minimal       — Elegant tracked day, dashed time subtext, baseline bars
2. Elegance Two-Tone  — Clean ultra-thin split-colored digits with subtext
3. Sonder Axis        — Central vertical accent stroke, greeting, dual-direction bars
4. Wild Youth         — Bold brush italic numerals with soft drop shadow & gradient bars
5. Chrono Block       — Heavy monospace rectangular digits with square colon & LED block visualizer
6. Vertical Overlap   — Two-tier stacked numbers with watermark day & right-aligned visualizer
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

import cairo
import numpy as np

from src.themes.base import BaseTheme, TimeData

# Alias requested in theme requirements
ThemeBase = BaseTheme


def _hex_to_rgb(hex_color: str) -> tuple[float, float, float]:
    """Parse '#RRGGBB' or '#RGB' hex string into float (r, g, b) in 0.0 .. 1.0."""
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    try:
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        return r, g, b
    except (ValueError, IndexError):
        return 1.0, 1.0, 1.0


def _ordinal_suffix(day: int) -> str:
    """Return English ordinal suffix: 1st, 2nd, 3rd, 4th, etc."""
    if 11 <= (day % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(day % 10, "th")


# ===========================================================================
# 1. Mond Minimal
# ===========================================================================

class MondMinimalTheme(BaseTheme):
    """
    **Mond Minimal**

    Iconic aesthetic inspired by the widely loved 'Mond' Rainmeter skin:
    * Day: Large uppercase string with deliberate letter tracking (e.g., 'F  R  I  D  A  Y').
    * Time: Minimalist centered time enclosed in dashes (e.g., '- 09:34 -').
    * Date: Clean medium sans subtext (e.g., '20 OCTOBER, 2026').
    * Visualizer: Thin, delicate baseline spectrum bars.
    """

    name: str = "Mond Minimal"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")
        font_family = cfg.get("font_family", "Sans")

        # Tracked uppercase day string (double space between letters)
        day_tracked = "  ".join(list(time_data.day_str.upper()))

        # Day label: font size 36 * scale, Bold
        day_size = 36.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(day_size)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(0, day_size)
        ctx.show_text(day_tracked)

        # Time label enclosed in dashes: font size 16 * scale, Normal
        time_str = f"- {time_data.time_str} -"
        time_size = 16.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(time_size)
        self.set_hex_color(ctx, clock_color, alpha=0.90)
        ctx.move_to(4 * scale, day_size + (24.0 * scale))
        ctx.show_text(time_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        # Date: e.g. "20 OCTOBER, 2026"
        month_name = time.strftime("%B", time.localtime()).upper()
        date_text = f"{time_data.day:02d} {month_name}, {time_data.year}"

        date_size = 14.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(date_size)
        self.set_hex_color(ctx, date_color, alpha=0.92)
        ctx.move_to(0, date_size)
        ctx.show_text(date_text)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        total_bars = len(audio_bars)
        bar_w = 2.0 * scale
        gap = 3.0 * scale
        total_w = total_bars * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (2.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        for i in range(total_bars):
            h = float(audio_bars[i]) * (height - 4.0 * scale) * amp
            h = max(0.0, min(float(height - 2.0 * scale), h))
            if h <= 1.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 2. Elegance Two-Tone
# ===========================================================================

class EleganceTwoToneTheme(BaseTheme):
    """
    **Elegance Two-Tone**

    Minimalist two-tone digital typography with ultra-thin numerals:
    * Hours in ``clock_color``, Minutes in ``visualizer_color``.
    * Clean lowercase subtext: 'wednesday | october 21, 2026'.
    * Low-profile 32-bar visualizer with rounded line caps.
    """

    name: str = "Elegance Two-Tone"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")
        vis_color = cfg.get("visualizer_color", "#FFFFFF")
        font_family = cfg.get("font_family", "Sans")

        font_size = 72.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)

        # Split into Hours and Minutes
        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        # 1. Hours in clock_color
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(0, font_size)
        ctx.show_text(hr_str)
        ext_hr = ctx.text_extents(hr_str)

        # 2. Colon in clock_color with soft transparency
        colon_x = ext_hr.x_advance + (4.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.60)
        ctx.move_to(colon_x, font_size)
        ctx.show_text(":")
        ext_colon = ctx.text_extents(":")

        # 3. Minutes in visualizer_color
        min_x = colon_x + ext_colon.x_advance + (4.0 * scale)
        self.set_hex_color(ctx, vis_color, alpha=1.0)
        ctx.move_to(min_x, font_size)
        ctx.show_text(min_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        # Lowercase clean subtext: e.g. "wednesday | october 21, 2026"
        subtext = time.strftime("%A | %B %d, %Y", time.localtime()).lower()
        font_size = 13.0 * scale

        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ctx.move_to(0, font_size)
        ctx.show_text(subtext)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        # Resample or clamp to 32 bars for the low-profile profile
        target_bars = 32
        if len(audio_bars) != target_bars:
            indices = np.linspace(0, len(audio_bars) - 1, target_bars).astype(int)
            bars = audio_bars[indices]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 3.0 * scale
        total_w = target_bars * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        for i in range(target_bars):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 3. Sonder Axis
# ===========================================================================

class SonderAxisTheme(BaseTheme):
    """
    **Sonder Axis**

    Editorial layout structured along a clean vertical accent axis:
    * Central vertical axis line in ``date_color`` (0.4 alpha).
    * Dynamic greeting: 'GOOD MORNING' / 'GOOD AFTERNOON' / 'GOOD EVENING'.
    * Bold 3-letter day abbreviation.
    * Symmetrical dual-direction horizontal bars extending outward from axis.
    """

    name: str = "Sonder Axis"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        cx = 120.0 * scale

        # 1. Central accent vertical stroke
        ctx.set_line_width(1.5 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.40)
        ctx.move_to(cx, 0)
        ctx.line_to(cx, 90.0 * scale)
        ctx.stroke()

        # 2. Dynamic greeting based on hour
        hr = time_data.hour
        greeting = (
            "GOOD MORNING" if hr < 12
            else "GOOD AFTERNOON" if hr < 18
            else "GOOD EVENING"
        )
        greet_sz = 11.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(greet_sz)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        ctx.move_to(cx + (14.0 * scale), 20.0 * scale)
        ctx.show_text(greeting)

        # 3. Bold compact 3-letter day (e.g. "WED")
        day_3 = time_data.day_str[:3].upper()
        day_sz = 44.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(day_sz)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ext = ctx.text_extents(day_3)
        # Position day to the left of the axis
        ctx.move_to(cx - ext.width - (14.0 * scale), 60.0 * scale)
        ctx.show_text(day_3)

        # 4. Digital time to the right of the axis
        time_sz = 20.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(time_sz)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ctx.move_to(cx + (14.0 * scale), 56.0 * scale)
        ctx.show_text(time_data.time_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        cx = 120.0 * scale
        date_text = time.strftime("%d %B %Y", time.localtime()).upper()

        date_sz = 12.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(date_sz)
        self.set_hex_color(ctx, date_color, alpha=0.80)
        ctx.move_to(cx + (14.0 * scale), 16.0 * scale)
        ctx.show_text(date_text)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        cx = 120.0 * scale
        # Symmetrical dual-direction bars extending outward from central vertical axis
        num_bars = min(16, len(audio_bars))
        bar_h = 2.0 * scale
        gap = 2.0 * scale
        max_len = 90.0 * scale

        ctx.set_line_width(bar_h)
        self.set_hex_color(ctx, vis_color, alpha=0.80)

        for i in range(num_bars):
            y = 4.0 * scale + i * (bar_h + gap)
            bar_len = float(audio_bars[i]) * max_len * amp
            if bar_len <= 1.0 * scale:
                continue

            # Draw left arm
            ctx.move_to(cx - (4.0 * scale), y)
            ctx.line_to(cx - (4.0 * scale) - bar_len, y)
            ctx.stroke()

            # Draw right arm
            ctx.move_to(cx + (4.0 * scale), y)
            ctx.line_to(cx + (4.0 * scale) + bar_len, y)
            ctx.stroke()


# ===========================================================================
# 4. Wild Youth
# ===========================================================================

class WildYouthTheme(BaseTheme):
    """
    **Wild Youth**

    Bold expressive aesthetic:
    * Numerals: Bold italicized brush/cursive font ('HH:MM') with soft 2px drop-shadow.
    * Date: Uppercase clean subtext with pipe separator.
    * Visualizer: Gradient-filled spectrum bars fading into a soft base.
    """

    name: str = "Wild Youth"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        # Expressive brush font selection with fallbacks
        font_family = "Serif"
        font_size = 68.0 * scale

        ctx.select_font_face(font_family, cairo.FontSlant.ITALIC, cairo.FontWeight.BOLD)
        ctx.set_font_size(font_size)

        # 2px offset drop shadow (0.25 alpha black)
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.25)
        ctx.move_to(2.0 * scale, font_size + (2.0 * scale))
        ctx.show_text(time_data.time_str)

        # Foreground
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(0, font_size)
        ctx.show_text(time_data.time_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        # e.g. "WEDNESDAY | OCTOBER 21"
        subtext = f"{time_data.day_str.upper()} | {time.strftime('%B %d', time.localtime()).upper()}"
        font_size = 12.0 * scale

        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)
        self.set_hex_color(ctx, date_color, alpha=0.90)
        ctx.move_to(0, font_size)
        ctx.show_text(subtext)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")
        r, g, b = _hex_to_rgb(vis_color)

        total_bars = len(audio_bars)
        bar_w = 4.0 * scale
        gap = 3.0 * scale
        total_w = total_bars * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (2.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)

        for i in range(total_bars):
            h = float(audio_bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)

            # Gradient-filled bar: full opacity at top, 0.20 at base
            grad = cairo.LinearGradient(x, base_y - h, x, base_y)
            grad.add_color_stop_rgba(0.0, r, g, b, 1.0)
            grad.add_color_stop_rgba(1.0, r, g, b, 0.20)
            ctx.set_source(grad)

            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 5. Chrono Block
# ===========================================================================

class ChronoBlockTheme(BaseTheme):
    """
    **Chrono Block**

    Heavy industrial cyberpunk digital block clock:
    * Heavy rectangular monospace digits (font size 60 * scale).
    * Colon drawn as two solid square blocks.
    * Uppercase monospace subtext: 'DAY | DD MONTH YYYY'.
    * Stepped LED block matrix bars (discrete vertical rectangles with 1.5px gaps).
    """

    name: str = "Chrono Block"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        font_size = 60.0 * scale
        ctx.select_font_face("Monospace", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(font_size)

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        # 1. Hours block
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(0, font_size)
        ctx.show_text(hr_str)
        ext_hr = ctx.text_extents(hr_str)

        # 2. Solid square block colon
        colon_x = ext_hr.x_advance + (10.0 * scale)
        sq_size = 7.0 * scale
        self.set_hex_color(ctx, clock_color, alpha=0.90)
        # Upper square
        ctx.rectangle(colon_x, font_size - (34.0 * scale), sq_size, sq_size)
        # Lower square
        ctx.rectangle(colon_x, font_size - (16.0 * scale), sq_size, sq_size)
        ctx.fill()

        # 3. Minutes block
        min_x = colon_x + sq_size + (10.0 * scale)
        ctx.move_to(min_x, font_size)
        ctx.show_text(min_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")

        # Uppercase monospace: e.g. "WEDNESDAY | 21 OCTOBER 2026"
        month_name = time.strftime("%B", time.localtime()).upper()
        subtext = f"{time_data.day_str.upper()} | {time_data.day:02d} {month_name} {time_data.year}"

        font_size = 12.0 * scale
        ctx.select_font_face("Monospace", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(font_size)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        ctx.move_to(0, font_size)
        ctx.show_text(subtext)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        total_bars = len(audio_bars)
        bar_w = 6.0 * scale
        bar_gap = 3.0 * scale
        block_h = 3.0 * scale
        block_gap = 1.5 * scale

        total_w = total_bars * (bar_w + bar_gap) - bar_gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (2.0 * scale)

        self.set_hex_color(ctx, vis_color, alpha=0.90)

        for i in range(total_bars):
            h = float(audio_bars[i]) * (height - 4.0 * scale) * amp
            if h < block_h:
                continue

            num_blocks = int(h / (block_h + block_gap))
            x = start_x + i * (bar_w + bar_gap)

            for b_idx in range(num_blocks):
                by = base_y - (b_idx + 1) * (block_h + block_gap)
                ctx.rectangle(x, by, bar_w, block_h)
            ctx.fill()


# ===========================================================================
# 6. Vertical Overlap
# ===========================================================================

class VerticalOverlapTheme(BaseTheme):
    """
    **Vertical Overlap**

    Two-tier stacked numbers with bold architectural layering:
    * Faint watermark 3-letter day ('WED') in 0.12 opacity behind numbers.
    * Hours stacked above Minutes (size 64 * scale) with tight baseline overlap.
    * Right-aligned micro date ('5th OCT, 2026').
    * Compact 20-bar visualizer aligned cleanly to the right edge.
    """

    name: str = "Vertical Overlap"

    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        opacity = float(cfg.get("background_opacity", 0.0) or 0.0)
        if opacity > 0.001:
            ctx.set_source_rgba(0.0, 0.0, 0.0, opacity)
            ctx.paint()

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")
        font_family = cfg.get("font_family", "Sans")

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        # 1. Background Watermark: Giant faint 3-letter day
        watermark_text = time_data.day_str[:3].upper()
        wm_size = 90.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(wm_size)
        self.set_hex_color(ctx, clock_color, alpha=0.12)
        ctx.move_to(0, 78.0 * scale)
        ctx.show_text(watermark_text)

        # 2. Hour on top (size 64 * scale, 0.85 opacity)
        num_size = 64.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(num_size)
        self.set_hex_color(ctx, clock_color, alpha=0.85)
        ctx.move_to(6.0 * scale, 52.0 * scale)
        ctx.show_text(hr_str)

        # 3. Minute on bottom overlapping baseline of hours (size 64 * scale, 1.0 opacity)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(6.0 * scale, 102.0 * scale)
        ctx.show_text(min_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = float(cfg.get("scale", 1.0) or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")
        font_family = cfg.get("font_family", "Sans")

        # Right-aligned micro date: e.g. "21st OCT, 2026"
        month_abbr = time.strftime("%b", time.localtime()).upper()
        suffix = _ordinal_suffix(time_data.day)
        date_text = f"{time_data.day}{suffix} {month_abbr}, {time_data.year}"

        font_size = 12.0 * scale
        ctx.select_font_face(font_family, cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ctx.move_to(0, font_size)
        ctx.show_text(date_text)

    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: np.ndarray,
    ) -> None:
        if audio_bars is None or len(audio_bars) == 0:
            return

        scale = float(cfg.get("scale", 1.0) or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        # Compact 20-bar visualizer aligned cleanly to the right edge
        target_bars = 20
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 2.5 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = float(width) - total_w - (4.0 * scale)
        base_y = float(height) - (2.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()
