"""
src.core.autostart
==================
Manages the XDG autostart entry for Desktop Suite.

The autostart ``.desktop`` file is written to:

    ``~/.config/autostart/desktop-suite.desktop``

Boot-safety wait loop
---------------------
On slow USB sticks, SD cards, or mechanical drives the XFCE session
manager fires autostart entries before the desktop environment is
fully ready.  Launching mpv or GTK windows at that point causes
rendering glitches or total lock-ups.

The ``Exec`` line therefore wraps the real launch in a shell one-liner
that blocks until ``xfce4-desktop`` is fully painted (the same trick
used by the original ``gui_current.py``):

.. code-block:: sh

    sh -c "until xfconf-query -c xfce4-desktop -p /backdrop -l \
    >/dev/null 2>&1; do sleep 1; done; sleep 2; python3 /path/to/main.py --daemon"

This means:

1. Poll ``xfconf-query`` once per second.
2. Once xfce4-desktop's backdrop keys are visible (desktop ready), wait
   an additional 2 s for compositing to settle.
3. Launch Desktop Suite in daemon mode (no GUI window shown at boot).
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

# Standard XDG autostart directory.
_AUTOSTART_DIR  = Path.home() / ".config" / "autostart"
_DESKTOP_FILE   = _AUTOSTART_DIR / "desktop-suite.desktop"

# Absolute path to src/main.py — resolved relative to *this* file.
_DEFAULT_ENTRY  = Path(__file__).resolve().parent.parent / "main.py"


_DESKTOP_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=Desktop Suite
Comment=Live wallpaper + canvas overlay (clock, visualizer)
Exec=sh -c "until xfconf-query -c xfce4-desktop -p /backdrop -l >/dev/null 2>&1; do sleep 1; done; sleep 2; python3 {entry_path} --daemon"
Terminal=false
X-GNOME-Autostart-enabled=true
X-GNOME-Autostart-Delay=0
StartupNotify=false
"""


class AutostartManager:
    """
    Enable / disable the Desktop Suite XDG autostart entry.

    Parameters
    ----------
    desktop_file:
        Override the path of the ``.desktop`` file (useful for tests).
    entry_path:
        Override the path of ``main.py`` embedded in ``Exec=``.
    """

    def __init__(
        self,
        desktop_file: Optional[Path] = None,
        entry_path:   Optional[Path] = None,
    ) -> None:
        self.desktop_file = Path(desktop_file) if desktop_file else _DESKTOP_FILE
        self.entry_path   = Path(entry_path)   if entry_path   else _DEFAULT_ENTRY

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def enable(self) -> bool:
        """
        Write (or overwrite) the ``.desktop`` autostart entry.

        Returns
        -------
        bool
            ``True`` on success, ``False`` if writing failed.
        """
        try:
            self.desktop_file.parent.mkdir(parents=True, exist_ok=True)
            content = _DESKTOP_TEMPLATE.format(entry_path=self.entry_path)
            self.desktop_file.write_text(content, encoding="utf-8")
            log.info("Autostart enabled: %s", self.desktop_file)
            return True
        except OSError as exc:
            log.error("Could not write autostart file: %s", exc)
            return False

    def disable(self) -> bool:
        """
        Remove the ``.desktop`` autostart entry.

        Returns
        -------
        bool
            ``True`` if the file was removed (or was already absent),
            ``False`` if removal failed due to a permission error.
        """
        try:
            self.desktop_file.unlink(missing_ok=True)
            log.info("Autostart disabled: %s", self.desktop_file)
            return True
        except OSError as exc:
            log.error("Could not remove autostart file: %s", exc)
            return False

    def is_enabled(self) -> bool:
        """Return ``True`` if the autostart file currently exists."""
        return self.desktop_file.exists()

    def sync_from_config(self, cfg_manager) -> None:
        """
        Read ``wallpaper.autostart`` from *cfg_manager* and
        enable or disable the autostart entry accordingly.
        """
        if cfg_manager.get("wallpaper.autostart"):
            self.enable()
        else:
            self.disable()

    def __repr__(self) -> str:  # pragma: no cover
        state = "enabled" if self.is_enabled() else "disabled"
        return f"AutostartManager({state}, file={self.desktop_file})"


# ---------------------------------------------------------------------------
# XFCE Keyboard Shortcut Manager
# ---------------------------------------------------------------------------

