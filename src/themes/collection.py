"""
src.themes.collection
=====================
Master collection of 6 iconic community Rainmeter themes with true typography.

Themes included:
1. Mond Minimal       — Tracked Comfortaa day, dashed time subtext, Montserrat date, baseline bars
2. Elegance Two-Tone  — Ultra-tall hairline Bebas Neue digits (hours/min decoupled), lowercase subtext
3. Sonder Axis        — Central vertical accent stroke, greeting, dual-direction bars
4. Wild Youth         — Expressive Caveat Bold handwriting with soft drop shadow & gradient bars
5. Chrono Block       — Heavy condensed Bebas Neue digits, square block colon, LED matrix visualizer
6. Vertical Overlap   — Giant Anton numbers stacked with slight overlap, faint watermark day
"""

from __future__ import annotations

import math
import time
from typing import Any, Optional

import cairo
import numpy as np

from src.themes.base import BaseTheme, TimeData
from src.core.fonts import register_bundled_fonts

# Ensure bundled fonts in assets/fonts/ are available to Cairo / Fontconfig
register_bundled_fonts()

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
    **Mond Minimal** (Option A)

    Iconic aesthetic inspired by the widely loved 'Mond' Rainmeter skin:
    * Date Component:
      - Line 1 (Day): All-caps weekday (e.g. "W E D N E S D A Y") using font family "Anurati"
        (fallback: "Montserrat Bold"), size ~ 38 * scale, explicit tracking (~8px * scale),
        centered at w / 2.
      - Line 2 (Date): Uppercase date formatted as "DD MONTH, YYYY." (e.g. "21 OCTOBER, 2026.")
        in font family "Montserrat" (bold), size ~ 13 * scale, letter-spacing 1.5px,
        centered at w / 2 with Y-offset ~ +36 * scale below Line 1.
    * Clock Component:
      - Dashed Time: Formatted as "- HH:MM -" (e.g. "- 03:04 -") in font family "Montserrat",
        font size ~ 15 * scale, strictly centered horizontally at w / 2.
    * Visualizer Component:
      - Minimalist thin baseline bars (width 2.5 * scale, gap 3 * scale) centered horizontally at w / 2.
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

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        # Scale calculation respecting independent component scales
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.date_scale', cfg.get('date_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        date_color = cfg.get("date_color", "#FFFFFF")

        # Line 1 (Day): All-caps weekday in "Anurati" (fallback: "Montserrat Bold"), size ~ 38 * scale
        day_str = time_data.day_str.upper()
        day_sz = 38.0 * scale
        tracking = 8.0 * scale
        line1_y = 38.0 * scale

        try:
            ctx.select_font_face("Anurati", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        except Exception:
            ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(day_sz)
        self.set_hex_color(ctx, date_color, alpha=1.0)

        char_extents = [ctx.text_extents(ch) for ch in day_str]
        total_day_w = sum(ext.x_advance for ext in char_extents) + tracking * (len(day_str) - 1)
        curr_x = (float(width) / 2.0) - (total_day_w / 2.0)
        for ch, ext in zip(day_str, char_extents):
            ctx.move_to(curr_x, line1_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + tracking

        # Line 2 (Date): Uppercase date formatted as "DD MONTH, YYYY." in "Montserrat" (bold), size ~ 13 * scale, letter-spacing 1.5px
        month_name = time.strftime("%B", time.localtime()).upper()
        date_str = f"{time_data.day:02d} {month_name}, {time_data.year}."
        date_sz = 13.0 * scale
        date_tracking = 1.5 * scale
        line2_y = line1_y + (36.0 * scale)

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(date_sz)
        self.set_hex_color(ctx, date_color, alpha=0.92)

        date_extents = [ctx.text_extents(ch) for ch in date_str]
        total_date_w = sum(ext.x_advance for ext in date_extents) + date_tracking * (len(date_str) - 1)
        curr_date_x = (float(width) / 2.0) - (total_date_w / 2.0)
        for ch, ext in zip(date_str, date_extents):
            ctx.move_to(curr_date_x, line2_y)
            ctx.show_text(ch)
            curr_date_x += ext.x_advance + date_tracking

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        # Scale calculation respecting independent component scales
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.clock_scale', cfg.get('clock_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        # Dashed Time: "- HH:MM -" in "Montserrat", size ~ 15 * scale
        dashed_time = f"- {time_data.time_str} -"
        time_sz = 15.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(time_sz)
        self.set_hex_color(ctx, clock_color, alpha=0.95)

        ext = ctx.text_extents(dashed_time)
        tx = (float(width) / 2.0) - (ext.width / 2.0) - ext.x_bearing
        ty = 20.0 * scale
        ctx.move_to(tx, ty)
        ctx.show_text(dashed_time)

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

        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.visualizer_scale', cfg.get('visualizer_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        total_bars = len(audio_bars)
        bar_w = 2.5 * scale
        gap = 3.0 * scale
        total_w = total_bars * (bar_w + gap) - gap
        start_x = (float(width) / 2.0) - (total_w / 2.0)
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
    * Time: Ultra-tall, hairline Bebas Neue or Montserrat Light digits. Hours in clock_color, Minutes in visualizer_color.
    * Date: Lowercase clean subtext with pipe separator 'day | month dd, yyyy'.
    * Visualizer: Low-profile 32-bar visualizer with rounded line caps.
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

        font_size = 78.0 * scale
        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        # 1. Hours in clock_color
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(0, font_size)
        ctx.show_text(hr_str)
        ext_hr = ctx.text_extents(hr_str)

        # 2. Colon in clock_color with soft transparency
        colon_x = ext_hr.x_advance + (5.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.50)
        ctx.move_to(colon_x, font_size)
        ctx.show_text(":")
        ext_colon = ctx.text_extents(":")

        # 3. Minutes in visualizer_color
        min_x = colon_x + ext_colon.x_advance + (5.0 * scale)
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

        # Lowercase clean subtext with pipe separator: 'day | month dd, yyyy' in Montserrat
        subtext = time.strftime("%A | %B %d, %Y", time.localtime()).lower()
        font_size = 13.0 * scale

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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
    * Central vertical axis line in date_color (0.4 alpha).
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

        cx = 120.0 * scale

        # 1. Central accent vertical stroke
        ctx.set_line_width(1.5 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.40)
        ctx.move_to(cx, 0)
        ctx.line_to(cx, 90.0 * scale)
        ctx.stroke()

        # 2. Dynamic greeting based on hour in Montserrat Bold
        hr = time_data.hour
        greeting = (
            "GOOD MORNING" if hr < 12
            else "GOOD AFTERNOON" if hr < 18
            else "GOOD EVENING"
        )
        greet_sz = 11.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(greet_sz)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        ctx.move_to(cx + (14.0 * scale), 20.0 * scale)
        ctx.show_text(greeting)

        # 3. Bold compact 3-letter day (e.g. "WED") in Montserrat Bold
        day_3 = time_data.day_str[:3].upper()
        day_sz = 44.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(day_sz)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ext = ctx.text_extents(day_3)
        # Position day to the left of the axis
        ctx.move_to(cx - ext.width - (14.0 * scale), 60.0 * scale)
        ctx.show_text(day_3)

        # 4. Digital time to the right of the axis in Montserrat
        time_sz = 20.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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

        cx = 120.0 * scale
        date_text = time.strftime("%d %B %Y", time.localtime()).upper()

        date_sz = 12.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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

            ctx.move_to(cx - (4.0 * scale), y)
            ctx.line_to(cx - (4.0 * scale) - bar_len, y)
            ctx.stroke()

            ctx.move_to(cx + (4.0 * scale), y)
            ctx.line_to(cx + (4.0 * scale) + bar_len, y)
            ctx.stroke()


# ===========================================================================
# 4. Wild Youth
# ===========================================================================

class WildYouthTheme(BaseTheme):
    """
    **Wild Youth**

    Authentic handwriting brush aesthetic:
    * Time: Dynamic brush handwriting using Caveat Bold with a soft blurred drop shadow.
    * Subtext: Uppercase sans date with pipe divider ('WEDNESDAY | OCTOBER 21').
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

        font_size = 78.0 * scale
        ctx.select_font_face("Caveat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(font_size)

        # Multi-pass soft blurred drop shadow
        for ox, oy, alpha in [
            (0, 3.0 * scale, 0.30),
            (1.0 * scale, 2.0 * scale, 0.20),
            (-1.0 * scale, 2.0 * scale, 0.20),
            (0, 4.0 * scale, 0.15),
            (2.0 * scale, 3.0 * scale, 0.12),
            (-2.0 * scale, 3.0 * scale, 0.12),
        ]:
            ctx.set_source_rgba(0.0, 0.0, 0.0, alpha)
            ctx.move_to(ox, font_size + oy)
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

        # Uppercase sans date with pipe divider: e.g. "WEDNESDAY | OCTOBER 21" in Montserrat
        subtext = f"{time_data.day_str.upper()} | {time.strftime('%B %d', time.localtime()).upper()}"
        font_size = 12.0 * scale

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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

    Heavy industrial digital block clock:
    * Time: Heavy condensed Bebas Neue glyphs with solid square colon blocks.
    * Date: Uppercase subtext 'DAY | DD MONTH YYYY'.
    * Visualizer: True segmented LED matrix blocks.
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

        font_size = 68.0 * scale
        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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
        colon_x = ext_hr.x_advance + (8.0 * scale)
        sq_size = 7.0 * scale
        self.set_hex_color(ctx, clock_color, alpha=0.90)
        # Upper square
        ctx.rectangle(colon_x, font_size - (36.0 * scale), sq_size, sq_size)
        # Lower square
        ctx.rectangle(colon_x, font_size - (18.0 * scale), sq_size, sq_size)
        ctx.fill()

        # 3. Minutes block
        min_x = colon_x + sq_size + (8.0 * scale)
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

        # Uppercase subtext: e.g. "WEDNESDAY | 21 OCTOBER 2026"
        month_name = time.strftime("%B", time.localtime()).upper()
        subtext = f"{time_data.day_str.upper()} | {time_data.day:02d} {month_name} {time_data.year}"

        font_size = 13.0 * scale
        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
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
    **Vertical Overlap** (StarLender aesthetic)

    Two-tier stacked numbers with bold architectural layering:
    * Time: Giant Anton numbers tightly stacked vertically (Hours directly over Minutes with slight overlap).
    * Background Watermark: Giant faint day abbreviation behind the numbers.
    * Subtext: Clean micro sans date with crisp right alignment ('21st OCT, 2026').
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
        date_color = cfg.get("date_color", "#D0D0D0")

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        # 1. Background Watermark: Giant day abbreviation in Anton using date_color (opacity 0.32)
        watermark_text = time_data.day_str[:3].upper()
        wm_size = 96.0 * scale
        ctx.select_font_face("Anton", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(wm_size)
        self.set_hex_color(ctx, date_color, alpha=0.32)
        ctx.move_to(0, 82.0 * scale)
        ctx.show_text(watermark_text)

        # 2. Hour on top in Anton (size 68 * scale, 0.85 opacity)
        num_size = 68.0 * scale
        ctx.select_font_face("Anton", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(num_size)
        self.set_hex_color(ctx, clock_color, alpha=0.85)
        ctx.move_to(6.0 * scale, 54.0 * scale)
        ctx.show_text(hr_str)

        # 3. Minute on bottom overlapping baseline of hours (size 68 * scale, 1.0 opacity)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(6.0 * scale, 104.0 * scale)
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

        # Clean micro sans date with crisp right alignment: e.g. "21st OCT, 2026" in Montserrat
        month_abbr = time.strftime("%b", time.localtime()).upper()
        suffix = _ordinal_suffix(time_data.day)
        date_text = f"{time_data.day}{suffix} {month_abbr}, {time_data.year}"

        font_size = 12.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_size)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(date_text)
        # Align crisp right relative to standard component width 430 * scale
        right_x = max(0.0, (430.0 * scale) - ext.width - (8.0 * scale))
        ctx.move_to(right_x, font_size)
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
