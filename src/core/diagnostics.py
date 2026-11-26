"""
src.core.diagnostics
====================
Portable, crash-safe diagnostics and telemetry subsystem for DesktopSuite.

Features
--------
1. Portable log directory resolution (`<app_root>/logs/`, falling back to `%TEMP%`
   only if the application folder is read-only).
2. Dual log output: `DesktopSuite_latest.log` (fresh per primary launch) plus
   rotated session history in `logs/history/` (keeps the 10 most recent runs),
   while secondary/CLI invocations append to `DesktopSuite_cli.log` so they
   never truncate the running primary instance's log.
3. Crash & exception capture for headless (`console=False`) builds:
   - `faulthandler.enable()` to capture native C/COM/Qt segfaults.
   - `sys.excepthook` & `threading.excepthook` for uncaught Python tracebacks.
   - PyQt5 `qInstallMessageHandler` forwarding Qt internal warnings/errors.
   - Safe `stdout`/`stderr` tee forwarding without recursion.
4. Thread-safe `RateLimiter` for 30-60 FPS render/audio loops.
5. Windows environment snapshot and Z-order shell window tree diagnostics.
"""

from __future__ import annotations

import atexit
import collections
from datetime import datetime
import faulthandler
import io
import json
import logging
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from typing import Any, Optional

_LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-8s] [%(threadName)s] %(name)s: %(message)s"
_LOG_DATEFMT = "%Y-%m-%d %H:%M:%S"
_MAX_HISTORY_FILES = 10

_INIT_LOCK = threading.Lock()
_INITIALIZED = False
_SESSION_KIND = ""
_START_TIME = time.monotonic()
_RESOLVED_LOG_DIR: Optional[Path] = None
_ACTIVE_LOG_PATH: Optional[Path] = None
_FILE_STREAM: Optional[Any] = None
_QT_HANDLER_INSTALLED = False
_PREV_QT_HANDLER: Any = None
_RATE_LIMITER: Optional["RateLimiter"] = None


class RateLimiter:
    """Thread-safe key-based rate limiter tracking suppressed repeat counts."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_logged: dict[str, float] = {}
        self._suppressed: dict[str, int] = {}

    def check(self, key: str, interval: float = 5.0) -> tuple[bool, int]:
        """
        Return ``(should_log, suppressed_count)``.

        Always allows the first occurrence for *key*. Subsequent calls within
        *interval* seconds return ``(False, current_suppressed)`` until the
        window elapses, at which point ``(True, suppressed_since_last)`` is returned.
        """
        now = time.monotonic()
        with self._lock:
            last = self._last_logged.get(key)
            if last is None or (now - last) >= interval:
                suppressed = self._suppressed.pop(key, 0)
                self._last_logged[key] = now
                return True, suppressed
            self._suppressed[key] = self._suppressed.get(key, 0) + 1
            return False, self._suppressed[key]


def get_rate_limiter() -> RateLimiter:
    """Return the process-wide shared :class:`RateLimiter`."""
    global _RATE_LIMITER
    if _RATE_LIMITER is None:
        _RATE_LIMITER = RateLimiter()
    return _RATE_LIMITER


class FlushingFileHandler(logging.FileHandler):
    """FileHandler that flushes to OS buffers after every record."""

    def emit(self, record: logging.LogRecord) -> None:
        super().emit(record)
        try:
            self.flush()
        except Exception:
            pass


class _TeeTextStream(io.TextIOBase):
    """
    Mirrors writes made to ``sys.stdout`` / ``sys.stderr`` into the log file
    without passing back through ``logging.StreamHandler`` (preventing recursion).
    """

    def __init__(
        self,
        orig_stream: Any,
        file_stream: Any,
        stream_lock: threading.Lock,
        tag: str,
    ) -> None:
        super().__init__()
        self._orig = orig_stream
        self._file_stream = file_stream
        self._lock = stream_lock
        self._tag = tag
        self._tls = threading.local()
        self._buf = ""

    @property
    def encoding(self) -> str:
        if self._orig is not None and getattr(self._orig, "encoding", None):
            return str(self._orig.encoding)
        return "utf-8"

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        try:
            return bool(self._orig is not None and self._orig.isatty())
        except Exception:
            return False

    def fileno(self) -> int:
        if self._orig is not None and hasattr(self._orig, "fileno"):
            return self._orig.fileno()
        raise io.UnsupportedOperation("underlying stream has no fileno")

    def write(self, data: str) -> int:
        if not data:
            return 0
        if not isinstance(data, str):
            data = str(data)

        if self._orig is not None:
            try:
                self._orig.write(data)
            except Exception:
                pass

        if getattr(self._tls, "in_write", False):
            return len(data)

        self._tls.in_write = True
        try:
            with self._lock:
                self._buf += data
                while "\n" in self._buf:
                    line, self._buf = self._buf.split("\n", 1)
                    self._write_line(line.rstrip("\r"))
        finally:
            self._tls.in_write = False
        return len(data)

    def flush(self) -> None:
        if self._orig is not None:
            try:
                self._orig.flush()
            except Exception:
                pass
        with self._lock:
            if self._buf:
                self._write_line(self._buf.rstrip("\r"))
                self._buf = ""
            try:
                self._file_stream.flush()
            except Exception:
                pass

    def _write_line(self, line: str) -> None:
        if not line:
            return
        ts = datetime.now().strftime(_LOG_DATEFMT)
        ms = int((time.time() % 1.0) * 1000)
        tname = threading.current_thread().name
        formatted = f"{ts}.{ms:03d} [{self._tag:<8}] [{tname}] stream: {line}\n"
        try:
            self._file_stream.write(formatted)
            self._file_stream.flush()
        except Exception:
            pass


def get_app_root() -> Path:
    """Return the portable application root directory (next to DesktopSuite.exe when frozen)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent.parent


