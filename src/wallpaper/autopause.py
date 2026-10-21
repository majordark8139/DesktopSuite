"""
src.wallpaper.autopause
=======================
Background thread that watches the active X11 window and automatically
pauses / resumes the video wallpaper via ``MpvIPC``.

Logic ported directly from ``daemon_current.sh`` lines 37–71:

.. code-block:: bash

    PAUSED=0
    while true; do
        WIN=$(xdotool getactivewindow 2>/dev/null)
        ...
        if ! echo "$CLS" | grep -qiE "xfdesktop|desktop-clock|plank"; then
            if [ "$AUTOPAUSE" = "focus" ]; then
                PAUSE=1
            elif [ "$AUTOPAUSE" = "maximized" ]; then
                STATE=$(xprop -id "$WIN" _NET_WM_STATE ...)
                if echo "$STATE" | grep -qE "MAXIMIZED_VERT|MAXIMIZED_HORZ|FULLSCREEN"; then
                    PAUSE=1
                fi
            fi
        fi
        ...
        sleep 0.4
    done

The three modes are:

``"focus"``
    Pause whenever any ordinary window is focused (the reference default).
    The wallpaper keeps playing when the desktop, clock overlay, or Plank
    dock are in focus — matching the ``grep -qiE "xfdesktop|desktop-clock|plank"``
    allowlist in the bash original.

``"maximized"``
    Pause only when the focused window is maximised or full-screen.

``"off"``
    Never pause; run continuously.
"""

from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
from typing import Literal

from .ipc import MpvIPC

log = logging.getLogger(__name__)

# Windows belonging to the desktop itself — wallpaper keeps playing while
# these are active.  Mirrors: grep -qiE "xfdesktop|desktop-clock|plank"
_DESKTOP_CLASSES: re.Pattern = re.compile(
    r"xfdesktop|desktop-clock|plank",
    re.IGNORECASE,
)

# Net WM state atoms that count as "maximised" for the 'maximized' mode.
# Mirrors: grep -qE "MAXIMIZED_VERT|MAXIMIZED_HORZ|FULLSCREEN"
_MAXIMISED_ATOMS: re.Pattern = re.compile(
    r"MAXIMIZED_VERT|MAXIMIZED_HORZ|FULLSCREEN",
)

# Poll interval — must stay ≤ 400 ms to match the reference daemon
POLL_INTERVAL: float = 0.4

AutopauseMode = Literal["focus", "maximized", "off"]


