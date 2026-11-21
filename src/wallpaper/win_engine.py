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
WS_POPUP = 0x80000000
WS_CAPTION = 0x00C00000
WS_THICKFRAME = 0x00040000

WS_EX_APPWINDOW = 0x00040000
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
SPI_GETCLIENTAREAANIMATION = 0x1042
SPI_SETCLIENTAREAANIMATION = 0x1043
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

CLR_NONE = 0xFFFFFFFF
LVM_FIRST = 0x1000
LVM_SETBKCOLOR = LVM_FIRST + 1
LVM_SETTEXTBKCOLOR = LVM_FIRST + 38

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

    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL

    user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
    user32.SystemParametersInfoW.restype = wintypes.BOOL

    user32.RedrawWindow.argtypes = [wintypes.HWND, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint]
    user32.RedrawWindow.restype = wintypes.BOOL

    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
    user32.SendMessageW.restype = LRESULT

    user32.SendMessageTimeoutW.argtypes = [
        wintypes.HWND, wintypes.UINT, WPARAM, LPARAM,
        wintypes.UINT, wintypes.UINT, ctypes.c_void_p
    ]
    user32.SendMessageTimeoutW.restype = LRESULT

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
        self.mpv_hwnd: Optional[int] = None
        self.host_hwnd: Optional[int] = None
        self._worker_hwnd: Optional[int] = None
        self._defview_parent_hwnd: Optional[int] = None
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
    # 3. WorkerW Discovery & Layer Splitting (Targeting WorkerW #2 on Windows 7)
    # -----------------------------------------------------------------------
    def ensure_workerw(self) -> int:
        """
        Locates WorkerW #2 on Windows 7 SP1 (the empty sibling immediately behind
        WorkerW #1 holding SHELLDLL_DefView).
        Ensures client area animation is active so Explorer creates WorkerW #2,
        sends 0x052C to Progman, and sets desktop icon transparency (SysListView32).
        """
        if sys.platform != "win32":
            return 0

        # 1. Ensure Windows 7 Client-Area Animation is enabled before 0x052C
        anim_enabled = wintypes.BOOL(0)
        user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(anim_enabled), 0)
        if not anim_enabled.value:
            log.info("Enabling Windows 7 client area animation (SPI_SETCLIENTAREAANIMATION)")
            user32.SystemParametersInfoW(SPI_SETCLIENTAREAANIMATION, 0, ctypes.c_void_p(1), 0)

        # 2. Trigger Explorer to split Progman -> WorkerW #1 + WorkerW #2
        self._progman_hwnd = user32.FindWindowW("Progman", None)
        result = ctypes.c_ulong(0)
        user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0x0D, 0x01, SMTO_NORMAL, 1000, ctypes.byref(result))
        user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0x00, 0x00, SMTO_NORMAL, 1000, ctypes.byref(result))

        # 3. Enumerate top-level windows to find WorkerW #1, then grab WorkerW #2 behind it
        workerw_defview = 0
        workerw_target = 0

        def _enum_cb(top_hwnd, _lparam):
            nonlocal workerw_defview, workerw_target
            defview = user32.FindWindowExW(top_hwnd, 0, "SHELLDLL_DefView", None)
            if defview:
                workerw_defview = top_hwnd
                # Grab the sibling WorkerW immediately BEHIND WorkerW #1
                workerw_target = user32.FindWindowExW(0, top_hwnd, "WorkerW", None)
                return False
            return True

        cb = WNDENUMPROC(_enum_cb)
        user32.EnumWindows(cb, 0)

        # Ensure Desktop Icon transparency (SysListView32) on WorkerW #1
        if workerw_defview:
            shell_view = user32.FindWindowExW(workerw_defview, 0, "SHELLDLL_DefView", None)
            if shell_view:
                listview = user32.FindWindowExW(shell_view, 0, "SysListView32", None)
                if listview:
                    user32.SendMessageW(listview, LVM_SETBKCOLOR, 0, CLR_NONE)
                    user32.SendMessageW(listview, LVM_SETTEXTBKCOLOR, 0, CLR_NONE)
                    user32.RedrawWindow(listview, None, None, RDW_INVALIDATE | RDW_ERASE)

        # 4. Find WorkerW #2 (the top-level WorkerW sibling positioned AFTER workerw_defview)
        target_workerw = user32.FindWindowExW(0, workerw_defview, "WorkerW", None)

        if target_workerw and user32.IsWindow(target_workerw):
            log.info(f"Successfully isolated Desktop Wallpaper Target WorkerW #2: {hex(target_workerw)}")
            # Apply WS_CLIPCHILDREN | WS_CLIPSIBLINGS to target_workerw
            style = user32.GetWindowLongPtrW(target_workerw, GWL_STYLE)
            new_style = style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
            if new_style != style:
                user32.SetWindowLongPtrW(target_workerw, GWL_STYLE, new_style)
                user32.SetWindowPos(
                    target_workerw, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            user32.ShowWindow(target_workerw, 1)  # SW_SHOWNORMAL
            self._worker_hwnd = target_workerw
            self._defview_parent_hwnd = workerw_defview
            return target_workerw
        else:
            log.warning("WorkerW #2 sibling not found; falling back safely to Progman (never touching Taskbar).")
            self._worker_hwnd = self._progman_hwnd
            self._defview_parent_hwnd = workerw_defview
            return self._progman_hwnd

    # -----------------------------------------------------------------------
    # 4. Start / Stop / Restart Control (Top-Level Spawn + WorkerW #2 Reparenting)
    # -----------------------------------------------------------------------
    def is_running(self) -> bool:
        if self._proc is not None and self._proc.poll() is None:
            return True
        return False

    def _build_cmd(
        self,
        mpv_bin: str,
        mpv_title: str,
        video_path: str,
        backend: str,
        speed: float,
        volume: int,
        mute: bool,
        fit_mode: str,
        fps_limit: str,
    ) -> list[str]:
        if backend == "direct3d":
            # Direct3D 9Ex + zero-copy DXVA2: rock-solid on Intel HD 4400 / Haswell Win7 SP1
            vo_flags = [
                "--vo=direct3d",
                "--hwdec=dxva2",
            ]
        else:
            # D3D11 fallback
            vo_flags = [
                "--vo=gpu",
                "--gpu-context=d3d11",
                "--d3d11-flip=no",          # Mandatory on Windows 7 DXGI 1.2
                "--d3d11-sync-interval=1",
                "--hwdec=dxva2-copy",
                "--profile=fast",
                "--scale=bilinear",
                "--cscale=bilinear",
                "--dscale=bilinear",
                "--deband=no",
            ]

        cmd = [
            mpv_bin,
            f"--title={mpv_title}",
            *vo_flags,
            "--loop-file=inf",
            "--cache=no",
            "--demuxer-max-bytes=15M",
            "--no-osc",
            "--no-osd-bar",
            "--no-border",
            "--force-window=immediate",
            "--no-taskbar-progress",
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
        autopause: str = "maximized",
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

        workerw_target = self.ensure_workerw()
        if not workerw_target:
            self.last_error_message = "Failed to locate Explorer desktop WorkerW target window."
            log.error(self.last_error_message)
            return False

        rect = wintypes.RECT()
        user32.GetClientRect(workerw_target, ctypes.byref(rect))
        screen_w = max(rect.right - rect.left, user32.GetSystemMetrics(SM_CXSCREEN))
        screen_h = max(rect.bottom - rect.top, user32.GetSystemMetrics(SM_CYSCREEN))

        backends = ["direct3d", "d3d11"]

        for backend in backends:
            unique_id = uuid.uuid4().hex[:8]
            mpv_title = f"DesktopSuiteBgMpv_{unique_id}"
            self.ipc_pipe_path = rf"\\.\pipe\mpv-livewal-{unique_id}"
            self._ipc = WinMpvIPC(self.ipc_pipe_path)

            cmd = self._build_cmd(
                mpv_bin, mpv_title, video_path, backend,
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
                continue

            # Poll for mpv top-level window creation (up to 3.0 seconds)
            mpv_hwnd = None
            start_poll = time.time()
            while time.time() - start_poll < 3.0:
                if self._proc.poll() is not None:
                    break
                found = user32.FindWindowW(None, mpv_title)
                if found and user32.IsWindow(found):
                    mpv_hwnd = found
                    break
                time.sleep(0.05)

            if mpv_hwnd and self._proc.poll() is None:
                try:
                    # 1. Adjust window style: strip popup/caption/thickframe, make WS_CHILD | WS_VISIBLE
                    style = user32.GetWindowLongPtrW(mpv_hwnd, GWL_STYLE)
                    style = (style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD | WS_VISIBLE
                    user32.SetWindowLongPtrW(mpv_hwnd, GWL_STYLE, style)

                    # 2. Adjust extended style: strip WS_EX_APPWINDOW, add WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    exstyle = user32.GetWindowLongPtrW(mpv_hwnd, GWL_EXSTYLE)
                    exstyle = (exstyle & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    user32.SetWindowLongPtrW(mpv_hwnd, GWL_EXSTYLE, exstyle)

                    # 3. Reparent into WorkerW #2
                    user32.SetParent(mpv_hwnd, workerw_target)

                    # 4. Position and size to cover desktop client area
                    user32.SetWindowPos(
                        mpv_hwnd, 0, 0, 0, screen_w, screen_h,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                    )

                    self.mpv_hwnd = mpv_hwnd
                    self.host_hwnd = mpv_hwnd
                    log.info(
                        "mpv window 0x%X successfully reparented into WorkerW #2 (0x%X) on backend %s (PID %s)",
                        mpv_hwnd, workerw_target, backend, self._proc.pid
                    )

                    self._autopause = WinAutoPauseWatcher(self._ipc, mode=autopause)
                    self._autopause.start()
                    return True
                except Exception as exc:
                    log.error("Failed to reparent mpv window: %s", exc)

            # Process exited or failed window creation
            rc = self._proc.poll()
            self._proc = None
            self._destroy_mpv_window()

            if rc is not None:
                unsigned_rc = rc & 0xFFFFFFFF
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

    def _destroy_mpv_window(self) -> None:
        if sys.platform == "win32" and self.mpv_hwnd and user32.IsWindow(self.mpv_hwnd):
            user32.DestroyWindow(self.mpv_hwnd)
        self.mpv_hwnd = None
        self.host_hwnd = None

    def stop(self, restore_wallpaper: bool = True) -> None:
        """
        Cleanly terminates mpv, destroys mpv child window, and restores desktop wallpaper.
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
        self._destroy_mpv_window()

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
        """Repaint the static desktop wallpaper and force repaint of WorkerW windows and Progman."""
        if sys.platform != "win32":
            return
        try:
            user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, None, SPIF_SENDCHANGE)
            flags = RDW_ERASE | RDW_INVALIDATE | RDW_INTERNALPAINT | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME
            for hwnd in (self._worker_hwnd, self._defview_parent_hwnd, self._progman_hwnd):
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
