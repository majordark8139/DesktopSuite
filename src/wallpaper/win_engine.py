"""
src.wallpaper.win_engine
========================
Native hardware-accelerated video wallpaper engine for Windows (Windows 7 SP1 / 8 / 10 / 11).
Optimized for Intel Core i3-4005U with Intel HD Graphics 4400.

Features (aligned with Gemini 4 Neon architecture):
1. Custom Win32 Host Class (DesktopSuiteWin7MpvHost) with hbrBackground=None and WM_ERASEBKGND->1
   to eliminate gray/black GDI flickers.
2. Parent Window Clipping: Forces WS_CLIPCHILDREN | WS_CLIPSIBLINGS on Explorer's WorkerW so
   desktop icon redraws never paint over video.
3. Dual-Backend Resilient Pipeline: Tries --vo=gpu --gpu-context=d3d11 --d3d11-flip=no with
   instant fallback to --vo=direct3d (Direct3D 9Ex) for rock-solid stability and lower RAM usage.
4. Binary Compatibility Verification: Catches exit code 0xC0000139 (STATUS_ENTRYPOINT_NOT_FOUND)
   to notify user if an incompatible Windows 10+ mpv build is detected.
5. Dynamic IPC pipe (\\\\.\\pipe\\mpv-livewal-<uuid8>) and debug log redirection.
6. Clean static wallpaper restoration upon stop/kill.
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
import tempfile
import threading
import time
from typing import Optional
import uuid

log = logging.getLogger(__name__)

# --- 64-bit Safe Pointer Types ---
LRESULT = ctypes.c_ssize_t
WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, WPARAM, LPARAM)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, LPARAM)

# --- Win32 Constants ---
GWL_STYLE = -16
GWL_EXSTYLE = -20

WS_CHILD = 0x40000000
WS_VISIBLE = 0x10000000
WS_CLIPSIBLINGS = 0x04000000
WS_CLIPCHILDREN = 0x02000000

WS_EX_NOPARENTNOTIFY = 0x00000004
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_NOACTIVATE = 0x08000000

WM_ERASEBKGND = 0x0014
CS_OWNDC = 0x0020

HWND_TOP = 0
HWND_BOTTOM = 1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
SWP_SHOWWINDOW = 0x0040

SMTO_NORMAL = 0x0000
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

STATUS_ENTRYPOINT_NOT_FOUND = 0xC0000139  # -1073741511 signed

# Win32 Ctypes 64-bit safety setup
if sys.platform == "win32":
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    try:
        dwmapi = ctypes.windll.dwmapi
    except Exception:
        dwmapi = None

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT),
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
            ("hIconSm", wintypes.HICON),
        ]

    user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.DefWindowProcW.restype = LRESULT

    user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t

    user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
    user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND

    user32.FindWindowExW.argtypes = [wintypes.HWND, wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowExW.restype = wintypes.HWND

    user32.SetParent.argtypes = [wintypes.HWND, wintypes.HWND]
    user32.SetParent.restype = wintypes.HWND

    user32.SetWindowPos.argtypes = [
        wintypes.HWND, wintypes.HWND,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.UINT
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    user32.DestroyWindow.argtypes = [wintypes.HWND]
    user32.DestroyWindow.restype = wintypes.BOOL

    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL

    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL

    user32.SystemParametersInfoW.argtypes = [ctypes.c_uint, ctypes.c_uint, wintypes.LPCWSTR, ctypes.c_uint]
    user32.SystemParametersInfoW.restype = wintypes.BOOL

    user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.RedrawWindow.restype = wintypes.BOOL

    @WNDPROC
    def _host_wnd_proc(hwnd, msg, wparam, lparam):
        if msg == WM_ERASEBKGND:
            return 1  # Suppress GDI background erasing to eliminate flicker
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    _HOST_CLASS_NAME = "DesktopSuiteWin7MpvHost"
    _HOST_CLASS_REGISTERED = False

    def _ensure_host_class_registered() -> None:
        global _HOST_CLASS_REGISTERED
        if _HOST_CLASS_REGISTERED:
            return

        hinstance = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.style = CS_OWNDC
        wc.lpfnWndProc = _host_wnd_proc
        wc.hInstance = hinstance
        wc.hbrBackground = None  # No brush -> zero GDI BTNFACE flash
        wc.lpszClassName = _HOST_CLASS_NAME

        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom and kernel32.GetLastError() != 1410:  # ERROR_CLASS_ALREADY_EXISTS
            raise ctypes.WinError()
        _HOST_CLASS_REGISTERED = True


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

                # Don't pause when our own Control Center or Canvas has focus
                fg_pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
                if fg_pid.value == os.getpid():
                    should_pause = False
                else:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd, buf, 256)
                    cls_name = buf.value

                    if cls_name in ("Progman", "WorkerW", "Shell_TrayWnd", "DesktopCanvasWindow", "DesktopSuiteWin7MpvHost"):
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
    Windows Live Wallpaper Engine embedding mpv into desktop background.
    Uses a sacrificial child host window attached to WorkerW with custom WndProc,
    parent WS_CLIPCHILDREN clipping, and dual-backend fallback (d3d11 -> direct3d).
    """

    def __init__(self) -> None:
        self._proc: Optional[subprocess.Popen] = None
        self._ipc: Optional[WinMpvIPC] = None
        self._autopause: Optional[WinAutoPauseWatcher] = None
        self.host_hwnd: Optional[int] = None
        self._worker_hwnd: Optional[int] = None
        self._progman_hwnd: Optional[int] = None
        self.ipc_pipe_path: Optional[str] = None
        self.last_error_message: str = ""
        self.log_path = os.path.join(tempfile.gettempdir(), "desktopsuite_mpv.log")
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
    # 2. Windows 7 Aero (DWM) Detection
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

    # -----------------------------------------------------------------------
    # 3. WorkerW Discovery & Layer Splitting with WS_CLIPCHILDREN
    # -----------------------------------------------------------------------
    def _find_workerw_behind_icons(self) -> Optional[int]:
        if sys.platform != "win32":
            return None
        found_workerw = ctypes.c_void_p(0)

        def _enum_cb(hwnd, _lparam):
            def_view = user32.FindWindowExW(hwnd, None, "SHELLDLL_DefView", None)
            if def_view:
                workerw = user32.FindWindowExW(None, hwnd, "WorkerW", None)
                if workerw:
                    found_workerw.value = workerw
                    return False
            return True

        cb = WNDENUMPROC(_enum_cb)
        user32.EnumWindows(cb, 0)

        if not found_workerw.value:
            def _find_any_workerw(hwnd, _lparam):
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

        workerw = self._find_workerw_behind_icons()
        if not workerw or not user32.IsWindow(workerw):
            result = ctypes.c_ulonglong(0)
            user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0, 0, SMTO_NORMAL, 1000, ctypes.byref(result))
            user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0xD, 0x1, SMTO_NORMAL, 1000, ctypes.byref(result))
            workerw = self._find_workerw_behind_icons()

        if not workerw:
            log.warning("Dedicated WorkerW not found; using Progman as background target")
            workerw = self._progman_hwnd

        # Ensure WorkerW clips its child host_hwnd so Explorer never draws over video
        style = user32.GetWindowLongPtrW(workerw, GWL_STYLE)
        new_style = style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
        if new_style != style:
            user32.SetWindowLongPtrW(workerw, GWL_STYLE, new_style)
            user32.SetWindowPos(
                workerw, 0, 0, 0, 0, 0,
                SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
            )

        user32.ShowWindow(workerw, SW_SHOW)
        self._worker_hwnd = workerw
        return workerw

    # -----------------------------------------------------------------------
    # 4. Sacrificial Host Child HWND Creation (Custom Class)
    # -----------------------------------------------------------------------
    def _create_sacrificial_host_hwnd(self, parent_workerw: int) -> int:
        _ensure_host_class_registered()

        rect = wintypes.RECT()
        user32.GetClientRect(parent_workerw, ctypes.byref(rect))
        width = max(1, rect.right - rect.left)
        height = max(1, rect.bottom - rect.top)

        hinstance = kernel32.GetModuleHandleW(None)
        hwnd = user32.CreateWindowExW(
            WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_NOPARENTNOTIFY,
            _HOST_CLASS_NAME,
            "DesktopSuiteMpvHost",
            WS_CHILD | WS_VISIBLE | WS_CLIPSIBLINGS | WS_CLIPCHILDREN,
            0, 0, width, height,
            parent_workerw,
            None,
            hinstance,
            None,
        )
        if not hwnd:
            raise ctypes.WinError()

        user32.SetParent(hwnd, parent_workerw)
        user32.ShowWindow(hwnd, SW_SHOW)
        user32.SetWindowPos(
            hwnd, HWND_TOP, 0, 0, width, height,
            SWP_NOACTIVATE | SWP_SHOWWINDOW | SWP_FRAMECHANGED
        )
        log.info("Created sacrificial host HWND %s on parent WorkerW %s (%dx%d)", hwnd, parent_workerw, width, height)
        return hwnd

    # -----------------------------------------------------------------------
    # 5. Start / Stop / Restart Control
    # -----------------------------------------------------------------------
    def is_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return False

    def _build_cmd(
        self,
        mpv_bin: str,
        host_hwnd: int,
        video_path: str,
        backend: str,
        speed: float,
        volume: int,
        mute: bool,
        fit_mode: str,
        fps_limit: str,
    ) -> list[str]:
        if backend == "d3d11":
            vo_flags = [
                "--vo=gpu",
                "--gpu-api=d3d11",
                "--gpu-context=d3d11",
                "--d3d11-flip=no",          # Mandatory on Windows 7 DXGI 1.2
                "--d3d11-sync-interval=1",
                "--hwdec=dxva2-copy",       # Stable hardware decode on Intel HD 4400
                "--profile=fast",
                "--scale=bilinear",
                "--cscale=bilinear",
                "--dscale=bilinear",
                "--deband=no",
            ]
        else:
            # Direct3D 9Ex fallback: minimal RAM, works with or without Aero
            vo_flags = [
                "--vo=direct3d",
                "--hwdec=dxva2-copy",
            ]

        cmd = [
            mpv_bin,
            f"--wid={int(host_hwnd)}",
            *vo_flags,
            "--loop-file=inf",
            "--cache=no",
            "--demuxer-max-bytes=15M",
            "--no-osc",
            "--no-osd-bar",
            "--no-border",
            "--no-window-dragging",
            "--no-input-default-bindings",
            "--no-input-cursor",
            "--keep-open=yes",
            f"--speed={speed:.2f}",
            f"--volume={volume}",
            f"--input-ipc-server={self.ipc_pipe_path}",
            f"--log-file={self.log_path}",
            "--msg-level=all=warn,vo=v,hwdec=v",
        ]
        if mute:
            cmd.append("--no-audio")
        if fit_mode == "fill":
            cmd.append("--panscan=1.0")
        elif fit_mode == "fit":
            cmd.append("--panscan=0.0")
        elif fit_mode == "stretch":
            cmd.append("--keepaspect=no")
        if fps_limit != "native":
            cmd.append(f"--vf=fps={fps_limit}")

        cmd.append(str(video_path))
        return cmd

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
        self.stop(restore_wallpaper=False)

        mpv_bin = self.find_mpv()
        if not mpv_bin:
            self.last_error_message = "mpv.exe binary not found. Please ensure assets/bin/mpv.exe is present."
            log.error(self.last_error_message)
            return False

        if not Path(video_path).is_file():
            self.last_error_message = f"Wallpaper video not found: {video_path}"
            log.error(self.last_error_message)
            return False

        if sys.platform != "win32":
            log.warning("WinWallpaperEngine invoked on non-Windows platform")
            return False

        workerw = self.ensure_workerw()
        aero_active = self.is_dwm_aero_enabled()

        # Try d3d11 first if Aero is active, otherwise direct3d
        backends = ["d3d11", "direct3d"] if aero_active else ["direct3d"]

        for backend in backends:
            try:
                self.host_hwnd = self._create_sacrificial_host_hwnd(workerw)
            except Exception as exc:
                log.error("Failed to create sacrificial host HWND: %s", exc)
                self.host_hwnd = workerw

            unique_id = uuid.uuid4().hex[:8]
            self.ipc_pipe_path = rf"\\.\pipe\mpv-livewal-{unique_id}"
            self._ipc = WinMpvIPC(self.ipc_pipe_path)

            cmd = self._build_cmd(
                mpv_bin, self.host_hwnd, video_path, backend,
                speed, volume, mute, fit_mode, fps_limit
            )

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                log.error("Failed to spawn mpv process: %s", exc)
                self._destroy_host_only()
                continue

            # Health-check startup for 0.6 seconds to catch instant crashes
            time.sleep(0.6)
            rc = self._proc.poll()
            if rc is None:
                log.info("mpv successfully running on %s backend (PID %s, pipe %s)", backend, self._proc.pid, self.ipc_pipe_path)
                self._autopause = WinAutoPauseWatcher(self._ipc, mode=autopause)
                self._autopause.start()
                return True

            # Process exited immediately
            unsigned_rc = rc & 0xFFFFFFFF
            self._proc = None
            self._destroy_host_only()

            if unsigned_rc == STATUS_ENTRYPOINT_NOT_FOUND:
                self.last_error_message = (
                    "mpv.exe is incompatible with Windows 7 (STATUS_ENTRYPOINT_NOT_FOUND 0xC0000139). "
                    "Use the bundled Windows 7 compatible mpv build (2023-08-27 / 2023-09-17)."
                )
                log.error(self.last_error_message)
                return False

            log.warning("Backend %s failed with exit code %s; trying fallback...", backend, rc)

        self.last_error_message = f"mpv failed to initialize video output. Check {self.log_path}"
        log.error(self.last_error_message)
        self.stop(restore_wallpaper=True)
        return False

    def _destroy_host_only(self) -> None:
        if sys.platform == "win32" and self.host_hwnd and user32.IsWindow(self.host_hwnd):
            user32.DestroyWindow(self.host_hwnd)
        self.host_hwnd = None

    def stop(self, restore_wallpaper: bool = True) -> None:
        """
        Cleanly terminates mpv, destroys sacrificial host HWND, and repaints desktop.
        """
        if self._autopause:
            self._autopause.stop()
            self._autopause = None

        if self._proc is not None:
            if self._proc.poll() is None:
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
        self._destroy_host_only()

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
            for hwnd in (self._worker_hwnd, self._progman_hwnd):
                if hwnd and user32.IsWindow(hwnd):
                    user32.RedrawWindow(hwnd, None, None, flags)
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
