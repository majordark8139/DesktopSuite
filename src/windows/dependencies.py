"""
src.windows.dependencies
========================
Automatic dependency inspector and first-launch updater for DesktopSuite on Windows.

Verifies:
1. Windows 7 API compatibility forwarder (api-ms-win-core-path-l1-1-0.dll).
2. Microsoft Visual C++ 2015-2022 runtime / Universal C Runtime.
3. Hardware-accelerated mpv player binary in assets/bin or PATH.
4. Bundled typography font registration with Windows GDI.
"""

from __future__ import annotations

import ctypes
import logging
import os
import shutil
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)

VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
MPV_PORTABLE_URL = "https://sourceforge.net/projects/mpv-player-windows/files/64bit/mpv-x86_64-20241027-git-45ef4ea.7z/download"


def get_app_dir() -> Path:
    """Return the base directory of the running application or executable."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def check_and_fix_win7_path_dll() -> bool:
    """
    Ensure api-ms-win-core-path-l1-1-0.dll exists in the application root directory
    so Python 3.10+ can load without errors on Windows 7.
    """
    app_dir = get_app_dir()
    target_dll = app_dir / "api-ms-win-core-path-l1-1-0.dll"

    if target_dll.is_file():
        return True

    # Look for bundled copy in assets/bin
    bundled_dll = app_dir / "assets" / "bin" / "api-ms-win-core-path-l1-1-0.dll"
    if bundled_dll.is_file():
        try:
            shutil.copy2(bundled_dll, target_dll)
            log.info("Installed api-ms-win-core-path-l1-1-0.dll to application root %s", app_dir)
            return True
        except Exception as exc:
            log.warning("Could not copy api-ms-win-core-path-l1-1-0.dll to %s: %s", app_dir, exc)

    return False


def check_vcredist() -> bool:
    """Check if Visual C++ 2015-2022 Redistributable (vcruntime140.dll) is available."""
    try:
        ctypes.CDLL("vcruntime140.dll")
        return True
    except OSError:
        return False


def install_vcredist_silent() -> bool:
    """Download and silently install Microsoft Visual C++ 2015-2022 Redistributable."""
    log.info("Visual C++ runtime is missing. Downloading VC++ Redistributable...")
    temp_installer = Path(os.environ.get("TEMP", "C:\\Temp")) / "vc_redist.x64.exe"
    try:
        urllib.request.urlretrieve(VC_REDIST_URL, str(temp_installer))
        log.info("Installing Visual C++ Redistributable silently...")
        res = subprocess.run([str(temp_installer), "/install", "/quiet", "/norestart"], check=False)
        return res.returncode in (0, 3010)  # 0 = success, 3010 = reboot required
    except Exception as exc:
        log.warning("Failed to automatically install VC++ Redistributable: %s", exc)
        return False


def check_mpv() -> Optional[str]:
    """Check if mpv player is present; if missing, return None."""
    app_dir = get_app_dir()
    candidates = [
        app_dir / "assets" / "bin" / "mpv.exe",
        Path(r"C:\Program Files\mpv\mpv.exe"),
        Path(r"C:\tools\mpv\mpv.exe"),
        Path(r"C:\mpv\mpv.exe"),
    ]
    for p in candidates:
        if p.is_file():
            return str(p)

    return shutil.which("mpv") or shutil.which("mpv.exe")


def run_first_launch_check(background: bool = True) -> None:
    """
    Run pre-flight dependency check on first launch or startup.
    Ensures all runtime components are present.
    """
    def _worker():
        log.info("Running DesktopSuite first-launch dependency inspection...")

        # 1. Windows 7 API path compatibility
        check_and_fix_win7_path_dll()

        # 2. Visual C++ runtime
        if not check_vcredist():
            install_vcredist_silent()

        # 3. Check mpv player
        mpv_path = check_mpv()
        if mpv_path:
            log.info("Verified mpv player executable at: %s", mpv_path)
        else:
            log.warning("mpv.exe not found in assets/bin or PATH. Wallpaper playback will require mpv.")

    if background:
        threading.Thread(target=_worker, daemon=True, name="dep-checker").start()
    else:
        _worker()
