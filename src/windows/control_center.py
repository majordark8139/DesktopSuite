"""
src.windows.control_center
==========================
PyQt5 Control Center GUI for Desktop Suite on Windows.
Replicates the dark Catppuccin theme styling and settings tabs of the Linux GUI.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

_WIN_DARK_QSS = """
QMainWindow, QWidget#CentralWidget {
    background-color: #1e1e2e;
    color: #cdd6f4;
    font-family: 'Segoe UI', sans-serif;
}
QTabWidget::pane {
    border: none;
    background-color: #181825;
}
QTabBar::tab {
    background-color: #181825;
    color: #a6adc8;
    padding: 8px 24px;
    font-weight: bold;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #313244;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
}
QGroupBox {
    background-color: #313244;
    border-radius: 8px;
    margin-top: 16px;
    padding: 14px;
    font-weight: bold;
    color: #89b4fa;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    padding: 0 6px;
    color: #89b4fa;
}
QPushButton {
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 6px 14px;
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
    padding: 8px 16px;
}
QPushButton#btn-lock {
    background-color: #e53935;
    color: #ffffff;
    font-size: 13px;
    padding: 8px 16px;
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
QComboBox {
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 6px;
    padding: 4px 10px;
    border: none;
}
QComboBox QAbstractItemView {
    background-color: #313244;
    color: #cdd6f4;
    selection-background-color: #89b4fa;
    selection-color: #1e1e2e;
}
QCheckBox {
    color: #cdd6f4;
    spacing: 8px;
}
QCheckBox::indicator {
    width: 16px;
    height: 16px;
    border-radius: 4px;
    background-color: #45475a;
}
QCheckBox::indicator:checked {
    background-color: #89b4fa;
}
QLabel {
    color: #cdd6f4;
}
"""


def create_control_center(ctrl: Any) -> Any:
    """Create PyQt5 Control Center window."""
    try:
        from PyQt5.QtWidgets import (
            QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
            QTabWidget, QGroupBox, QPushButton, QLabel, QSlider, QCheckBox,
            QComboBox, QFileDialog, QColorDialog, QScrollArea
        )
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QColor, QIcon
    except ImportError:
        log.warning("PyQt5 not installed; skipping GUI window")
        return None

    class ControlCenter(QMainWindow):
        def __init__(self, controller: Any) -> None:
            super().__init__()
            self.ctrl = controller
            self.cfg = controller.cfg
            self.setWindowTitle("DesktopSuite Control Center")
            self.resize(580, 680)
            self.setStyleSheet(_WIN_DARK_QSS)

            central = QWidget(self)
            central.setObjectName("CentralWidget")
            self.setCentralWidget(central)
            main_layout = QVBoxLayout(central)

            tabs = QTabWidget()
            main_layout.addWidget(tabs)

            # Tab 1: Live Wallpaper
            tab_wp = QWidget()
            layout_wp = QVBoxLayout(tab_wp)
            self._build_wallpaper_tab(layout_wp)
            tabs.addTab(tab_wp, "Live Wallpaper")

            # Tab 2: Clock & Canvas Studio
            tab_cv = QWidget()
            layout_cv = QVBoxLayout(tab_cv)
            self._build_canvas_tab(layout_cv)
            tabs.addTab(tab_cv, "Clock & Canvas Studio")

        def _build_wallpaper_tab(self, layout: QVBoxLayout) -> None:
            from PyQt5.QtWidgets import (
                QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                QSlider, QCheckBox, QComboBox, QFileDialog
            )
            from PyQt5.QtCore import Qt

            # Engine Controls Box
            grp_eng = QGroupBox("Engine Controls")
            v_eng = QVBoxLayout(grp_eng)

            h_status = QHBoxLayout()
            h_status.addWidget(QLabel("Status:"))
            self.lbl_status = QLabel(" Stopped ")
            self.lbl_status.setStyleSheet("background-color: #45475a; border-radius: 8px; padding: 2px 8px; color: #cdd6f4;")
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
            self.lbl_file = QLabel(self.cfg.get("wallpaper.video_path") or "None selected")
            self.lbl_file.setStyleSheet("color: #a6adc8;")
            btn_browse = QPushButton("Browse...")
            btn_browse.clicked.connect(self._on_browse)
            h_file.addWidget(self.lbl_file, 1)
            h_file.addWidget(btn_browse)
            v_eng.addLayout(h_file)

            layout.addWidget(grp_eng)

            # Playback Settings Box
            grp_pb = QGroupBox("Playback")
            v_pb = QVBoxLayout(grp_pb)

            # Volume
            h_vol = QHBoxLayout()
            h_vol.addWidget(QLabel("Volume:"))
            sl_vol = QSlider(Qt.Horizontal)
            sl_vol.setRange(0, 100)
            sl_vol.setValue(int(self.cfg.get("wallpaper.volume") or 50))
            sl_vol.valueChanged.connect(self._on_volume)
            h_vol.addWidget(sl_vol)
            v_pb.addLayout(h_vol)

            # Speed
            h_spd = QHBoxLayout()
            h_spd.addWidget(QLabel("Speed:"))
            sl_spd = QSlider(Qt.Horizontal)
            sl_spd.setRange(50, 200)
            sl_spd.setValue(int(float(self.cfg.get("wallpaper.playback_speed") or 1.0) * 100))
            sl_spd.valueChanged.connect(lambda v: self._on_speed(v / 100.0))
            h_spd.addWidget(sl_spd)
            v_pb.addLayout(h_spd)

            # Mute
            chk_mute = QCheckBox("Mute Audio")
            chk_mute.setChecked(bool(self.cfg.get("wallpaper.mute", True)))
            chk_mute.toggled.connect(self._on_mute)
            v_pb.addWidget(chk_mute)

            layout.addWidget(grp_pb)

            # Behavior Box
            grp_beh = QGroupBox("Behaviour")
            v_beh = QVBoxLayout(grp_beh)

            h_fit = QHBoxLayout()
            h_fit.addWidget(QLabel("Screen Fit:"))
            cb_fit = QComboBox()
            cb_fit.addItems(["Fill / Zoom", "Fit Inside", "Stretch"])
            fit_map = {"fill": 0, "fit": 1, "stretch": 2}
            cb_fit.setCurrentIndex(fit_map.get(self.cfg.get("wallpaper.fit_mode"), 0))
            cb_fit.currentIndexChanged.connect(lambda i: self._on_fit(["fill", "fit", "stretch"][i]))
            h_fit.addWidget(cb_fit)
            v_beh.addLayout(h_fit)

            h_ap = QHBoxLayout()
            h_ap.addWidget(QLabel("Auto-Pause:"))
            cb_ap = QComboBox()
            cb_ap.addItems(["Focus (Any App)", "Maximized Only", "Off"])
            ap_map = {"focus": 0, "maximized": 1, "off": 2}
            cb_ap.setCurrentIndex(ap_map.get(self.cfg.get("wallpaper.autopause"), 0))
            cb_ap.currentIndexChanged.connect(lambda i: self._on_ap(["focus", "maximized", "off"][i]))
            h_ap.addWidget(cb_ap)
            v_beh.addLayout(h_ap)

            layout.addWidget(grp_beh)
            layout.addStretch()

        def _build_canvas_tab(self, layout: QVBoxLayout) -> None:
            from PyQt5.QtWidgets import (
                QGroupBox, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
                QSlider, QCheckBox, QComboBox, QColorDialog
            )
            from PyQt5.QtCore import Qt

            # Theme Box
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

            # Components Box
            grp_cmp = QGroupBox("Components")
            v_cmp = QVBoxLayout(grp_cmp)
            chk_clk = QCheckBox("Show Clock")
            chk_clk.setChecked(bool(self.cfg.get("canvas.clock_enabled", True)))
            chk_clk.toggled.connect(lambda v: self._set_cfg("canvas.clock_enabled", v))
            v_cmp.addWidget(chk_clk)

            chk_dt = QCheckBox("Show Date")
            chk_dt.setChecked(bool(self.cfg.get("canvas.date_enabled", True)))
            chk_dt.toggled.connect(lambda v: self._set_cfg("canvas.date_enabled", v))
            v_cmp.addWidget(chk_dt)

            chk_vis = QCheckBox("Show Audio Visualizer")
            chk_vis.setChecked(bool(self.cfg.get("canvas.visualizer_enabled", True)))
            chk_vis.toggled.connect(lambda v: self._set_cfg("canvas.visualizer_enabled", v))
            v_cmp.addWidget(chk_vis)
            layout.addWidget(grp_cmp)

            # Appearance Box
            grp_app = QGroupBox("Appearance & Layout")
            v_app = QVBoxLayout(grp_app)

            # Colors
            h_col = QHBoxLayout()
            btn_col_clk = QPushButton("Clock Color")
            btn_col_clk.clicked.connect(lambda: self._pick_color("canvas.clock_color"))
            btn_col_dt = QPushButton("Date Color")
            btn_col_dt.clicked.connect(lambda: self._pick_color("canvas.date_color"))
            btn_col_vis = QPushButton("Visualizer Color")
            btn_col_vis.clicked.connect(lambda: self._pick_color("canvas.visualizer_color"))
            h_col.addWidget(btn_col_clk)
            h_col.addWidget(btn_col_dt)
            h_col.addWidget(btn_col_vis)
            v_app.addLayout(h_col)

            # Scale
            h_sc = QHBoxLayout()
            h_sc.addWidget(QLabel("Scale:"))
            sl_sc = QSlider(Qt.Horizontal)
            sl_sc.setRange(50, 250)
            sl_sc.setValue(int(float(self.cfg.get("canvas.scale") or 1.0) * 100))
            sl_sc.valueChanged.connect(lambda v: self._set_cfg("canvas.scale", v / 100.0))
            h_sc.addWidget(sl_sc)
            v_app.addLayout(h_sc)

            # Drag Controls
            h_drag = QHBoxLayout()
            self.btn_drag = QPushButton("🔓  Unlock Drag Mode")
            self.btn_drag.setObjectName("btn-unlock")
            self.btn_drag.clicked.connect(self._on_toggle_drag)
            btn_reset = QPushButton("Reset Center")
            btn_reset.clicked.connect(self._on_reset_layout)
            h_drag.addWidget(self.btn_drag)
            h_drag.addWidget(btn_reset)
            v_app.addLayout(h_drag)

            layout.addWidget(grp_app)
            layout.addStretch()

        def _on_start(self) -> None:
            if self.ctrl.start_wallpaper():
                self.lbl_status.setText(" Active ")
                self.lbl_status.setStyleSheet("background-color: #a6e3a1; border-radius: 8px; padding: 2px 8px; color: #1e1e2e;")

        def _on_stop(self) -> None:
            self.ctrl.stop_wallpaper()
            self.lbl_status.setText(" Stopped ")
            self.lbl_status.setStyleSheet("background-color: #45475a; border-radius: 8px; padding: 2px 8px; color: #cdd6f4;")

        def _on_restart(self) -> None:
            if self.ctrl.restart_wallpaper():
                self.lbl_status.setText(" Active ")
                self.lbl_status.setStyleSheet("background-color: #a6e3a1; border-radius: 8px; padding: 2px 8px; color: #1e1e2e;")

        def _on_pause(self) -> None:
            self.ctrl.engine.toggle_pause()

        def _on_browse(self) -> None:
            from PyQt5.QtWidgets import QFileDialog
            path, _ = QFileDialog.getOpenFileName(
                self, "Select Wallpaper Video", "", "Video Files (*.mp4 *.mkv *.webm *.mov *.avi)"
            )
            if path:
                self.cfg.set("wallpaper.video_path", path)
                self.cfg.save()
                self.lbl_file.setText(Path(path).name)

        def _on_volume(self, val: int) -> None:
            self.cfg.set("wallpaper.volume", val)
            self.cfg.save()
            self.ctrl.engine.set_volume(val)

        def _on_speed(self, val: float) -> None:
            self.cfg.set("wallpaper.playback_speed", val)
            self.cfg.save()
            self.ctrl.engine.set_speed(val)

        def _on_mute(self, val: bool) -> None:
            self.cfg.set("wallpaper.mute", val)
            self.cfg.save()
            self.ctrl.engine.set_mute(val)

        def _on_fit(self, val: str) -> None:
            self.cfg.set("wallpaper.fit_mode", val)
            self.cfg.save()

        def _on_ap(self, val: str) -> None:
            self.cfg.set("wallpaper.autopause", val)
            self.cfg.save()

        def _on_theme_changed(self, name: str) -> None:
            self.ctrl.apply_theme(name)

        def _set_cfg(self, key: str, val: Any) -> None:
            self.cfg.set(key, val)
            self.cfg.save()
            self.ctrl.reload_canvas()

        def _pick_color(self, key: str) -> None:
            from PyQt5.QtWidgets import QColorDialog
            from PyQt5.QtGui import QColor
            cur_hex = self.cfg.get(key) or "#FFFFFF"
            col = QColorDialog.getColor(QColor(cur_hex), self, "Select Color")
            if col.isValid():
                self._set_cfg(key, col.name().upper())

        def _on_toggle_drag(self) -> None:
            editing = self.ctrl.toggle_canvas_edit_mode()
            if editing:
                self.btn_drag.setText("🔒  Lock Positions")
                self.btn_drag.setObjectName("btn-lock")
                self.btn_drag.setStyleSheet("background-color: #e53935; color: white;")
            else:
                self.btn_drag.setText("🔓  Unlock Drag Mode")
                self.btn_drag.setObjectName("btn-unlock")
                self.btn_drag.setStyleSheet("background-color: #00acc1; color: white;")

        def _on_reset_layout(self) -> None:
            sw = self.ctrl.canvas.width if self.ctrl.canvas else 1366
            sh = self.ctrl.canvas.height if self.ctrl.canvas else 768
            cx = (sw - 430) // 2
            self.cfg.set("positions.clock", {"x": cx, "y": int(sh * 0.35)})
            self.cfg.set("positions.date", {"x": cx, "y": int(sh * 0.48)})
            self.cfg.set("positions.visualizer", {"x": cx, "y": int(sh * 0.55)})
            self.cfg.save()
            self.ctrl.reload_canvas()

    return ControlCenter(ctrl)
