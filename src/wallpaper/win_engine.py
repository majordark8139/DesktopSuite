"""
src.wallpaper.win_engine
========================
Native hardware-accelerated video wallpaper engine for Windows (Windows 7 / 8 / 10 / 11).

Embeds mpv into the Windows desktop background using the WorkerW / Progman message trick:
1. Sends message 0x052C to Progman.
2. Locates the WorkerW window positioned immediately behind desktop icons (SHELLDLL_DefView).
3. Spawns mpv with ``--wid=<HWND>``, ``--vo=gpu``, and hardware decoding (DXVA2 / D3D11).
4. Provides named-pipe JSON IPC (\\\\.\\pipe\\mpv-livewal) and automatic pause/resume.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import json
import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional, Literal

log = logging.getLogger(__name__)

WIN_MPV_PIPE = r"\\.\pipe\mpv-livewal"

# Windows API constants
SMTO_NORMAL = 0x0000
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SW_HIDE = 0
SW_SHOW = 5


def get_workerw_hwnd() -> Optional[int]:
    """
    Locate or spawn the WorkerW window immediately behind desktop icons.
    Compatible with Windows 7, Windows 8, Windows 10, and Windows 11.
    """
    user32 = ctypes.windll.user32
    progman = user32.FindWindowW("Progman", None)
    if not progman:
        log.error("Could not find Progman window")
        return None

    # Send undocumented message 0x052C to Progman to split desktop layers
    result = wintypes.DWORD()
    user32.SendMessageTimeoutW(
        progman, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result)
    )

    worker_w = None
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def enum_windows_callback(hwnd, lparam):
        nonlocal worker_w
        shell_view = user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None)
        if shell_view:
            target = user32.FindWindowExW(0, hwnd, "WorkerW", None)
            if target:
                worker_w = target
                return False
        return True

    user32.EnumWindows(WNDENUMPROC(enum_windows_callback), 0)

    # Fallback search if not found directly as sibling
    if not worker_w:
        def find_workerw(hwnd, lparam):
            nonlocal worker_w
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == "WorkerW":
                if not user32.FindWindowExW(hwnd, 0, "SHELLDLL_DefView", None):
                    worker_w = hwnd
                    return False
            return True
        user32.EnumWindows(WNDENUMPROC(find_workerw), 0)

    if not worker_w:
        log.warning("Dedicated WorkerW not found; using Progman as background target")
        worker_w = progman

    return int(worker_w)


class WinMpvIPC:
    """
    JSON-IPC client for mpv running on Windows via named pipe (\\\\.\\pipe\\mpv-livewal).
    """

    def __init__(self, pipe_path: str = WIN_MPV_PIPE, timeout: float = 1.0) -> None:
        self.pipe_path = pipe_path
        self.timeout = timeout

    def send_command(self, cmd_list: list) -> Optional[dict]:
        payload = json.dumps({"command": cmd_list}) + "\n"
        try:
            # Open Windows named pipe in binary mode
            with open(self.pipe_path, "r+b", buffering=0) as pipe:
                pipe.write(payload.encode("utf-8"))
                # Read response line
                line = pipe.readline()
                if line:
                    return json.loads(line.decode("utf-8", errors="replace"))
        except Exception as exc:
            log.debug("WinMpvIPC send_command %s failed: %s", cmd_list, exc)
            return None
        return None

    def is_alive(self) -> bool:
        res = self.send_command(["get_property", "pause"])
        return res is not None and "data" in res

    def pause(self) -> bool:
        res = self.send_command(["set_property", "pause", True])
        return res is not None and res.get("error") == "success"

    def resume(self) -> bool:
        res = self.send_command(["set_property", "pause", False])
        return res is not None and res.get("error") == "success"

    def set_volume(self, vol: int) -> bool:
        res = self.send_command(["set_property", "volume", max(0, min(100, vol))])
        return res is not None and res.get("error") == "success"

    def set_mute(self, mute: bool) -> bool:
        res = self.send_command(["set_property", "mute", mute])
        return res is not None and res.get("error") == "success"

    def set_speed(self, speed: float) -> bool:
        res = self.send_command(["set_property", "speed", speed])
        return res is not None and res.get("error") == "success"


class WinAutoPauseWatcher:
    """
    Monitors active foreground window state on Windows to pause mpv when
    applications are maximized or fullscreen, saving GPU and battery.
    """

    def __init__(self, ipc: WinMpvIPC, mode: str = "focus", interval: float = 0.5) -> None:
        self.ipc = ipc
        self.mode = mode
        self.interval = interval
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_paused = False

    def start(self) -> None:
        if self.mode == "off":
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="win-autopause")
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None

    def _loop(self) -> None:
        user32 = ctypes.windll.user32
        sw = user32.GetSystemMetrics(SM_CXSCREEN)
        sh = user32.GetSystemMetrics(SM_CYSCREEN)

        while not self._stop_event.is_set():
            try:
                hwnd = user32.GetForegroundWindow()
                if not hwnd:
                    time.sleep(self.interval)
                    continue

                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                cls_name = buf.value

                # Desktop elements where wallpaper should continue playing
                if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd", "DesktopCanvasWindow"):
                    should_pause = False
                elif self.mode == "focus":
                    should_pause = True
                elif self.mode == "maximized":
                    is_zoomed = bool(user32.IsZoomed(hwnd))
                    rect = wintypes.RECT()
                    user32.GetWindowRect(hwnd, ctypes.byref(rect))
                    is_fullscreen = (
                        rect.left <= 0 and rect.top <= 0 and
                        rect.right >= sw and rect.bottom >= sh
                    )
                    should_pause = is_zoomed or is_fullscreen
                else:
                    should_pause = False

                if should_pause != self._is_paused:
                    if should_pause:
                        self.ipc.pause()
                    else:
                        self.ipc.resume()
                    self._is_paused = should_pause
            except Exception as exc:
                log.debug("WinAutoPauseWatcher error: %s", exc)

            time.sleep(self.interval)


class WinWallpaperEngine:
    """
    Windows Live Wallpaper engine embedding mpv into WorkerW.
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._ipc = WinMpvIPC()
        self._autopause: Optional[WinAutoPauseWatcher] = None
        self._worker_hwnd: Optional[int] = None
        atexit.register(self.stop)

    @staticmethod
    def find_mpv() -> Optional[str]:
        """Locate mpv executable in assets/bin, PATH, or common install locations."""
        candidates = []
        if getattr(sys, "frozen", False):
            exe_dir = Path(sys.executable).resolve().parent
            candidates.append(exe_dir / "assets" / "bin" / "mpv.exe")
            candidates.append(exe_dir / "_internal" / "assets" / "bin" / "mpv.exe")
            if hasattr(sys, "_MEIPASS"):
                candidates.append(Path(sys._MEIPASS) / "assets" / "bin" / "mpv.exe")
        candidates.append(Path(__file__).resolve().parent.parent.parent / "assets" / "bin" / "mpv.exe")
        candidates.append(Path.cwd() / "assets" / "bin" / "mpv.exe")

        for c in candidates:
            if c.is_file():
                return str(c)

        which = shutil.which("mpv") or shutil.which("mpv.exe")
        if which:
            return which

        for candidate in [
            r"C:\Program Files\mpv\mpv.exe",
            r"C:\tools\mpv\mpv.exe",
            r"C:\mpv\mpv.exe",
        ]:
            if os.path.isfile(candidate):
                return candidate
        return None

    def is_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return self._ipc.is_alive()

    def start(
        self,
        video_path: str,
        speed: float = 1.0,
        volume: int = 50,
        mute: bool = True,
        fit_mode: str = "fill",
        fps_limit: str = "native",
        autopause: str = "focus",
    ) -> bool:
        self.stop()

        mpv_bin = self.find_mpv()
        if not mpv_bin:
            log.error("mpv binary not found on Windows")
            return False

        if not Path(video_path).is_file():
            log.error("Wallpaper video not found: %s", video_path)
            return False

        self._worker_hwnd = get_workerw_hwnd()
        if not self._worker_hwnd:
            log.error("Could not obtain desktop background window handle (WorkerW)")
            return False

        args = [
            mpv_bin,
            f"--wid={self._worker_hwnd}",
            "--loop=inf",
            "--vo=gpu",
            "--hwdec=dxva2-copy",
            "--cache=no",
            "--demuxer-max-bytes=15M",
            "--no-osc",
            "--no-osd-bar",
            f"--speed={speed:.2f}",
            f"--volume={volume}",
            f"--input-ipc-server={WIN_MPV_PIPE}",
        ]
        if mute:
            args.append("--no-audio")
        if fit_mode == "fill":
            args.append("--panscan=1.0")
        elif fit_mode == "fit":
            args.append("--panscan=0.0")
        elif fit_mode == "stretch":
            args.append("--keepaspect=no")
        if fps_limit != "native":
            args.append(f"--vf=fps={fps_limit}")

        args.append(str(video_path))

        try:
            # CREATE_NO_WINDOW = 0x08000000
            self._proc = subprocess.Popen(
                args,
                creationflags=0x08000000,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Started Windows live wallpaper process (PID %s) on HWND %s", self._proc.pid, self._worker_hwnd)

            # Wait briefly for pipe creation
            time.sleep(0.3)

            # Start autopause watcher
            self._autopause = WinAutoPauseWatcher(self._ipc, mode=autopause)
            self._autopause.start()
            return True
        except Exception as exc:
            log.error("Failed to launch mpv wallpaper on Windows: %s", exc)
            return False

    def stop(self) -> None:
        if self._autopause:
            self._autopause.stop()
            self._autopause = None

        if self._proc is not None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=1.5)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass
            self._proc = None

    def restart(
        self,
        video_path: str,
        speed: float = 1.0,
        volume: int = 50,
        mute: bool = True,
        fit_mode: str = "fill",
        fps_limit: str = "native",
        autopause: str = "focus",
    ) -> bool:
        self.stop()
        return self.start(video_path, speed, volume, mute, fit_mode, fps_limit, autopause)

    def toggle_pause(self) -> bool:
        if not self._ipc.is_alive():
            return False
        res = self._ipc.send_command(["get_property", "pause"])
        if res and "data" in res:
            is_paused = bool(res["data"])
            if is_paused:
                return self._ipc.resume()
            else:
                return self._ipc.pause()
        return False

    def set_volume(self, vol: int) -> None:
        self._ipc.set_volume(vol)

    def set_speed(self, speed: float) -> None:
        self._ipc.set_speed(speed)

    def set_mute(self, mute: bool) -> None:
        self._ipc.set_mute(mute)
