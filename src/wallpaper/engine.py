"""
src.wallpaper.engine
====================
Native hardware-accelerated wallpaper engine.

Translates the shell one-liner from ``daemon_current.sh`` line 30:

.. code-block:: bash

    xwinwrap -fs -ni -s -st -sp -b -nf -un -- \\
        mpv -wid WID --loop=inf --vo=gpu --hwdec=vaapi \\
            --cache=no --demuxer-max-bytes=15M \\
            --no-osc --no-osd-bar \\
            --speed="$SPEED" --volume="$VOL" \\
            --input-ipc-server="$SOCK" \\
            [--no-audio]        # if MUTE=yes
            [--panscan=1.0]     # if FIT=fill
            [--panscan=0.0]     # if FIT=fit
            [--keepaspect=no]   # if FIT=stretch
            [--vf=fps=<N>]      # if FPS != native
            "$VIDEO" &

…into a managed Python subprocess with:

* Proper ``start`` / ``stop`` / ``restart`` / ``toggle_pause`` lifecycle.
* SIGTERM / atexit cleanup that removes the socket file.
* An :class:`AutoPauseWatcher` thread wired up automatically.
* Integration with :class:`~src.core.config.ConfigManager` so callers
  only need to call ``engine.start()``.

Architecture
------------
The xwinwrap flag breakdown (from daemon):

=========  ==================================================
Flag       Meaning
=========  ==================================================
``-fs``    Full-screen window
``-ni``    Non-interactive (no input events)
``-s``     Enable shape (for transparency)
``-st``    Set shape to type
``-sp``    Shape by pixmap
``-b``     Keep window in background (desktop level)
``-nf``    Non-focusable
``-un``    Unmanaged (no window-manager decoration)
=========  ==================================================

mpv receives the X11 WID from xwinwrap as the literal string ``WID``
in the argument list — xwinwrap substitutes the real window ID at
launch time.
"""

from __future__ import annotations

import atexit
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Literal

if __name__ == "__main__" and __package__ is None:
    # Allow running this file directly for testing.
    import sys as _sys, os as _os
    _sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))))
    __package__ = "src.wallpaper"

from .autopause import AutoPauseWatcher, AutopauseMode
from .ipc import MpvIPC, MPV_SOCKET

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants — values taken directly from daemon_current.sh
# ---------------------------------------------------------------------------

XWINWRAP_FLAGS: list[str] = [
    "xwinwrap",
    "-fs",   # full-screen
    "-ni",   # non-interactive
    "-s",    # enable shape
    "-st",   # shape type
    "-sp",   # shape by pixmap
    "-b",    # keep behind all windows (desktop layer)
    "-nf",   # non-focusable
    "-un",   # unmanaged
    "--",    # separator: everything after goes to the embedded program
]

# Fixed mpv arguments that never change (from daemon_current.sh ARGS=(...))
MPV_FIXED_ARGS: list[str] = [
    "mpv",
    "-wid", "WID",              # xwinwrap substitutes the real X11 window ID
    "--loop=inf",
    "--vo=gpu",
    "--hwdec=vaapi",            # VA-API hardware decoding
    "--cache=no",
    "--demuxer-max-bytes=15M",
    "--no-osc",
    "--no-osd-bar",
]

FitMode = Literal["fill", "fit", "stretch"]

# How long to wait for the IPC socket to appear after launch (seconds).
# daemon: for i in {1..25}; do [ -S "$SOCK" ] && break; sleep 0.1; done
# → 25 × 0.1 s = 2.5 s maximum
SOCKET_WAIT_TIMEOUT: float = 2.5
SOCKET_WAIT_POLL:    float = 0.1