def get_log_dir(force_refresh: bool = False) -> Path:
    """
    Resolve and ensure a writable ``logs/`` directory.

    Priority:
    1. ``DESKTOPSUITE_LOG_DIR`` environment variable (if set).
    2. ``<app_root>/logs`` (right inside the portable folder next to DesktopSuite.exe).
    3. ``%TEMP%/DesktopSuite_logs`` fallback if the portable folder is read-only.
    """
    global _RESOLVED_LOG_DIR
    env_override = os.environ.get("DESKTOPSUITE_LOG_DIR", "").strip()
    if env_override:
        p = Path(env_override).expanduser()
        p.mkdir(parents=True, exist_ok=True)
        return p

    if _RESOLVED_LOG_DIR is not None and not force_refresh:
        return _RESOLVED_LOG_DIR

    candidates = [
        get_app_root() / "logs",
        Path(tempfile.gettempdir()) / "DesktopSuite_logs",
    ]
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
            probe = candidate / f".probe_{os.getpid()}"
            probe.write_text("", encoding="utf-8")
            probe.unlink()
            _RESOLVED_LOG_DIR = candidate
            return candidate
        except Exception:
            continue

    fallback = Path(tempfile.gettempdir())
    _RESOLVED_LOG_DIR = fallback
    return fallback


def get_active_log_path() -> Optional[Path]:
    """Return the active main log path if diagnostics have been initialized."""
    return _ACTIVE_LOG_PATH


