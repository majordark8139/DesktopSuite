"""
src.windows.control_center
==========================
Comprehensive PyQt5 Control Center GUI for DesktopSuite on Windows.
Replicates the full feature set and dark Catppuccin theme styling of the Linux GUI.
Includes global Windows hotkey integration (RegisterHotKey / WM_HOTKEY) for live wallpaper toggling/killing.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import logging
import os
import sys
from pathlib import Path
from typing import Any, Optional

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QGroupBox, QPushButton, QLabel, QSlider, QCheckBox,
    QComboBox, QFileDialog, QColorDialog, QScrollArea, QFrame
)
from PyQt5.QtCore import Qt, QEvent
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap, QPalette

from src.core.diagnostics import get_rate_limiter

log = logging.getLogger(__name__)

# Win32 Hotkey Modifiers
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312

HOTKEY_PRESETS = {
    "Win + W (Default)": (MOD_WIN | MOD_NOREPEAT, ord('W')),
    "Ctrl + Alt + W": (MOD_CONTROL | MOD_ALT | MOD_NOREPEAT, ord('W')),
    "Ctrl + Shift + W": (MOD_CONTROL | MOD_SHIFT | MOD_NOREPEAT, ord('W')),
    "Alt + W": (MOD_ALT | MOD_NOREPEAT, ord('W')),
    "F12": (MOD_NOREPEAT, 0x7B),  # VK_F12
    "Disabled": None,
}

_WIN_DARK_QSS = """
QMainWindow, QWidget#CentralWidget, QWidget#tab_wp, QWidget#tab_cv, QWidget#content_wp, QWidget#content_cv {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', 'Segoe UI Web (West European)', -apple-system, BlinkMacSystemFont, Roboto, Helvetica, Arial, sans-serif;
    font-size: 12px;
}
QScrollArea {
    border: none;
    background-color: #1e1e2e;
}
QScrollArea > QWidget {
    background-color: #1e1e2e;
    border: none;
}
QTabWidget::pane {
    border: none;
    background-color: #1e1e2e;
}
QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    padding: 10px 24px;
    font-size: 13px;
    font-weight: bold;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    margin-right: 4px;
    min-width: 150px;
}
QTabBar::tab:selected {
    background-color: #1e1e2e;
    color: #89b4fa;
    border-bottom: 3px solid #89b4fa;
}
QGroupBox {
    background-color: #252839;
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px;
    font-weight: bold;
    color: #89b4fa;
    border: 1px solid #363a4f;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #89b4fa;
    font-size: 12px;
    font-weight: bold;
}
QPushButton {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: bold;
    border: 1px solid #45475a;
}
QPushButton:hover {
    background-color: #45475a;
    border-color: #585b70;
}
QPushButton:pressed {
    background-color: #585b70;
}
QSlider::groove:horizontal {
    height: 6px;
    background-color: #313244;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background-color: #89b4fa;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    background-color: #cdd6f4;
    width: 14px;
    margin-top: -4px;
    margin-bottom: -4px;
    border-radius: 7px;
}
QSlider::handle:horizontal:hover {
    background-color: #89b4fa;
}
QComboBox {
    background-color: #313244;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 5px 12px;
    border: 1px solid #45475a;
    min-height: 24px;
}
QComboBox:hover {
    border-color: #89b4fa;
}
QComboBox QAbstractItemView {
    background-color: #252839;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
    padding: 4px;
    border: 1px solid #45475a;
}
QCheckBox {
    color: #cdd6f4;
    spacing: 8px;
    font-weight: normal;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    background-color: #313244;
    border: 1px solid #45475a;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
    border-color: #89b4fa;
}
QLabel {
    color: #cdd6f4;
}
"""


def get_windows_startup_dir() -> Path:
    """Return the Windows user startup directory."""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"


class ControlCenterWindow(QMainWindow):
    """
    Full-featured Control Center GUI for DesktopSuite on Windows.
    """

    HOTKEY_ID = 1001

    def __init__(self, controller: Any) -> None:
        super().__init__()
        self.ctrl = controller
        self.cfg = controller.cfg
        self._building = True
        self._current_hotkey = self.cfg.get("wallpaper.shortcut", "Win + W (Default)")

        self.setWindowTitle("Desktop Suite Control Center")
        self.resize(660, 780)
        self.setMinimumSize(580, 660)
        self.setStyleSheet(_WIN_DARK_QSS)

        central = QWidget(self)
        central.setObjectName("CentralWidget")
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(12, 12, 12, 12)

        tabs = QTabWidget()
        main_layout.addWidget(tabs)

        # Tab 1: Live Wallpaper
        tab_wp = QWidget()
        tab_wp.setObjectName("tab_wp")
        scroll_wp = QScrollArea()
        scroll_wp.setObjectName("scroll_wp")
        scroll_wp.setWidgetResizable(True)
        scroll_wp.viewport().setStyleSheet("background-color: #1e1e2e; border: none;")
        content_wp = QWidget()
        content_wp.setObjectName("content_wp")
        layout_wp = QVBoxLayout(content_wp)
        layout_wp.setSpacing(12)
        layout_wp.setContentsMargins(12, 12, 12, 12)
        self._build_wallpaper_tab(layout_wp)
        scroll_wp.setWidget(content_wp)
        layout_tab_wp = QVBoxLayout(tab_wp)
        layout_tab_wp.setContentsMargins(0, 0, 0, 0)
        layout_tab_wp.addWidget(scroll_wp)
        tabs.addTab(tab_wp, "🎬 Live Wallpaper")

        # Tab 2: Clock & Canvas Studio
        tab_cv = QWidget()
        tab_cv.setObjectName("tab_cv")
        scroll_cv = QScrollArea()
        scroll_cv.setObjectName("scroll_cv")
        scroll_cv.setWidgetResizable(True)
        scroll_cv.viewport().setStyleSheet("background-color: #1e1e2e; border: none;")
        content_cv = QWidget()
        content_cv.setObjectName("content_cv")
        layout_cv = QVBoxLayout(content_cv)
        layout_cv.setSpacing(12)
        layout_cv.setContentsMargins(12, 12, 12, 12)
        self._build_canvas_tab(layout_cv)
        scroll_cv.setWidget(content_cv)
        layout_tab_cv = QVBoxLayout(tab_cv)
        layout_tab_cv.setContentsMargins(0, 0, 0, 0)
        layout_tab_cv.addWidget(scroll_cv)
        tabs.addTab(tab_cv, "🕒 Clock && Canvas Studio")
        tabs.currentChanged.connect(lambda idx: log.info("UI Tab switched -> %r (index=%d)", tabs.tabText(idx), idx))

        self._building = False
        self._update_engine_status()
        self._register_global_hotkey(self._current_hotkey)
        log.info(
            "ControlCenterWindow initialized (hotkey=%r, theme=%r, video=%r)",
            self._current_hotkey,
            self.cfg.get("canvas.active_theme"),
            self.cfg.get("wallpaper.video_path"),
        )

    # -----------------------------------------------------------------------
    # Native Event Handling for Global Win32 Hotkey
    # -----------------------------------------------------------------------

    def nativeEvent(self, eventType, message) -> tuple[bool, int]:
        if eventType in (b"windows_generic_MSG", "windows_generic_MSG"):
            try:
                msg = wintypes.MSG.from_address(int(message))
                if msg.message == WM_HOTKEY and msg.wParam == self.HOTKEY_ID:
                    self._on_global_hotkey_triggered()
                    return True, 0
            except Exception as exc:
                allowed, suppressed = get_rate_limiter().check("ui:nativeEvent", interval=5.0)
                if allowed:
                    log.warning("nativeEvent MSG handling error (suppressed=%d): %s", suppressed, exc)
        return super().nativeEvent(eventType, message)

    def _register_global_hotkey(self, hotkey_name: str) -> bool:
        """Register the system-wide global hotkey via Win32 RegisterHotKey."""
        try:
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())
            user32.UnregisterHotKey(hwnd, self.HOTKEY_ID)

            if hotkey_name not in HOTKEY_PRESETS or hotkey_name == "Disabled":
                self.lbl_hk_status.setText("● Hotkey Disabled")
                self.lbl_hk_status.setStyleSheet("color: #a6adc8; font-weight: normal;")
                self._current_hotkey = "Disabled"
                if not self._building:
                    self.cfg.set("wallpaper.shortcut", "Disabled")
                    self.cfg.save()
                log.info("Global Windows hotkey disabled")
                return False

            params = HOTKEY_PRESETS[hotkey_name]
            if params is None:
                return False

            mods, vk = params
            res = user32.RegisterHotKey(hwnd, self.HOTKEY_ID, mods, vk)
            if res:
                self._current_hotkey = hotkey_name
                self.cfg.set("wallpaper.shortcut", hotkey_name)
                self.cfg.save()
                self.lbl_hk_status.setText(f"● Hotkey Active: {hotkey_name} (press anywhere in Windows to toggle/kill)")
                self.lbl_hk_status.setStyleSheet("color: #a6e3a1; font-weight: bold;")
                log.info("Registered global Windows hotkey: %s", hotkey_name)
                return True
            else:
                self.lbl_hk_status.setText(f"⚠ Could not bind {hotkey_name} (in use by another application)")
                self.lbl_hk_status.setStyleSheet("color: #fab387; font-weight: bold;")
                log.warning("Could not register hotkey %s (Win32 error: %s)", hotkey_name, ctypes.GetLastError())
                return False
        except Exception as exc:
            log.warning("RegisterHotKey exception: %s", exc)
            return False

    def _on_global_hotkey_triggered(self) -> None:
        """Toggles wallpaper playback or kills active video engine on global shortcut press."""
        log.info("Global hotkey triggered: %s", self._current_hotkey)
        if self.ctrl.engine.is_running():
            self.ctrl.stop_wallpaper()
            log.info("Global hotkey: Stopped / killed live wallpaper")
        else:
            self.ctrl.start_wallpaper()
            log.info("Global hotkey: Started live wallpaper")
        self._update_engine_status()

    def showEvent(self, event) -> None:
        log.info("ControlCenterWindow.showEvent()")
        super().showEvent(event)

    def hideEvent(self, event) -> None:
        log.info("ControlCenterWindow.hideEvent()")
        super().hideEvent(event)

    def changeEvent(self, event) -> None:
        if event.type() == QEvent.WindowStateChange:
            log.info("ControlCenterWindow state changed -> minimized=%s", self.isMinimized())
        super().changeEvent(event)

    def closeEvent(self, event) -> None:
        """Unregister hotkey when window closes."""
        log.info("ControlCenterWindow.closeEvent() -> closing Control Center")
        try:
            ctypes.windll.user32.UnregisterHotKey(int(self.winId()), self.HOTKEY_ID)
        except Exception:
            pass
        event.accept()

    # -----------------------------------------------------------------------
    # Tab 1: Live Wallpaper
    # -----------------------------------------------------------------------

    def _build_wallpaper_tab(self, layout: QVBoxLayout) -> None:
        # 1. Engine Controls
        grp_eng = QGroupBox("Engine Controls")
        v_eng = QVBoxLayout(grp_eng)
        v_eng.setSpacing(10)

        h_status = QHBoxLayout()
        h_status.addWidget(QLabel("Status:"))
        self.lbl_status = QLabel(" Stopped ")
        self.lbl_status.setStyleSheet("background-color: #45475a; border-radius: 8px; padding: 3px 10px; color: #cdd6f4; font-weight: bold;")
        h_status.addWidget(self.lbl_status)
        h_status.addStretch()
        v_eng.addLayout(h_status)

        # Engine buttons: 2-row layout with bold, high-contrast, crystal-clear buttons
        # Row 1: Primary Controls (Start, Stop, Restart)
        h_btns_row1 = QHBoxLayout()
        h_btns_row1.setSpacing(8)

        btn_start = QPushButton("▶  Start")
        btn_start.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
            QPushButton:pressed {
                background-color: #74c7ec;
            }
        """)
        btn_start.clicked.connect(self._on_start)

        btn_stop = QPushButton("■  Stop")
        btn_stop.setStyleSheet("""
            QPushButton {
                background-color: #f38ba8;
                color: #11111b;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #f5c2e7;
            }
            QPushButton:pressed {
                background-color: #eba0ac;
            }
        """)
        btn_stop.clicked.connect(self._on_stop)

        btn_restart = QPushButton("↺  Restart")
        btn_restart.setStyleSheet("""
            QPushButton {
                background-color: #fab387;
                color: #11111b;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 13px;
                border: none;
            }
            QPushButton:hover {
                background-color: #f9e2af;
            }
            QPushButton:pressed {
                background-color: #f5a97f;
            }
        """)
        btn_restart.clicked.connect(self._on_restart)

        h_btns_row1.addWidget(btn_start, 1)
        h_btns_row1.addWidget(btn_stop, 1)
        h_btns_row1.addWidget(btn_restart, 1)
        v_eng.addLayout(h_btns_row1)

        # Row 2: Secondary / Safety Controls (Pause / Resume, Kill Wallpaper)
        h_btns_row2 = QHBoxLayout()
        h_btns_row2.setSpacing(8)

        btn_pause = QPushButton("⏸  Pause / Resume")
        btn_pause.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
                border: 1px solid #45475a;
            }
            QPushButton:hover {
                background-color: #45475a;
                border-color: #585b70;
            }
            QPushButton:pressed {
                background-color: #585b70;
            }
        """)
        btn_pause.clicked.connect(self._on_pause)

        btn_kill = QPushButton("💀  Kill Wallpaper")
        btn_kill.setStyleSheet("""
            QPushButton {
                background-color: #e53935;
                color: #ffffff;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
                font-size: 12px;
                border: none;
            }
            QPushButton:hover {
                background-color: #ef5350;
            }
            QPushButton:pressed {
                background-color: #c62828;
            }
        """)
        btn_kill.setToolTip("Force terminate mpv process immediately")
        btn_kill.clicked.connect(self._on_kill)

        h_btns_row2.addWidget(btn_pause, 1)
        h_btns_row2.addWidget(btn_kill, 1)
        v_eng.addLayout(h_btns_row2)

        h_file = QHBoxLayout()
        h_file.addWidget(QLabel("Video:"))
        cur_video = self.cfg.get("wallpaper.video_path") or ""
        video_display = Path(cur_video).name if cur_video else "None selected"
        self.lbl_file = QLabel(video_display)
        self.lbl_file.setStyleSheet("color: #a6adc8; font-style: italic;")
        btn_browse = QPushButton("Browse...")
        btn_browse.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                border: 1px solid #45475a;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
        """)
        btn_browse.clicked.connect(self._on_browse)
        h_file.addWidget(self.lbl_file, 1)
        h_file.addWidget(btn_browse)
        v_eng.addLayout(h_file)

        layout.addWidget(grp_eng)

        # 2. Playback Tuning
        grp_pb = QGroupBox("Playback")
        v_pb = QVBoxLayout(grp_pb)
        v_pb.setSpacing(10)

        # Volume
        h_vol = QHBoxLayout()
        vol_val = int(self.cfg.get("wallpaper.volume") or 50)
        self.lbl_vol_val = QLabel(f"{vol_val}%")
        self.lbl_vol_val.setFixedWidth(45)
        h_vol.addWidget(QLabel("Volume:"))
        sl_vol = QSlider(Qt.Horizontal)
        sl_vol.setRange(0, 100)
        sl_vol.setValue(vol_val)
        sl_vol.valueChanged.connect(self._on_volume_changed)
        sl_vol.sliderReleased.connect(lambda: log.info("UI Slider released: volume=%d%%", sl_vol.value()))
        h_vol.addWidget(sl_vol, 1)
        h_vol.addWidget(self.lbl_vol_val)
        v_pb.addLayout(h_vol)

        # Speed
        h_spd = QHBoxLayout()
        spd_val = float(self.cfg.get("wallpaper.playback_speed") or 1.0)
        self.lbl_spd_val = QLabel(f"{spd_val:.2f}x")
        self.lbl_spd_val.setFixedWidth(45)
        h_spd.addWidget(QLabel("Speed:"))
        sl_spd = QSlider(Qt.Horizontal)
        sl_spd.setRange(25, 200)
        sl_spd.setValue(int(spd_val * 100))
        sl_spd.valueChanged.connect(self._on_speed_changed)
        sl_spd.sliderReleased.connect(lambda: log.info("UI Slider released: speed=%.2fx", sl_spd.value() / 100.0))
        h_spd.addWidget(sl_spd, 1)
        h_spd.addWidget(self.lbl_spd_val)
        v_pb.addLayout(h_spd)

        # Mute
        chk_mute = QCheckBox("Mute Video Audio")
        chk_mute.setChecked(bool(self.cfg.get("wallpaper.mute", True)))
        chk_mute.toggled.connect(self._on_mute_changed)
        v_pb.addWidget(chk_mute)

        layout.addWidget(grp_pb)

        # 3. Global Hotkey / Shortcut Manager
        grp_hk = QGroupBox("Keyboard Shortcut && Global Hotkey")
        v_hk = QVBoxLayout(grp_hk)
        v_hk.setSpacing(8)

        lbl_hk_desc = QLabel("System-wide hotkey to toggle or kill live wallpaper from any application or game.")
        lbl_hk_desc.setStyleSheet("color: #a6adc8; font-size: 11px;")
        v_hk.addWidget(lbl_hk_desc)

        h_hk = QHBoxLayout()
        h_hk.addWidget(QLabel("Toggle Hotkey:"))
        self.cb_hotkey = QComboBox()
        for k in HOTKEY_PRESETS.keys():
            self.cb_hotkey.addItem(k)
        cur_hk = self.cfg.get("wallpaper.shortcut") or "Win + W (Default)"
        if cur_hk in HOTKEY_PRESETS:
            self.cb_hotkey.setCurrentText(cur_hk)
        h_hk.addWidget(self.cb_hotkey, 1)

        btn_bind_hk = QPushButton("Bind Hotkey")
        btn_bind_hk.setStyleSheet("""
            QPushButton {
                background-color: #89b4fa;
                color: #11111b;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                border: none;
            }
            QPushButton:hover {
                background-color: #b4befe;
            }
        """)
        btn_bind_hk.clicked.connect(lambda: self._register_global_hotkey(self.cb_hotkey.currentText()))
        btn_remove_hk = QPushButton("Disable")
        btn_remove_hk.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: bold;
                border: 1px solid #45475a;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
        """)
        btn_remove_hk.clicked.connect(lambda: (self.cb_hotkey.setCurrentText("Disabled"), self._register_global_hotkey("Disabled")))
        h_hk.addWidget(btn_bind_hk)
        h_hk.addWidget(btn_remove_hk)
        v_hk.addLayout(h_hk)

        self.lbl_hk_status = QLabel("● Initializing global hotkey...")
        self.lbl_hk_status.setStyleSheet("color: #a6adc8; font-size: 11px;")
        v_hk.addWidget(self.lbl_hk_status)

        layout.addWidget(grp_hk)

        # 4. Behaviour & System Integration
        grp_beh = QGroupBox("Behaviour && System")
        v_beh = QVBoxLayout(grp_beh)
        v_beh.setSpacing(10)

        # Fit Mode
        h_fit = QHBoxLayout()
        h_fit.addWidget(QLabel("Screen Fit:"))
        cb_fit = QComboBox()
        cb_fit.addItems(["Fill (Zoom / Crop)", "Fit (Letterbox)", "Stretch"])
        fit_map = {"fill": 0, "fit": 1, "stretch": 2}
        cb_fit.setCurrentIndex(fit_map.get(self.cfg.get("wallpaper.fit_mode"), 0))
        cb_fit.currentIndexChanged.connect(lambda i: self._on_fit_changed(["fill", "fit", "stretch"][i]))
        h_fit.addWidget(cb_fit, 1)
        v_beh.addLayout(h_fit)

        # Auto-Pause
        h_ap = QHBoxLayout()
        h_ap.addWidget(QLabel("Auto-Pause:"))
        cb_ap = QComboBox()
        cb_ap.addItems(["Focus (Any App)", "Maximized Only", "Off"])
        ap_map = {"focus": 0, "maximized": 1, "off": 2}
        cb_ap.setCurrentIndex(ap_map.get(self.cfg.get("wallpaper.autopause"), 0))
        cb_ap.currentIndexChanged.connect(lambda i: self._on_ap_changed(["focus", "maximized", "off"][i]))
        h_ap.addWidget(cb_ap, 1)
        v_beh.addLayout(h_ap)

        # FPS Limiter
        h_fps = QHBoxLayout()
        h_fps.addWidget(QLabel("FPS Limiter:"))
        cb_fps = QComboBox()
        cb_fps.addItems(["Native (Uncapped)", "30 FPS", "24 FPS"])
        fps_map = {"native": 0, "30": 1, "24": 2}
        cb_fps.setCurrentIndex(fps_map.get(self.cfg.get("wallpaper.fps_limit"), 0))
        cb_fps.currentIndexChanged.connect(lambda i: self._on_fps_changed(["native", "30", "24"][i]))
        h_fps.addWidget(cb_fps, 1)
        v_beh.addLayout(h_fps)

        # Autostart on Windows login
        chk_auto = QCheckBox("Launch DesktopSuite on Windows Login")
        chk_auto.setChecked(bool(self.cfg.get("wallpaper.autostart", False)))
        chk_auto.toggled.connect(self._on_autostart_toggled)
        v_beh.addWidget(chk_auto)

        layout.addWidget(grp_beh)
        layout.addStretch()

    # -----------------------------------------------------------------------
    # Tab 2: Clock & Canvas Studio
    # -----------------------------------------------------------------------

    def _build_canvas_tab(self, layout: QVBoxLayout) -> None:
        # 1. Theme Selector
        grp_th = QGroupBox("Visual Theme")
        v_th = QVBoxLayout(grp_th)
        h_th = QHBoxLayout()
        h_th.addWidget(QLabel("Theme:"))
        self.cb_theme = QComboBox()
        theme_names = self.ctrl.registry.names()
        self.cb_theme.addItems(theme_names)
        cur_th = self.cfg.get("canvas.active_theme") or "Mond Minimal"
        if cur_th in theme_names:
            self.cb_theme.setCurrentText(cur_th)
        self.cb_theme.currentTextChanged.connect(self._on_theme_changed)
        h_th.addWidget(self.cb_theme, 1)
        v_th.addLayout(h_th)
        layout.addWidget(grp_th)

        # 2. Components Visibility
        grp_cmp = QGroupBox("Components")
        v_cmp = QVBoxLayout(grp_cmp)
        v_cmp.setSpacing(8)

        chk_clk = QCheckBox("Show Clock")
        chk_clk.setChecked(bool(self.cfg.get("canvas.clock_enabled", True)))
        chk_clk.toggled.connect(lambda v: self._set_canvas_cfg("canvas.clock_enabled", v))
        v_cmp.addWidget(chk_clk)

        chk_dt = QCheckBox("Show Date")
        chk_dt.setChecked(bool(self.cfg.get("canvas.date_enabled", True)))
        chk_dt.toggled.connect(lambda v: self._set_canvas_cfg("canvas.date_enabled", v))
        v_cmp.addWidget(chk_dt)

        chk_vis = QCheckBox("Show Audio Visualizer")
        chk_vis.setChecked(bool(self.cfg.get("canvas.visualizer_enabled", True)))
        chk_vis.toggled.connect(lambda v: self._set_canvas_cfg("canvas.visualizer_enabled", v))
        v_cmp.addWidget(chk_vis)
        layout.addWidget(grp_cmp)

        # 3. Decoupled RGB Colors with Live Swatches
        grp_col = QGroupBox("Decoupled Component Colors")
        v_col = QVBoxLayout(grp_col)
        v_col.setSpacing(10)

        # Clock Color Row
        self.btn_col_clk = QPushButton()
        self._update_color_button(self.btn_col_clk, self.cfg.get("canvas.clock_color") or "#FFFFFF", "Clock Color")
        self.btn_col_clk.clicked.connect(lambda: self._pick_color("canvas.clock_color", self.btn_col_clk, "Clock Color"))
        v_col.addWidget(self.btn_col_clk)

        # Date Color Row
        self.btn_col_dt = QPushButton()
        self._update_color_button(self.btn_col_dt, self.cfg.get("canvas.date_color") or "#D0D0D0", "Date Color")
        self.btn_col_dt.clicked.connect(lambda: self._pick_color("canvas.date_color", self.btn_col_dt, "Date Color"))
        v_col.addWidget(self.btn_col_dt)

        # Visualizer Color Row
        self.btn_col_vis = QPushButton()
        self._update_color_button(self.btn_col_vis, self.cfg.get("canvas.visualizer_color") or "#FFFFFF", "Visualizer Color")
        self.btn_col_vis.clicked.connect(lambda: self._pick_color("canvas.visualizer_color", self.btn_col_vis, "Visualizer Color"))
        v_col.addWidget(self.btn_col_vis)

        layout.addWidget(grp_col)

        # 4. Scaling, Opacity & Intensity
        grp_sc = QGroupBox("Scaling && Appearance")
        v_sc = QVBoxLayout(grp_sc)
        v_sc.setSpacing(10)

        # Background Opacity
        h_op = QHBoxLayout()
        h_op.addWidget(QLabel("BG Opacity:"))
        op_val = float(self.cfg.get("canvas.background_opacity") or 0.0)
        self.lbl_op_val = QLabel(f"{int(op_val * 100)}%")
        self.lbl_op_val.setFixedWidth(45)
        sl_op = QSlider(Qt.Horizontal)
        sl_op.setRange(0, 100)
        sl_op.setValue(int(op_val * 100))
        sl_op.valueChanged.connect(self._on_opacity_changed)
        sl_op.sliderReleased.connect(lambda: log.info("UI Slider released: background_opacity=%d%%", sl_op.value()))
        h_op.addWidget(sl_op, 1)
        h_op.addWidget(self.lbl_op_val)
        v_sc.addLayout(h_op)

        # Master Scale
        h_msc = QHBoxLayout()
        h_msc.addWidget(QLabel("Master Scale:"))
        msc_val = float(self.cfg.get("canvas.scale") or 1.0)
        self.lbl_msc_val = QLabel(f"{msc_val:.2f}x")
        self.lbl_msc_val.setFixedWidth(45)
        sl_msc = QSlider(Qt.Horizontal)
        sl_msc.setRange(50, 250)
        sl_msc.setValue(int(msc_val * 100))
        sl_msc.valueChanged.connect(self._on_scale_changed)
        sl_msc.sliderReleased.connect(lambda: log.info("UI Slider released: master_scale=%.2fx", sl_msc.value() / 100.0))
        h_msc.addWidget(sl_msc, 1)
        h_msc.addWidget(self.lbl_msc_val)
        v_sc.addLayout(h_msc)

        # Visualizer Intensity
        h_int = QHBoxLayout()
        h_int.addWidget(QLabel("Vis Intensity:"))
        int_val = float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        self.lbl_int_val = QLabel(f"{int(int_val * 100)}%")
        self.lbl_int_val.setFixedWidth(45)
        sl_int = QSlider(Qt.Horizontal)
        sl_int.setRange(10, 200)
        sl_int.setValue(int(int_val * 100))
        sl_int.valueChanged.connect(self._on_intensity_changed)
        sl_int.sliderReleased.connect(lambda: log.info("UI Slider released: visualizer_intensity=%d%%", sl_int.value()))
        h_int.addWidget(sl_int, 1)
        h_int.addWidget(self.lbl_int_val)
        v_sc.addLayout(h_int)

        # Independent Scales Toggle
        self.chk_ind = QCheckBox("Independent Element Scaling")
        self.chk_ind.setChecked(bool(self.cfg.get("canvas.independent_scales", False)))
        self.chk_ind.toggled.connect(self._on_independent_toggled)
        v_sc.addWidget(self.chk_ind)

        # Clock Scale Slider
        self.box_clk_sc = QWidget()
        h_csc = QHBoxLayout(self.box_clk_sc)
        h_csc.setContentsMargins(0, 0, 0, 0)
        h_csc.addWidget(QLabel("  Clock Scale:"))
        clk_sc = float(self.cfg.get("canvas.clock_scale") or 1.0)
        self.lbl_clk_sc = QLabel(f"{clk_sc:.2f}x")
        self.lbl_clk_sc.setFixedWidth(45)
        self.sl_clk_sc = QSlider(Qt.Horizontal)
        self.sl_clk_sc.setRange(40, 300)
        self.sl_clk_sc.setValue(int(clk_sc * 100))
        self.sl_clk_sc.valueChanged.connect(lambda v: self._on_elem_scale_changed("clock", v, self.lbl_clk_sc))
        self.sl_clk_sc.sliderReleased.connect(lambda: log.info("UI Slider released: clock_scale=%.2fx", self.sl_clk_sc.value() / 100.0))
        h_csc.addWidget(self.sl_clk_sc, 1)
        h_csc.addWidget(self.lbl_clk_sc)
        v_sc.addWidget(self.box_clk_sc)

        # Date Scale Slider
        self.box_dt_sc = QWidget()
        h_dsc = QHBoxLayout(self.box_dt_sc)
        h_dsc.setContentsMargins(0, 0, 0, 0)
        h_dsc.addWidget(QLabel("  Date Scale:"))
        dt_sc = float(self.cfg.get("canvas.date_scale") or 1.0)
        self.lbl_dt_sc = QLabel(f"{dt_sc:.2f}x")
        self.lbl_dt_sc.setFixedWidth(45)
        self.sl_dt_sc = QSlider(Qt.Horizontal)
        self.sl_dt_sc.setRange(40, 300)
        self.sl_dt_sc.setValue(int(dt_sc * 100))
        self.sl_dt_sc.valueChanged.connect(lambda v: self._on_elem_scale_changed("date", v, self.lbl_dt_sc))
        self.sl_dt_sc.sliderReleased.connect(lambda: log.info("UI Slider released: date_scale=%.2fx", self.sl_dt_sc.value() / 100.0))
        h_dsc.addWidget(self.sl_dt_sc, 1)
        h_dsc.addWidget(self.lbl_dt_sc)
        v_sc.addWidget(self.box_dt_sc)

        # Visualizer Scale Slider
        self.box_vis_sc = QWidget()
        h_vsc = QHBoxLayout(self.box_vis_sc)
        h_vsc.setContentsMargins(0, 0, 0, 0)
        h_vsc.addWidget(QLabel("  Visualizer Scale:"))
        vis_sc = float(self.cfg.get("canvas.visualizer_scale") or 1.0)
        self.lbl_vis_sc = QLabel(f"{vis_sc:.2f}x")
        self.lbl_vis_sc.setFixedWidth(45)
        self.sl_vis_sc = QSlider(Qt.Horizontal)
        self.sl_vis_sc.setRange(40, 300)
        self.sl_vis_sc.setValue(int(vis_sc * 100))
        self.sl_vis_sc.valueChanged.connect(lambda v: self._on_elem_scale_changed("visualizer", v, self.lbl_vis_sc))
        self.sl_vis_sc.sliderReleased.connect(lambda: log.info("UI Slider released: visualizer_scale=%.2fx", self.sl_vis_sc.value() / 100.0))
        h_vsc.addWidget(self.sl_vis_sc, 1)
        h_vsc.addWidget(self.lbl_vis_sc)
        v_sc.addWidget(self.box_vis_sc)

        # Apply visibility of independent sliders based on state
        self._update_independent_visibility(self.chk_ind.isChecked())

        layout.addWidget(grp_sc)

        # 5. Interactive Drag-and-Drop Positioning
        grp_drag = QGroupBox("Layout && Positioning")
        v_drag = QVBoxLayout(grp_drag)
        v_drag.setSpacing(10)

        lbl_drag_desc = QLabel("Unlock the canvas to drag Clock, Date, and Visualizer freely on the desktop. Lock to save positions.")
        lbl_drag_desc.setStyleSheet("color: #a6adc8; font-size: 11px;")
        v_drag.addWidget(lbl_drag_desc)

        h_drag_btns = QHBoxLayout()
        self.btn_drag = QPushButton("🔓  Unlock Drag Mode")
        self.btn_drag.setStyleSheet("""
            QPushButton {
                background-color: #00acc1;
                color: #ffffff;
                font-weight: bold;
                padding: 9px 18px;
                border-radius: 6px;
                font-size: 13px;
                border: 1px solid #26c6da;
            }
            QPushButton:hover {
                background-color: #00bcd4;
            }
        """)
        self.btn_drag.clicked.connect(self._on_toggle_drag)

        btn_reset = QPushButton("↺  Reset Center Layout")
        btn_reset.setStyleSheet("""
            QPushButton {
                background-color: #313244;
                color: #cdd6f4;
                font-weight: bold;
                padding: 9px 18px;
                border-radius: 6px;
                font-size: 12px;
                border: 1px solid #45475a;
            }
            QPushButton:hover {
                background-color: #45475a;
            }
        """)
        btn_reset.clicked.connect(self._on_reset_layout)

        h_drag_btns.addWidget(self.btn_drag)
        h_drag_btns.addWidget(btn_reset)
        v_drag.addLayout(h_drag_btns)

        layout.addWidget(grp_drag)
        layout.addStretch()

    # -----------------------------------------------------------------------
    # Helper methods & Callbacks
    # -----------------------------------------------------------------------

    def _update_engine_status(self) -> None:
        if self.ctrl.engine.is_running():
            self.lbl_status.setText(" Active ")
            self.lbl_status.setStyleSheet("background-color: #a6e3a1; border-radius: 8px; padding: 3px 10px; color: #1e1e2e; font-weight: bold;")
        else:
            self.lbl_status.setText(" Stopped ")
            self.lbl_status.setStyleSheet("background-color: #45475a; border-radius: 8px; padding: 3px 10px; color: #cdd6f4; font-weight: bold;")

    def _on_start(self) -> None:
        log.info("UI Action: Click Start Wallpaper")
        cur_video = self.cfg.get("wallpaper.video_path") or ""
        if not cur_video or not Path(cur_video).is_file():
            self._on_browse()
            cur_video = self.cfg.get("wallpaper.video_path") or ""
            if not cur_video or not Path(cur_video).is_file():
                log.info("UI Action Start aborted: no valid video selected")
                return
        self.ctrl.start_wallpaper()
        self._update_engine_status()

    def _on_stop(self) -> None:
        log.info("UI Action: Click Stop Wallpaper")
        self.ctrl.stop_wallpaper()
        self._update_engine_status()

    def _on_kill(self) -> None:
        """Emergency kill wallpaper engine and stop any background mpv processes."""
        log.info("UI Action: Click Kill Wallpaper")
        self.ctrl.stop_wallpaper()
        try:
            import subprocess
            res = subprocess.run(["taskkill", "/F", "/IM", "mpv.exe"], capture_output=True, text=True, check=False)
            log.info("taskkill /F /IM mpv.exe rc=%d stdout=%r stderr=%r", res.returncode, res.stdout.strip(), res.stderr.strip())
        except Exception as exc:
            log.warning("taskkill error: %s", exc)
        self._update_engine_status()
        log.info("Killed wallpaper playback process")

    def _on_restart(self) -> None:
        log.info("UI Action: Click Restart Wallpaper")
        self.ctrl.restart_wallpaper()
        self._update_engine_status()

    def _on_pause(self) -> None:
        log.info("UI Action: Click Pause / Resume")
        ok = self.ctrl.engine.toggle_pause()
        log.info("UI Action Pause / Resume result=%s", ok)

    def _on_browse(self) -> None:
        log.info("UI Action: Click Browse Video")
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Wallpaper Video", "", "Video Files (*.mp4 *.mkv *.webm *.mov *.avi)"
        )
        if path:
            log.info("UI Video selected: %s", path)
            self.cfg.set("wallpaper.video_path", path)
            self.cfg.save()
            self.lbl_file.setText(Path(path).name)
        else:
            log.info("UI Browse Video cancelled")

    def _on_volume_changed(self, val: int) -> None:
        self.lbl_vol_val.setText(f"{val}%")
        self.cfg.set("wallpaper.volume", val)
        self.cfg.save()
        self.ctrl.engine.set_volume(val)
        allowed, _ = get_rate_limiter().check("ui:slider:vol", interval=0.5)
        if allowed:
            log.info("UI Change: wallpaper.volume=%d%%", val)

    def _on_speed_changed(self, val: int) -> None:
        speed = val / 100.0
        self.lbl_spd_val.setText(f"{speed:.2f}x")
        self.cfg.set("wallpaper.playback_speed", speed)
        self.cfg.save()
        self.ctrl.engine.set_speed(speed)
        allowed, _ = get_rate_limiter().check("ui:slider:spd", interval=0.5)
        if allowed:
            log.info("UI Change: wallpaper.playback_speed=%.2fx", speed)

    def _on_mute_changed(self, val: bool) -> None:
        log.info("UI Change: wallpaper.mute=%s", val)
        self.cfg.set("wallpaper.mute", val)
        self.cfg.save()
        self.ctrl.engine.set_mute(val)

    def _on_fit_changed(self, val: str) -> None:
        log.info("UI Change: wallpaper.fit_mode=%r", val)
        self.cfg.set("wallpaper.fit_mode", val)
        self.cfg.save()

    def _on_ap_changed(self, val: str) -> None:
        log.info("UI Change: wallpaper.autopause=%r", val)
        self.cfg.set("wallpaper.autopause", val)
        self.cfg.save()

    def _on_fps_changed(self, val: str) -> None:
        log.info("UI Change: wallpaper.fps_limit=%r", val)
        self.cfg.set("wallpaper.fps_limit", val)
        self.cfg.save()

    def _on_autostart_toggled(self, enabled: bool) -> None:
        log.info("UI Change: wallpaper.autostart=%s", enabled)
        self.cfg.set("wallpaper.autostart", enabled)
        self.cfg.save()
        startup_dir = get_windows_startup_dir()
        vbs_shortcut = startup_dir / "DesktopSuite.vbs"
        if enabled:
            try:
                startup_dir.mkdir(parents=True, exist_ok=True)
                exe_path = sys.executable if getattr(sys, "frozen", False) else str(Path(__file__).resolve().parent.parent / "main.py")
                cmd = f'"{exe_path}" --daemon'
                vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run "{cmd}", 0, False\n'
                vbs_shortcut.write_text(vbs_content, encoding="utf-8")
                log.info("Created Windows startup shortcut at: %s", vbs_shortcut)
            except Exception as exc:
                log.warning("Failed to create startup shortcut: %s", exc)
        else:
            try:
                if vbs_shortcut.is_file():
                    vbs_shortcut.unlink()
                    log.info("Removed Windows startup shortcut: %s", vbs_shortcut)
            except Exception as exc:
                log.warning("Failed to remove startup shortcut: %s", exc)

    def _on_theme_changed(self, name: str) -> None:
        log.info("UI Change: canvas.active_theme=%r", name)
        self.ctrl.apply_theme(name)

    def _set_canvas_cfg(self, key: str, val: Any, quiet: bool = False) -> None:
        if not quiet:
            log.info("UI Change: %s=%r", key, val)
        self.cfg.set(key, val)
        self.cfg.save()
        self.ctrl.reload_canvas()

    def _on_opacity_changed(self, val: int) -> None:
        opacity = val / 100.0
        self.lbl_op_val.setText(f"{val}%")
        allowed, _ = get_rate_limiter().check("ui:slider:op", interval=0.5)
        self._set_canvas_cfg("canvas.background_opacity", opacity, quiet=not allowed)

    def _on_scale_changed(self, val: int) -> None:
        scale = val / 100.0
        self.lbl_msc_val.setText(f"{scale:.2f}x")
        allowed, _ = get_rate_limiter().check("ui:slider:scale", interval=0.5)
        self._set_canvas_cfg("canvas.scale", scale, quiet=not allowed)

    def _on_intensity_changed(self, val: int) -> None:
        intensity = val / 100.0
        self.lbl_int_val.setText(f"{val}%")
        self.ctrl.audio.set_intensity(intensity)
        allowed, _ = get_rate_limiter().check("ui:slider:intensity", interval=0.5)
        self._set_canvas_cfg("canvas.visualizer_intensity", intensity, quiet=not allowed)

    def _on_independent_toggled(self, checked: bool) -> None:
        self._update_independent_visibility(checked)
        self._set_canvas_cfg("canvas.independent_scales", checked)

    def _update_independent_visibility(self, visible: bool) -> None:
        self.box_clk_sc.setVisible(visible)
        self.box_dt_sc.setVisible(visible)
        self.box_vis_sc.setVisible(visible)

    def _on_elem_scale_changed(self, elem: str, val: int, label: QLabel) -> None:
        scale = val / 100.0
        label.setText(f"{scale:.2f}x")
        allowed, _ = get_rate_limiter().check(f"ui:slider:{elem}_scale", interval=0.5)
        self._set_canvas_cfg(f"canvas.{elem}_scale", scale, quiet=not allowed)

    def _update_color_button(self, btn: QPushButton, hex_col: str, title: str) -> None:
        btn.setText(f"  {title}:  {hex_col}  ")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #252839;
                color: #cdd6f4;
                border: 2px solid {hex_col};
                border-radius: 6px;
                padding: 6px 14px;
                text-align: left;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #313244;
            }}
        """)

    def _pick_color(self, key: str, btn: QPushButton, title: str) -> None:
        cur_hex = self.cfg.get(key) or "#FFFFFF"
        log.info("UI Action: Open color picker for %s (current=%s)", key, cur_hex)
        col = QColorDialog.getColor(QColor(cur_hex), self, f"Select {title}")
        if col.isValid():
            new_hex = col.name().upper()
            log.info("UI Color chosen: %s -> %s", key, new_hex)
            self._update_color_button(btn, new_hex, title)
            self._set_canvas_cfg(key, new_hex)
        else:
            log.info("UI Color picker cancelled for %s", key)

    def _on_toggle_drag(self) -> None:
        editing = self.ctrl.toggle_canvas_edit_mode()
        log.info("UI Action: Toggle Drag Mode -> editing=%s", editing)
        if editing:
            self.btn_drag.setText("🔒  Lock Positions (Save)")
            self.btn_drag.setObjectName("btn-lock")
            self.btn_drag.setStyleSheet("background-color: #e53935; color: white; font-weight: bold; padding: 9px 18px; border-radius: 6px;")
        else:
            self.btn_drag.setText("🔓  Unlock Drag Mode")
            self.btn_drag.setObjectName("btn-unlock")
            self.btn_drag.setStyleSheet("background-color: #00acc1; color: white; font-weight: bold; padding: 9px 18px; border-radius: 6px;")

    def _on_reset_layout(self) -> None:
        log.info("UI Action: Click Reset Center Layout")
        sw = self.ctrl.canvas.width if self.ctrl.canvas else 1366
        sh = self.ctrl.canvas.height if self.ctrl.canvas else 768
        cx = (sw - 430) // 2
        self.cfg.set("positions.clock", {"x": cx, "y": int(sh * 0.35)})
        self.cfg.set("positions.date", {"x": cx, "y": int(sh * 0.48)})
        self.cfg.set("positions.visualizer", {"x": cx, "y": int(sh * 0.55)})
        self.cfg.save()
        self.ctrl.reload_canvas()


def create_control_center(ctrl: Any) -> ControlCenterWindow:
    return ControlCenterWindow(ctrl)
