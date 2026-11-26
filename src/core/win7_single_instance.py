"""
src.core.win7_single_instance
=============================
Win32 Named Mutex Single-Instance Guard and Inter-Process Activation Filter.
Guarantees that launching DesktopSuite a second time wakes and raises the existing
Control Center window instead of spawning duplicate transparent canvas overlays.
"""

from __future__ import annotations

import logging
import sys
from typing import Callable, Optional

log = logging.getLogger(__name__)

MUTEX_NAME = "Local\\DesktopSuite_SingleInstance_Mutex_v1"
ACTIVATE_MSG_NAME = "DesktopSuite_Activate_ControlCenter_v1"
CONTROL_CENTER_TITLE = "Desktop Suite Control Center"

WM_DESKTOPSUITE_ACTIVATE = 0

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32 = ctypes.WinDLL("user32", use_last_error=True)

    ERROR_ALREADY_EXISTS = 183
    SW_RESTORE = 9
    SW_SHOW = 5
    HWND_BROADCAST = 0xFFFF

    kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE

    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL

    user32.RegisterWindowMessageW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterWindowMessageW.restype = wintypes.UINT

    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND

    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
    user32.AllowSetForegroundWindow.restype = wintypes.BOOL

    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, ctypes.c_size_t, ctypes.c_ssize_t]
    user32.PostMessageW.restype = wintypes.BOOL

    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL

    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.IsIconic.restype = wintypes.BOOL

    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL

    WM_DESKTOPSUITE_ACTIVATE = user32.RegisterWindowMessageW(ACTIVATE_MSG_NAME)


class SingleInstanceGuard:
    """
    Holds a Win32 Named Mutex for the lifetime of the application.
    If another instance is already running, activates its Control Center
    and returns False.
    """

    def __init__(
        self,
        mutex_name: str = MUTEX_NAME,
        window_title: str = CONTROL_CENTER_TITLE,
    ) -> None:
        self.mutex_name = mutex_name
        self.window_title = window_title
        self._handle: Optional[int] = None

    def acquire_or_activate_existing(self) -> bool:
        if sys.platform != "win32":
            return True

        self._handle = kernel32.CreateMutexW(None, False, self.mutex_name)
        last_error = ctypes.get_last_error()

        if not self._handle:
            return True

        if last_error == ERROR_ALREADY_EXISTS:
            self._wake_existing_instance()
            self.release()
            return False

        return True

    def _wake_existing_instance(self) -> None:
        hwnd = user32.FindWindowW(None, self.window_title)
        if hwnd:
            log.info("SingleInstanceGuard found existing Control Center hwnd=0x%X; raising window", hwnd)
            pid = wintypes.DWORD(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value:
                user32.AllowSetForegroundWindow(pid.value)

            user32.PostMessageW(hwnd, WM_DESKTOPSUITE_ACTIVATE, 0, 0)

            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, SW_RESTORE)
            else:
                user32.ShowWindow(hwnd, SW_SHOW)
            user32.SetForegroundWindow(hwnd)
        else:
            log.info("SingleInstanceGuard Control Center window not found; broadcasting WM_DESKTOPSUITE_ACTIVATE")
            user32.AllowSetForegroundWindow(0xFFFFFFFF)  # ASFW_ANY
            user32.PostMessageW(HWND_BROADCAST, WM_DESKTOPSUITE_ACTIVATE, 0, 0)

    def release(self) -> None:
        if sys.platform == "win32" and self._handle:
            kernel32.CloseHandle(self._handle)
            self._handle = None


try:
    from PyQt5.QtCore import QAbstractNativeEventFilter

    class ActivateMessageFilter(QAbstractNativeEventFilter):
        """
        Installed on QApplication to catch WM_DESKTOPSUITE_ACTIVATE and restore
        the Control Center window when a secondary instance is launched.
        """

        def __init__(self, on_activate_callback: Callable[[], None]) -> None:
            super().__init__()
            self.on_activate_callback = on_activate_callback

        def nativeEventFilter(self, event_type, message):
            if event_type == b"windows_generic_MSG" and sys.platform == "win32":
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_DESKTOPSUITE_ACTIVATE and WM_DESKTOPSUITE_ACTIVATE != 0:
                    log.info("ActivateMessageFilter received WM_DESKTOPSUITE_ACTIVATE")
                    try:
                        self.on_activate_callback()
                    except Exception:
                        log.exception("on_activate_callback error")
                    return True, 0
            return False, 0

except ImportError:
    class ActivateMessageFilter:  # type: ignore[no-redef]
        def __init__(self, on_activate_callback: Callable[[], None]) -> None:
            pass
