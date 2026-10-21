"""
src.themes.base
===============
Abstract base class for all Desktop Suite visual themes.

A **theme** is responsible for drawing four independent surfaces onto a
Cairo context:

* ``draw_background`` — optional dim/blur layer behind all widgets.
* ``draw_clock``      — the digital time string.
* ``draw_date``       — the date string.
* ``draw_visualizer`` — the audio spectrum bar graph.

Each method receives the Cairo context already translated to the widget's
position; the theme draws at the origin ``(0, 0)``.

Pre-computation cache
---------------------
Themes inherit :class:`ThemeCache` which pre-computes expensive constants
(sin/cos LUTs, gradient stops, static image surfaces) at theme load time
so that the per-frame draw callbacks are as lean as possible.  Subclasses
override :meth:`_precompute` to populate the cache dict.
"""

from __future__ import annotations

import math
import time
from abc import ABC, abstractmethod
from typing import Any

import cairo

from src.core.fonts import register_bundled_fonts
register_bundled_fonts()


# ---------------------------------------------------------------------------
# Shared time snapshot passed to every draw call on a given frame.
# Avoids calling time.localtime() multiple times per tick.
# ---------------------------------------------------------------------------

class TimeData:
    """Snapshot of the current local time for one render frame."""

    __slots__ = (
        "hour", "minute", "second",
        "day", "month", "year",
        "weekday",
        "time_str", "date_str", "day_str",
        "is_24h",
    )

    def __init__(self, is_24h: bool = False) -> None:
        now = time.localtime()
        self.is_24h   = is_24h
        self.hour     = now.tm_hour
        self.minute   = now.tm_min
        self.second   = now.tm_sec
        self.day      = now.tm_mday
        self.month    = now.tm_mon
        self.year     = now.tm_year
        self.weekday  = now.tm_wday   # 0 = Monday

        fmt = "%H:%M" if is_24h else "%I:%M"
        self.time_str = time.strftime(fmt, now)
        self.day_str  = time.strftime("%A", now)
        self.date_str = time.strftime("%d %B %Y", now).upper()

    @classmethod
    def now(cls, is_24h: bool = False) -> "TimeData":
        """Convenience factory that always snapshots the *current* time."""
        return cls(is_24h=is_24h)


# ---------------------------------------------------------------------------
# Pre-computation cache
# ---------------------------------------------------------------------------

class ThemeCache:
    """
    Lightweight key/value store for expensive pre-computed data.

    Subclasses call ``self.cache["key"] = value`` inside
    :meth:`BaseTheme._precompute`.  The cache is populated once at
    construction and re-populated whenever :meth:`BaseTheme.invalidate` is
    called (e.g. when the user changes theme colours).
    """

    def __init__(self) -> None:
        self._store: dict[str, Any] = {}
        # Pre-built sin/cos lookup arrays (index → angle in full circle)
        self._store["sin_lut"] = [math.sin(2 * math.pi * i / 360) for i in range(360)]
        self._store["cos_lut"] = [math.cos(2 * math.pi * i / 360) for i in range(360)]

    def __getitem__(self, key: str) -> Any:
        return self._store[key]

    def __setitem__(self, key: str, value: Any) -> None:
        self._store[key] = value

    def get(self, key: str, default: Any = None) -> Any:
        return self._store.get(key, default)

    def clear_derived(self) -> None:
        """Remove all keys except built-ins (sin/cos LUTs)."""
        builtins = {"sin_lut", "cos_lut"}
        for key in list(self._store.keys()):
            if key not in builtins:
                del self._store[key]


# ---------------------------------------------------------------------------
# Abstract base theme
# ---------------------------------------------------------------------------