class AutoPauseWatcher:
    """
    Low-overhead daemon thread that polls the active X11 window and
    drives mpv pause / resume through :class:`~src.wallpaper.ipc.MpvIPC`.

    Parameters
    ----------
    ipc:
        A connected :class:`MpvIPC` instance.
    mode:
        One of ``"focus"``, ``"maximized"``, or ``"off"``.
    poll_interval:
        Seconds between each window check.  Default 0.4 s (matches daemon).
    """

    def __init__(
        self,
        ipc: MpvIPC,
        mode: AutopauseMode = "focus",
        poll_interval: float = POLL_INTERVAL,
    ) -> None:
        self.ipc = ipc
        self.mode = mode
        self.poll_interval = poll_interval

        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()

        # Track last state to avoid redundant IPC calls.
        # None = unknown (first iteration will always send a command).
        self._was_paused: bool | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """
        Start the background polling thread.

        Does nothing if already running or if mode is ``"off"``.
        """
        if self.mode == "off":
            log.info("AutoPauseWatcher: mode='off' — thread not started")
            return
        if self._thread and self._thread.is_alive():
            log.debug("AutoPauseWatcher: already running")
            return

        self._stop_event.clear()
        self._was_paused = None
        self._thread = threading.Thread(
            target=self._run,
            name="autopause-watcher",
            daemon=True,          # killed automatically when main thread exits
        )
        self._thread.start()
        log.info("AutoPauseWatcher started (mode=%r)", self.mode)

    def stop(self) -> None:
        """Signal the polling thread to exit and wait for it to finish."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.poll_interval * 3)
        self._thread = None
        self._was_paused = None
        log.info("AutoPauseWatcher stopped")

    def update_mode(self, mode: AutopauseMode) -> None:
        """
        Change the auto-pause mode at runtime without restarting the thread.

        If the new mode is ``"off"``, the thread is stopped.
        If the previous mode was ``"off"`` and the new one is not, the
        thread is started.
        """
        old_mode = self.mode
        self.mode = mode
        log.info("AutoPauseWatcher mode: %r → %r", old_mode, mode)

        if mode == "off":
            self.stop()
            # Make sure video is playing when we turn off auto-pause.
            self.ipc.resume()
        elif old_mode == "off":
            self.start()

    @property
    def is_running(self) -> bool:
        """``True`` if the background thread is alive."""
        return self._thread is not None and self._thread.is_alive()

    # ------------------------------------------------------------------
    # Internal polling loop
    # ------------------------------------------------------------------

    def _run(self) -> None:
        """Main loop executed in the daemon thread."""
        while not self._stop_event.is_set():
            try:
                should_pause = self._evaluate()
            except Exception as exc:  # noqa: BLE001
                log.warning("AutoPauseWatcher: unexpected error: %s", exc)
                should_pause = False

            if should_pause != self._was_paused:
                if should_pause:
                    log.debug("AutoPauseWatcher: → pausing")
                    self.ipc.pause()
                else:
                    log.debug("AutoPauseWatcher: → resuming")
                    self.ipc.resume()
                self._was_paused = should_pause

            self._stop_event.wait(timeout=self.poll_interval)

    def _evaluate(self) -> bool:
        """
        Query the current active window and decide whether to pause.

        Returns
        -------
        bool
            ``True`` if the wallpaper should be paused right now.
        """
        if self.mode == "off":
            return False

        win_id = self._active_window_id()

        # No active window or bare desktop — keep playing.
        if not win_id:
            return False

        wm_class = self._get_wm_class(win_id)

        # Allowlist: desktop background, clock overlay, Plank dock.
        # Mirrors: grep -qiE "xfdesktop|desktop-clock|plank"
        if _DESKTOP_CLASSES.search(wm_class):
            return False

        if self.mode == "focus":
            return True

        if self.mode == "maximized":
            state = self._get_net_wm_state(win_id)
            return bool(_MAXIMISED_ATOMS.search(state))

        # Unknown mode — be conservative and keep playing.
        return False

    # ------------------------------------------------------------------
    # X11 helper calls (xdotool / xprop — same tools as the bash daemon)
    # ------------------------------------------------------------------

    @staticmethod
    def _active_window_id() -> str:
        """
        Return the hex window ID string of the currently focused window.

        Mirrors: ``WIN=$(xdotool getactivewindow 2>/dev/null)``

        Returns an empty string if xdotool is unavailable or there is no
        focused window.
        """
        try:
            result = subprocess.run(
                ["xdotool", "getactivewindow"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            wid = result.stdout.strip()
            # xdotool returns "0" when no window is focused.
            return wid if wid and wid != "0" else ""
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    @staticmethod
    def _get_wm_class(win_id: str) -> str:
        """
        Return the ``WM_CLASS`` string for *win_id*.

        Mirrors: ``CLS=$(xprop -id "$WIN" WM_CLASS 2>/dev/null)``
        """
        try:
            result = subprocess.run(
                ["xprop", "-id", win_id, "WM_CLASS"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    @staticmethod
    def _get_net_wm_state(win_id: str) -> str:
        """
        Return the ``_NET_WM_STATE`` string for *win_id*.

        Mirrors: ``STATE=$(xprop -id "$WIN" _NET_WM_STATE 2>/dev/null)``
        """
        try:
            result = subprocess.run(
                ["xprop", "-id", win_id, "_NET_WM_STATE"],
                capture_output=True,
                text=True,
                timeout=1.0,
            )
            return result.stdout
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
            return ""

    def __repr__(self) -> str:  # pragma: no cover
        state = "running" if self.is_running else "stopped"
        return f"AutoPauseWatcher(mode={self.mode!r}, {state})"
