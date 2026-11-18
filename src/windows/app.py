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

from src.core.config import ConfigManager
from src.core.fonts import register_bundled_fonts
from src.themes.registry import REGISTRY
from src.wallpaper.win_engine import WinWallpaperEngine
from src.canvas.win_audio import WinAudioStream
from src.canvas.win_window import WinDesktopCanvasWindow

log = logging.getLogger(__name__)


class WinAppController:
    """
    Central controller managing all DesktopSuite subsystems on Windows.
    """

    def __init__(self) -> None:
        register_bundled_fonts()

        self.cfg = ConfigManager()
        self.registry = REGISTRY
        self.engine = WinWallpaperEngine()
        self.audio = WinAudioStream(
            intensity=float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        )
        self.canvas: Optional[WinDesktopCanvasWindow] = None
        self._gui_app = None
        self._gui_window = None

        log.info("WinAppController initialised")

    def start_wallpaper(self) -> bool:
        wp = self.cfg.get("wallpaper") or {}
        path = wp.get("video_path", "")
        if not path or not Path(path).is_file():
            log.warning("start_wallpaper: no valid video_path in config")
            return False

        return self.engine.start(
            video_path=path,
            speed=float(wp.get("playback_speed", 1.0)),
            volume=int(wp.get("volume", 50)),
            mute=bool(wp.get("mute", True)),
            fit_mode=wp.get("fit_mode", "fill"),
            fps_limit=wp.get("fps_limit", "native"),
            autopause=wp.get("autopause", "focus"),
        )

    def stop_wallpaper(self) -> None:
        self.engine.stop()

    def restart_wallpaper(self) -> bool:
        self.engine.stop()
        return self.start_wallpaper()

    def start_canvas(self) -> None:
        if self.canvas is not None:
            return
        theme_name = self.cfg.get("canvas.active_theme") or "Original Cursive"
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

    def show_control_center(self) -> None:
        try:
            from PyQt5.QtWidgets import QApplication
            from src.windows.control_center import create_control_center

            if self._gui_app is None:
                self._gui_app = QApplication.instance() or QApplication(sys.argv)

            if self._gui_window is None:
                self._gui_window = create_control_center(self)

            if self._gui_window:
                self._gui_window.show()
                self._gui_window.raise_()
                self._gui_window.activateWindow()
                self._gui_app.exec_()
        except ImportError:
            log.warning("PyQt5 is not installed; running in background mode")
            # Keep main thread alive
            try:
                while True:
                    time.sleep(1.0)
            except KeyboardInterrupt:
                pass


def run_windows(daemon: bool = False) -> None:
    """Windows entry point for DesktopSuite."""
    ctrl = WinAppController()
    ctrl.start_all()

    if not daemon:
        ctrl.show_control_center()
    else:
        try:
            while True:
                time.sleep(1.0)
        except KeyboardInterrupt:
            ctrl.engine.stop()
            ctrl.stop_canvas()