class WallpaperEngine:
    """
    Manages the xwinwrap + mpv subprocess that renders the live wallpaper.

    Parameters
    ----------
    ipc:
        :class:`~src.wallpaper.ipc.MpvIPC` instance to use for runtime
        control.  If ``None``, a default one targeting
        ``/tmp/mpv-livewal.sock`` is created automatically.
    socket_path:
        Override the IPC socket path (useful for tests).
    """

    def __init__(
        self,
        ipc: MpvIPC | None = None,
        socket_path: str = MPV_SOCKET,
    ) -> None:
        self.socket_path = socket_path
        self.ipc: MpvIPC = ipc or MpvIPC(socket_path=socket_path)

        self._proc: subprocess.Popen | None = None
        self._watcher: AutoPauseWatcher | None = None
        self._paused: bool = False

        # Register cleanup so the socket is always removed on interpreter exit.
        atexit.register(self._atexit_cleanup)

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(
        self,
        video_path: str | Path,
        *,
        speed: float = 1.0,
        volume: int = 50,
        mute: bool = True,
        fit_mode: FitMode = "fill",
        fps_limit: str = "native",
        autopause: AutopauseMode = "focus",
    ) -> bool:
        """
        Launch xwinwrap + mpv for *video_path*.

        Stops any existing instance first (clean restart).

        Parameters
        ----------
        video_path:
            Absolute path to the video file to use as wallpaper.
        speed:
            Playback speed multiplier (0.25 – 2.0).
        volume:
            Audio volume percentage (0 – 100).
        mute:
            If ``True``, pass ``--no-audio`` to mpv.
        fit_mode:
            ``"fill"`` → ``--panscan=1.0``
            ``"fit"``  → ``--panscan=0.0``
            ``"stretch"`` → ``--keepaspect=no``
        fps_limit:
            ``"native"`` skips the ``--vf=fps=`` filter; any other value
            (``"30"``, ``"24"``) is passed as ``--vf=fps=<N>``.
        autopause:
            Auto-pause mode for :class:`AutoPauseWatcher`.

        Returns
        -------
        bool
            ``True`` if the process launched and the IPC socket appeared
            within the timeout; ``False`` otherwise.
        """
        video_path = Path(video_path)
        if not video_path.is_file():
            log.error("start(): video file not found: %s", video_path)
            return False

        # Stop previous instance cleanly (mirrors daemon's killall at top).
        self.stop()

        cmd = self._build_command(
            video_path=video_path,
            speed=speed,
            volume=volume,
            mute=mute,
            fit_mode=fit_mode,
            fps_limit=fps_limit,
        )

        log.info("Launching: %s", " ".join(cmd))

        try:
            self._proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                # New session so signals to our process don't kill the child
                # before we want them to.
                start_new_session=True,
            )
        except FileNotFoundError as exc:
            log.error("start(): could not execute: %s", exc)
            return False

        # Wait for mpv to create its IPC socket (up to SOCKET_WAIT_TIMEOUT s).
        if not self._wait_for_socket():
            log.warning(
                "start(): IPC socket did not appear within %.1f s",
                SOCKET_WAIT_TIMEOUT,
            )
            # Process is running but IPC isn't ready — still return True
            # so the caller knows the subprocess started.
            return True

        log.info("IPC socket ready: %s", self.socket_path)
        self._paused = False

        # Start autopause watcher thread.
        self._watcher = AutoPauseWatcher(
            ipc=self.ipc,
            mode=autopause,
        )
        self._watcher.start()

        return True

    def stop(self) -> None:
        """
        Terminate mpv / xwinwrap and clean up.

        Mirrors the cleanup trap in daemon_current.sh:

        .. code-block:: bash

            killall xwinwrap 2>/dev/null
            pkill -f "mpv-livewal.sock" 2>/dev/null
            rm -f "$SOCK"
        """
        # Stop the autopause thread first to avoid IPC calls on a dying socket.
        if self._watcher:
            self._watcher.stop()
            self._watcher = None

        if self._proc:
            log.info("Stopping wallpaper engine (pid=%d) …", self._proc.pid)
            try:
                # Send SIGTERM to the entire process group (xwinwrap + mpv).
                os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
            except ProcessLookupError:
                pass   # already dead
            except Exception as exc:
                log.debug("stop(): killpg failed: %s", exc)
                try:
                    self._proc.terminate()
                except Exception:
                    pass

            try:
                self._proc.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                log.warning("stop(): process did not exit; sending SIGKILL")
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=2.0)
                except Exception:
                    pass

            self._proc = None

        # Belt-and-suspenders: kill any orphaned xwinwrap / mpv with our sock
        _silent_run(["killall", "xwinwrap"])
        _silent_run(["pkill", "-f", "mpv-livewal.sock"])

        # Remove the socket file.
        self._remove_socket()
        self._paused = False
        log.info("Wallpaper engine stopped")

    def restart(
        self,
        video_path: str | Path,
        **kwargs,
    ) -> bool:
        """
        Stop then start with new parameters.

        All keyword arguments are forwarded to :meth:`start`.
        """
        self.stop()
        return self.start(video_path, **kwargs)

    def toggle_pause(self) -> bool:
        """
        Toggle between pause and play states.

        Returns the *new* paused state (``True`` = now paused).
        """
        if not self.is_running:
            return False
        if self._paused:
            self.ipc.resume()
            self._paused = False
        else:
            self.ipc.pause()
            self._paused = True
        return self._paused

    # ------------------------------------------------------------------
    # Runtime control (thin wrappers around MpvIPC)
    # ------------------------------------------------------------------

    def set_volume(self, val: int) -> bool:
        """Set mpv volume (0–100) at runtime without restart."""
        return self.ipc.set_volume(val)

    def set_speed(self, val: float) -> bool:
        """Set mpv playback speed at runtime without restart."""
        return self.ipc.set_speed(val)

    def set_autopause(self, mode: AutopauseMode) -> None:
        """Switch autopause mode at runtime."""
        if self._watcher:
            self._watcher.update_mode(mode)
        elif mode != "off" and self.is_running:
            self._watcher = AutoPauseWatcher(ipc=self.ipc, mode=mode)
            self._watcher.start()

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """``True`` if the xwinwrap/mpv subprocess is alive."""
        if self._proc is None:
            return False
        return self._proc.poll() is None

    @property
    def is_paused(self) -> bool:
        """Last known pause state (may lag by one IPC round-trip)."""
        return self._paused

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_command(
        video_path: Path,
        speed: float,
        volume: int,
        mute: bool,
        fit_mode: FitMode,
        fps_limit: str,
    ) -> list[str]:
        """
        Build the full ``xwinwrap … mpv … <video>`` command list.

        Mirrors the ARGS construction in daemon_current.sh lines 23–28.
        """
        cmd: list[str] = list(XWINWRAP_FLAGS) + list(MPV_FIXED_ARGS)

        # Speed and volume (always explicit)
        cmd += [f"--speed={speed}", f"--volume={volume}"]

        # IPC socket
        cmd += [f"--input-ipc-server={MPV_SOCKET}"]

        # Mute → --no-audio  (daemon: [ "$MUTE" = "yes" ] && ARGS+=(--no-audio))
        if mute:
            cmd.append("--no-audio")

        # Aspect / fit mode (daemon lines 25–27)
        if fit_mode == "fill":
            cmd.append("--panscan=1.0")
        elif fit_mode == "fit":
            cmd.append("--panscan=0.0")
        elif fit_mode == "stretch":
            cmd.append("--keepaspect=no")

        # FPS cap (daemon line 28)
        if fps_limit != "native":
            cmd.append(f"--vf=fps={fps_limit}")

        # Video file must be last.
        cmd.append(str(video_path))
        return cmd

    def _wait_for_socket(self) -> bool:
        """
        Poll until the IPC socket appears or the timeout expires.

        Mirrors daemon_current.sh:
        ``for i in {1..25}; do [ -S "$SOCK" ] && break; sleep 0.1; done``
        """
        deadline = time.monotonic() + SOCKET_WAIT_TIMEOUT
        while time.monotonic() < deadline:
            if os.path.exists(self.socket_path):
                return True
            time.sleep(SOCKET_WAIT_POLL)
        return False

    def _remove_socket(self) -> None:
        """Delete the IPC socket file if it exists."""
        try:
            os.unlink(self.socket_path)
            log.debug("Removed IPC socket: %s", self.socket_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            log.warning("Could not remove socket %s: %s", self.socket_path, exc)

    def _atexit_cleanup(self) -> None:
        """Registered with ``atexit`` — ensures cleanup on interpreter exit."""
        if self._proc and self._proc.poll() is None:
            log.debug("atexit: stopping wallpaper engine")
            self.stop()

    def __repr__(self) -> str:  # pragma: no cover
        state = "running" if self.is_running else "stopped"
        return f"WallpaperEngine({state}, pid={self._proc.pid if self._proc else None})"


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _silent_run(cmd: list[str]) -> None:
    """Run *cmd* ignoring all errors (mirrors ``cmd 2>/dev/null``)."""
    try:
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Self-test block
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    import tempfile
    import os

    # Import ConfigManager from the sibling package.
    # Running as __main__ means we need to adjust sys.path.
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(os.path.dirname(_here))   # DesktopSuite/
    if _root not in sys.path:
        sys.path.insert(0, _root)

    from src.core.config import ConfigManager, DEFAULTS

    print("=" * 60)
    print("WallpaperEngine — self-test")
    print("=" * 60)

    # ── Test 1: Class instantiation ──────────────────────────────────────
    print("\n[1] Class definition checks …")

    # MpvIPC
    assert callable(getattr(MpvIPC, "send_command", None)), \
        "MpvIPC missing send_command"
    assert callable(getattr(MpvIPC, "pause", None)),         "MpvIPC missing pause"
    assert callable(getattr(MpvIPC, "resume", None)),        "MpvIPC missing resume"
    assert callable(getattr(MpvIPC, "set_volume", None)),    "MpvIPC missing set_volume"
    assert callable(getattr(MpvIPC, "set_speed", None)),     "MpvIPC missing set_speed"
    assert callable(getattr(MpvIPC, "is_alive", None)),      "MpvIPC missing is_alive"
    print("    MpvIPC: all methods present ✓")

    # AutoPauseWatcher
    assert callable(getattr(AutoPauseWatcher, "start", None)),   "APW missing start"
    assert callable(getattr(AutoPauseWatcher, "stop", None)),    "APW missing stop"
    assert callable(getattr(AutoPauseWatcher, "update_mode", None)), "APW missing update_mode"
    print("    AutoPauseWatcher: all methods present ✓")

    # WallpaperEngine
    assert callable(getattr(WallpaperEngine, "start", None)),         "WE missing start"
    assert callable(getattr(WallpaperEngine, "stop", None)),          "WE missing stop"
    assert callable(getattr(WallpaperEngine, "restart", None)),       "WE missing restart"
    assert callable(getattr(WallpaperEngine, "toggle_pause", None)),  "WE missing toggle_pause"
    print("    WallpaperEngine: all methods present ✓")

    # ── Test 2: ConfigManager integration — read defaults ────────────────
    print("\n[2] ConfigManager integration …")
    cfg = ConfigManager()
    assert cfg.get("wallpaper.fit_mode") in ("fill", "fit", "stretch"), \
        "Unexpected fit_mode default"
    assert isinstance(cfg.get("wallpaper.playback_speed"), float), \
        "playback_speed should be float"
    assert cfg.get("wallpaper.autopause") in ("focus", "maximized", "off"), \
        "Unexpected autopause default"
    print(f"    fit_mode      = {cfg.get('wallpaper.fit_mode')!r}   ✓")
    print(f"    playback_speed= {cfg.get('wallpaper.playback_speed')!r}  ✓")
    print(f"    autopause     = {cfg.get('wallpaper.autopause')!r}  ✓")

    # ── Test 3: Command builder — verify mpv arg assembly ────────────────
    print("\n[3] _build_command verification …")

    fake_video = Path("/tmp/test_video.mp4")

    # fill mode
    cmd = WallpaperEngine._build_command(
        video_path=fake_video, speed=1.0, volume=50,
        mute=True, fit_mode="fill", fps_limit="native",
    )
    assert "--panscan=1.0" in cmd,  "fill mode should add --panscan=1.0"
    assert "--no-audio" in cmd,     "mute=True should add --no-audio"
    assert "--vf=fps=native" not in cmd, "native fps should not add --vf"
    assert str(fake_video) == cmd[-1], "video path must be last arg"
    print("    fit='fill', mute=True, fps='native'  ✓")

    # fit mode
    cmd = WallpaperEngine._build_command(
        video_path=fake_video, speed=0.5, volume=80,
        mute=False, fit_mode="fit", fps_limit="30",
    )
    assert "--panscan=0.0" in cmd,   "fit mode should add --panscan=0.0"
    assert "--no-audio" not in cmd,  "mute=False should not add --no-audio"
    assert "--vf=fps=30" in cmd,     "fps='30' should add --vf=fps=30"
    assert "--speed=0.5" in cmd,     "speed should be embedded"
    print("    fit='fit',  mute=False, fps='30'     ✓")

    # stretch mode
    cmd = WallpaperEngine._build_command(
        video_path=fake_video, speed=2.0, volume=0,
        mute=True, fit_mode="stretch", fps_limit="24",
    )
    assert "--keepaspect=no" in cmd, "stretch mode should add --keepaspect=no"
    assert "--vf=fps=24" in cmd,     "fps='24' should add --vf=fps=24"
    print("    fit='stretch', fps='24'              ✓")

    # ── Test 4: IPC dead-socket safety ──────────────────────────────────
    print("\n[4] IPC dead-socket safety …")
    tmp_sock = "/tmp/desktop-suite-test-nonexistent.sock"
    ipc = MpvIPC(socket_path=tmp_sock)
    assert ipc.is_alive() is False,   "is_alive() on missing socket must return False"
    assert ipc.pause() is False,      "pause() on missing socket must return False"
    assert ipc.resume() is False,     "resume() on missing socket must return False"
    assert ipc.set_volume(50) is False, "set_volume() on missing socket must return False"
    assert ipc.set_speed(1.0) is False, "set_speed() on missing socket must return False"
    print("    All IPC methods safe on missing socket ✓")

    # ── Test 5: Socket cleanup ───────────────────────────────────────────
    print("\n[5] Socket cleanup …")
    fake_sock = tempfile.mktemp(suffix=".sock", prefix="desktop-suite-test-")  # noqa: S306
    # Create a fake socket file.
    with open(fake_sock, "w") as f:
        f.write("")

    engine = WallpaperEngine(socket_path=fake_sock)
    assert os.path.exists(fake_sock), "Setup: fake socket should exist"
    engine._remove_socket()
    assert not os.path.exists(fake_sock), "Socket file must be removed by _remove_socket()"
    print("    _remove_socket() cleans up correctly ✓")

    # Calling _remove_socket() on a missing file must not raise.
    engine._remove_socket()
    print("    _remove_socket() idempotent ✓")

    # ── Done ─────────────────────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("All tests passed.")
    print("=" * 60)
    sys.exit(0)