def _prune_history(history_dir: Path, keep: int = _MAX_HISTORY_FILES) -> None:
    try:
        files = sorted(
            history_dir.glob("DesktopSuite_*.log"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in files[keep:]:
            try:
                stale.unlink()
            except Exception:
                pass
    except Exception:
        pass


def _install_exception_hooks() -> None:
    orig_sys_hook = sys.excepthook

    def _sys_excepthook(exc_type, exc_value, exc_tb) -> None:
        try:
            logging.getLogger("DesktopSuite.Crash").critical(
                "Uncaught main-thread exception (%s): %s",
                getattr(exc_type, "__name__", str(exc_type)),
                exc_value,
                exc_info=(exc_type, exc_value, exc_tb),
            )
        except Exception:
            pass
        if orig_sys_hook:
            try:
                orig_sys_hook(exc_type, exc_value, exc_tb)
            except Exception:
                pass

    sys.excepthook = _sys_excepthook

    if hasattr(threading, "excepthook"):
        orig_thread_hook = threading.excepthook

        def _thread_excepthook(args) -> None:
            try:
                tname = args.thread.name if args.thread else "unknown"
                logging.getLogger("DesktopSuite.Crash").critical(
                    "Uncaught thread exception in %r (%s): %s",
                    tname,
                    getattr(args.exc_type, "__name__", str(args.exc_type)),
                    args.exc_value,
                    exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
                )
            except Exception:
                pass
            if orig_thread_hook:
                try:
                    orig_thread_hook(args)
                except Exception:
                    pass

        threading.excepthook = _thread_excepthook


def install_qt_message_handler() -> None:
    """Install a Qt message handler forwarding Qt warnings/errors into Python logging."""
    global _QT_HANDLER_INSTALLED, _PREV_QT_HANDLER
    if _QT_HANDLER_INSTALLED:
        return
    try:
        from PyQt5.QtCore import QtMsgType, qInstallMessageHandler
    except Exception:
        return

    qt_log = logging.getLogger("DesktopSuite.Qt")
    limiter = get_rate_limiter()

    def _qt_handler(mode, context, message: str) -> None:
        try:
            file_name = getattr(context, "file", None) or "?"
            line_no = getattr(context, "line", 0) or 0
            func_name = getattr(context, "function", None) or ""
            loc = f"{file_name}:{line_no}" + (f" ({func_name})" if func_name else "")

            if mode == QtMsgType.QtDebugMsg:
                level = logging.DEBUG
            elif mode == QtMsgType.QtInfoMsg:
                level = logging.INFO
            elif mode == QtMsgType.QtWarningMsg:
                level = logging.WARNING
            elif mode == QtMsgType.QtCriticalMsg:
                level = logging.ERROR
            else:
                level = logging.CRITICAL

            allowed, suppressed = limiter.check(f"qt:{level}:{message[:80]}", interval=3.0)
            if allowed:
                suffix = f" [suppressed {suppressed} repeats]" if suppressed else ""
                qt_log.log(level, "[%s] %s%s", loc, message, suffix)
        except Exception:
            pass

    _PREV_QT_HANDLER = qInstallMessageHandler(_qt_handler)
    _QT_HANDLER_INSTALLED = True
    logging.getLogger("DesktopSuite.Diagnostics").info("Installed PyQt5 qInstallMessageHandler")


def uninstall_qt_message_handler() -> None:
    """Restore default Qt message handler before Python/QApplication teardown."""
    global _QT_HANDLER_INSTALLED, _PREV_QT_HANDLER
    if not _QT_HANDLER_INSTALLED:
        return
    try:
        from PyQt5.QtCore import qInstallMessageHandler
        qInstallMessageHandler(None)
    except Exception:
        pass
    _PREV_QT_HANDLER = None
    _QT_HANDLER_INSTALLED = False


def _on_process_exit() -> None:
    try:
        uptime = time.monotonic() - _START_TIME
        logging.getLogger("DesktopSuite.Diagnostics").info(
            "=== DesktopSuite exiting (session=%s, pid=%d, uptime=%.2fs) ===",
            _SESSION_KIND or "unknown",
            os.getpid(),
            uptime,
        )
        logging.shutdown()
    except Exception:
        pass


def init_diagnostics(
    session_kind: str = "primary",
    redirect_streams: bool = True,
    reconfigure: bool = False,
) -> Path:
    """
    Initialize file/console logging, crash hooks, and stream capture.

    Parameters
    ----------
    session_kind:
        ``"primary"`` creates/overwrites ``DesktopSuite_latest.log`` and writes a
        timestamped archive in ``logs/history/``. Any other value (e.g. ``"cli"`` or
        ``"secondary"``) appends to ``DesktopSuite_cli.log`` so a running primary
        instance's log is never truncated.
    """
    global _INITIALIZED, _SESSION_KIND, _START_TIME, _ACTIVE_LOG_PATH, _FILE_STREAM

    with _INIT_LOCK:
        if _INITIALIZED and not reconfigure:
            assert _ACTIVE_LOG_PATH is not None
            return _ACTIVE_LOG_PATH

        _START_TIME = time.monotonic()
        _SESSION_KIND = session_kind
        log_dir = get_log_dir(force_refresh=reconfigure)

        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        for existing in list(root.handlers):
            root.removeHandler(existing)
            try:
                existing.close()
            except Exception:
                pass

        formatter = logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATEFMT)

        if session_kind == "primary":
            latest_path = log_dir / "DesktopSuite_latest.log"
            latest_handler = FlushingFileHandler(latest_path, mode="w", encoding="utf-8")
            latest_handler.setLevel(logging.DEBUG)
            latest_handler.setFormatter(formatter)
            root.addHandler(latest_handler)
            _FILE_STREAM = latest_handler.stream

            history_dir = log_dir / "history"
            try:
                history_dir.mkdir(parents=True, exist_ok=True)
                stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                hist_path = history_dir / f"DesktopSuite_{stamp}_pid{os.getpid()}.log"
                hist_handler = FlushingFileHandler(hist_path, mode="w", encoding="utf-8")
                hist_handler.setLevel(logging.DEBUG)
                hist_handler.setFormatter(formatter)
                root.addHandler(hist_handler)
                _prune_history(history_dir)
            except Exception:
                pass
        else:
            latest_path = log_dir / f"DesktopSuite_{session_kind}.log"
            latest_handler = FlushingFileHandler(latest_path, mode="a", encoding="utf-8")
            latest_handler.setLevel(logging.DEBUG)
            latest_handler.setFormatter(formatter)
            root.addHandler(latest_handler)
            _FILE_STREAM = latest_handler.stream

        # Console output (only when an actual console stream exists)
        if orig_stdout is not None and hasattr(orig_stdout, "write"):
            console_handler = logging.StreamHandler(orig_stdout)
            console_handler.setLevel(logging.INFO)
            console_handler.setFormatter(formatter)
            root.addHandler(console_handler)

        # Native C-level crash dumps (SIGSEGV / access violation / fatal abort)
        if session_kind == "primary" and _FILE_STREAM is not None:
            try:
                faulthandler.enable(file=_FILE_STREAM, all_threads=True)
            except Exception:
                pass

        _install_exception_hooks()

        if redirect_streams and _FILE_STREAM is not None:
            stream_lock = threading.Lock()
            sys.stdout = _TeeTextStream(orig_stdout, _FILE_STREAM, stream_lock, "STDOUT")
            sys.stderr = _TeeTextStream(orig_stderr, _FILE_STREAM, stream_lock, "STDERR")

        if not _INITIALIZED:
            atexit.register(_on_process_exit)

        _ACTIVE_LOG_PATH = latest_path
        _INITIALIZED = True

        diag_log = logging.getLogger("DesktopSuite.Diagnostics")
        diag_log.info("======================================================================")
        diag_log.info(
            "DesktopSuite Diagnostic Session Started | kind=%s | pid=%d | log=%s",
            session_kind, os.getpid(), latest_path,
        )
        diag_log.info("======================================================================")
        return latest_path


def write_startup_error(context: str, exc: BaseException) -> Optional[Path]:
    """Emergency writer if an error occurs before logging is initialized."""
    try:
        err_path = get_log_dir() / "DesktopSuite_startup_error.log"
        tb_str = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        msg = (
            f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {context} (pid={os.getpid()})\n"
            f"{tb_str}\n"
        )
        with err_path.open("a", encoding="utf-8") as fh:
            fh.write(msg)
        return err_path
    except Exception:
        return None


def read_log_tail(path: str | Path, max_lines: int = 35) -> str:
    """Safely return the last *max_lines* lines from a text/log file."""
    try:
        p = Path(path)
        if not p.is_file():
            return f"<file not found: {p}>"
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            lines = collections.deque(fh, maxlen=max_lines)
        return "".join(lines).rstrip()
    except Exception as exc:
        return f"<could not read {path}: {exc}>"


def log_environment_snapshot(cfg_manager: Any = None) -> None:
    """Record OS, graphics/DWM, dependencies, fonts, and config state to the log."""
    diag_log = logging.getLogger("DesktopSuite.Env")
    try:
        diag_log.info("--- System & Environment Snapshot ---")
        diag_log.info("Python: %s (%s)", sys.version.replace("\n", " "), sys.executable)
        diag_log.info("Frozen: %s | AppRoot: %s | CWD: %s", getattr(sys, "frozen", False), get_app_root(), Path.cwd())
        diag_log.info("CLI Args: %s", sys.argv)
        diag_log.info(
            "Platform: %s | Machine: %s | CPUs: %s | LogDir: %s",
            platform.platform(), platform.machine(), os.cpu_count(), get_log_dir(),
        )
        diag_log.info("Env QT_QPA_PLATFORM=%r", os.environ.get("QT_QPA_PLATFORM"))

        if sys.platform == "win32":
            _log_windows_snapshot(diag_log)

        try:
            from src.core.fonts import get_font_dir
            font_dir = get_font_dir()
            font_count = 0
            if font_dir.is_dir():
                font_count = len(list(font_dir.glob("*.ttf"))) + len(list(font_dir.glob("*.otf")))
            diag_log.info("Fonts dir: %s (exists=%s, font_files=%d)", font_dir, font_dir.is_dir(), font_count)
        except Exception as exc:
            diag_log.warning("Font dir check failed: %s", exc)

        if cfg_manager is not None:
            try:
                cfg_path = getattr(cfg_manager, "_path", "unknown")
                diag_log.info("Config file: %s (exists=%s)", cfg_path, Path(cfg_path).is_file() if cfg_path != "unknown" else "?")
                diag_log.info("Config snapshot: %s", json.dumps(cfg_manager.data, ensure_ascii=False))
            except Exception as exc:
                diag_log.warning("Could not serialize config snapshot: %s", exc)

        diag_log.info("--- End Snapshot ---")
    except Exception as exc:
        diag_log.warning("log_environment_snapshot error: %s", exc)


def _log_windows_snapshot(diag_log: logging.Logger) -> None:
    import ctypes
    from ctypes import wintypes

    try:
        wv = sys.getwindowsversion()
        diag_log.info(
            "Windows version: %d.%d.%d service_pack=%r product_type=%s",
            wv.major, wv.minor, wv.build, wv.service_pack, getattr(wv, "product_type", "?"),
        )
    except Exception as exc:
        diag_log.debug("getwindowsversion failed: %s", exc)

    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        cx, cy = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        vx, vy = user32.GetSystemMetrics(76), user32.GetSystemMetrics(77)
        vw, vh = user32.GetSystemMetrics(78), user32.GetSystemMetrics(79)
        anim = wintypes.BOOL(0)
        user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(anim), 0)
        diag_log.info(
            "Display: primary=%dx%d virtual=(%d,%d %dx%d) client_area_animation=%s",
            cx, cy, vx, vy, vw, vh, bool(anim.value),
        )
    except Exception as exc:
        diag_log.warning("Display metrics probe failed: %s", exc)

    try:
        dwmapi = ctypes.WinDLL("dwmapi")
        dwm_on = wintypes.BOOL(0)
        hr = dwmapi.DwmIsCompositionEnabled(ctypes.byref(dwm_on))
        diag_log.info("DWM Aero composition: hr=0x%08X enabled=%s", hr & 0xFFFFFFFF, bool(dwm_on.value))
    except Exception as exc:
        diag_log.warning("DWM composition check failed: %s", exc)

    # Check bundled Win7 DLLs & runtimes
    app_root = get_app_root()
    path_dll_root = app_root / "api-ms-win-core-path-l1-1-0.dll"
    path_dll_internal = app_root / "_internal" / "api-ms-win-core-path-l1-1-0.dll"
    vcruntime_ok = False
    try:
        ctypes.CDLL("vcruntime140.dll")
        vcruntime_ok = True
    except OSError:
        vcruntime_ok = False

    diag_log.info(
        "Runtime DLLs: api-ms-win-core-path(root=%s, _internal=%s) vcruntime140=%s",
        path_dll_root.is_file(), path_dll_internal.is_file(), vcruntime_ok,
    )

    try:
        from src.wallpaper.win_engine import WinWallpaperEngine
        mpv_bin = WinWallpaperEngine.find_mpv()
        diag_log.info("Resolved mpv binary: %s", mpv_bin)
        if mpv_bin:
            proc = subprocess.run(
                [mpv_bin, "--version"],
                capture_output=True,
                text=True,
                timeout=3.0,
                creationflags=0x08000000,
                check=False,
            )
            first_line = (proc.stdout or proc.stderr or "").splitlines()[:2]
            diag_log.info("mpv --version (rc=%s): %s", proc.returncode, " | ".join(first_line))
    except Exception as exc:
        diag_log.warning("mpv probe failed: %s", exc)


