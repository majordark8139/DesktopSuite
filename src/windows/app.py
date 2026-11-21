"""
src.windows.app
===============
Windows application controller coordinating wallpaper, canvas, and GUI.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from typing import Optional

from PyQt5.QtWidgets import QApplication

from src.core.config import ConfigManager
from src.core.fonts import register_bundled_fonts
from src.themes.registry import REGISTRY
from src.wallpaper.win_engine import WinWallpaperEngine
from src.canvas.win_audio import WinAudioStream
from src.canvas.win_window import WinDesktopCanvasWindow
from src.windows.dependencies import run_first_launch_check

log = logging.getLogger(__name__)


class WinAppController:
    """
    Central controller managing all DesktopSuite subsystems on Windows.
    """

    def __init__(self) -> None:
        # 0. Enable Qt FreeType font engine on Windows 7
        from src.core.win7_font_engine import enable_qt_freetype_on_win7, get_font_registry
        enable_qt_freetype_on_win7()

        # 1. Initialize QApplication before any QWidgets
        self._gui_app = QApplication.instance()
        if self._gui_app is None:
            self._gui_app = QApplication(sys.argv)

        # Install inter-process activation filter for single-instance waking
        from src.core.win7_single_instance import ActivateMessageFilter
        self._msg_filter = ActivateMessageFilter(self.show_control_center)
        self._gui_app.installNativeEventFilter(self._msg_filter)

        # Initialize bundled font registry with Qt FreeType engine
        self._font_registry = get_font_registry()

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

        # 2. Register bundled fonts with Windows GDI
        register_bundled_fonts()

        # 3. Asynchronously inspect dependencies (zero blocking on startup)
        run_first_launch_check(background=True)

        self.cfg = ConfigManager()
        self.registry = REGISTRY
        self.engine = WinWallpaperEngine()
        self.audio = WinAudioStream(
            intensity=float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        )
        self.canvas: Optional[WinDesktopCanvasWindow] = None
        self._gui_window = None

        self._gui_app.aboutToQuit.connect(self.stop_all)

        log.info("WinAppController initialised successfully")

    def start_wallpaper(self) -> bool:
        wp = self.cfg.get("wallpaper") or {}
        path = wp.get("video_path", "")
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
        if started and self.canvas:
            self.canvas.lower_to_desktop()
        return started

    def stop_wallpaper(self) -> None:
        self.engine.stop()

    def restart_wallpaper(self) -> bool:
        self.engine.stop()
        res = self.start_wallpaper()
        if self.canvas:
            self.canvas.lower_to_desktop()
        return res

    def start_canvas(self) -> None:
        if self.canvas is not None:
            return
        theme_name = self.cfg.get("canvas.active_theme") or "Mond Minimal"
        theme = self.registry.get(theme_name) or self.registry.get_default()

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
        if self.canvas:
            self.canvas.stop()
            self.canvas = None
        self.audio.stop()

    def reload_canvas(self) -> None:
        if self.canvas:
            self.canvas.reload_config()

    def apply_theme(self, theme_name: str) -> None:
        theme = self.registry.get(theme_name)
        if theme and self.canvas:
            self.canvas.set_theme(theme)
        self.cfg.set("canvas.active_theme", theme_name)
        self.cfg.save()

    def toggle_canvas_edit_mode(self) -> bool:
        if self.canvas:
            return self.canvas.toggle_edit_mode()
        return False

    def start_all(self) -> None:
        self.start_canvas()
        self.start_wallpaper()

    def stop_all(self) -> None:
        self.stop_canvas()
        self.stop_wallpaper()

    def show_control_center(self) -> None:
        from src.windows.control_center import create_control_center

        if self._gui_window is None:
            self._gui_window = create_control_center(self)

        if self._gui_window:
            self._gui_window.show()
            self._gui_window.raise_()
            self._gui_window.activateWindow()

    def run(self, daemon: bool = False) -> None:
        self.start_all()
        if not daemon:
            self.show_control_center()
        self._gui_app.exec_()


def run_windows(daemon: bool = False) -> None:
    """Windows entry point for DesktopSuite."""
    ctrl = WinAppController()
    ctrl.run(daemon=daemon)
