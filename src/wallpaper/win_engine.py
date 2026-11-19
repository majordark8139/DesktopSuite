"""
src.wallpaper.win_engine
========================
Native hardware-accelerated video wallpaper engine for Windows (Windows 7 SP1 / 8 / 10 / 11).
Optimized for Intel Core i3-4005U with Intel HD Graphics 4400.

Features:
1. Sacrificial Child Host HWND architecture: Never passes WorkerW directly to mpv --wid,
   preventing WorkerW Direct3D swapchain lockup, black screens, and pixel-format corruption
   across repeated Start / Stop / Kill / Restart cycles.
2. Unique per-spawn named pipe (\\\\.\\pipe\\mpv-livewal-<uuid8>) eliminating NPFS zombie pipe collisions.
3. Windows 7 DWM Aero detection with automatic fallback to Direct3D 9 (--vo=direct3d) when
   Aero / Desktop Composition is disabled (Windows 7 Basic / Classic themes).
4. Clean wallpaper restoration (SystemParametersInfoW SPI_SETDESKWALLPAPER + RedrawWindow)
   upon stop or kill to erase residual video frames from Progman and WorkerW.
"""

from __future__ import annotations

import atexit
import ctypes
from ctypes import wintypes
import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
from typing import Optional
import uuid

log = logging.getLogger(__name__)

# Win32 Constants
SMTO_NORMAL = 0x0000
SMTO_ABORTIFHUNG = 0x0002

WS_POPUP = 0x80000000
WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOOLWINDOW = 0x00000080

SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_BOTTOM = 1

SPI_SETDESKWALLPAPER = 0x0014
SPIF_SENDCHANGE = 0x0002

RDW_INVALIDATE = 0x0001
RDW_INTERNALPAINT = 0x0002
RDW_ERASE = 0x0004
RDW_ALLCHILDREN = 0x0080
RDW_UPDATENOW = 0x0100
RDW_FRAME = 0x0400

SM_CXSCREEN = 0
SM_CYSCREEN = 1

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

# Win32 Ctypes 64-bit safety setup
if sys.platform == "win32":
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    kernel32 = ctypes.windll.kernel32
    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        dwmapi = None

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND

    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND

    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL

    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, wintypes.LPCWSTR, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = wintypes.BOOL

    user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.RedrawWindow.restype = wintypes.BOOL


