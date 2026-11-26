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

from src.core.diagnostics import (
    get_log_dir,
    get_rate_limiter,
    log_win32_window_tree,
    read_log_tail,
)

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

WS_EX_TRANSPARENT = 0x00000020
WS_EX_APPWINDOW = 0x00040000
WS_EX_NOPARENTNOTIFY = 0x00000004
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_LAYERED = 0x00080000
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

SW_HIDE = 0
SW_SHOWNORMAL = 1
SW_SHOWNA = 8
LWA_ALPHA = 0x00000002

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

    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int

    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL

    user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetClassNameW.restype = ctypes.c_int

    user32.GetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        ctypes.POINTER(wintypes.COLORREF),
        ctypes.POINTER(ctypes.c_ubyte),
        ctypes.POINTER(wintypes.DWORD),
    ]
    user32.GetLayeredWindowAttributes.restype = wintypes.BOOL

    user32.SetLayeredWindowAttributes.argtypes = [
        wintypes.HWND,
        wintypes.COLORREF,
        ctypes.c_ubyte,
        wintypes.DWORD,
    ]
    user32.SetLayeredWindowAttributes.restype = wintypes.BOOL

    _ole32 = ctypes.WinDLL("ole32")
    _ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    _ole32.CoInitializeEx.restype = ctypes.c_long
    _ole32.CoUninitialize.argtypes = []
    _ole32.CoUninitialize.restype = None

    class _GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", wintypes.DWORD),
            ("Data2", wintypes.WORD),
            ("Data3", wintypes.WORD),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    def _com_guid(s: str) -> _GUID:
        u = uuid.UUID(s)
        return _GUID(u.fields[0], u.fields[1], u.fields[2], (ctypes.c_ubyte * 8)(*u.bytes[8:]))

    _ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(_GUID),
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(_GUID),
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _ole32.CoCreateInstance.restype = ctypes.c_long

    _CLSID_TaskbarList = _com_guid("{56FDF344-FD6D-11d0-958A-006097C9A090}")
    _IID_ITaskbarList = _com_guid("{56FDF342-FD6D-11d0-958A-006097C9A090}")

    def _com_vcall(obj_ptr, index, restype, *argtypes):
        vtable = ctypes.cast(obj_ptr, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)))[0]
        fn = ctypes.WINFUNCTYPE(restype, ctypes.c_void_p, *argtypes)(vtable[index])
        return lambda *args: fn(obj_ptr, *args)

    def _delete_taskbar_tab(hwnd: int) -> bool:
        """Explicitly remove an HWND's button from Explorer's taskbar via ITaskbarList::DeleteTab."""
        if not hwnd:
            return False
        hr_init = _ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        rpc_e_changed_mode = -2147417850  # 0x80010106
        should_uninit = hr_init in (0, 1)
        if hr_init < 0 and hr_init != rpc_e_changed_mode:
            log.warning("ITaskbarList CoInitializeEx failed: 0x%08X", hr_init & 0xFFFFFFFF)
            return False
        taskbar_ptr = ctypes.c_void_p()
        try:
            hr = _ole32.CoCreateInstance(
                ctypes.byref(_CLSID_TaskbarList), None, 0x1,
                ctypes.byref(_IID_ITaskbarList), ctypes.byref(taskbar_ptr),
            )
            if hr < 0 or not taskbar_ptr.value:
                log.warning("CoCreateInstance(CLSID_TaskbarList) failed: 0x%08X", hr & 0xFFFFFFFF)
                return False
            hr_hr = _com_vcall(taskbar_ptr, 3, ctypes.c_long)()
            hr_del = _com_vcall(taskbar_ptr, 5, ctypes.c_long, wintypes.HWND)(hwnd)
            log.info(
                "ITaskbarList::DeleteTab(0x%X): HrInit=0x%08X DeleteTab=0x%08X",
                hwnd, hr_hr & 0xFFFFFFFF, hr_del & 0xFFFFFFFF,
            )
            return hr_hr >= 0 and hr_del >= 0
        except Exception as exc:
            log.warning("ITaskbarList::DeleteTab(0x%X) exception: %s", hwnd, exc)
            return False
        finally:
            if taskbar_ptr.value:
                try:
                    _com_vcall(taskbar_ptr, 2, wintypes.ULONG)()
                except Exception:
                    pass
            if should_uninit:
                _ole32.CoUninitialize()

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
        self._lock = threading.Lock()

    def send_command(self, cmd_list: list) -> Optional[dict]:
        payload = json.dumps({"command": cmd_list}) + "\n"
        with self._lock:
            try:
                with open(self.pipe_path, "r+b", buffering=0) as pipe:
                    pipe.write(payload.encode("utf-8"))
                    line = pipe.readline()
                    if line:
                        return json.loads(line.decode("utf-8", errors="replace"))
            except FileNotFoundError:
                return None
            except Exception as exc:
                allowed, suppressed = get_rate_limiter().check(f"ipc:{cmd_list[:1]}", interval=5.0)
                if allowed:
                    suffix = f" [suppressed {suppressed}]" if suppressed else ""
                    log.debug("WinMpvIPC.send_command(%s) error: %s%s", cmd_list, exc, suffix)
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

    def __init__(
        self,
        ipc: WinMpvIPC,
        mode: str = "focus",
        interval: float = 0.5,
        mpv_pid: Optional[int] = None,
    ) -> None:
        self.ipc = ipc
        self.mode = mode
        self.interval = interval
        self.mpv_pid = mpv_pid
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._is_paused = False

    def start(self) -> None:
        if self.mode == "off":
            log.info("WinAutoPauseWatcher disabled (mode=off)")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True, name="win-autopause")
        self._thread.start()
        log.info("WinAutoPauseWatcher started (mode=%s, interval=%.2fs)", self.mode, self.interval)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=1.0)
            self._thread = None
        log.info("WinAutoPauseWatcher stopped")

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

                # Don't pause when our own Control Center, Canvas, or mpv has focus
                fg_pid = wintypes.DWORD(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(fg_pid))
                cls_buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(hwnd, cls_buf, 256)
                cls_name = cls_buf.value
                title_buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title_buf, 256)
                fg_title = title_buf.value
                is_zoomed = False
                fg_rect = (0, 0, 0, 0)

                if fg_pid.value == os.getpid() or (self.mpv_pid and fg_pid.value == self.mpv_pid):
                    should_pause = False
                else:
                    if cls_name in (
                        "Progman", "WorkerW", "Shell_TrayWnd",
                        "DesktopCanvasWindow", "DesktopSuiteWin7MpvHost", "mpv",
                    ):
                        should_pause = False
                    elif self.mode == "focus":
                        should_pause = True
                    elif self.mode == "maximized":
                        is_zoomed = bool(user32.IsZoomed(hwnd))
                        rect = wintypes.RECT()
                        user32.GetWindowRect(hwnd, ctypes.byref(rect))
                        fg_rect = (rect.left, rect.top, rect.right, rect.bottom)
                        is_fullscreen = (
                            rect.left <= 0 and rect.top <= 0 and
                            rect.right >= sw and rect.bottom >= sh
                        )
                        should_pause = is_zoomed or is_fullscreen
                    else:
                        should_pause = False

                if should_pause != self._is_paused:
                    log.info(
                        "WinAutoPauseWatcher -> %s (mode=%s, fg_hwnd=0x%X, pid=%d, cls=%r, title=%r, zoomed=%s, rect=%s)",
                        "PAUSE" if should_pause else "RESUME",
                        self.mode, int(hwnd), fg_pid.value, cls_name, fg_title, is_zoomed, fg_rect,
                    )
                    if should_pause:
                        self.ipc.pause()
                    else:
                        self.ipc.resume()
                    self._is_paused = should_pause
            except Exception as exc:
                allowed, suppressed = get_rate_limiter().check("autopause:err", interval=5.0)
                if allowed:
                    suffix = f" [suppressed {suppressed}]" if suppressed else ""
                    log.warning("WinAutoPauseWatcher error: %s%s", exc, suffix)

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
        self._worker_orig_exstyle: Optional[int] = None
        self._defview_parent_hwnd: Optional[int] = None
        self._progman_hwnd: Optional[int] = None
        self.ipc_pipe_path: Optional[str] = None
        self.last_error_message: str = ""
        self.log_path = str(get_log_dir() / "mpv_latest.log")
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

        dwm_active = self.is_dwm_aero_enabled()
        log.info("ensure_workerw(): DWM composition enabled = %s", dwm_active)

        # 1. Ensure Windows 7 Client-Area Animation is enabled before 0x052C
        anim_enabled = wintypes.BOOL(0)
        user32.SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, ctypes.byref(anim_enabled), 0)
        log.info("ensure_workerw(): SPI_GETCLIENTAREAANIMATION initial = %s", bool(anim_enabled.value))
        if not anim_enabled.value:
            log.info("Enabling Windows 7 client area animation (SPI_SETCLIENTAREAANIMATION)")
            set_ok = user32.SystemParametersInfoW(SPI_SETCLIENTAREAANIMATION, 0, ctypes.c_void_p(1), 0)
            log.info("SPI_SETCLIENTAREAANIMATION returned %s (err=%d)", bool(set_ok), kernel32.GetLastError())

        log_win32_window_tree("before 0x052C", log)

        # 2. Trigger Explorer to split Progman -> WorkerW #1 + WorkerW #2
        self._progman_hwnd = user32.FindWindowW("Progman", None)
        log.info("ensure_workerw(): Progman hwnd = 0x%X", self._progman_hwnd or 0)
        result = ctypes.c_ulong(0)
        sm1 = user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0x0D, 0x01, SMTO_NORMAL, 1000, ctypes.byref(result))
        err1 = kernel32.GetLastError()
        sm2 = user32.SendMessageTimeoutW(self._progman_hwnd, 0x052C, 0x00, 0x00, SMTO_NORMAL, 1000, ctypes.byref(result))
        err2 = kernel32.GetLastError()
        log.info(
            "ensure_workerw(): 0x052C(0x0D,0x01)->ret=%s err=%d | 0x052C(0x00,0x00)->ret=%s err=%d | out=%s",
            sm1, err1, sm2, err2, result.value,
        )

        log_win32_window_tree("after 0x052C", log)

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
        log.info(
            "ensure_workerw(): workerw_defview=0x%X, next_WorkerW=0x%X",
            workerw_defview or 0, workerw_target or 0,
        )

        # Ensure Desktop Icon transparency (SysListView32) on WorkerW #1
        if workerw_defview:
            shell_view = user32.FindWindowExW(workerw_defview, 0, "SHELLDLL_DefView", None)
            if shell_view:
                listview = user32.FindWindowExW(shell_view, 0, "SysListView32", None)
                log.info(
                    "ensure_workerw(): SHELLDLL_DefView=0x%X, SysListView32=0x%X",
                    shell_view or 0, listview or 0,
                )
                if listview:
                    user32.SendMessageW(listview, LVM_SETBKCOLOR, 0, CLR_NONE)
                    user32.SendMessageW(listview, LVM_SETTEXTBKCOLOR, 0, CLR_NONE)
                    user32.RedrawWindow(listview, None, None, RDW_INVALIDATE | RDW_ERASE)
        else:
            # Also check if SHELLDLL_DefView lives directly inside Progman
            prog_defview = user32.FindWindowExW(self._progman_hwnd, 0, "SHELLDLL_DefView", None) if self._progman_hwnd else 0
            log.warning(
                "ensure_workerw(): No top-level WorkerW hosting SHELLDLL_DefView! Progman->SHELLDLL_DefView=0x%X",
                prog_defview or 0,
            )

        # 4. Find WorkerW #2 (the top-level WorkerW sibling positioned AFTER workerw_defview)
        target_workerw = user32.FindWindowExW(0, workerw_defview, "WorkerW", None)
        self._worker_orig_exstyle = None

        if target_workerw and user32.IsWindow(target_workerw):
            log.info(f"Successfully isolated Desktop Wallpaper Target WorkerW #2: {hex(target_workerw)}")
            # Apply WS_CLIPCHILDREN | WS_CLIPSIBLINGS to target_workerw
            style = user32.GetWindowLongPtrW(target_workerw, GWL_STYLE)
            new_style = style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
            if new_style != style:
                user32.SetWindowLongPtrW(target_workerw, GWL_STYLE, new_style)

            # Win7 Explorer sets WS_EX_LAYERED | WS_EX_TRANSPARENT on WorkerW #2 for fade transitions;
            # strip both so child video windows aren't composited at 0 alpha or click/paint-transparent.
            exstyle = user32.GetWindowLongPtrW(target_workerw, GWL_EXSTYLE)
            if exstyle & WS_EX_LAYERED:
                cr_key = wintypes.COLORREF(0)
                b_alpha = ctypes.c_ubyte(0)
                dw_flags = wintypes.DWORD(0)
                lwa_ok = user32.GetLayeredWindowAttributes(
                    target_workerw, ctypes.byref(cr_key), ctypes.byref(b_alpha), ctypes.byref(dw_flags)
                )
                log.info(
                    "WorkerW #2 prior layered state: ok=%s key=0x%08X alpha=%d flags=0x%X",
                    bool(lwa_ok), cr_key.value, b_alpha.value, dw_flags.value,
                )

            desired_exstyle = (exstyle & ~(WS_EX_LAYERED | WS_EX_TRANSPARENT)) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
            if desired_exstyle != exstyle:
                self._worker_orig_exstyle = exstyle
                user32.SetWindowLongPtrW(target_workerw, GWL_EXSTYLE, desired_exstyle)

            wrect = wintypes.RECT()
            user32.GetWindowRect(target_workerw, ctypes.byref(wrect))
            swp_flags = SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
            if (wrect.right - wrect.left) <= 0 or (wrect.bottom - wrect.top) <= 0:
                sw = user32.GetSystemMetrics(SM_CXSCREEN)
                sh = user32.GetSystemMetrics(SM_CYSCREEN)
                user32.SetWindowPos(target_workerw, 0, 0, 0, sw, sh, swp_flags)
            else:
                user32.SetWindowPos(target_workerw, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | swp_flags)

            sw_res = user32.ShowWindow(target_workerw, SW_SHOWNA)
            verify_exstyle = user32.GetWindowLongPtrW(target_workerw, GWL_EXSTYLE)
            if verify_exstyle & WS_EX_LAYERED:
                slwa_ok = user32.SetLayeredWindowAttributes(target_workerw, 0, 255, LWA_ALPHA)
                log.warning(
                    "WorkerW #2 retained WS_EX_LAYERED (verify_ex=0x%08X); SetLayeredWindowAttributes(alpha=255)=%s err=%d",
                    verify_exstyle & 0xFFFFFFFF, bool(slwa_ok), kernel32.GetLastError(),
                )
                if (
                    not slwa_ok
                    and self._progman_hwnd
                    and user32.IsWindow(self._progman_hwnd)
                    and not user32.FindWindowExW(self._progman_hwnd, 0, "SHELLDLL_DefView", None)
                ):
                    log.warning(
                        "WorkerW #2 cannot be made opaque; falling back cleanly to Progman=0x%X",
                        self._progman_hwnd,
                    )
                    prog_style = user32.GetWindowLongPtrW(self._progman_hwnd, GWL_STYLE)
                    user32.SetWindowLongPtrW(
                        self._progman_hwnd, GWL_STYLE, prog_style | WS_CLIPCHILDREN | WS_CLIPSIBLINGS
                    )
                    user32.SetWindowPos(
                        self._progman_hwnd, 0, 0, 0, 0, 0,
                        SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                    )
                    self._worker_orig_exstyle = None
                    self._worker_hwnd = self._progman_hwnd
                    self._defview_parent_hwnd = workerw_defview
                    return self._progman_hwnd

            user32.GetWindowRect(target_workerw, ctypes.byref(wrect))
            user32.RedrawWindow(
                target_workerw, None, None,
                RDW_INVALIDATE | RDW_ERASE | RDW_FRAME | RDW_UPDATENOW | RDW_ALLCHILDREN,
            )
            log.info(
                "WorkerW #2 configured: style=0x%08X->0x%08X, ex=0x%08X->0x%08X, ShowWindow=%s, visible=%s, rect=(%d,%d,%d,%d)",
                style & 0xFFFFFFFF, new_style & 0xFFFFFFFF,
                exstyle & 0xFFFFFFFF, verify_exstyle & 0xFFFFFFFF,
                bool(sw_res), bool(user32.IsWindowVisible(target_workerw)),
                wrect.left, wrect.top, wrect.right, wrect.bottom,
            )
            self._worker_hwnd = target_workerw
            self._defview_parent_hwnd = workerw_defview
            return target_workerw
        else:
            log.warning(
                "WorkerW #2 sibling not found; falling back safely to Progman=0x%X (never touching Taskbar).",
                self._progman_hwnd or 0,
            )
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
            # Direct3D 9Ex + DXVA2-copy: reliable hardware decode on Intel HD 4400 Win7 SP1
            vo_flags = [
                "--vo=direct3d",
                "--hwdec=dxva2-copy",
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
            "--no-config",
            "--load-scripts=no",
            "--no-sub",
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

        log.info(
            "WinWallpaperEngine.start(video=%r, speed=%.2f, volume=%d, mute=%s, fit=%s, fps=%s, autopause=%s, mpv_log=%s)",
            video_path, speed, volume, mute, fit_mode, fps_limit, autopause, self.log_path,
        )

        workerw_target = self.ensure_workerw()
        if not workerw_target:
            self.last_error_message = "Failed to locate Explorer desktop WorkerW target window."
            log.error(self.last_error_message)
            return False

        rect = wintypes.RECT()
        user32.GetClientRect(workerw_target, ctypes.byref(rect))
        sys_w = user32.GetSystemMetrics(SM_CXSCREEN)
        sys_h = user32.GetSystemMetrics(SM_CYSCREEN)
        screen_w = max(rect.right - rect.left, sys_w)
        screen_h = max(rect.bottom - rect.top, sys_h)
        log.info(
            "Target container hwnd=0x%X client=(%d x %d), system_screen=(%d x %d), final=(%d x %d)",
            workerw_target, rect.right - rect.left, rect.bottom - rect.top, sys_w, sys_h, screen_w, screen_h,
        )

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
            log.info("Spawning mpv backend=%s: %s", backend, cmd)

            try:
                self._proc = subprocess.Popen(
                    cmd,
                    creationflags=0x08000000,  # CREATE_NO_WINDOW
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as exc:
                log.exception("Failed to spawn mpv process (backend=%s): %s", backend, exc)
                continue

            log.info("Spawned mpv PID=%d (backend=%s, title=%r)", self._proc.pid, backend, mpv_title)

            # Poll fast (10ms) for mpv top-level window creation (up to 3.0 seconds)
            mpv_hwnd = None
            start_poll = time.time()
            while time.time() - start_poll < 3.0:
                if self._proc.poll() is not None:
                    break
                found = user32.FindWindowW(None, mpv_title)
                if found and user32.IsWindow(found):
                    mpv_hwnd = found
                    break
                time.sleep(0.01)

            elapsed_poll = time.time() - start_poll
            log.info(
                "mpv window poll finished in %.2fs: hwnd=0x%X, proc.poll()=%s",
                elapsed_poll, mpv_hwnd or 0, self._proc.poll(),
            )

            if mpv_hwnd and self._proc.poll() is None:
                try:
                    # Hide while top-level and strip taskbar button before reparenting into WorkerW #2
                    user32.ShowWindow(mpv_hwnd, SW_HIDE)
                    _delete_taskbar_tab(mpv_hwnd)

                    # 1. Adjust window style: strip popup/caption/thickframe/visible until child-reparented
                    old_style = user32.GetWindowLongPtrW(mpv_hwnd, GWL_STYLE)
                    new_style = (
                        (old_style & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME | WS_VISIBLE))
                        | WS_CHILD
                        | WS_CLIPSIBLINGS
                    )
                    user32.SetWindowLongPtrW(mpv_hwnd, GWL_STYLE, new_style)
                    err_style = kernel32.GetLastError()

                    # 2. Adjust extended style: strip WS_EX_APPWINDOW, add WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    old_exstyle = user32.GetWindowLongPtrW(mpv_hwnd, GWL_EXSTYLE)
                    new_exstyle = (old_exstyle & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    user32.SetWindowLongPtrW(mpv_hwnd, GWL_EXSTYLE, new_exstyle)
                    err_exstyle = kernel32.GetLastError()

                    # 3. Reparent into WorkerW #2 while still hidden
                    prev_parent = user32.SetParent(mpv_hwnd, workerw_target)
                    err_parent = kernel32.GetLastError()
                    _delete_taskbar_tab(mpv_hwnd)

                    # 4. Position, size, and show without activating
                    swp_ok = user32.SetWindowPos(
                        mpv_hwnd, 0, 0, 0, screen_w, screen_h,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW
                    )
                    err_swp = kernel32.GetLastError()
                    user32.ShowWindow(mpv_hwnd, SW_SHOWNA)
                    user32.RedrawWindow(
                        mpv_hwnd, None, None,
                        RDW_INVALIDATE | RDW_FRAME | RDW_UPDATENOW,
                    )
                    # Purge any Explorer shell-hook taskbar entry queued during creation/show
                    self._scrub_mpv_taskbar_windows(self._proc.pid, mpv_hwnd, workerw_target, screen_w, screen_h)

                    actual_parent = user32.GetParent(mpv_hwnd)
                    actual_vis = bool(user32.IsWindowVisible(mpv_hwnd))
                    mrect = wintypes.RECT()
                    user32.GetWindowRect(mpv_hwnd, ctypes.byref(mrect))

                    log.info(
                        "Reparent metrics: style=0x%08X->0x%08X(err=%d), ex=0x%08X->0x%08X(err=%d), "
                        "SetParent prev=0x%X actual_parent=0x%X(err=%d), SetWindowPos=%s(err=%d), "
                        "vis=%s, rect=(%d,%d,%d,%d)",
                        old_style & 0xFFFFFFFF, new_style & 0xFFFFFFFF, err_style,
                        old_exstyle & 0xFFFFFFFF, new_exstyle & 0xFFFFFFFF, err_exstyle,
                        prev_parent or 0, actual_parent or 0, err_parent,
                        bool(swp_ok), err_swp, actual_vis,
                        mrect.left, mrect.top, mrect.right, mrect.bottom,
                    )

                    self.mpv_hwnd = mpv_hwnd
                    self.host_hwnd = mpv_hwnd
                    log.info(
                        "mpv window 0x%X successfully reparented into container (0x%X) on backend %s (PID %s)",
                        mpv_hwnd, workerw_target, backend, self._proc.pid
                    )
                    log_win32_window_tree(f"after reparent ({backend})", log)

                    self._autopause = WinAutoPauseWatcher(
                        self._ipc, mode=autopause, mpv_pid=self._proc.pid,
                    )
                    self._autopause.start()
                    self._start_health_probe(
                        self._proc, self._ipc, mpv_hwnd, workerw_target, screen_w, screen_h, backend
                    )
                    return True
                except Exception as exc:
                    log.exception("Failed to reparent mpv window: %s", exc)

            # Process exited or failed window creation
            rc = self._proc.poll()
            self._proc = None
            self._destroy_mpv_window()

            mpv_tail = read_log_tail(self.log_path, max_lines=35)
            log.warning("mpv tail (%s) after backend=%s failure:\n%s", self.log_path, backend, mpv_tail)

            if rc is not None:
                unsigned_rc = rc & 0xFFFFFFFF
                if unsigned_rc == STATUS_ENTRYPOINT_NOT_FOUND:
                    self.last_error_message = (
                        "mpv.exe is incompatible with Windows 7 (STATUS_ENTRYPOINT_NOT_FOUND 0xC0000139). "
                        "Use the bundled Windows 7 compatible mpv build (2023-08-27 / 2023-09-17)."
                    )
                    log.error(self.last_error_message)
                    return False
                log.warning("Backend %s failed with exit code %s (0x%08X); trying fallback...", backend, rc, unsigned_rc)

        self.last_error_message = f"mpv failed to initialize video output. Check {self.log_path}"
        log.error(self.last_error_message)
        self.stop(restore_wallpaper=True)
        return False

    def _scrub_mpv_taskbar_windows(
        self,
        pid: int,
        main_hwnd: int,
        workerw_target: int,
        screen_w: int,
        screen_h: int,
    ) -> list[str]:
        """
        Ensure neither `main_hwnd` nor any auxiliary top-level window owned by `pid`
        holds a Windows taskbar button or non-child/appwindow style.
        """
        if sys.platform != "win32":
            return []

        found_top: list[str] = []
        _delete_taskbar_tab(main_hwnd)

        def _enum_mpv_cb(hwnd, _lparam):
            win_pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(win_pid))
            if win_pid.value != pid:
                return True
            cls_buf = ctypes.create_unicode_buffer(128)
            user32.GetClassNameW(hwnd, cls_buf, 128)
            st = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
            ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
            vis = bool(user32.IsWindowVisible(hwnd))
            par = user32.GetParent(hwnd) or 0
            found_top.append(
                f"hwnd=0x{hwnd:X}(cls={cls_buf.value!r},vis={vis},par=0x{par:X},"
                f"st=0x{st & 0xFFFFFFFF:08X},ex=0x{ex & 0xFFFFFFFF:08X})"
            )
            if hwnd == main_hwnd:
                fixed_st = (st & ~(WS_POPUP | WS_CAPTION | WS_THICKFRAME)) | WS_CHILD | WS_CLIPSIBLINGS
                fixed_ex = (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                if fixed_st != st:
                    user32.SetWindowLongPtrW(hwnd, GWL_STYLE, fixed_st)
                if fixed_ex != ex:
                    user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, fixed_ex)
                if par != workerw_target:
                    user32.SetParent(hwnd, workerw_target)
                    user32.SetWindowPos(
                        hwnd, 0, 0, 0, screen_w, screen_h,
                        SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED | SWP_SHOWWINDOW,
                    )
            else:
                # Any secondary top-level window created by mpv must never sit in the taskbar
                if vis or not (ex & WS_EX_TOOLWINDOW) or (ex & WS_EX_APPWINDOW):
                    user32.SetWindowLongPtrW(
                        hwnd, GWL_EXSTYLE, (ex & ~WS_EX_APPWINDOW) | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
                    )
                    if vis:
                        user32.ShowWindow(hwnd, SW_HIDE)
            _delete_taskbar_tab(hwnd)
            return True

        try:
            cb = WNDENUMPROC(_enum_mpv_cb)
            user32.EnumWindows(cb, 0)
        except Exception as exc:
            log.debug("EnumWindows taskbar scrub error (pid=%d): %s", pid, exc)
        return found_top

    def _start_health_probe(
        self,
        proc: subprocess.Popen,
        ipc: WinMpvIPC,
        mpv_hwnd: int,
        workerw_target: int,
        screen_w: int,
        screen_h: int,
        backend: str,
    ) -> None:
        """Schedule non-blocking post-launch scrubs (removing delayed taskbar tabs) and health probes."""
        def _probe():
            props = [
                "pause", "core-idle", "vo-configured", "current-vo",
                "hwdec-current", "video-params/w", "video-params/h", "time-pos", "eof-reached",
            ]
            # Early intervals flush Explorer's async HSHELL_WINDOWCREATED & mpv's vo_w32_config;
            # later intervals inspect live IPC state.
            schedule_steps = (
                (0.20, False),
                (0.45, False),
                (0.85, True),
                (1.50, False),
                (2.00, True),
            )
            elapsed = 0.0
            for wait_dt, run_ipc in schedule_steps:
                time.sleep(wait_dt)
                elapsed += wait_dt
                if self._proc is not proc:
                    return
                rc = proc.poll()
                if rc is not None:
                    log.warning("mpv exited unexpectedly (rc=%s). Tail:\n%s", rc, read_log_tail(self.log_path, 30))
                    return

                scrubbed = self._scrub_mpv_taskbar_windows(
                    proc.pid, mpv_hwnd, workerw_target, screen_w, screen_h
                )
                if not run_ipc:
                    continue

                win_ok = bool(user32.IsWindow(mpv_hwnd))
                win_vis = bool(user32.IsWindowVisible(mpv_hwnd)) if win_ok else False
                parent_hwnd = user32.GetParent(mpv_hwnd) if win_ok else 0
                st_cur = user32.GetWindowLongPtrW(mpv_hwnd, GWL_STYLE) & 0xFFFFFFFF if win_ok else 0
                ex_cur = user32.GetWindowLongPtrW(mpv_hwnd, GWL_EXSTYLE) & 0xFFFFFFFF if win_ok else 0
                mrect = wintypes.RECT()
                if win_ok:
                    user32.GetWindowRect(mpv_hwnd, ctypes.byref(mrect))
                state = {}
                for p in props:
                    res = ipc.send_command(["get_property", p])
                    state[p] = res.get("data") if res else None
                log.info(
                    "mpv health probe (+%.1fs, backend=%s, pid=%d, rc=%s): "
                    "IsWindow=%s vis=%s parent=0x%X st=0x%08X ex=0x%08X rect=(%d,%d,%d,%d) top_wins=%s ipc=%s",
                    elapsed, backend, proc.pid, rc, win_ok, win_vis, parent_hwnd or 0,
                    st_cur, ex_cur, mrect.left, mrect.top, mrect.right, mrect.bottom,
                    scrubbed, state,
                )

        threading.Thread(target=_probe, daemon=True, name="mpv-health-probe").start()

    def _destroy_mpv_window(self) -> None:
        if sys.platform == "win32" and self.mpv_hwnd and user32.IsWindow(self.mpv_hwnd):
            user32.DestroyWindow(self.mpv_hwnd)
        self.mpv_hwnd = None
        self.host_hwnd = None

    def stop(self, restore_wallpaper: bool = True) -> None:
        """
        Cleanly terminates mpv, destroys mpv child window, and restores desktop wallpaper.
        """
        log.info(
            "WinWallpaperEngine.stop(restore_wallpaper=%s, has_proc=%s, mpv_hwnd=0x%X)",
            restore_wallpaper, self._proc is not None, self.mpv_hwnd or 0,
        )
        if self._autopause:
            self._autopause.stop()
            self._autopause = None

        if self._proc is not None:
            pid = self._proc.pid
            rc = self._proc.poll()
            if rc is None:
                if self._ipc:
                    self._ipc.send_command(["quit"])
                try:
                    rc = self._proc.wait(timeout=0.4)
                except subprocess.TimeoutExpired:
                    log.info("mpv PID=%d did not quit cleanly via IPC; force-killing", pid)
                    self._proc.kill()
                    try:
                        rc = self._proc.wait(timeout=1.0)
                    except subprocess.TimeoutExpired:
                        pass
            log.info("mpv PID=%d stopped (exit_code=%s)", pid, rc)
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
        autopause: str = "maximized",
    ) -> bool:
        self.stop(restore_wallpaper=False)
        return self.start(video_path, speed, volume, mute, fit_mode, fps_limit, autopause)

    def refresh_desktop_wallpaper(self) -> None:
        """Repaint the static desktop wallpaper and force repaint of WorkerW windows and Progman."""
        if sys.platform != "win32":
            return
        try:
            if (
                self._worker_orig_exstyle is not None
                and self._worker_hwnd
                and user32.IsWindow(self._worker_hwnd)
            ):
                user32.SetWindowLongPtrW(self._worker_hwnd, GWL_EXSTYLE, self._worker_orig_exstyle)
                user32.SetWindowPos(
                    self._worker_hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED,
                )
                self._worker_orig_exstyle = None

            user32.SystemParametersInfoW(SPI_SETDESKWALLPAPER, 0, None, SPIF_SENDCHANGE)
            flags = RDW_ERASE | RDW_INVALIDATE | RDW_INTERNALPAINT | RDW_ALLCHILDREN | RDW_UPDATENOW | RDW_FRAME
            for hwnd in (self._worker_hwnd, self._defview_parent_hwnd, self._progman_hwnd):
                if hwnd and user32.IsWindow(hwnd):
                    user32.RedrawWindow(hwnd, None, None, flags)
            log.debug("Refreshed static desktop wallpaper")
        except Exception as exc:
            log.warning("refresh_desktop_wallpaper error: %s", exc)

    def toggle_pause(self) -> bool:
        if not self._ipc or not self._ipc.is_alive():
            log.warning("toggle_pause: mpv IPC not alive")
            return False
        res = self._ipc.send_command(["get_property", "pause"])
        if res and "data" in res:
            is_paused = bool(res["data"])
            ok = self._ipc.resume() if is_paused else self._ipc.pause()
            log.info("toggle_pause: %s -> %s (ok=%s)", "RESUMED" if is_paused else "PAUSED", not is_paused, ok)
            return ok
        return False

    def set_volume(self, vol: int) -> None:
        if self._ipc:
            ok = self._ipc.set_volume(vol)
            log.debug("set_volume(%d) -> ok=%s", vol, ok)

    def set_speed(self, speed: float) -> None:
        if self._ipc:
            ok = self._ipc.set_speed(speed)
            log.debug("set_speed(%.2f) -> ok=%s", speed, ok)

    def set_mute(self, mute: bool) -> None:
        if self._ipc:
            ok = self._ipc.set_mute(mute)
            log.info("set_mute(%s) -> ok=%s", mute, ok)
