"""
src.windows.control_center
==========================
Comprehensive PyQt5 Control Center GUI for DesktopSuite on Windows.
Replicates the full feature set and dark Catppuccin theme styling of the Linux GUI.
"""

from __future__ import annotations

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
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QFont, QIcon, QPixmap

log = logging.getLogger(__name__)

_WIN_DARK_QSS = """
QMainWindow, QWidget#CentralWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', sans-serif;
    font-size: 12px;
}
QScrollArea {
    border: none;
    background-color: #181825;
}
QTabWidget::pane {
    border: none;
    background-color: #181825;
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
    min-width: 160px;
}
QTabBar::tab:selected {
    background-color: #313244;
    color: #cdd6f4;
    border-bottom: 3px solid #89b4fa;
}
QGroupBox {
    background-color: #313244;
    border-radius: 8px;
    margin-top: 18px;
    padding: 14px;
    font-weight: bold;
    color: #89b4fa;
    border: 1px solid #45475a;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 8px;
    color: #89b4fa;
    font-size: 12px;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: bold;
    border: none;
}
QPushButton:hover {
    background-color: #585b70;
}
QPushButton#btn-primary {
    background-color: #89b4fa;
    color: #1e1e2e;
}
QPushButton#btn-primary:hover {
    background-color: #b4befe;
}
QPushButton#btn-danger {
    background-color: #f38ba8;
    color: #1e1e2e;
}
QPushButton#btn-danger:hover {
    background-color: #f5c2e7;
}
QPushButton#btn-warning {
    background-color: #fab387;
    color: #1e1e2e;
}
QPushButton#btn-warning:hover {
    background-color: #f9e2af;
}
QPushButton#btn-unlock {
    background-color: #00acc1;
    color: #ffffff;
    font-size: 13px;
    padding: 9px 18px;
}
QPushButton#btn-unlock:hover {
    background-color: #00bcd4;
}
QPushButton#btn-lock {
    background-color: #e53935;
    color: #ffffff;
    font-size: 13px;
    padding: 9px 18px;
}
QPushButton#btn-lock:hover {
    background-color: #ef5350;
}
QSlider::groove:horizontal {
    height: 6px;
    background-color: #45475a;
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
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 5px 12px;
    border: 1px solid #585b70;
    min-height: 24px;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
    padding: 4px;
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
    background-color: #45475a;
    border: 1px solid #585b70;
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

    def __init__(self, controller: Any) -> None:
        super().__init__()
        self.ctrl = controller
        self.cfg = controller.cfg
        self._building = True

        self.setWindowTitle("DesktopSuite Control Center")
        self.resize(640, 760)
        self.setMinimumSize(560, 640)
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
        scroll_wp = QScrollArea()
        scroll_wp.setWidgetResizable(True)
        content_wp = QWidget()
        layout_wp = QVBoxLayout(content_wp)
        layout_wp.setSpacing(12)
        layout_wp.setContentsMargins(12, 12, 12, 12)
        self._build_wallpaper_tab(layout_wp)
        scroll_wp.setWidget(content_wp)
        layout_tab_wp = QVBoxLayout(tab_wp)
        layout_tab_wp.setContentsMargins(0, 0, 0, 0)
        layout_tab_wp.addWidget(scroll_wp)
        tabs.addTab(tab_wp, "Live Wallpaper")

        # Tab 2: Clock & Canvas Studio (use && so '&' is not swallowed as accelerator)
        tab_cv = QWidget()
        scroll_cv = QScrollArea()
        scroll_cv.setWidgetResizable(True)
        content_cv = QWidget()
        layout_cv = QVBoxLayout(content_cv)
        layout_cv.setSpacing(12)
        layout_cv.setContentsMargins(12, 12, 12, 12)
        self._build_canvas_tab(layout_cv)
        scroll_cv.setWidget(content_cv)
        layout_tab_cv = QVBoxLayout(tab_cv)
        layout_tab_cv.setContentsMargins(0, 0, 0, 0)
        layout_tab_cv.addWidget(scroll_cv)
        tabs.addTab(tab_cv, "Clock && Canvas Studio")

        self._building = False
        self._update_engine_status()

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

        h_btns = QHBoxLayout()
        btn_start = QPushButton("▶  Start")
        btn_start.setObjectName("btn-primary")
        btn_start.clicked.connect(self._on_start)
        btn_stop = QPushButton("■  Stop")
        btn_stop.setObjectName("btn-danger")
        btn_stop.clicked.connect(self._on_stop)
        btn_restart = QPushButton("↺  Restart")
        btn_restart.setObjectName("btn-warning")
        btn_restart.clicked.connect(self._on_restart)
        btn_pause = QPushButton("⏸  Pause / Resume")
        btn_pause.clicked.connect(self._on_pause)

        for b in (btn_start, btn_stop, btn_restart, btn_pause):
            h_btns.addWidget(b)
        v_eng.addLayout(h_btns)

        h_file = QHBoxLayout()
        h_file.addWidget(QLabel("Video:"))
        cur_video = self.cfg.get("wallpaper.video_path") or ""
        video_display = Path(cur_video).name if cur_video else "None selected"
        self.lbl_file = QLabel(video_display)
        self.lbl_file.setStyleSheet("color: #a6adc8; font-style: italic;")
        btn_browse = QPushButton("Browse...")
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
        h_spd.addWidget(sl_spd, 1)
        h_spd.addWidget(self.lbl_spd_val)
        v_pb.addLayout(h_spd)

        # Mute
        chk_mute = QCheckBox("Mute Audio")
        chk_mute.setChecked(bool(self.cfg.get("wallpaper.mute", True)))
        chk_mute.toggled.connect(self._on_mute_changed)
        v_pb.addWidget(chk_mute)

        layout.addWidget(grp_pb)

        # 3. Behaviour & System Integration
        grp_beh = QGroupBox("Behaviour & System")
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

        # FPS Limiter (Added feature from Linux)
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
        cur_th = self.cfg.get("canvas.active_theme") or "Original Cursive"
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
        grp_sc = QGroupBox("Scaling & Appearance")
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
        h_msc.addWidget(sl_msc, 1)
        h_msc.addWidget(self.lbl_msc_val)
        v_sc.addLayout(h_msc)

        # Visualizer Intensity
        h_int = QHBoxLayout()
        h_int.addWidget(QLabel("Visualizer Intensity:"))
        int_val = float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        self.lbl_int_val = QLabel(f"{int(int_val * 100)}%")
        self.lbl_int_val.setFixedWidth(45)
        sl_int = QSlider(Qt.Horizontal)
        sl_int.setRange(10, 200)
        sl_int.setValue(int(int_val * 100))
        sl_int.valueChanged.connect(self._on_intensity_changed)
        h_int.addWidget(sl_int, 1)
        h_int.addWidget(self.lbl_int_val)
        v_sc.addLayout(h_int)

        # Independent Scales Toggle
        self.chk_ind = QCheckBox("Independent Component Scaling")
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
        h_vsc.addWidget(self.sl_vis_sc, 1)
        h_vsc.addWidget(self.lbl_vis_sc)
        v_sc.addWidget(self.box_vis_sc)

        # Apply visibility of independent sliders based on state
        self._update_independent_visibility(self.chk_ind.isChecked())

        layout.addWidget(grp_sc)

        # 5. Interactive Drag-and-Drop Positioning
        grp_drag = QGroupBox("Layout & Positioning")
        v_drag = QVBoxLayout(grp_drag)
        v_drag.setSpacing(10)

        h_drag_btns = QHBoxLayout()
        self.btn_drag = QPushButton("🔓  Unlock Drag Mode")
        self.btn_drag.setObjectName("btn-unlock")
        self.btn_drag.clicked.connect(self._on_toggle_drag)

        btn_reset = QPushButton("Reset Center Layout")
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
        self.ctrl.start_wallpaper()
        self._update_engine_status()

    def _on_stop(self) -> None:
        self.ctrl.stop_wallpaper()
        self._update_engine_status()

    def _on_restart(self) -> None:
        self.ctrl.restart_wallpaper()
        self._update_engine_status()

    def _on_pause(self) -> None:
        self.ctrl.engine.toggle_pause()

    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Wallpaper Video", "", "Video Files (*.mp4 *.mkv *.webm *.mov *.avi)"
        )
        if path:
            self.cfg.set("wallpaper.video_path", path)
            self.cfg.save()
            self.lbl_file.setText(Path(path).name)

    def _on_volume_changed(self, val: int) -> None:
        self.lbl_vol_val.setText(f"{val}%")
        self.cfg.set("wallpaper.volume", val)
        self.cfg.save()
        self.ctrl.engine.set_volume(val)

    def _on_speed_changed(self, val: int) -> None:
        speed = val / 100.0
        self.lbl_spd_val.setText(f"{speed:.2f}x")
        self.cfg.set("wallpaper.playback_speed", speed)
        self.cfg.save()
        self.ctrl.engine.set_speed(speed)

    def _on_mute_changed(self, val: bool) -> None:
        self.cfg.set("wallpaper.mute", val)
        self.cfg.save()
        self.ctrl.engine.set_mute(val)

    def _on_fit_changed(self, val: str) -> None:
        self.cfg.set("wallpaper.fit_mode", val)
        self.cfg.save()

    def _on_ap_changed(self, val: str) -> None:
        self.cfg.set("wallpaper.autopause", val)
        self.cfg.save()

    def _on_fps_changed(self, val: str) -> None:
        self.cfg.set("wallpaper.fps_limit", val)
        self.cfg.save()

    def _on_autostart_toggled(self, enabled: bool) -> None:
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
        self.ctrl.apply_theme(name)

    def _set_canvas_cfg(self, key: str, val: Any) -> None:
        self.cfg.set(key, val)
        self.cfg.save()
        self.ctrl.reload_canvas()

    def _on_opacity_changed(self, val: int) -> None:
        opacity = val / 100.0
        self.lbl_op_val.setText(f"{val}%")
        self._set_canvas_cfg("canvas.background_opacity", opacity)

    def _on_scale_changed(self, val: int) -> None:
        scale = val / 100.0
        self.lbl_msc_val.setText(f"{scale:.2f}x")
        self._set_canvas_cfg("canvas.scale", scale)

    def _on_intensity_changed(self, val: int) -> None:
        intensity = val / 100.0
        self.lbl_int_val.setText(f"{val}%")
        self.ctrl.audio.set_intensity(intensity)
        self._set_canvas_cfg("canvas.visualizer_intensity", intensity)

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
        self._set_canvas_cfg(f"canvas.{elem}_scale", scale)

    def _update_color_button(self, btn: QPushButton, hex_col: str, title: str) -> None:
        # Style button with color swatch and hex text
        btn.setText(f"  {title}:  {hex_col}  ")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: #313244;
                color: #cdd6f4;
                border: 2px solid {hex_col};
                border-radius: 6px;
                padding: 6px 12px;
                text-align: left;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: #45475a;
            }}
        """)

    def _pick_color(self, key: str, btn: QPushButton, title: str) -> None:
        cur_hex = self.cfg.get(key) or "#FFFFFF"
        col = QColorDialog.getColor(QColor(cur_hex), self, f"Select {title}")
        if col.isValid():
            new_hex = col.name().upper()
            self._update_color_button(btn, new_hex, title)
            self._set_canvas_cfg(key, new_hex)

    def _on_toggle_drag(self) -> None:
        editing = self.ctrl.toggle_canvas_edit_mode()
        if editing:
            self.btn_drag.setText("🔒  Lock Positions")
            self.btn_drag.setObjectName("btn-lock")
            self.btn_drag.setStyleSheet("background-color: #e53935; color: white; font-weight: bold; padding: 9px 18px; border-radius: 6px;")
        else:
            self.btn_drag.setText("🔓  Unlock Drag Mode")
            self.btn_drag.setObjectName("btn-unlock")
            self.btn_drag.setStyleSheet("background-color: #00acc1; color: white; font-weight: bold; padding: 9px 18px; border-radius: 6px;")

    def _on_reset_layout(self) -> None:
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
