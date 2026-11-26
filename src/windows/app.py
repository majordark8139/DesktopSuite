"""
src.windows.app
===============
Windows application controller coordinating wallpaper, canvas, and GUI.
"""

from __future__ import annotations

import ctypes
import logging
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QIcon, QPixmap
from PyQt5.QtWidgets import QApplication

from src.core.config import ConfigManager
from src.core.diagnostics import (
    install_qt_message_handler,
    log_environment_snapshot,
    uninstall_qt_message_handler,
)
from src.themes.registry import REGISTRY
from src.wallpaper.win_engine import WinWallpaperEngine
from src.canvas.win_audio import WinAudioStream
from src.canvas.win_window import WinDesktopCanvasWindow
from src.windows.dependencies import run_first_launch_check

log = logging.getLogger(__name__)


def load_app_icon() -> QIcon:
    """Build a multi-resolution QIcon from bundled PNG/ICO assets for Windows 7 taskbar & titlebar."""
    icon = QIcon()
    search_dirs: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        search_dirs.append(exe_dir / "assets" / "icons")
        search_dirs.append(exe_dir / "_internal" / "assets" / "icons")
        if hasattr(sys, "_MEIPASS"):
            search_dirs.append(Path(sys._MEIPASS) / "assets" / "icons")
    search_dirs.append(Path(__file__).resolve().parent.parent.parent / "assets" / "icons")
    search_dirs.append(Path.cwd() / "assets" / "icons")

    png_path: Optional[Path] = None
    ico_path: Optional[Path] = None
    for d in search_dirs:
        if png_path is None and (d / "desktop-suite.png").is_file():
            png_path = d / "desktop-suite.png"
        if ico_path is None and (d / "desktop-suite.ico").is_file():
            ico_path = d / "desktop-suite.ico"

    if png_path is not None:
        base_pm = QPixmap(str(png_path))
        if not base_pm.isNull():
            for sz in (16, 20, 24, 32, 48, 64, 128, 256):
                icon.addPixmap(base_pm.scaled(sz, sz, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    if ico_path is not None:
        icon.addFile(str(ico_path))
    return icon


class WinAppController:
    """
    Central controller managing all DesktopSuite subsystems on Windows.
    """

    def __init__(self) -> None:
        # 0. Enable Qt FreeType font engine on Windows 7 & explicit AppUserModelID for taskbar grouping/icon
        from src.core.win7_font_engine import enable_qt_freetype_on_win7, get_font_registry
        enable_qt_freetype_on_win7()
        if sys.platform == "win32":
            try:
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("DesktopSuite.ControlCenter.1")
            except Exception:
                pass
        install_qt_message_handler()

        # 1. Initialize QApplication before any QWidgets
        self._gui_app = QApplication.instance()
        if self._gui_app is None:
            self._gui_app = QApplication(sys.argv)

        self.app_icon = load_app_icon()
        if not self.app_icon.isNull():
            self._gui_app.setWindowIcon(self.app_icon)

        # Install inter-process activation filter for single-instance waking
        from src.core.win7_single_instance import ActivateMessageFilter
        self._msg_filter = ActivateMessageFilter(self.show_control_center)
        self._gui_app.installNativeEventFilter(self._msg_filter)

        # Initialize bundled font registry with Qt FreeType engine
        self._font_registry = get_font_registry()
        log.info(
            "BundledFontRegistry active: %d mapped keys, %d families (%s)",
            len(self._font_registry.family_map),
            len(self._font_registry.available_weights),
            ", ".join(sorted(self._font_registry.available_weights.keys())),
        )

        from PyQt5.QtGui import QPalette, QColor
        pal = QPalette()
        pal.setColor(QPalette.Window, QColor("#1e1e2e"))
        pal.setColor(QPalette.WindowText, QColor("#cdd6f4"))
        pal.setColor(QPalette.Base, QColor("#1e1e2e"))
        pal.setColor(QPalette.AlternateBase, QColor("#181825"))
        pal.setColor(QPalette.ToolTipBase, QColor("#1e1e2e"))
        pal.setColor(QPalette.ToolTipText, QColor("#cdd6f4"))
        pal.setColor(QPalette.Text, QColor("#cdd6f4"))
        pal.setColor(QPalette.Button, QColor("#313244"))
        pal.setColor(QPalette.ButtonText, QColor("#cdd6f4"))
        pal.setColor(QPalette.Highlight, QColor("#89b4fa"))
        pal.setColor(QPalette.HighlightedText, QColor("#1e1e2e"))
        self._gui_app.setPalette(pal)

        # 2. Asynchronously inspect dependencies (zero blocking on startup)
        run_first_launch_check(background=True)

        self.cfg = ConfigManager()
        log_environment_snapshot(self.cfg)
        self.registry = REGISTRY
        self.engine = WinWallpaperEngine()
        self.audio = WinAudioStream(
            intensity=float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        )
        self.canvas: Optional[WinDesktopCanvasWindow] = None
        self._gui_window = None
        self._stopping = False

        self._gui_app.aboutToQuit.connect(self.stop_all)

        log.info("WinAppController initialised successfully")

    def start_wallpaper(self) -> bool:
        wp = self.cfg.get("wallpaper") or {}
        path = wp.get("video_path", "")
        log.info("Controller.start_wallpaper requested (configured path=%r)", path)
        if not path or not Path(path).is_file():
            candidates = []
            if getattr(sys, "frozen", False):
                exe_dir = Path(sys.executable).resolve().parent
                candidates.append(exe_dir / "assets" / "screenshots" / "00-hero-demo.mp4")
                candidates.append(exe_dir / "_internal" / "assets" / "screenshots" / "00-hero-demo.mp4")
            candidates.append(Path(__file__).resolve().parent.parent.parent / "assets" / "screenshots" / "00-hero-demo.mp4")
            candidates.append(Path.cwd() / "assets" / "screenshots" / "00-hero-demo.mp4")
            for c in candidates:
                if c.is_file():
                    path = str(c.resolve())
                    log.info("Resolved fallback bundled demo video: %s", path)
                    self.cfg.set("wallpaper.video_path", path)
                    self.cfg.save()
                    break

        if not path or not Path(path).is_file():
            log.warning("start_wallpaper: no valid video_path in config")
            return False

        started = self.engine.start(
            video_path=path,
            speed=float(wp.get("playback_speed", 1.0)),
            volume=int(wp.get("volume", 50)),
            mute=bool(wp.get("mute", True)),
            fit_mode=wp.get("fit_mode", "fill"),
            fps_limit=wp.get("fps_limit", "native"),
            autopause=wp.get("autopause", "maximized"),
        )
        log.info("Controller.start_wallpaper result=%s", started)
        if started and self.canvas:
            self.canvas.lower_to_desktop()
        return started

    def stop_wallpaper(self) -> None:
        log.info("Controller.stop_wallpaper requested")
        self.engine.stop()

    def restart_wallpaper(self) -> bool:
        log.info("Controller.restart_wallpaper requested")
        self.engine.stop()
        res = self.start_wallpaper()
        if self.canvas:
            self.canvas.lower_to_desktop()
        log.info("Controller.restart_wallpaper result=%s", res)
        return res

    def start_canvas(self) -> None:
        if self.canvas is not None:
            log.info("Controller.start_canvas skipped (already running)")
            return
        theme_name = self.cfg.get("canvas.active_theme") or "Mond Minimal"
        theme = self.registry.get(theme_name) or self.registry.get_default()
        log.info("Controller.start_canvas starting audio stream & overlay (theme=%r)", getattr(theme, "name", theme_name))

        self.audio.start()
        self.canvas = WinDesktopCanvasWindow(
            cfg_manager=self.cfg,
            theme=theme,
            audio_stream=self.audio,
            wallpaper_engine=self.engine,
        )
        self.canvas.start()
        log.info("Windows canvas overlay started")

    def stop_canvas(self) -> None:
        log.info("Controller.stop_canvas requested")
        if self.canvas:
            self.canvas.stop()
            self.canvas = None
        self.audio.stop()

    def reload_canvas(self) -> None:
        log.debug("Controller.reload_canvas")
        if self.canvas:
            self.canvas.reload_config()

    def apply_theme(self, theme_name: str) -> None:
        log.info("Controller.apply_theme(%r)", theme_name)
        theme = self.registry.get(theme_name)
        if theme and self.canvas:
            self.canvas.set_theme(theme)
        self.cfg.set("canvas.active_theme", theme_name)
        self.cfg.save()

    def toggle_canvas_edit_mode(self) -> bool:
        if self.canvas:
            editing = self.canvas.toggle_edit_mode()
            log.info("Controller.toggle_canvas_edit_mode -> %s", editing)
            return editing
        return False

    def start_all(self) -> None:
        log.info("Controller.start_all()")
        self.start_wallpaper()
        self.start_canvas()

    def stop_all(self) -> None:
        if self._stopping:
            return
        self._stopping = True
        log.info("Controller.stop_all()")
        self.stop_canvas()
        self.stop_wallpaper()
        if self._msg_filter is not None and self._gui_app is not None:
            try:
                self._gui_app.removeNativeEventFilter(self._msg_filter)
            except Exception:
                pass
            self._msg_filter = None
        if self._gui_window is not None:
            try:
                self._gui_window.close()
                self._gui_window.deleteLater()
            except Exception:
                pass
            self._gui_window = None
        if self._gui_app is not None:
            try:
                self._gui_app.processEvents()
            except Exception:
                pass

    def show_control_center(self) -> None:
        from src.windows.control_center import create_control_center

        if self._gui_window is None:
            log.info("Creating ControlCenterWindow")
            self._gui_window = create_control_center(self)

        if self._gui_window:
            log.info("Showing & raising ControlCenterWindow")
            self._gui_window.show()
            self._gui_window.raise_()
            self._gui_window.activateWindow()

    def run(self, daemon: bool = False) -> None:
        log.info("WinAppController.run(daemon=%s)", daemon)
        self.start_all()
        if not daemon:
            self.show_control_center()
        try:
            rc = self._gui_app.exec_()
            log.info("QApplication.exec_() exited with code %s", rc)
        finally:
            self.stop_all()
            uninstall_qt_message_handler()
            self._gui_app = None


def run_windows(daemon: bool = False) -> None:
    """Windows entry point for DesktopSuite."""
    ctrl = WinAppController()
    ctrl.run(daemon=daemon)