class XfceShortcutManager:
    """
    Manages custom XFCE keyboard shortcuts for Desktop Suite commands
    via ``xfconf-query``.
    """

    CHANNEL: str = "xfce4-keyboard-shortcuts"
    PREFIX: str = "/commands/custom"

    def __init__(self, entry_path: Optional[Path] = None) -> None:
        self.entry_path = Path(entry_path) if entry_path else _DEFAULT_ENTRY

    @property
    def target_command(self) -> str:
        return f"python3 {self.entry_path} --toggle-wallpaper"

    def normalize_shortcut(self, text: str) -> str:
        """
        Convert human-readable or variant shortcuts (e.g. 'Super + W', 'Ctrl+Alt+w')
        into canonical XFCE xfconf format (e.g. '<Super>w', '<Primary><Alt>w').
        """
        raw = text.strip()
        if not raw:
            return "<Super>w"

        # If already formatted like <Super>w, return normalized
        if "<" in raw and ">" in raw:
            return re.sub(r">\s+<", "><", raw).strip()

        # Parse tokens like "Super + Alt + W"
        tokens = [t.strip() for t in raw.replace("+", " ").split() if t.strip()]
        mods = []
        key = "w"
        for tok in tokens:
            t_lower = tok.lower()
            if t_lower in ("super", "win", "mod4"):
                mods.append("<Super>")
            elif t_lower in ("ctrl", "control", "primary"):
                mods.append("<Primary>")
            elif t_lower in ("alt", "mod1"):
                mods.append("<Alt>")
            elif t_lower == "shift":
                mods.append("<Shift>")
            else:
                key = tok.lower() if len(tok) == 1 else tok

        return "".join(mods) + key

    def get_current_shortcut(self) -> Optional[str]:
        """
        Read xfconf to find which custom shortcut currently invokes
        ``--toggle-wallpaper`` or ``live-wallpaper-toggle.sh``.

        Returns the shortcut string (e.g. '<Super>w') or None.
        """
        try:
            res = subprocess.run(
                ["xfconf-query", "-c", self.CHANNEL, "-p", self.PREFIX, "-l"],
                capture_output=True,
                text=True,
                timeout=1.5,
            )
            if res.returncode != 0:
                return None

            lines = [l.strip() for l in res.stdout.strip().splitlines() if l.strip()]
            for prop in lines:
                if prop.endswith("/startup-notify"):
                    continue
                q_res = subprocess.run(
                    ["xfconf-query", "-c", self.CHANNEL, "-p", prop],
                    capture_output=True,
                    text=True,
                    timeout=1.0,
                )
                val = q_res.stdout.strip()
                if "--toggle-wallpaper" in val or "live-wallpaper-toggle" in val:
                    sc = prop.removeprefix(self.PREFIX + "/")
                    return sc
        except Exception as exc:
            log.warning("XfceShortcutManager: could not read shortcuts: %s", exc)

        return None

    def bind_shortcut(self, shortcut: str) -> bool:
        """
        Bind *shortcut* to toggle the live wallpaper in XFCE.

        Removes any previously bound shortcut pointing to this command first.
        """
        canonical = self.normalize_shortcut(shortcut)

        old = self.get_current_shortcut()
        if old and old != canonical:
            self.remove_shortcut(old)

        prop = f"{self.PREFIX}/{canonical}"
        cmd = self.target_command
        try:
            res = subprocess.run(
                [
                    "xfconf-query",
                    "-c", self.CHANNEL,
                    "-p", prop,
                    "-s", cmd,
                    "--create",
                    "-t", "string",
                ],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if res.returncode == 0:
                log.info("XfceShortcutManager: successfully bound %s -> %s", canonical, cmd)
                return True
            else:
                log.error("XfceShortcutManager: failed to bind: %s", res.stderr)
                return False
        except Exception as exc:
            log.error("XfceShortcutManager: exception while binding: %s", exc)
            return False

    def remove_shortcut(self, shortcut: Optional[str] = None) -> bool:
        """
        Remove the XFCE shortcut binding.
        If *shortcut* is None, removes whatever shortcut is currently bound to DesktopSuite.
        """
        sc = shortcut or self.get_current_shortcut()
        if not sc:
            return True

        canonical = self.normalize_shortcut(sc)
        prop = f"{self.PREFIX}/{canonical}"
        try:
            res = subprocess.run(
                ["xfconf-query", "-c", self.CHANNEL, "-p", prop, "-r", "-R"],
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            log.info("XfceShortcutManager: removed %s", prop)
            return res.returncode == 0
        except Exception as exc:
            log.error("XfceShortcutManager: error removing shortcut: %s", exc)
            return False
