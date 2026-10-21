"""
src.core.config
===============
Unified configuration manager for Desktop Suite.

Reads and writes ``~/.config/desktop-suite/config.json``.

Defaults are derived from the legacy scripts:
  * ``reference/gui_current.py``   — wallpaper GUI settings
  * ``reference/daemon_current.sh``— daemon defaults (fit, speed, mute, vol,
                                     autopause, opacity)

Atomic writes (write-to-tempfile → os.replace) guarantee the config file
is never left in a corrupted state after a power cut or USB disconnect.
"""

from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Filesystem locations
# ---------------------------------------------------------------------------

CONFIG_DIR: Path = Path.home() / ".config" / "desktop-suite"
CONFIG_FILE: Path = CONFIG_DIR / "config.json"

# ---------------------------------------------------------------------------
# Schema / default values
# (keys mirror the legacy settings; new keys are clearly documented)
# ---------------------------------------------------------------------------

#: Complete default configuration.  Every key present here will be present in
#: any config loaded from disk — missing keys are backfilled automatically.
DEFAULTS: dict[str, Any] = {
    # ------------------------------------------------------------------ #
    # Wallpaper section                                                    #
    # (sourced from gui_current.py self.cfg + daemon_current.sh defaults) #
    # ------------------------------------------------------------------ #
    "wallpaper": {
        # Absolute path to the active video file (empty = none selected).
        # Legacy key: "video"
        "video_path": "",

        # How the video is scaled to fill the screen.
        # Options: "fill" (zoom/crop), "fit" (letterbox), "stretch" (ignore AR)
        # daemon: FIT="fill" → --panscan=1.0
        "fit_mode": "fill",

        # Playback speed multiplier.  Range 0.25 – 2.0.
        # daemon: SPEED="1.0"
        "playback_speed": 1.0,

        # Audio volume percentage (0 – 100).
        # daemon: VOL="50"
        "volume": 50,

        # Mute the video's audio track entirely.
        # daemon: MUTE="yes" → --no-audio
        "mute": True,

        # When to automatically pause playback.
        # "focus"     → pause whenever any window has keyboard focus
        # "maximized" → pause only when a window is maximised / full-screen
        # "off"       → never pause
        # daemon: AUTOPAUSE="focus"
        "autopause": "focus",

        # FPS cap applied via mpv --vf=fps=<value>.
        # "native" means no cap (pass-through).
        # gui: fps options: "native", "30", "24"
        "fps_limit": "native",

        # Place a .desktop entry in ~/.config/autostart/ so the daemon
        # launches automatically on login.
        # gui: k_auto checkbox
        "autostart": False,

        # Keyboard shortcut label used to toggle the wallpaper on/off.
        # Stored as the human-readable label; resolved to the X11 keysym
        # at apply-time.
        # gui: shortcut options: "Super + W", "Ctrl + Alt + W", …
        "shortcut": "Super + W",
    },

    # ------------------------------------------------------------------ #
    # Canvas section                                                       #
    # (canvas = transparent always-on-top overlay window that renders     #
    #  the clock, date label, and audio visualizer)                       #
    # ------------------------------------------------------------------ #
    "canvas": {
        # Show a digital clock on the canvas.
        "clock_enabled": True,

        # Show the current date below the clock.
        "date_enabled": True,

        # Show the audio visualizer bar graph on the canvas.
        "visualizer_enabled": True,

        # Name of the active visual theme (corresponds to a key in
        # src/themes/).
        "active_theme": "Original Cursive",

        # Decoupled component colours (hex strings).
        "clock_color": "#FFFFFF",
        "date_color": "#D0D0D0",
        "visualizer_color": "#FFFFFF",

        # Opacity of the canvas background (0.0 = fully transparent,
        # 1.0 = fully opaque).  The window itself is always composited;
        # this controls an optional dim-layer behind the widgets.
        # daemon: OPACITY="1.0" (used for background layer)
        "background_opacity": 0.0,

        # Font family used for clock and date labels.
        "font_family": "Sans",

        # Overall canvas scale multiplier (0.5 to 2.5).
        "scale": 1.0,

        # Audio visualizer intensity multiplier (0.1 to 2.0).
        "visualizer_intensity": 0.65,
    },

    # ------------------------------------------------------------------ #
    # Positions section                                                    #
    # Decoupled X / Y pixel coordinates for each draggable component.    #
    # Sourced from ~/.config/desktop-clock-settings.json center layout    #
    # ------------------------------------------------------------------ #
    "positions": {
        # Clock widget position (center aligned on 1366x768 desktop)
        "clock": {"x": 468, "y": 260},

        # Date label position (spaced uppercase date below clock)
        "date": {"x": 468, "y": 370},

        # Audio visualizer position (symmetrical 27-bar below date)
        "visualizer": {"x": 468, "y": 410},
    },
}


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """
    Load, validate, mutate, and save the Desktop Suite configuration.

    Usage
    -----
    ::

        cfg = ConfigManager()          # load from disk (or create defaults)
        path = cfg.get("wallpaper.video_path")
        cfg.set("wallpaper.mute", False)
        cfg.save()                     # atomic write — power-cut safe

    Dot-notation accessors traverse nested dicts:
    ``"wallpaper.fit_mode"`` → ``cfg["wallpaper"]["fit_mode"]``.

    The raw dict is always accessible via :attr:`data`.
    """

    def __init__(self, config_path: Path | str | None = None) -> None:
        """
        Parameters
        ----------
        config_path:
            Override the default config path (useful for tests).
        """
        self._path: Path = Path(config_path) if config_path else CONFIG_FILE
        self.data: dict[str, Any] = {}
        self.load()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self) -> None:
        """
        Load the config from disk, backfilling any missing keys from
        :data:`DEFAULTS`.  If the file does not exist, the full defaults
        are used and persisted immediately so the file is always present
        after the first run.
        """
        self.data = deepcopy(DEFAULTS)

        if self._path.exists():
            try:
                with self._path.open("r", encoding="utf-8") as fh:
                    on_disk: dict[str, Any] = json.load(fh)

                # Backwards-compatibility migration for decoupled colors
                canvas_disk = on_disk.get("canvas")
                if isinstance(canvas_disk, dict):
                    if "clock_color" not in canvas_disk:
                        canvas_disk["clock_color"] = canvas_disk.get("primary_color", "#FFFFFF")
                    if "date_color" not in canvas_disk:
                        canvas_disk["date_color"] = "#D0D0D0"
                    if "visualizer_color" not in canvas_disk:
                        canvas_disk["visualizer_color"] = canvas_disk.get("primary_color", "#FFFFFF")
                    canvas_disk.pop("primary_color", None)
                    canvas_disk.pop("accent_color", None)

                _deep_merge(self.data, on_disk)
            except (json.JSONDecodeError, OSError) as exc:
                # Corrupt / unreadable file → back up and start fresh.
                backup = self._path.with_suffix(".json.bak")
                try:
                    self._path.rename(backup)
                except OSError:
                    pass
                print(
                    f"[ConfigManager] WARNING: could not read {self._path} "
                    f"({exc!r}). Defaults restored; broken file → {backup}"
                )
        else:
            # First run: persist defaults right away.
            self._write()

    def save(self) -> None:
        """Atomically write :attr:`data` to disk."""
        self._write()

    def get(self, key: str, default: Any = None) -> Any:
        """
        Retrieve a value using dot-notation.

        Examples
        --------
        ::

            cfg.get("wallpaper.mute")          # → True
            cfg.get("positions.clock.x")       # → 60
            cfg.get("missing.key", "fallback") # → "fallback"
        """
        # Backwards-compatibility aliases for deprecated keys
        if key == "canvas.primary_color":
            return self.get("canvas.clock_color", default if default is not None else "#FFFFFF")
        if key == "canvas.accent_color":
            return self.get("canvas.visualizer_color", default if default is not None else "#FFFFFF")

        parts = key.split(".")
        node: Any = self.data
        for part in parts:
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def set(self, key: str, value: Any) -> None:
        """
        Set a value using dot-notation, creating intermediate dicts as needed.

        The change is kept in memory until :meth:`save` is called.

        Examples
        --------
        ::

            cfg.set("wallpaper.fit_mode", "fit")
            cfg.set("positions.visualizer.y", 850)
        """
        parts = key.split(".")
        node: dict[str, Any] = self.data
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value

    def reset_to_defaults(self) -> None:
        """Overwrite :attr:`data` with a fresh copy of :data:`DEFAULTS`."""
        self.data = deepcopy(DEFAULTS)

    def as_json(self, indent: int = 2) -> str:
        """Return a pretty-printed JSON string of the current config."""
        return json.dumps(self.data, indent=indent, ensure_ascii=False)

    def __repr__(self) -> str:  # pragma: no cover
        return f"ConfigManager(path={self._path!r})"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _write(self) -> None:
        """
        Atomic write: serialise to a sibling temp file, then ``os.replace``
        it into place.  This ensures the config file is *never* partially
        written — even if the process is killed mid-write or the storage
        device is removed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Write to a temporary file in the same directory so that the
        # os.replace() call is guaranteed to be an atomic rename on the
        # same filesystem.
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent,
            prefix=".config_tmp_",
            suffix=".json",
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
                fh.write("\n")   # POSIX: end file with newline
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up the orphaned temp file on failure.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _deep_merge(base: dict, override: dict) -> None:
    """
    Recursively merge *override* into *base* **in-place**.

    * Existing keys in *base* that are also dicts are merged recursively.
    * All other keys in *override* overwrite those in *base*.
    * Keys present only in *base* (i.e. new defaults) are left untouched,
      so schema additions in future releases are automatically backfilled.
    """
    for key, value in override.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, dict)
        ):
            _deep_merge(base[key], value)
        else:
            base[key] = value


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    print("=" * 60)
    print("Desktop Suite — ConfigManager self-test")
    print("=" * 60)

    # ── 1. Load (or create) config ──────────────────────────────────────
    cfg = ConfigManager()
    print(f"\n[1] Config file location: {cfg._path}")
    print(f"    File exists after load: {cfg._path.exists()}")

    # ── 2. Print the full config ─────────────────────────────────────────
    print("\n[2] Current configuration:")
    print(cfg.as_json())

    # ── 3. Dot-notation get / set ────────────────────────────────────────
    print("[3] Dot-notation round-trip:")
    original_mute = cfg.get("wallpaper.mute")
    print(f"    wallpaper.mute (before) = {original_mute!r}")

    cfg.set("wallpaper.mute", not original_mute)
    print(f"    wallpaper.mute (after)  = {cfg.get('wallpaper.mute')!r}")

    cfg.set("positions.clock.x", 120)
    print(f"    positions.clock.x set to {cfg.get('positions.clock.x')!r}")

    # ── 4. Save and reload — verify persistence ──────────────────────────
    print("\n[4] Saving …")
    cfg.save()
    print("    Save OK")

    cfg2 = ConfigManager()
    assert cfg2.get("wallpaper.mute") == (not original_mute), \
        "FAIL: mute value did not persist!"
    assert cfg2.get("positions.clock.x") == 120, \
        "FAIL: clock.x did not persist!"
    print("    Reload verified — all values match ✓")

    # ── 5. Restore original values ───────────────────────────────────────
    cfg2.set("wallpaper.mute", original_mute)
    cfg2.set("positions.clock.x", DEFAULTS["positions"]["clock"]["x"])
    cfg2.save()
    print("    Original values restored ✓")

    # ── 6. Test missing-key fallback ─────────────────────────────────────
    sentinel = object()
    result = cfg2.get("does.not.exist", sentinel)
    assert result is sentinel, "FAIL: missing key should return default!"
    print("\n[5] Missing-key fallback ✓")

    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)
    sys.exit(0)
