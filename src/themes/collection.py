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


_NUM_WORDS = {
    0: "ZERO", 1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR",
    5: "FIVE", 6: "SIX", 7: "SEVEN", 8: "EIGHT", 9: "NINE",
    10: "TEN", 11: "ELEVEN", 12: "TWELVE", 13: "THIRTEEN",
    14: "FOURTEEN", 15: "FIFTEEN", 16: "SIXTEEN", 17: "SEVENTEEN",
    18: "EIGHTEEN", 19: "NINETEEN", 20: "TWENTY", 30: "THIRTY",
    40: "FORTY", 50: "FIFTY",
}


def _number_to_words(n: int) -> str:
    """Convert an integer 0..59 to English capital words."""
    if n in _NUM_WORDS:
        return _NUM_WORDS[n]
    tens = (n // 10) * 10
    ones = n % 10
    if tens in _NUM_WORDS and ones in _NUM_WORDS:
        return f"{_NUM_WORDS[tens]} {_NUM_WORDS[ones]}"
    return str(n)


def _draw_rounded_rect(ctx: cairo.Context, x: float, y: float, w: float, h: float, r: float) -> None:
    """Path a rounded rectangle into ctx."""
    r = max(0.0, min(r, w / 2.0, h / 2.0))
    ctx.new_sub_path()
    ctx.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    ctx.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    ctx.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    ctx.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    ctx.close_path()


def _show_tracked_text(ctx: cairo.Context, text: str, cx: float, y: float, tracking: float) -> None:
    """Draw text centered at cx with explicit tracking (letter spacing) in pixels."""
    if not text:
        return
    total_w = 0.0
    advances = []
    for ch in text:
        ext = ctx.text_extents(ch)
        advances.append(ext.x_advance)
        total_w += ext.x_advance
    total_w += (len(text) - 1) * tracking
    cur_x = cx - total_w / 2.0
    for i, ch in enumerate(text):
        ctx.move_to(cur_x, y)
        ctx.show_text(ch)
        cur_x += advances[i] + tracking



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

    Centered vertical spine layout inspired by clean editorial design:
    * Date Component:
      - Vertical Axis Line: 1.5px vertical stroke along x = cx (from Y=0 to Y=h) with 0.35 alpha.
      - Line 1 & Line 2 (Greeting): Stacked micro greeting centered at cx:
        "GOOD" (size 10 * scale, tracking 3px * scale), followed by "MORNING" / "AFTERNOON" / "EVENING" (Y-offset +14 * scale).
      - Line 3 (Day): 3-letter uppercase day in font family "Shojumaru" (fallback: "Montserrat Bold"),
        font size ~ 40 * scale, centered at cx (Y-offset +50 * scale), rendered in clock_color.
      - Line 4 (Date): Micro uppercase date "DD MONTH" (e.g. "21 OCTOBER") in font family "Montserrat" Bold,
        font size ~ 11 * scale, tracking ~ 2px * scale, centered at cx (Y-offset +78 * scale), rendered in date_color.
    * Clock Component:
      - Micro Time: Formatted as "HH:MM PM" in font family "Montserrat", font size ~ 12 * scale, tracking 1.5px * scale,
        strictly centered horizontally at w / 2.0.
    * Visualizer Component:
      - Symmetrical dual-direction horizontal bars extending left and right from w / 2.0.
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

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        # Scale resolution
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.date_scale', cfg.get('date_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        date_color = cfg.get("date_color", "#FFFFFF")
        clock_color = cfg.get("clock_color", "#FFFFFF")

        cx = float(width) / 2.0

        # 1. Vertical Line: 1.5px vertical stroke along x = cx (from Y=0 to Y=h)
        ctx.set_line_width(1.5 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.35)
        ctx.move_to(cx, 0.0)
        ctx.line_to(cx, float(height))
        ctx.stroke()

        line1_y = 12.0 * scale

        # 2. Line 1 (Greeting 1): "GOOD" in Montserrat Bold (size 10 * scale, tracking 3px * scale)
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(10.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.90)

        g1_text = "GOOD"
        g1_track = 3.0 * scale
        g1_exts = [ctx.text_extents(ch) for ch in g1_text]
        g1_total_w = sum(ext.x_advance for ext in g1_exts) + g1_track * (len(g1_text) - 1)
        curr_x = cx - (g1_total_w / 2.0)
        for ch, ext in zip(g1_text, g1_exts):
            ctx.move_to(curr_x, line1_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + g1_track

        # 3. Line 2 (Greeting 2): Contextual "MORNING" / "AFTERNOON" / "EVENING" (Y-offset +14 * scale)
        hr = time_data.hour
        context = (
            "MORNING" if hr < 12
            else "AFTERNOON" if hr < 18
            else "EVENING"
        )
        line2_y = line1_y + (14.0 * scale)
        g2_exts = [ctx.text_extents(ch) for ch in context]
        g2_total_w = sum(ext.x_advance for ext in g2_exts) + g1_track * (len(context) - 1)
        curr_x = cx - (g2_total_w / 2.0)
        for ch, ext in zip(context, g2_exts):
            ctx.move_to(curr_x, line2_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + g1_track

        # 4. Line 3 (Day): 3-letter uppercase day in "Shojumaru" (fallback: "Montserrat Bold"), size ~ 40 * scale (Y-offset +50 * scale)
        day_3 = time_data.day_str[:3].upper()
        day_sz = 40.0 * scale
        line3_y = line1_y + (50.0 * scale)
        try:
            ctx.select_font_face("Shojumaru", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        except Exception:
            ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(day_sz)
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ext_day = ctx.text_extents(day_3)
        day_x = cx - (ext_day.width / 2.0) - ext_day.x_bearing
        ctx.move_to(day_x, line3_y)
        ctx.show_text(day_3)

        # 5. Line 4 (Date): Micro uppercase date "DD MONTH" in Montserrat Bold (size 11 * scale, tracking 2px * scale, Y-offset +78 * scale)
        month_name = time.strftime("%B", time.localtime()).upper()
        date_text = f"{time_data.day:02d} {month_name}"
        date_sz = 11.0 * scale
        date_track = 2.0 * scale
        line4_y = line1_y + (78.0 * scale)

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(date_sz)
        self.set_hex_color(ctx, date_color, alpha=0.90)

        d_exts = [ctx.text_extents(ch) for ch in date_text]
        d_total_w = sum(ext.x_advance for ext in d_exts) + date_track * (len(date_text) - 1)
        curr_x = cx - (d_total_w / 2.0)
        for ch, ext in zip(date_text, d_exts):
            ctx.move_to(curr_x, line4_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + date_track

    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        # Scale resolution
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.clock_scale', cfg.get('clock_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        cx = float(width) / 2.0

        if time_data.is_24h:
            time_str = f"{time_data.hour:02d}:{time_data.minute:02d}"
        else:
            hr_12 = time_data.hour % 12
            if hr_12 == 0:
                hr_12 = 12
            ampm = "AM" if time_data.hour < 12 else "PM"
            time_str = f"{hr_12:02d}:{time_data.minute:02d} {ampm}"

        time_sz = 12.0 * scale
        time_track = 1.5 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(time_sz)
        self.set_hex_color(ctx, clock_color, alpha=0.95)

        t_exts = [ctx.text_extents(ch) for ch in time_str]
        t_total_w = sum(ext.x_advance for ext in t_exts) + time_track * (len(time_str) - 1)
        curr_x = cx - (t_total_w / 2.0)
        ty = 18.0 * scale
        for ch, ext in zip(time_str, t_exts):
            ctx.move_to(curr_x, ty)
            ctx.show_text(ch)
            curr_x += ext.x_advance + time_track

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

        cx = float(width) / 2.0
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

            # Left bar extending outward from center spine
            ctx.move_to(cx - (4.0 * scale), y)
            ctx.line_to(cx - (4.0 * scale) - bar_len, y)
            ctx.stroke()

            # Right bar extending outward from center spine
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
    * Clock Component: Time 'HH:MM' in font family 'Wild Youth' (fallback 'Caveat Bold'),
      size ~ 84 * clock_scale, centered at w / 2.0, in clock_color.
    * Date Component: Uppercase 'WEEKDAY | MONTH DD' in 'Montserrat' Bold, size ~ 12 * date_scale,
      tracking ~ 2.5px, centered at w / 2.0, in date_color. Second line for year/micro-subtext ~ 10 * date_scale.
    * Visualizer Component: 32-bar baseline visualizer centered at w / 2.0, in visualizer_color.
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
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.clock_scale', cfg.get('clock_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        time_str = time_data.time_str
        font_sz = 84.0 * scale
        try:
            ctx.select_font_face("Wild Youth", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        except Exception:
            ctx.select_font_face("Caveat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(font_sz)

        ext = ctx.text_extents(time_str)
        tx = (float(width) / 2.0) - (ext.width / 2.0) - ext.x_bearing
        ty = 70.0 * scale

        # Soft drop shadow for authentic depth
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.25)
        ctx.move_to(tx + (2.0 * scale), ty + (2.0 * scale))
        ctx.show_text(time_str)

        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(tx, ty)
        ctx.show_text(time_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.date_scale', cfg.get('date_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")

        cx = float(width) / 2.0

        # Line 1: Uppercase "WEEKDAY | MONTH DD" in "Montserrat" Bold, size ~ 12 * date_scale, tracking ~ 2.5px
        month_day = time.strftime("%B %d", time.localtime()).upper()
        line1_text = f"{time_data.day_str.upper()} | {month_day}"
        l1_sz = 12.0 * scale
        l1_track = 2.5 * scale
        l1_y = 18.0 * scale

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(l1_sz)
        self.set_hex_color(ctx, date_color, alpha=0.92)

        l1_exts = [ctx.text_extents(ch) for ch in line1_text]
        l1_total_w = sum(ext.x_advance for ext in l1_exts) + l1_track * (len(line1_text) - 1)
        curr_x = cx - (l1_total_w / 2.0)
        for ch, ext in zip(line1_text, l1_exts):
            ctx.move_to(curr_x, l1_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + l1_track

        # Line 2: Year / micro-subtext ~ 10 * date_scale
        line2_text = f"— {time_data.year} —"
        l2_sz = 10.0 * scale
        l2_track = 2.0 * scale
        line2_y = l1_y + (18.0 * scale)

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(l2_sz)
        self.set_hex_color(ctx, date_color, alpha=0.75)

        l2_exts = [ctx.text_extents(ch) for ch in line2_text]
        l2_total_w = sum(ext.x_advance for ext in l2_exts) + l2_track * (len(line2_text) - 1)
        curr_x = cx - (l2_total_w / 2.0)
        for ch, ext in zip(line2_text, l2_exts):
            ctx.move_to(curr_x, line2_y)
            ctx.show_text(ch)
            curr_x += ext.x_advance + l2_track

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
        r, g, b = _hex_to_rgb(vis_color)

        target_bars = 32
        if len(audio_bars) != target_bars:
            indices = np.linspace(0, len(audio_bars) - 1, target_bars).astype(int)
            bars = audio_bars[indices]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 3.0 * scale
        total_w = target_bars * (bar_w + gap) - gap
        start_x = (float(width) / 2.0) - (total_w / 2.0)
        base_y = float(height) - (2.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)

        for i in range(target_bars):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
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
    * Clock Component: Time 'HH:MM' in font family 'SF Sports Night' (fallback 'Anton'),
      size ~ 74 * clock_scale, centered at w / 2.0, in clock_color.
    * Date Component: Subtext 'Weekday | DD Month YYYY' (or 'AM/PM | Weekday | DD Month YYYY' in 12h mode)
      in 'Montserrat' Regular, size ~ 13 * date_scale, centered at w / 2.0, in date_color.
    * Visualizer Component: Stepped LED block-matrix bars centered at w / 2.0, in visualizer_color.
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
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.clock_scale', cfg.get('clock_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        clock_color = cfg.get("clock_color", "#FFFFFF")

        time_str = time_data.time_str
        font_sz = 74.0 * scale
        try:
            ctx.select_font_face("SF Sports Night", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        except Exception:
            ctx.select_font_face("Anton", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(font_sz)
        self.set_hex_color(ctx, clock_color, alpha=1.0)

        ext = ctx.text_extents(time_str)
        tx = (float(width) / 2.0) - (ext.width / 2.0) - ext.x_bearing
        ty = 68.0 * scale
        ctx.move_to(tx, ty)
        ctx.show_text(time_str)

    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.date_scale', cfg.get('date_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        date_color = cfg.get("date_color", "#D0D0D0")

        cx = float(width) / 2.0
        month_name = time.strftime("%B", time.localtime())
        weekday_name = time_data.day_str.capitalize()
        if time_data.is_24h:
            subtext = f"{weekday_name} | {time_data.day:02d} {month_name} {time_data.year}"
        else:
            ampm = "AM" if time_data.hour < 12 else "PM"
            subtext = f"{ampm} | {weekday_name} | {time_data.day:02d} {month_name} {time_data.year}"

        date_sz = 13.0 * scale
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(date_sz)
        self.set_hex_color(ctx, date_color, alpha=0.90)

        ext = ctx.text_extents(subtext)
        dx = cx - (ext.width / 2.0) - ext.x_bearing
        dy = 22.0 * scale
        ctx.move_to(dx, dy)
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

        scale = (
            (cfg.get('canvas.scale', cfg.get('scale', 1.0)) * cfg.get('canvas.visualizer_scale', cfg.get('visualizer_scale', 1.0)))
            if (cfg.get('canvas.independent_scales') or cfg.get('independent_scales'))
            else cfg.get('canvas.scale', cfg.get('scale', 1.0))
        )
        scale = float(scale or 1.0)
        amp = float(cfg.get("visualizer_intensity", 0.65) or 0.65) / 0.65
        vis_color = cfg.get("visualizer_color", "#FFFFFF")

        total_bars = len(audio_bars)
        bar_w = 6.0 * scale
        bar_gap = 3.0 * scale
        block_h = 3.0 * scale
        block_gap = 1.5 * scale

        total_w = total_bars * (bar_w + bar_gap) - bar_gap
        start_x = (float(width) / 2.0) - (total_w / 2.0)
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


# ===========================================================================
# 7. Textime
# ===========================================================================

class TextimeTheme(ThemeBase):
    """
    **Textime**
    Phonetic word clock rendered in two stacked lines with micro uppercase date
    and minimalist 24-bar baseline visualizer.
    """

    name: str = "Textime"
    clock_base_height: float = 110.0

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
        cx = width / 2.0

        h_val = time_data.hour % 12
        if h_val == 0:
            h_val = 12
        hr_word = _number_to_words(h_val)
        min_word = "O'CLOCK" if time_data.minute == 0 else _number_to_words(time_data.minute)

        # Line 1: Hour in Montserrat Bold
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(36.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext1 = ctx.text_extents(hr_word)
        x1 = cx - ext1.width / 2.0 - ext1.x_bearing
        ctx.move_to(x1, 44.0 * scale)
        ctx.show_text(hr_word)

        # Line 2: Minute in Montserrat Light
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(36.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.85)
        ext2 = ctx.text_extents(min_word)
        x2 = cx - ext2.width / 2.0 - ext2.x_bearing
        ctx.move_to(x2, 88.0 * scale)
        ctx.show_text(min_word)

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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        date_text = f"{time_data.day_str.upper()}, {time_data.day} {month_name} {time_data.year}"

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(11.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        _show_tracked_text(ctx, date_text, cx, 30.0 * scale, tracking=3.0 * scale)

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

        target_bars = 24
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 3.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
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


# ===========================================================================
# 8. Lumiero Capsule
# ===========================================================================

class LumieroTheme(ThemeBase):
    """
    **Lumiero Capsule**
    Large clean Bebas Neue numerals with frosted rounded capsule badge date
    and symmetrical rounded-tip bars.
    """

    name: str = "Lumiero Capsule"

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
        cx = width / 2.0

        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(68.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 72.0 * scale)
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
        cx = width / 2.0

        bw = 230.0 * scale
        bh = 32.0 * scale
        bx = cx - bw / 2.0
        by = 8.0 * scale
        r = 16.0 * scale

        _draw_rounded_rect(ctx, bx, by, bw, bh, r)
        self.set_hex_color(ctx, date_color, alpha=0.20)
        ctx.fill_preserve()
        self.set_hex_color(ctx, date_color, alpha=0.35)
        ctx.set_line_width(1.0 * scale)
        ctx.stroke()

        month_abbr = time.strftime("%b", time.localtime()).upper()
        txt = f"{time_data.day_str[:3].upper()} · {time_data.day} {month_abbr} {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.95)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = by + bh / 2.0 + ext.height / 2.0
        ctx.move_to(tx, ty)
        ctx.show_text(txt)

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

        target_bars = 30
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.5 * scale
        gap = 3.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.88)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 9. FLHUD
# ===========================================================================

class FLHUDTheme(ThemeBase):
    """
    **FLHUD**
    Sci-fi brackets numerals using Orbitron with dual-column HUD subtext and flanked visualizer.
    """

    name: str = "FLHUD"

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
        cx = width / 2.0

        txt = f"[  {time_data.time_str}  ]"
        ctx.select_font_face("Orbitron", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(52.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext = ctx.text_extents(txt)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 70.0 * scale)
        ctx.show_text(txt)

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
        cx = width / 2.0

        txt = f"SYS // {time_data.day:02d}.{time_data.month:02d}.{time_data.year} // ONLINE"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(13.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 30.0 * scale)
        ctx.show_text(txt)

        # Subtle neon HUD rule
        self.set_hex_color(ctx, date_color, alpha=0.35)
        ctx.set_line_width(1.0 * scale)
        ctx.move_to(cx - 130.0 * scale, 42.0 * scale)
        ctx.line_to(cx + 130.0 * scale, 42.0 * scale)
        ctx.stroke()

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
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 2.5 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (4.0 * scale)

        # Flanking brackets
        self.set_hex_color(ctx, vis_color, alpha=0.60)
        ctx.set_line_width(1.5 * scale)
        max_h = 32.0 * scale
        # Left bracket [
        lb_x = start_x - 8.0 * scale
        ctx.move_to(lb_x + 5.0 * scale, base_y - max_h)
        ctx.line_to(lb_x, base_y - max_h)
        ctx.line_to(lb_x, base_y)
        ctx.line_to(lb_x + 5.0 * scale, base_y)
        ctx.stroke()
        # Right bracket ]
        rb_x = start_x + total_w + 8.0 * scale
        ctx.move_to(rb_x - 5.0 * scale, base_y - max_h)
        ctx.line_to(rb_x, base_y - max_h)
        ctx.line_to(rb_x, base_y)
        ctx.line_to(rb_x - 5.0 * scale, base_y)
        ctx.stroke()

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.88)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 8.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 10. Lines 2.0
# ===========================================================================

class LinesTwoTheme(ThemeBase):
    """
    **Lines 2.0**
    Clean Montserrat numerals with horizontal baseline accent lines extending across w.
    """

    name: str = "Lines 2.0"

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
        cx = width / 2.0

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(64.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = 70.0 * scale
        ctx.move_to(tx, ty)
        ctx.show_text(time_data.time_str)

        # Twin horizontal baseline accent lines
        self.set_hex_color(ctx, clock_color, alpha=0.45)
        ctx.set_line_width(1.5 * scale)
        # Left line
        ctx.move_to(15.0 * scale, ty)
        ctx.line_to(max(15.0 * scale, tx - 14.0 * scale), ty)
        ctx.stroke()
        # Right line
        rx_start = tx + ext.width + 14.0 * scale
        ctx.move_to(rx_start, ty)
        ctx.line_to(width - 15.0 * scale, ty)
        ctx.stroke()

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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day_str.upper()}   {time_data.day}   {month_name}   {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        _show_tracked_text(ctx, txt, cx, 30.0 * scale, tracking=2.5 * scale)

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

        target_bars = 48
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 2.0 * scale
        gap = 2.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (2.0 * scale)

        # Bottom rule
        self.set_hex_color(ctx, vis_color, alpha=0.35)
        ctx.set_line_width(1.0 * scale)
        ctx.move_to(start_x, base_y)
        ctx.line_to(start_x + total_w, base_y)
        ctx.stroke()

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.88)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 1.5 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 11. Enigma Classic
# ===========================================================================

class EnigmaTheme(ThemeBase):
    """
    **Enigma Classic**
    Classic Rainmeter Enigma HUD layout using Share Tech Mono with headers and precision spectrum.
    """

    name: str = "Enigma Classic"

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
        cx = width / 2.0

        # Header
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(10.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.60)
        _show_tracked_text(ctx, "LOCAL TIME", cx, 22.0 * scale, tracking=3.0 * scale)

        # Numerals
        ctx.set_font_size(48.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext = ctx.text_extents(time_data.time_str)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 70.0 * scale)
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
        cx = width / 2.0

        txt = f"{time_data.day_str[:3].upper()}  .  {time_data.day:02d}  .  {time_data.month:02d}  .  {time_data.year}"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(13.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 30.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 40
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 3.0 * scale
        gap = 2.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
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


# ===========================================================================
# 12. Pixel Arcade
# ===========================================================================

class PixelArcadeTheme(ThemeBase):
    """
    **Pixel Arcade**
    Authentic 8-bit retro gaming typography using Press Start 2P with stepped LED block visualizer.
    """

    name: str = "Pixel Arcade"

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
        cx = width / 2.0

        ctx.select_font_face("Press Start 2P", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(40.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.98)
        ext = ctx.text_extents(time_data.time_str)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 66.0 * scale)
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
        cx = width / 2.0

        txt = f"{time_data.day:02d}/{time_data.month:02d}/{time_data.year}"
        ctx.select_font_face("Press Start 2P", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.90)
        ext = ctx.text_extents(txt)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 32.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 24
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        block_w = 5.0 * scale
        block_h = 3.5 * scale
        gap_x = 3.0 * scale
        gap_y = 2.0 * scale
        max_blocks = max(1, int((height - 6.0 * scale) / (block_h + gap_y)))

        total_w = len(bars) * (block_w + gap_x) - gap_x
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        self.set_hex_color(ctx, vis_color, alpha=0.90)

        for i in range(len(bars)):
            active_blocks = int(float(bars[i]) * max_blocks * amp)
            active_blocks = max(0, min(max_blocks, active_blocks))
            col_x = start_x + i * (block_w + gap_x)
            for b in range(active_blocks):
                by = base_y - (b + 1) * (block_h + gap_y)
                ctx.rectangle(col_x, by, block_w, block_h)
                ctx.fill()


# ===========================================================================
# 13. Dot Matrix LED
# ===========================================================================

class DotMatrixTheme(ThemeBase):
    """
    **Dot Matrix LED**
    Digital vacuum fluorescent / LED tube style using VT323 with fading dot matrix columns.
    """

    name: str = "Dot Matrix LED"

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
        cx = width / 2.0

        ctx.select_font_face("VT323", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(78.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 74.0 * scale)
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
        cx = width / 2.0

        txt = f"[ {time_data.year}-{time_data.month:02d}-{time_data.day:02d} {time_data.day_str[:3].upper()} ]"
        ctx.select_font_face("VT323", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(20.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.90)
        ext = ctx.text_extents(txt)
        x = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(x, 32.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 28
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        dot_r = 1.8 * scale
        gap_x = 3.5 * scale
        step_y = 4.5 * scale
        max_dots = max(1, int((height - 6.0 * scale) / step_y))

        col_w = dot_r * 2.0
        total_w = len(bars) * (col_w + gap_x) - gap_x
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        for i in range(len(bars)):
            active_dots = int(float(bars[i]) * max_dots * amp)
            active_dots = max(0, min(max_dots, active_dots))
            dot_cx = start_x + i * (col_w + gap_x) + dot_r
            for d in range(active_dots):
                cy = base_y - (d + 1) * step_y + dot_r
                ratio = (d + 1) / max(1, active_dots)
                alpha = 0.35 + 0.65 * ratio
                self.set_hex_color(ctx, vis_color, alpha=alpha)
                ctx.arc(dot_cx, cy, dot_r, 0, 2 * math.pi)
                ctx.fill()


# ===========================================================================
# 14. Liquid Glass
# ===========================================================================

class LiquidGlassTheme(ThemeBase):
    """
    **Liquid Glass**
    Frosted glass rounded cards with specular highlights and rounded pill bars.
    """

    name: str = "Liquid Glass"

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
        cx = width / 2.0

        card_w = min(width - 20.0 * scale, 310.0 * scale)
        card_h = 76.0 * scale
        card_x = cx - card_w / 2.0
        card_y = 10.0 * scale
        r = 16.0 * scale

        # Glass fill
        _draw_rounded_rect(ctx, card_x, card_y, card_w, card_h, r)
        pat = cairo.LinearGradient(card_x, card_y, card_x, card_y + card_h)
        pat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.14)
        pat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.04)
        ctx.set_source(pat)
        ctx.fill_preserve()

        # Specular border
        spat = cairo.LinearGradient(card_x, card_y, card_x, card_y + card_h)
        spat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.38)
        spat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.08)
        ctx.set_source(spat)
        ctx.set_line_width(1.0 * scale)
        ctx.stroke()

        # Text
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(56.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = card_y + card_h / 2.0 + ext.height / 2.0
        ctx.move_to(tx, ty)
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
        cx = width / 2.0

        card_w = min(width - 30.0 * scale, 240.0 * scale)
        card_h = 32.0 * scale
        card_x = cx - card_w / 2.0
        card_y = 10.0 * scale
        r = 12.0 * scale

        _draw_rounded_rect(ctx, card_x, card_y, card_w, card_h, r)
        pat = cairo.LinearGradient(card_x, card_y, card_x, card_y + card_h)
        pat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.12)
        pat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.04)
        ctx.set_source(pat)
        ctx.fill_preserve()

        spat = cairo.LinearGradient(card_x, card_y, card_x, card_y + card_h)
        spat.add_color_stop_rgba(0.0, 1.0, 1.0, 1.0, 0.32)
        spat.add_color_stop_rgba(1.0, 1.0, 1.0, 1.0, 0.06)
        ctx.set_source(spat)
        ctx.set_line_width(1.0 * scale)
        ctx.stroke()

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day_str.upper()} · {time_data.day} {month_name} {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(11.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.92)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = card_y + card_h / 2.0 + ext.height / 2.0
        ctx.move_to(tx, ty)
        ctx.show_text(txt)

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

        target_bars = 28
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 5.0 * scale
        gap = 3.5 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

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


# ===========================================================================
# 15. Circular Orbit
# ===========================================================================

class CircularOrbitTheme(ThemeBase):
    """
    **Circular Orbit**
    Compact digital time inside circular dial space with radial ray visualizer.
    """

    name: str = "Circular Orbit"
    clock_base_width: float = 240.0
    clock_base_height: float = 160.0
    vis_base_width: float = 240.0
    vis_base_height: float = 180.0

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
        cx = width / 2.0
        cy = 75.0 * scale

        # Rings
        self.set_hex_color(ctx, clock_color, alpha=0.20)
        ctx.set_line_width(1.2 * scale)
        ctx.arc(cx, cy, 48.0 * scale, 0, 2 * math.pi)
        ctx.stroke()

        self.set_hex_color(ctx, clock_color, alpha=0.10)
        ctx.set_line_width(0.8 * scale)
        ctx.arc(cx, cy, 60.0 * scale, 0, 2 * math.pi)
        ctx.stroke()

        # Orbit satellite dot
        sec_angle = 2.0 * math.pi * time_data.second / 60.0 - math.pi / 2.0
        sat_r = 60.0 * scale
        sat_x = cx + sat_r * math.cos(sec_angle)
        sat_y = cy + sat_r * math.sin(sec_angle)
        self.set_hex_color(ctx, clock_color, alpha=0.90)
        ctx.arc(sat_x, sat_y, 2.5 * scale, 0, 2 * math.pi)
        ctx.fill()

        # Time
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(30.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = cy + ext.height / 2.0
        ctx.move_to(tx, ty)
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
        cx = width / 2.0

        month_abbr = time.strftime("%b", time.localtime()).upper()
        txt = f"{month_abbr} {time_data.day}, {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        _show_tracked_text(ctx, txt, cx, 30.0 * scale, tracking=2.0 * scale)

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

        cx = width / 2.0
        cy = height / 2.0
        r_inner = 36.0 * scale
        max_ray = 35.0 * scale

        target_bars = 40
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(2.5 * scale)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        n = len(bars)
        for i in range(n):
            theta = 2.0 * math.pi * i / float(n) - math.pi / 2.0
            rlen = float(bars[i]) * max_ray * amp
            if rlen <= 1.5 * scale:
                continue
            cos_t = math.cos(theta)
            sin_t = math.sin(theta)
            x1 = cx + r_inner * cos_t
            y1 = cy + r_inner * sin_t
            x2 = cx + (r_inner + rlen) * cos_t
            y2 = cy + (r_inner + rlen) * sin_t
            ctx.move_to(x1, y1)
            ctx.line_to(x2, y2)
            ctx.stroke()


# ===========================================================================
# 16. Elegance 2
# ===========================================================================

class EleganceThinTheme(ThemeBase):
    """
    **Elegance 2**
    Hairline ultra-thin numerals with extra-wide tracked subtext and razor-thin bars.
    """

    name: str = "Elegance 2"

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
        cx = width / 2.0

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(86.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 82.0 * scale)
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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day_str.upper()}   ·   {time_data.day} {month_name}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        _show_tracked_text(ctx, txt, cx, 30.0 * scale, tracking=5.0 * scale)

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

        target_bars = 60
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 1.0 * scale
        gap = 2.2 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (2.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 1.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 17. Cyberpunk 2077
# ===========================================================================

class CyberpunkTheme(ThemeBase):
    """
    **Cyberpunk 2077**
    Chromatic aberration stencil Orbitron numerals with chamfered status badge and segmented neon bars.
    """

    name: str = "Cyberpunk 2077"

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
        cx = width / 2.0

        ctx.select_font_face("Orbitron", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(62.0 * scale)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = 72.0 * scale

        # Chromatic aberration pass 1: Cyan (#00FFFF)
        self.set_hex_color(ctx, "#00FFFF", alpha=0.65)
        ctx.move_to(tx - 2.5 * scale, ty)
        ctx.show_text(time_data.time_str)

        # Chromatic aberration pass 2: Magenta (#FF007F)
        self.set_hex_color(ctx, "#FF007F", alpha=0.65)
        ctx.move_to(tx + 2.5 * scale, ty)
        ctx.show_text(time_data.time_str)

        # Foreground pass: clock_color
        self.set_hex_color(ctx, clock_color, alpha=1.0)
        ctx.move_to(tx, ty)
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
        cx = width / 2.0

        bw = 270.0 * scale
        bh = 30.0 * scale
        bx = cx - bw / 2.0
        by = 8.0 * scale
        cut = 7.0 * scale

        # Chamfered polygon
        ctx.new_path()
        ctx.move_to(bx + cut, by)
        ctx.line_to(bx + bw, by)
        ctx.line_to(bx + bw, by + bh - cut)
        ctx.line_to(bx + bw - cut, by + bh)
        ctx.line_to(bx, by + bh)
        ctx.line_to(bx, by + cut)
        ctx.close_path()

        self.set_hex_color(ctx, "#00FFFF", alpha=0.12)
        ctx.fill_preserve()
        self.set_hex_color(ctx, "#00FFFF", alpha=0.60)
        ctx.set_line_width(1.2 * scale)
        ctx.stroke()

        month_abbr = time.strftime("%b", time.localtime()).upper()
        txt = f"STATUS: ONLINE // {time_data.day:02d}-{month_abbr}-{time_data.year}"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.95)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = by + bh / 2.0 + ext.height / 2.0
        ctx.move_to(tx, ty)
        ctx.show_text(txt)

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
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.5 * scale
        gap = 3.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        self.set_hex_color(ctx, vis_color, alpha=0.90)

        seg_gap = 1.5 * scale
        num_segs = 3

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap)
            seg_h = (h - (num_segs - 1) * seg_gap) / float(num_segs)
            if seg_h < 1.0 * scale:
                ctx.rectangle(x, base_y - h, bar_w, h)
                ctx.fill()
            else:
                for s in range(num_segs):
                    sy = base_y - (s + 1) * seg_h - s * seg_gap
                    ctx.rectangle(x, sy, bar_w, seg_h)
                    ctx.fill()


# ===========================================================================
# 18. Astro Editorial
# ===========================================================================

class AstroPosterTheme(ThemeBase):
    """
    **Astro Editorial**
    Huge poster-scale stacked numerals with vertical day text and solid wave visualizer.
    """

    name: str = "Astro Editorial"
    clock_base_width: float = 300.0
    clock_base_height: float = 180.0

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
        cx = width / 2.0

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        ctx.select_font_face("Bebas Neue", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(82.0 * scale)

        # Hours on top
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext1 = ctx.text_extents(hr_str)
        ctx.move_to(cx - ext1.width / 2.0 - ext1.x_bearing, 78.0 * scale)
        ctx.show_text(hr_str)

        # Minutes directly below
        self.set_hex_color(ctx, clock_color, alpha=0.88)
        ext2 = ctx.text_extents(min_str)
        ctx.move_to(cx - ext2.width / 2.0 - ext2.x_bearing, 160.0 * scale)
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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day_str[:3].upper()}  /  {time_data.day} {month_name} {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.90)
        ext = ctx.text_extents(txt)
        ctx.move_to(cx - ext.width / 2.0 - ext.x_bearing, 30.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 24
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 7.0 * scale
        gap = 3.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.92)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 19. Neumorph Soft
# ===========================================================================

class NeumorphSoftTheme(ThemeBase):
    """
    **Neumorph Soft**
    Soft UI embossed dual highlights styling with recessed capsule badge and blended bars.
    """

    name: str = "Neumorph Soft"

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
        cx = width / 2.0

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(64.0 * scale)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = 70.0 * scale

        # Dark shadow offset (+2.5, +2.5)
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.40)
        ctx.move_to(tx + 2.5 * scale, ty + 2.5 * scale)
        ctx.show_text(time_data.time_str)

        # Light highlight offset (-2.0, -2.0)
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.30)
        ctx.move_to(tx - 2.0 * scale, ty - 2.0 * scale)
        ctx.show_text(time_data.time_str)

        # Main text
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ctx.move_to(tx, ty)
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
        cx = width / 2.0

        bw = 230.0 * scale
        bh = 32.0 * scale
        bx = cx - bw / 2.0
        by = 8.0 * scale
        r = 16.0 * scale

        # Recessed pill container
        _draw_rounded_rect(ctx, bx, by, bw, bh, r)
        ctx.set_source_rgba(0.0, 0.0, 0.0, 0.25)
        ctx.fill_preserve()
        ctx.set_source_rgba(1.0, 1.0, 1.0, 0.15)
        ctx.set_line_width(1.0 * scale)
        ctx.stroke()

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day_str.upper()} · {time_data.day} {month_name}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(11.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.90)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = by + bh / 2.0 + ext.height / 2.0
        ctx.move_to(tx, ty)
        ctx.show_text(txt)

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

        target_bars = 26
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 6.0 * scale
        gap = 4.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)

        # Outer soft glow pass
        ctx.set_line_width(bar_w + 3.0 * scale)
        self.set_hex_color(ctx, vis_color, alpha=0.20)
        for i in range(len(bars)):
            h = float(bars[i]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()

        # Inner solid pass
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


# ===========================================================================
# 20. Braun Dieter
# ===========================================================================

class BraunModernTheme(ThemeBase):
    """
    **Braun Dieter**
    Mid-century German functionalist layout with safety-orange dot and dual-sided level meter.
    """

    name: str = "Braun Dieter"

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
        cx = width / 2.0

        parts = time_data.time_str.split(":")
        hr_str = parts[0] if len(parts) > 0 else f"{time_data.hour:02d}"
        min_str = parts[1] if len(parts) > 1 else f"{time_data.minute:02d}"

        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(68.0 * scale)

        ext_hr = ctx.text_extents(hr_str)
        ext_min = ctx.text_extents(min_str)
        dot_spacing = 26.0 * scale
        total_w = ext_hr.width + dot_spacing + ext_min.width
        start_x = cx - total_w / 2.0

        # Hours
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ctx.move_to(start_x - ext_hr.x_bearing, 72.0 * scale)
        ctx.show_text(hr_str)

        # Signature safety-orange dot
        dot_cx = start_x + ext_hr.width + dot_spacing / 2.0
        dot_cy = 48.0 * scale
        self.set_hex_color(ctx, "#FF5500", alpha=1.0)
        ctx.arc(dot_cx, dot_cy, 4.5 * scale, 0, 2 * math.pi)
        ctx.fill()

        # Minutes
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        min_x = start_x + ext_hr.width + dot_spacing - ext_min.x_bearing
        ctx.move_to(min_x, 72.0 * scale)
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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime())
        txt = f"{time_data.day_str}, {time_data.day} {month_name} {time_data.year}"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(13.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 32.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 30
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 2.5 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        cy = float(height) / 2.0

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.88)

        for i in range(len(bars)):
            h = float(bars[i]) * (height * 0.45) * amp
            h = max(0.0, min(float(height * 0.48), h))
            if h <= 1.5 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, cy - h)
            ctx.line_to(x, cy + h)
            ctx.stroke()


# ===========================================================================
# 21. Nordic Glint
# ===========================================================================

class NordicGlintTheme(ThemeBase):
    """
    **Nordic Glint**
    Refined geometric serif layout using Cinzel with diamond glyph separators and sine-weighted bars.
    """

    name: str = "Nordic Glint"

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
        cx = width / 2.0

        ctx.select_font_face("Cinzel", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(58.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 70.0 * scale)
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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"{time_data.day}  ◇  {month_name}  ◇  {time_data.year}"
        ctx.select_font_face("Cinzel", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(13.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 32.0 * scale)
        ctx.show_text(txt)

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
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 3.5 * scale
        gap = 2.5 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.85)

        n = len(bars)
        for i in range(n):
            envelope = math.sin(math.pi * (i + 1) / float(n + 1)) ** 0.75
            h = float(bars[i]) * (height - 6.0 * scale) * amp * envelope
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()


# ===========================================================================
# 22. Matrix CLI
# ===========================================================================

class MatrixTerminalTheme(ThemeBase):
    """
    **Matrix CLI**
    Monospace terminal prompt with Linux uptime subtext and ASCII block meter.
    """

    name: str = "Matrix CLI"

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
        clock_color = cfg.get("clock_color", "#20FF50")
        cx = width / 2.0

        txt = f"[user@mint ~]$ {time_data.time_str}:00 █"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(28.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 58.0 * scale)
        ctx.show_text(txt)

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
        cx = width / 2.0

        txt = f"UPTIME: 14:32 // {time_data.year}-{time_data.month:02d}-{time_data.day:02d} // TTY1"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(13.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 32.0 * scale)
        ctx.show_text(txt)

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
        vis_color = cfg.get("visualizer_color", "#20FF50")

        target_bars = 22
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        block_w = 4.5 * scale
        block_h = 3.0 * scale
        gap_x = 3.0 * scale
        gap_y = 2.0 * scale
        max_blocks = max(1, int((height - 6.0 * scale) / (block_h + gap_y)))

        total_w = len(bars) * (block_w + gap_x) - gap_x
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (3.0 * scale)

        self.set_hex_color(ctx, vis_color, alpha=0.90)

        for i in range(len(bars)):
            active_blocks = int(float(bars[i]) * max_blocks * amp)
            active_blocks = max(0, min(max_blocks, active_blocks))
            col_x = start_x + i * (block_w + gap_x)
            for b in range(active_blocks):
                by = base_y - (b + 1) * (block_h + gap_y)
                ctx.rectangle(col_x, by, block_w, block_h)
                ctx.fill()


# ===========================================================================
# 23. Zen Garden
# ===========================================================================

class ZenGardenTheme(ThemeBase):
    """
    **Zen Garden**
    Minimalist serene proportions using Comfortaa with Japanese en-dash rules and water ripple visualizer.
    """

    name: str = "Zen Garden"

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
        cx = width / 2.0

        ctx.select_font_face("Comfortaa", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(52.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.95)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = 68.0 * scale
        ctx.move_to(tx, ty)
        ctx.show_text(time_data.time_str)

        # Flanking serene pebble rings
        self.set_hex_color(ctx, clock_color, alpha=0.25)
        ctx.set_line_width(1.0 * scale)
        # Left pebble
        ctx.arc(tx - 20.0 * scale, ty - ext.height / 2.0, 7.0 * scale, 0, 2 * math.pi)
        ctx.stroke()
        # Right pebble
        ctx.arc(tx + ext.width + 20.0 * scale, ty - ext.height / 2.0, 7.0 * scale, 0, 2 * math.pi)
        ctx.stroke()

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
        cx = width / 2.0

        month_name = time.strftime("%B", time.localtime()).upper()
        txt = f"—   {time_data.day} {month_name} {time_data.year}   —"
        ctx.select_font_face("Montserrat", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.85)
        _show_tracked_text(ctx, txt, cx, 30.0 * scale, tracking=2.0 * scale)

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

        target_pairs = 16
        if len(audio_bars) >= target_pairs:
            bars = audio_bars[-target_pairs:]
        else:
            bars = audio_bars

        bar_w = 3.5 * scale
        gap = 3.5 * scale
        cx = width / 2.0
        base_y = float(height) - (3.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_ROUND)
        ctx.set_line_width(bar_w)

        for k in range(len(bars)):
            h = float(bars[k]) * (height - 6.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            alpha = max(0.20, 0.90 - (k / float(len(bars))) * 0.50)
            self.set_hex_color(ctx, vis_color, alpha=alpha)

            offset = (k + 0.5) * (bar_w + gap)
            ctx.move_to(cx - offset, base_y)
            ctx.line_to(cx - offset, base_y - h)
            ctx.stroke()
            ctx.move_to(cx + offset, base_y)
            ctx.line_to(cx + offset, base_y - h)
            ctx.stroke()


# ===========================================================================
# 24. Vector Tactical
# ===========================================================================

class VectorTacticalTheme(ThemeBase):
    """
    **Vector Tactical**
    Military HUD stencil numerals with crosshair coordinate reticles and targeting visualizer.
    """

    name: str = "Vector Tactical"

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
        cx = width / 2.0

        ctx.select_font_face("Orbitron", cairo.FontSlant.NORMAL, cairo.FontWeight.BOLD)
        ctx.set_font_size(54.0 * scale)
        self.set_hex_color(ctx, clock_color, alpha=0.96)
        ext = ctx.text_extents(time_data.time_str)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ty = 70.0 * scale
        ctx.move_to(tx, ty)
        ctx.show_text(time_data.time_str)

        # Tactical crosshairs flanking text
        self.set_hex_color(ctx, clock_color, alpha=0.50)
        ctx.set_line_width(1.2 * scale)
        arm = 6.0 * scale
        # Left crosshair
        lx = tx - 24.0 * scale
        ly = ty - ext.height / 2.0
        ctx.move_to(lx - arm, ly); ctx.line_to(lx + arm, ly); ctx.stroke()
        ctx.move_to(lx, ly - arm); ctx.line_to(lx, ly + arm); ctx.stroke()
        # Right crosshair
        rx = tx + ext.width + 24.0 * scale
        ry = ly
        ctx.move_to(rx - arm, ry); ctx.line_to(rx + arm, ry); ctx.stroke()
        ctx.move_to(rx, ry - arm); ctx.line_to(rx, ry + arm); ctx.stroke()

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
        cx = width / 2.0

        month_abbr = time.strftime("%b", time.localtime()).upper()
        txt = f"GRID: 28.61N 77.20E // {time_data.day:02d}-{month_abbr}-{time_data.year} // TAC-1"
        ctx.select_font_face("Share Tech Mono", cairo.FontSlant.NORMAL, cairo.FontWeight.NORMAL)
        ctx.set_font_size(12.0 * scale)
        self.set_hex_color(ctx, date_color, alpha=0.88)
        ext = ctx.text_extents(txt)
        tx = cx - ext.width / 2.0 - ext.x_bearing
        ctx.move_to(tx, 32.0 * scale)
        ctx.show_text(txt)

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

        target_bars = 28
        if len(audio_bars) >= target_bars:
            bars = audio_bars[-target_bars:]
        else:
            bars = audio_bars

        bar_w = 4.0 * scale
        gap = 3.0 * scale
        total_w = len(bars) * (bar_w + gap) - gap
        start_x = (width - total_w) / 2.0
        base_y = float(height) - (4.0 * scale)

        ctx.set_line_cap(cairo.LINE_CAP_BUTT)
        ctx.set_line_width(bar_w)
        self.set_hex_color(ctx, vis_color, alpha=0.88)

        for i in range(len(bars)):
            h = float(bars[i]) * (height - 8.0 * scale) * amp
            h = max(0.0, min(float(height - 4.0 * scale), h))
            if h <= 2.0 * scale:
                continue
            x = start_x + i * (bar_w + gap) + (bar_w / 2.0)
            ctx.move_to(x, base_y)
            ctx.line_to(x, base_y - h)
            ctx.stroke()