class WinMpvIPC:
    """JSON-IPC client for mpv running on Windows via dynamic named pipe."""

    def __init__(self, pipe_path: str, timeout: float = 0.5) -> None:
        self.pipe_path = pipe_path
        self.timeout = timeout

    def send_command(self, cmd_list: list) -> Optional[dict]:
        payload = json.dumps({"command": cmd_list}) + "\n"
        try:
            with open(self.pipe_path, "r+b", buffering=0) as pipe:
                pipe.write(payload.encode("utf-8"))
                line = pipe.readline()
                if line:
                    return json.loads(line.decode("utf-8", errors="replace"))
        except Exception:
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
        if sys.platform != "win32":
            return
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

                if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd", "DesktopCanvasWindow", "DesktopSuiteMpvHost"):
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
    Production Windows Live Wallpaper Engine embedding mpv into desktop background.
    Uses a sacrificial child host window attached to WorkerW to guarantee pristine WorkerW
    state across thousands of Start / Stop / Kill / Restart cycles.
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._ipc: Optional[WinMpvIPC] = None
        self._autopause: Optional[WinAutoPauseWatcher] = None
        self.host_hwnd: Optional[int] = None
        self._worker_hwnd: Optional[int] = None
        self._progman_hwnd: Optional[int] = None
        self.ipc_pipe_path: Optional[str] = None
        atexit.register(self.stop)

    # -----------------------------------------------------------------------
    # 1. MPV Discovery
    # -----------------------------------------------------------------------
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

    # -----------------------------------------------------------------------
    # 2. Windows 7 Aero (DWM) Detection & Recovery
    # -----------------------------------------------------------------------
    @staticmethod
    def is_dwm_aero_enabled() -> bool:
        if sys.platform != "win32" or dwmapi is None:
            return True
        enabled = wintypes.BOOL(False)
        try:
            hr = dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled))
            return (hr == 0) and bool(enabled.value)
        except Exception:
            return True

    def try_enable_dwm_aero(self) -> bool:
        if self.is_dwm_aero_enabled():
            return True
        if sys.platform == "win32" and dwmapi is not None:
            try:
                dwmapi.DwmEnableComposition(1)
                time.sleep(0.15)
            except Exception:
                pass
        return self.is_dwm_aero_enabled()

    # -----------------------------------------------------------------------
    # 3. WorkerW Discovery & Layer Splitting
    # -----------------------------------------------------------------------
    def _find_workerw_behind_icons(self) -> Optional[int]:
        if sys.platform != "win32":
            return None
        found_workerw = ctypes.c_void_p(0)

        def _enum_proc(hwnd, lparam):
            def_view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if def_view:
                workerw = user32.FindWindowExW(None, hwnd, "WorkerW", None)
                if workerw:
                    found_workerw.value = workerw
                    return False
            return True

        cb = WNDENUMPROC(_enum_proc)
        user32.EnumWindows(cb, 0)

        if not found_workerw.value:
            # Fallback search if not direct sibling
            def _find_any_workerw(hwnd, lparam):
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, buf, 256)
                if buf.value == "WorkerW":
                    if not user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None):
                        found_workerw.value = hwnd
                        return False
                return True
            user32.EnumWindows(WNDENUMPROC(_find_any_workerw), 0)

        return found_workerw.value if found_workerw.value else None

    def ensure_workerw(self) -> int:
        if sys.platform != "win32":
            return 0
        self._progman_hwnd = user32.FindWindowW("Progman", None)

        existing = self._find_workerw_behind_icons()
        if existing and user32.IsWindow(existing):
            self._worker_hwnd = existing
            return existing

        # Send 0x052C to Progman to split the desktop layer
        result = ctypes.c_ulonglong(0)
        user32.SendMessageTimeoutW(
            self._progman_hwnd, 0x052C, 0, 0,
            SMTO_NORMAL, 1000, ctypes.byref(result)
        )
        user32.SendMessageTimeoutW(
            self._progman_hwnd, 0x052C, 0xD, 0x1,
            SMTO_NORMAL, 1000, ctypes.byref(result)
        )

        workerw = self._find_workerw_behind_icons()
        if not workerw:
            log.warning("Dedicated WorkerW not found; using Progman as background target")
            workerw = self._progman_hwnd

        self._worker_hwnd = workerw
        return workerw

    # -----------------------------------------------------------------------
    # 4. Sacrificial Host Child HWND Creation
    # -----------------------------------------------------------------------
    def _create_sacrificial_host_hwnd(self, parent_workerw: int) -> int:
        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)

        hinstance = kernel32.GetModuleHandleW(None)
        hwnd = user32.CreateWindowExW(
            WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            "STATIC",
            "DesktopSuiteMpvHost",
            WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN,
            0, 0, screen_w, screen_h,
            parent_workerw,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError()

        user32.SetParent(hwnd, parent_workerw)
        user32.SetWindowPos(
            hwnd, HWND_BOTTOM, 0, 0, screen_w, screen_h,
            SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        log.info("Created sacrificial host HWND %s on parent WorkerW %s", hwnd, parent_workerw)
        return hwnd

    # -----------------------------------------------------------------------
    # 5. Start / Stop / Restart Control
    # -----------------------------------------------------------------------
    def is_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return False

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
        # Tear down any previous instance cleanly
        self.stop(restore_wallpaper=False)

        mpv_bin = self.find_mpv()
        if not mpv_bin:
            log.error("mpv binary not found on Windows")
            return False

        if not Path(video_path).is_file():
            log.error("Wallpaper video not found: %s", video_path)
            return False

        if sys.platform != "win32":
            log.warning("WinWallpaperEngine invoked on non-Windows platform")
            return False

        aero_active = self.try_enable_dwm_aero()
        workerw = self.ensure_workerw()

        # Create sacrificial host HWND
        try:
            self.host_hwnd = self._create_sacrificial_host_hwnd(workerw)
        except Exception as exc:
            log.error("Failed to create sacrificial host HWND: %s", exc)
            self.host_hwnd = workerw

        # Unique named pipe per spawn
        unique_id = uuid.uuid4().hex[:8]
        self.ipc_pipe_path = rf"\\.\pipe\mpv-livewal-{unique_id}"
        self._ipc = WinMpvIPC(self.ipc_pipe_path)

        # Select optimal video output flags
        if aero_active:
            vo_args = ["--vo=gpu", "--gpu-context=d3d11", "--hwdec=dxva2-copy"]
        else:
            vo_args = ["--vo=direct3d", "--hwdec=dxva2-copy"]

        args = [
            mpv_bin,
            f"--wid={int(self.host_hwnd)}",
            *vo_args,
            "--loop=inf",
            "--cache=no",
            "--demuxer-max-bytes=15M",
            "--no-osc",
            "--no-osd-bar",
            "--no-input-default-bindings",
            "--keep-open=no",
            f"--speed={speed:.2f}",
            f"--volume={volume}",
            f"--input-ipc-server={self.ipc_pipe_path}",
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
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log.info("Started mpv (PID %s) on host HWND %s (pipe %s)", self._proc.pid, self.host_hwnd, self.ipc_pipe_path)

            time.sleep(0.3)
            self._autopause = WinAutoPauseWatcher(self._ipc, mode=autopause)
            self._autopause.start()
            return True
        except Exception as exc:
            log.error("Failed to launch mpv: %s", exc)
            self.stop(restore_wallpaper=True)
            return False

    def stop(self, restore_wallpaper: bool = True) -> None:
        """
        Cleanly terminates mpv, destroys sacrificial host HWND, and repaints desktop.
        """
        if self._autopause:
            self._autopause.stop()
            self._autopause = None

        if self._proc is not None:
            if self._proc.poll() is None:
                # 1. Graceful quit over IPC
                if self._ipc:
                    self._ipc.send_command(["quit"])
                try:
                    self._proc.wait(timeout=0.4)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    try:
                        self._proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
            self._proc = None

        self._ipc = None
        self.ipc_pipe_path = None

        # 2. Destroy the sacrificial host HWND
        if sys.platform == "win32" and self.host_hwnd and user32.IsWindow(self.host_hwnd):
            user32.DestroyWindow(self.host_hwnd)
        self.host_hwnd = None

        # 3. Restore static wallpaper
        if restore_wallpaper and sys.platform == "win32":
            self.refresh_desktop_wallpaper()

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
        self.stop(restore_wallpaper=False)
        return self.start(video_path, speed, volume, mute, fit_mode, fps_limit, autopause)

    def refresh_desktop_wallpaper(self) -> None:
        """Repaint the static desktop wallpaper and force repaint of WorkerW and Progman."""
        if sys.platform != "win32":
            return
        try:
            user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, None, SPIF_SENDCHANGE)
            flags = RDW_ERASE | RDW_INVALIDATE | RDW_INTERNALPAINT | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME
            if self._worker_hwnd and user32.IsWindow(self._worker_hwnd):
                user32.RedrawWindow(self._worker_hwnd, None, None, flags)
            if self._progman_hwnd and user32.IsWindow(self._progman_hwnd):
                user32.RedrawWindow(self._progman_hwnd, None, None, flags)
        except Exception as exc:
            log.debug("refresh_desktop_wallpaper error: %s", exc)

    def toggle_pause(self) -> bool:
        if not self._ipc or not self._ipc.is_alive():
            return False
        res = self._ipc.send_command(["get_property", "pause"])
        if res and "data" in res:
            is_paused = bool(res["data"])
            return self._ipc.resume() if is_paused else self._ipc.pause()
        return False

    def set_volume(self, vol: int) -> None:
        if self._ipc:
            self._ipc.set_volume(vol)

    def set_speed(self, speed: float) -> None:
        if self._ipc:
            self._ipc.set_speed(speed)

    def set_mute(self, mute: bool) -> None:
        if self._ipc:
            self._ipc.set_mute(mute)