def log_win32_window_tree(context_label: str, logger: Optional[logging.Logger] = None) -> None:
    """
    Dump top-to-bottom Win32 Z-order entries for desktop shell, taskbar,
    mpv, and DesktopSuite windows to diagnose occlusion and parenting bugs.
    """
    if sys.platform != "win32":
        return

    target_log = logger or logging.getLogger("DesktopSuite.WinTree")
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        LPARAM = ctypes.c_ssize_t
        WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, LPARAM)

        user32.EnumWindows.argtypes = [WNDENUMPROC, LPARAM]
        user32.EnumWindows.restype = wintypes.BOOL
        user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, LPARAM]
        user32.EnumChildWindows.restype = wintypes.BOOL
        user32.IsWindowVisible.argtypes = [wintypes.HWND]
        user32.IsWindowVisible.restype = wintypes.BOOL
        user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
        user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
        user32.GetWindowRect.restype = wintypes.BOOL
        user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW.restype = ctypes.c_int
        user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetWindowTextW.restype = ctypes.c_int

        def _win_info(hwnd: int) -> dict[str, Any]:
            cls_buf = ctypes.create_unicode_buffer(256)
            title_buf = ctypes.create_unicode_buffer(256)
            pid = wintypes.DWORD(0)
            rect = wintypes.RECT()
            style = 0
            exstyle = 0
            vis = False
            try:
                user32.GetClassNameW(hwnd, cls_buf, 256)
                user32.GetWindowTextW(hwnd, title_buf, 256)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                style = user32.GetWindowLongPtrW(hwnd, -16)
                exstyle = user32.GetWindowLongPtrW(hwnd, -20)
                vis = bool(user32.IsWindowVisible(hwnd))
            except Exception:
                pass
            return {
                "hwnd": hwnd,
                "cls": cls_buf.value,
                "title": title_buf.value,
                "pid": pid.value,
                "vis": vis,
                "style": style & 0xFFFFFFFF,
                "exstyle": exstyle & 0xFFFFFFFF,
                "rect": (rect.left, rect.top, rect.right, rect.bottom),
            }

        top_windows: list[dict[str, Any]] = []
        my_pid = os.getpid()

        def _enum_top(hwnd, _lp):
            top_windows.append(_win_info(int(hwnd or 0)))
            return True

        cb_top = WNDENUMPROC(_enum_top)
        user32.EnumWindows(cb_top, 0)

        target_log.info("--- Win32 Z-Order Shell/App Tree (%s) [total top=%d] ---", context_label, len(top_windows))
        interesting_classes = {
            "Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd",
            "DesktopSuiteWin7MpvHost", "mpv",
        }
        for z_idx, info in enumerate(top_windows):
            hwnd = info["hwnd"]
            children: list[dict[str, Any]] = []

            def _enum_child(chwnd, _lp):
                children.append(_win_info(int(chwnd or 0)))
                return True

            cb_child = WNDENUMPROC(_enum_child)
            user32.EnumChildWindows(hwnd, cb_child, 0)

            has_defview = any(c["cls"] == "SHELLDLL_DefView" for c in children)
            has_mpv = any("DesktopSuite" in c["title"] or c["cls"] == "mpv" for c in children)
            is_match = (
                info["cls"] in interesting_classes
                or info["pid"] == my_pid
                or "DesktopSuite" in info["title"]
                or "Desktop Suite" in info["title"]
                or has_defview
                or has_mpv
            )
            if not is_match:
                continue

            target_log.info(
                "  [z=%03d] hwnd=0x%X cls=%r title=%r pid=%d vis=%s style=0x%08X ex=0x%08X rect=%s children=%d",
                z_idx, hwnd, info["cls"], info["title"], info["pid"],
                info["vis"], info["style"], info["exstyle"], info["rect"], len(children),
            )
            for c_idx, child in enumerate(children[:20]):
                target_log.info(
                    "      [child %02d] hwnd=0x%X cls=%r title=%r pid=%d vis=%s style=0x%08X rect=%s",
                    c_idx, child["hwnd"], child["cls"], child["title"], child["pid"],
                    child["vis"], child["style"], child["rect"],
                )
            if len(children) > 20:
                target_log.info("      ... (%d more children omitted)", len(children) - 20)
        target_log.info("--- End Win32 Tree (%s) ---", context_label)
    except Exception as exc:
        target_log.warning("log_win32_window_tree(%s) failed: %s", context_label, exc)