class BaseTheme(ABC):
    """
    Abstract base class for all canvas themes.

    Subclasses must implement the four ``draw_*`` abstract methods.
    They may optionally override :meth:`_precompute` to populate
    :attr:`cache` with derived constants (gradient stops, font metrics, …).

    Lifecycle
    ---------
    ::

        theme = MyTheme()            # __init__ calls _precompute()
        theme.draw_clock(ctx, ...)   # fast per-frame path
        theme.invalidate()           # re-runs _precompute after a config change
    """

    #: Human-readable display name shown in the settings UI.
    name: str = "Unnamed Theme"

    def __init__(self) -> None:
        self.cache = ThemeCache()
        self._precompute()

    # ------------------------------------------------------------------
    # Pre-computation hook (optional override)
    # ------------------------------------------------------------------

    def _precompute(self) -> None:
        """
        Populate :attr:`cache` with expensive derived data.

        Called once at construction and again on :meth:`invalidate`.
        The default implementation is a no-op; subclasses should override
        this to pre-build gradient patterns, font extents, image surfaces, etc.
        """

    def invalidate(self) -> None:
        """
        Discard derived cache entries and recompute them.

        Call this whenever a config property (colour, font, scale) changes
        at runtime so the next draw frame picks up the new values without
        needing a full restart.
        """
        self.cache.clear_derived()
        self._precompute()

    # ------------------------------------------------------------------
    # Abstract draw methods
    # ------------------------------------------------------------------

    @abstractmethod
    def draw_background(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
    ) -> None:
        """
        Draw the optional background dim layer.

        The layer should cover the full ``(width × height)`` rectangle
        and use ``cfg["background_opacity"]`` as its alpha.  Pass-through
        (no-op) when opacity is 0.

        Parameters
        ----------
        ctx:
            Cairo context, already set up by the caller.
        width, height:
            Widget allocation in pixels.
        cfg:
            The ``canvas`` section from :class:`~src.core.config.ConfigManager`.
        """

    @abstractmethod
    def draw_clock(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """
        Draw the clock (time string) onto *ctx*.

        The context origin ``(0, 0)`` corresponds to the clock widget's
        configured position; the theme is free to lay out the text however
        it likes within that space.

        Parameters
        ----------
        time_data:
            Pre-snapshotted time values for this frame.
        """

    @abstractmethod
    def draw_date(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        time_data: TimeData,
    ) -> None:
        """Draw the date string onto *ctx*."""

    @abstractmethod
    def draw_visualizer(
        self,
        ctx: cairo.Context,
        width: int,
        height: int,
        cfg: dict[str, Any],
        audio_bars: "np.ndarray",  # noqa: F821  (avoid circular import in type hint)
    ) -> None:
        """
        Draw the audio spectrum bar graph onto *ctx*.

        Parameters
        ----------
        audio_bars:
            Normalised bar heights, shape ``(total_bars,)``, values 0.0–1.0.
            Each bar should be scaled to ``height * audio_bars[i]`` pixels.
        """

    # ------------------------------------------------------------------
    # Shared Cairo helpers available to all subclasses
    # ------------------------------------------------------------------

    @staticmethod
    def set_hex_color(
        ctx: cairo.Context,
        hex_color: str,
        alpha: float = 1.0,
    ) -> None:
        """
        Set the Cairo source from a ``"#RRGGBB"`` or ``"#RGB"`` hex string.

        Parameters
        ----------
        alpha:
            Override alpha (0.0 – 1.0).
        """
        h = hex_color.lstrip("#")
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        r = int(h[0:2], 16) / 255.0
        g = int(h[2:4], 16) / 255.0
        b = int(h[4:6], 16) / 255.0
        ctx.set_source_rgba(r, g, b, alpha)

    @staticmethod
    def layout_text(
        ctx: cairo.Context,
        text: str,
        font_family: str,
        font_size: float,
        bold: bool = False,
        italic: bool = False,
    ) -> tuple[float, float]:
        """
        Set the current font and return ``(text_width, text_height)``
        measured via Cairo text extents.
        """
        slant  = cairo.FontSlant.ITALIC  if italic else cairo.FontSlant.NORMAL
        weight = cairo.FontWeight.BOLD   if bold   else cairo.FontWeight.NORMAL
        ctx.select_font_face(font_family, slant, weight)
        ctx.set_font_size(font_size)
        ext = ctx.text_extents(text)
        return ext.width, ext.height

    def __repr__(self) -> str:  # pragma: no cover
        return f"{type(self).__name__}(name={self.name!r})"
