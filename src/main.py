"""
src.main
========
Desktop Suite — Unified Control Center, System Tray, and Process Manager.

This module is the single entry point that:

1. Instantiates the singleton subsystems (:class:`AppController`).
2. Starts the live wallpaper engine and the canvas overlay.
3. Optionally displays the tabbed Control Center GUI.
4. Provides a system-tray icon with a right-click menu.

CLI flags
---------
``--daemon`` / ``--start-all``
    Start both subsystems silently (no GUI window). Used by the autostart
    ``.desktop`` entry so the app launches headlessly at login.

No flags (default)
    Start subsystems **and** open the Control Center window.

Usage
-----
::

    python3 src/main.py              # full GUI
    python3 src/main.py --daemon     # headless / autostart mode
    python3 src/main.py --help

Architecture overview
---------------------
::

    AppController
        ├── ConfigManager          (src/core/config.py)
        ├── AutostartManager       (src/core/autostart.py)
        ├── WallpaperEngine        (src/wallpaper/engine.py)
        ├── AudioStream            (src/canvas/audio.py)
        ├── DesktopCanvasWindow    (src/canvas/window.py)   ← always running
        └── ControlCenterWindow    (Gtk.Window, this file)  ← shown on demand
            ├── Tab 1: Live Wallpaper
            └── Tab 2: Clock & Canvas Studio
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Path setup — allow running as `python3 src/main.py` from project root
# ---------------------------------------------------------------------------
_HERE = Path(__file__).resolve().parent          # src/
_ROOT = _HERE.parent                              # DesktopSuite/
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# ---------------------------------------------------------------------------
# Fast-path CLI handlers (0ms GUI overhead: no GTK import)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    if "--kill-wallpaper" in sys.argv:
        from src.wallpaper.engine import WallpaperEngine
        engine = WallpaperEngine()
        engine.stop()
        print("[Desktop Suite] Live wallpaper killed.")
        sys.exit(0)

    if "--toggle-wallpaper" in sys.argv:
        from src.wallpaper.ipc import MpvIPC
        ipc = MpvIPC()
        if ipc.is_alive():
            is_paused = ipc.get_property("pause")
            if is_paused is True:
                ipc.resume()
                print("[Desktop Suite] Wallpaper resumed.")
            else:
                ipc.pause()
                print("[Desktop Suite] Wallpaper paused.")
        else:
            from src.core.config import ConfigManager
            from src.wallpaper.engine import WallpaperEngine
            cfg = ConfigManager()
            wp = cfg.get("wallpaper") or {}
            path = wp.get("video_path", "")
            if path and Path(path).is_file():
                engine = WallpaperEngine()
                started = engine.start(
                    video_path   = path,
                    speed        = float(wp.get("playback_speed", 1.0)),
                    volume       = int(wp.get("volume", 50)),
                    mute         = bool(wp.get("mute", True)),
                    fit_mode     = wp.get("fit_mode", "fill"),
                    fps_limit    = wp.get("fps_limit", "native"),
                    autopause    = wp.get("autopause", "focus"),
                )
                if started:
                    print(f"[Desktop Suite] Wallpaper started ({path}).")
                else:
                    print("[Desktop Suite] Failed to start wallpaper engine.")
            else:
                print("[Desktop Suite] Cannot start wallpaper: no valid video_path configured.")
        sys.exit(0)

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from src.core.fonts import register_bundled_fonts
register_bundled_fonts()

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Dark-theme CSS applied globally to the Control Center window
# ---------------------------------------------------------------------------

_DARK_CSS = b"""
window.control-center {
    background-color: #1e1e2e;
    color: #cdd6f4;
}
notebook {
    background-color: #181825;
}
notebook header {
    background-color: #181825;
}
notebook tab {
    background-color: #181825;
    color: #a6adc8;
    padding: 6px 16px;
}
notebook tab:checked {
    background-color: #313244;
    color: #cdd6f4;
    border-bottom: 2px solid #89b4fa;
}
.card {
    background-color: #313244;
    border-radius: 8px;
    padding: 12px;
    margin: 6px;
}
.section-label {
    color: #89b4fa;
    font-weight: bold;
    font-size: 11px;
}
.status-active {
    background-color: #a6e3a1;
    color: #1e1e2e;
    border-radius: 10px;
    padding: 2px 10px;
    font-weight: bold;
    font-size: 11px;
}
.status-stopped {
    background-color: #45475a;
    color: #cdd6f4;
    border-radius: 10px;
    padding: 2px 10px;
    font-size: 11px;
}
.btn-danger {
    background-color: #f38ba8;
    color: #1e1e2e;
    border-radius: 6px;
    font-weight: bold;
}
.btn-primary {
    background-color: #89b4fa;
    color: #1e1e2e;
    border-radius: 6px;
    font-weight: bold;
}
.btn-warning {
    background-color: #fab387;
    color: #1e1e2e;
    border-radius: 6px;
    font-weight: bold;
}
/* High-contrast canvas drag & lock buttons */
.btn-drag-unlock {
    background-color: #00acc1;
    color: #ffffff;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
    border: 1px solid #26c6da;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}
.btn-drag-unlock:hover {
    background-color: #00bcd4;
    color: #ffffff;
    border-color: #80deea;
}
.btn-drag-unlock:active {
    background-color: #0097a7;
    color: #ffffff;
}
.btn-drag-lock {
    background-color: #e53935;
    color: #ffffff;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
    border: 1px solid #ef5350;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
}
.btn-drag-lock:hover {
    background-color: #ef5350;
    color: #ffffff;
    border-color: #e57373;
}
.btn-drag-lock:active {
    background-color: #c62828;
    color: #ffffff;
}
scale trough {
    background-color: #45475a;
}
scale highlight {
    background-color: #89b4fa;
}
checkbutton check {
    background-color: #313244;
    border-color: #585b70;
}
checkbutton check:checked {
    background-color: #89b4fa;
}
"""


# ===========================================================================
# AppController — singleton subsystem holder
# ===========================================================================

class AppController:
    """
    Central singleton that owns and coordinates all Desktop Suite subsystems.

    All GTK widgets hold a reference to the *same* ``AppController``
    so UI interactions immediately affect the live engine and canvas.
    """

    def __init__(self) -> None:
        from src.core.config    import ConfigManager
        from src.core.autostart import AutostartManager, XfceShortcutManager
        from src.wallpaper.engine import WallpaperEngine
        from src.canvas.audio   import AudioStream
        from src.themes.registry import REGISTRY

        self.cfg        = ConfigManager()
        self.autostart  = AutostartManager()
        self.shortcuts  = XfceShortcutManager()
        self.engine     = WallpaperEngine()
        self.audio      = AudioStream(
            intensity=float(self.cfg.get("canvas.visualizer_intensity") or 0.65)
        )
        self.registry   = REGISTRY

        # Canvas window — created lazily in start_canvas().
        self._canvas: Optional[object] = None

        # Control Center window — created lazily in show_control_center().
        self._cc_win: Optional["ControlCenterWindow"] = None

        log.info("AppController initialised")

    # ------------------------------------------------------------------
    # Subsystem start / stop
    # ------------------------------------------------------------------

    def start_wallpaper(self) -> bool:
        """Start the wallpaper engine from current config values."""
        wp = self.cfg.get("wallpaper") or {}
        path = wp.get("video_path", "")
        if not path or not Path(path).is_file():
            log.warning("start_wallpaper: no valid video_path in config")
            return False
        started = self.engine.start(
            video_path   = path,
            speed        = float(wp.get("playback_speed", 1.0)),
            volume       = int(wp.get("volume", 50)),
            mute         = bool(wp.get("mute", True)),
            fit_mode     = wp.get("fit_mode", "fill"),
            fps_limit    = wp.get("fps_limit", "native"),
            autopause    = wp.get("autopause", "focus"),
        )
        if started and self._canvas:
            self._canvas.raise_above_wallpaper()
        return started

    def stop_wallpaper(self) -> None:
        """Stop the wallpaper engine."""
        self.engine.stop()

    def restart_wallpaper(self) -> bool:
        """Stop then restart the wallpaper engine."""
        self.engine.stop()
        res = self.start_wallpaper()
        if self._canvas:
            self._canvas.raise_above_wallpaper()
        return res

    def start_canvas(self) -> None:
        """Create and show the DesktopCanvasWindow if not already shown."""
        if self._canvas is not None:
            return
        from src.canvas.window   import DesktopCanvasWindow
        theme_name = self.cfg.get("canvas.active_theme") or "Original Cursive"
        theme = self.registry.get(theme_name) or self.registry.get_default()
        self.audio.start()
        self._canvas = DesktopCanvasWindow(
            cfg_manager      = self.cfg,
            theme            = theme,
            audio_stream     = self.audio,
            wallpaper_engine = self.engine,
        )
        self._canvas.show_all()
        self._canvas.raise_above_wallpaper()
        log.info("Canvas started")

    def stop_canvas(self) -> None:
        """Hide and destroy the canvas window."""
        if self._canvas:
            self._canvas.hide()
            self._canvas.destroy()
            self._canvas = None
        self.audio.stop()

    def reload_canvas(self) -> None:
        """Push latest config into the live canvas without recreating it."""
        if self._canvas:
            self._canvas.reload_config()

    def redraw_canvas(self) -> None:
        """Alias for reload_canvas to immediately repaint canvas."""
        self.reload_canvas()

    def start_all(self) -> None:
        """Boot sequence: start canvas then wallpaper."""
        self.start_canvas()
        self.start_wallpaper()

    def quit(self) -> None:
        """Clean shutdown of all subsystems then GTK main loop."""
        log.info("Desktop Suite shutting down …")
        self.engine.stop()
        self.audio.stop()
        if Gtk.main_level() > 0:
            Gtk.main_quit()

    # ------------------------------------------------------------------
    # Canvas passthrough helpers (used by tray / CC)
    # ------------------------------------------------------------------

    def toggle_canvas_edit_mode(self) -> bool:
        if self._canvas:
            return self._canvas.toggle_edit_mode()
        return False

    def apply_theme(self, theme_name: str) -> None:
        theme = self.registry.get(theme_name)
        if theme and self._canvas:
            self._canvas.set_theme(theme)
        self.cfg.set("canvas.active_theme", theme_name)
        self.cfg.save()

    # ------------------------------------------------------------------
    # Control Center
    # ------------------------------------------------------------------

    def show_control_center(self) -> None:
        """Show the Control Center window, creating it if necessary."""
        if self._cc_win is None:
            self._cc_win = ControlCenterWindow(self)
        self._cc_win.show_all()
        self._cc_win.present()

    def _on_cc_close(self, window: Gtk.Window, event) -> bool:
        """Hide rather than destroy so re-opening is instant."""
        return window.hide_on_delete()


# ===========================================================================
# Tab 1 — Live Wallpaper
# ===========================================================================

class WallpaperTab(Gtk.Box):
    """GTK3 widget for the 'Live Wallpaper' tab."""

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._ctrl = ctrl
        self._cfg  = ctrl.cfg
        self._building = True   # suppress config-write callbacks during init
        self._build()
        self._building = False

    def _build(self) -> None:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        scroll.add(vbox)
        self.pack_start(scroll, True, True, 0)

        # ── Status + Engine Controls ───────────────────────────────────
        vbox.pack_start(self._section("Engine Controls"), False, False, 0)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("card")

        # Status row
        status_row = Gtk.Box(spacing=8)
        Gtk.Label(label="Status:").set_halign(Gtk.Align.START)
        lbl = Gtk.Label(label="Status:")
        lbl.set_halign(Gtk.Align.START)
        self._status_pill = Gtk.Label(label=" Stopped ")
        self._status_pill.get_style_context().add_class("status-stopped")
        status_row.pack_start(lbl, False, False, 0)
        status_row.pack_start(self._status_pill, False, False, 4)
        card.pack_start(status_row, False, False, 0)

        # Engine buttons row
        btn_row = Gtk.Box(spacing=8)
        self._btn_start   = self._btn("▶  Start",   "btn-primary", self._on_start)
        self._btn_stop    = self._btn("■  Stop",    "btn-danger",  self._on_stop)
        self._btn_restart = self._btn("↺  Restart", "btn-warning", self._on_restart)
        self._btn_pause   = self._btn("⏸  Pause",   None,          self._on_pause_toggle)
        for b in (self._btn_start, self._btn_stop, self._btn_restart, self._btn_pause):
            btn_row.pack_start(b, False, False, 0)
        card.pack_start(btn_row, False, False, 0)

        # Video file chooser
        file_row = Gtk.Box(spacing=8)
        lbl2 = Gtk.Label(label="Video File:")
        lbl2.set_halign(Gtk.Align.START)
        self._file_btn = Gtk.FileChooserButton(
            title="Select Wallpaper Video",
            action=Gtk.FileChooserAction.OPEN,
        )
        # Filter for video files
        filt = Gtk.FileFilter()
        filt.set_name("Video files")
        for pat in ("*.mp4", "*.mkv", "*.webm", "*.mov", "*.avi", "*.gif"):
            filt.add_pattern(pat)
        self._file_btn.add_filter(filt)
        current_path = self._cfg.get("wallpaper.video_path") or ""
        if current_path and Path(current_path).exists():
            self._file_btn.set_filename(current_path)
        self._file_btn.connect("file-set", self._on_file_set)
        file_row.pack_start(lbl2, False, False, 0)
        file_row.pack_start(self._file_btn, True, True, 0)
        card.pack_start(file_row, False, False, 0)

        vbox.pack_start(card, False, False, 0)

        # ── Playback Controls ──────────────────────────────────────────
        vbox.pack_start(self._section("Playback"), False, False, 8)

        pb_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        pb_card.get_style_context().add_class("card")

        # Volume slider
        vol = int(self._cfg.get("wallpaper.volume") or 50)
        self._vol_scale = self._scale("Volume", 0, 100, vol, 5, 0)
        self._vol_scale.connect("value-changed", self._on_volume)
        pb_card.pack_start(self._labeled_widget("Volume:", self._vol_scale), False, False, 0)

        # Speed slider
        spd = float(self._cfg.get("wallpaper.playback_speed") or 1.0)
        self._spd_scale = self._scale("Speed", 0.5, 2.0, spd, 0.1, 2)
        self._spd_scale.connect("value-changed", self._on_speed)
        pb_card.pack_start(self._labeled_widget("Speed:", self._spd_scale), False, False, 0)

        # Mute checkbox
        self._mute_chk = Gtk.CheckButton(label="Mute Audio")
        self._mute_chk.set_active(bool(self._cfg.get("wallpaper.mute")))
        self._mute_chk.connect("toggled", self._on_mute)
        pb_card.pack_start(self._mute_chk, False, False, 0)

        vbox.pack_start(pb_card, False, False, 0)

        # ── Behaviour Dropdowns ────────────────────────────────────────
        vbox.pack_start(self._section("Behaviour"), False, False, 8)

        beh_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        beh_card.get_style_context().add_class("card")

        # Fit mode
        self._fit_combo = self._combo(
            [("fill", "Fill / Zoom"), ("fit", "Fit Inside"), ("stretch", "Stretch")],
            self._cfg.get("wallpaper.fit_mode") or "fill",
            self._on_fit,
        )
        beh_card.pack_start(self._labeled_widget("Screen Fit:", self._fit_combo), False, False, 0)

        # Auto-pause mode
        self._ap_combo = self._combo(
            [("focus", "Focus (Any App)"), ("maximized", "Maximized Only"), ("off", "Off")],
            self._cfg.get("wallpaper.autopause") or "focus",
            self._on_autopause,
        )
        beh_card.pack_start(self._labeled_widget("Auto-Pause:", self._ap_combo), False, False, 0)

        # FPS limit
        self._fps_combo = self._combo(
            [("native", "Native FPS"), ("30", "30 FPS"), ("24", "24 FPS")],
            self._cfg.get("wallpaper.fps_limit") or "native",
            self._on_fps,
        )
        beh_card.pack_start(self._labeled_widget("FPS Limit:", self._fps_combo), False, False, 0)

        vbox.pack_start(beh_card, False, False, 0)

        # ── Keyboard Shortcut ──────────────────────────────────────────
        vbox.pack_start(self._section("Keyboard Shortcut"), False, False, 8)
        sc_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sc_card.get_style_context().add_class("card")

        sc_desc = Gtk.Label(
            label="Global XFCE keyboard shortcut to toggle live wallpaper playback.",
            xalign=0,
        )
        sc_card.pack_start(sc_desc, False, False, 0)

        sc_row = Gtk.Box(spacing=8)
        self._shortcut_entry = Gtk.Entry()
        curr_sc = self._ctrl.shortcuts.get_current_shortcut() or "<Super>w"
        self._shortcut_entry.set_text(curr_sc)
        self._shortcut_entry.set_hexpand(True)
        sc_row.pack_start(self._shortcut_entry, True, True, 0)

        self._btn_bind_sc = self._btn("Bind Shortcut", "btn-primary", self._on_bind_shortcut)
        self._btn_remove_sc = self._btn("Remove Shortcut", "btn-danger", self._on_remove_shortcut)
        sc_row.pack_start(self._btn_bind_sc, False, False, 0)
        sc_row.pack_start(self._btn_remove_sc, False, False, 0)
        sc_card.pack_start(sc_row, False, False, 0)

        bound_sc = self._ctrl.shortcuts.get_current_shortcut()
        status_text = f"Currently bound in XFCE: {bound_sc}" if bound_sc else "No hotkey currently bound in XFCE"
        self._sc_status_lbl = Gtk.Label(label=status_text, xalign=0)
        self._sc_status_lbl.get_style_context().add_class("section-label")
        sc_card.pack_start(self._sc_status_lbl, False, False, 0)

        vbox.pack_start(sc_card, False, False, 0)

        # ── Autostart ─────────────────────────────────────────────────
        vbox.pack_start(self._section("System"), False, False, 8)
        sys_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        sys_card.get_style_context().add_class("card")

        self._auto_chk = Gtk.CheckButton(label="Start Desktop Suite automatically on login")
        self._auto_chk.set_active(self._ctrl.autostart.is_enabled())
        self._auto_chk.connect("toggled", self._on_autostart)
        sys_card.pack_start(self._auto_chk, False, False, 0)

        vbox.pack_start(sys_card, False, False, 0)

        # ── Poll status every 2 s ──────────────────────────────────────
        GLib.timeout_add_seconds(2, self._refresh_status)
        self._refresh_status()

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _section(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text.upper(), xalign=0)
        lbl.get_style_context().add_class("section-label")
        return lbl

    def _btn(self, label: str, css_class: Optional[str], callback) -> Gtk.Button:
        b = Gtk.Button(label=label)
        if css_class:
            b.get_style_context().add_class(css_class)
        b.connect("clicked", callback)
        return b

    def _scale(
        self, name: str, lo: float, hi: float,
        val: float, step: float, digits: int,
    ) -> Gtk.Scale:
        adj = Gtk.Adjustment(value=val, lower=lo, upper=hi, step_increment=step)
        s = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj)
        s.set_digits(digits)
        s.set_hexpand(True)
        return s

    def _combo(
        self,
        items: list[tuple[str, str]],
        active_id: str,
        callback,
    ) -> Gtk.ComboBoxText:
        c = Gtk.ComboBoxText()
        for id_, label in items:
            c.append(id_, label)
        c.set_active_id(active_id)
        c.connect("changed", callback)
        return c

    def _labeled_widget(self, label: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(spacing=8)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_size_request(90, -1)
        row.pack_start(lbl, False, False, 0)
        row.pack_start(widget, True, True, 0)
        return row

    # ------------------------------------------------------------------
    # Status refresh
    # ------------------------------------------------------------------

    def _refresh_status(self) -> bool:
        running = self._ctrl.engine.is_running
        if running:
            self._status_pill.set_text(" Active ")
            self._status_pill.get_style_context().remove_class("status-stopped")
            self._status_pill.get_style_context().add_class("status-active")
            self._btn_pause.set_label("⏸  Pause" if not self._ctrl.engine.is_paused else "▶  Resume")
        else:
            self._status_pill.set_text(" Stopped ")
            self._status_pill.get_style_context().remove_class("status-active")
            self._status_pill.get_style_context().add_class("status-stopped")
            self._btn_pause.set_label("⏸  Pause")
        return True   # keep timer alive

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_start(self, _btn) -> None:
        self._ctrl.start_wallpaper()
        GLib.timeout_add(500, self._refresh_status)

    def _on_stop(self, _btn) -> None:
        self._ctrl.stop_wallpaper()
        GLib.timeout_add(300, self._refresh_status)

    def _on_restart(self, _btn) -> None:
        self._ctrl.restart_wallpaper()
        GLib.timeout_add(600, self._refresh_status)

    def _on_pause_toggle(self, _btn) -> None:
        self._ctrl.engine.toggle_pause()
        self._refresh_status()

    def _on_file_set(self, chooser) -> None:
        path = chooser.get_filename() or ""
        self._cfg.set("wallpaper.video_path", path)
        self._cfg.save()

    def _on_volume(self, scale) -> None:
        val = int(scale.get_value())
        self._cfg.set("wallpaper.volume", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.engine.set_volume(val)

    def _on_speed(self, scale) -> None:
        val = round(scale.get_value(), 2)
        self._cfg.set("wallpaper.playback_speed", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.engine.set_speed(val)

    def _on_mute(self, chk) -> None:
        self._cfg.set("wallpaper.mute", chk.get_active())
        if not self._building:
            self._cfg.save()

    def _on_fit(self, combo) -> None:
        val = combo.get_active_id() or "fill"
        self._cfg.set("wallpaper.fit_mode", val)
        if not self._building:
            self._cfg.save()

    def _on_autopause(self, combo) -> None:
        val = combo.get_active_id() or "focus"
        self._cfg.set("wallpaper.autopause", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.engine.set_autopause(val)

    def _on_fps(self, combo) -> None:
        val = combo.get_active_id() or "native"
        self._cfg.set("wallpaper.fps_limit", val)
        if not self._building:
            self._cfg.save()

    def _on_autostart(self, chk) -> None:
        if chk.get_active():
            self._ctrl.autostart.enable()
        else:
            self._ctrl.autostart.disable()
        self._cfg.set("wallpaper.autostart", chk.get_active())
        self._cfg.save()

    def _on_bind_shortcut(self, _btn) -> None:
        text = self._shortcut_entry.get_text().strip()
        if not text:
            return
        ok = self._ctrl.shortcuts.bind_shortcut(text)
        if ok:
            canon = self._ctrl.shortcuts.normalize_shortcut(text)
            self._shortcut_entry.set_text(canon)
            self._cfg.set("wallpaper.shortcut", canon)
            self._cfg.save()
            self._sc_status_lbl.set_text(f"Currently bound in XFCE: {canon}")
        else:
            self._sc_status_lbl.set_text("Failed to bind shortcut via xfconf")

    def _on_remove_shortcut(self, _btn) -> None:
        ok = self._ctrl.shortcuts.remove_shortcut()
        if ok:
            self._cfg.set("wallpaper.shortcut", "")
            self._cfg.save()
            self._sc_status_lbl.set_text("No hotkey currently bound in XFCE")


# ===========================================================================
# Tab 2 — Clock & Canvas Studio
# ===========================================================================

class CanvasTab(Gtk.Box):
    """GTK3 widget for the 'Clock & Canvas Studio' tab."""

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self._ctrl = ctrl
        self._cfg  = ctrl.cfg
        self._building = True
        self._build()
        self._building = False

    def _build(self) -> None:
        scroll = Gtk.ScrolledWindow()
        scroll.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        vbox.set_margin_top(12)
        vbox.set_margin_bottom(12)
        vbox.set_margin_start(16)
        vbox.set_margin_end(16)
        scroll.add(vbox)
        self.pack_start(scroll, True, True, 0)

        # ── Theme Selector ─────────────────────────────────────────────
        vbox.pack_start(self._section("Visual Theme"), False, False, 0)
        theme_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        theme_card.get_style_context().add_class("card")

        self._theme_combo = Gtk.ComboBoxText()
        active_theme = self._cfg.get("canvas.active_theme") or "Original Cursive"
        for name in self._ctrl.registry.names():
            self._theme_combo.append(name, name)
        self._theme_combo.set_active_id(active_theme)
        self._theme_combo.connect("changed", self._on_theme)
        theme_card.pack_start(
            self._labeled("Theme:", self._theme_combo), False, False, 0
        )
        vbox.pack_start(theme_card, False, False, 0)

        # ── Component Toggles ──────────────────────────────────────────
        vbox.pack_start(self._section("Components"), False, False, 8)
        comp_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        comp_card.get_style_context().add_class("card")

        self._clock_chk = Gtk.CheckButton(label="Show Clock")
        self._clock_chk.set_active(bool(self._cfg.get("canvas.clock_enabled")))
        self._clock_chk.connect("toggled", lambda c: self._toggle_canvas("clock_enabled", c))
        comp_card.pack_start(self._clock_chk, False, False, 0)

        self._date_chk = Gtk.CheckButton(label="Show Date")
        self._date_chk.set_active(bool(self._cfg.get("canvas.date_enabled")))
        self._date_chk.connect("toggled", lambda c: self._toggle_canvas("date_enabled", c))
        comp_card.pack_start(self._date_chk, False, False, 0)

        self._vis_chk = Gtk.CheckButton(label="Show Audio Visualizer")
        self._vis_chk.set_active(bool(self._cfg.get("canvas.visualizer_enabled")))
        self._vis_chk.connect("toggled", lambda c: self._toggle_canvas("visualizer_enabled", c))
        comp_card.pack_start(self._vis_chk, False, False, 0)

        vbox.pack_start(comp_card, False, False, 0)

        # ── Appearance ─────────────────────────────────────────────────
        vbox.pack_start(self._section("Appearance"), False, False, 8)
        app_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        app_card.get_style_context().add_class("card")

        # Clock Color
        clock_hex = self._cfg.get("canvas.clock_color") or "#FFFFFF"
        self._clock_color_btn = Gtk.ColorButton()
        self._clock_color_btn.set_use_alpha(False)
        rgba_clk = Gdk.RGBA()
        rgba_clk.parse(clock_hex)
        self._clock_color_btn.set_rgba(rgba_clk)
        self._clock_color_btn.connect("color-set", self._on_clock_color)
        app_card.pack_start(self._labeled("Clock Color:", self._clock_color_btn), False, False, 0)

        # Date Color
        date_hex = self._cfg.get("canvas.date_color") or "#D0D0D0"
        self._date_color_btn = Gtk.ColorButton()
        self._date_color_btn.set_use_alpha(False)
        rgba_dt = Gdk.RGBA()
        rgba_dt.parse(date_hex)
        self._date_color_btn.set_rgba(rgba_dt)
        self._date_color_btn.connect("color-set", self._on_date_color)
        app_card.pack_start(self._labeled("Date Color:", self._date_color_btn), False, False, 0)

        # Visualizer Color
        vis_hex = self._cfg.get("canvas.visualizer_color") or "#FFFFFF"
        self._vis_color_btn = Gtk.ColorButton()
        self._vis_color_btn.set_use_alpha(False)
        rgba_vis = Gdk.RGBA()
        rgba_vis.parse(vis_hex)
        self._vis_color_btn.set_rgba(rgba_vis)
        self._vis_color_btn.connect("color-set", self._on_vis_color)
        app_card.pack_start(self._labeled("Visualizer Color:", self._vis_color_btn), False, False, 0)

        # Background opacity slider
        opacity = float(self._cfg.get("canvas.background_opacity") or 0.0)
        adj = Gtk.Adjustment(value=opacity, lower=0.0, upper=1.0, step_increment=0.05)
        self._opacity_scale = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj
        )
        self._opacity_scale.set_digits(2)
        self._opacity_scale.set_hexpand(True)
        self._opacity_scale.connect("value-changed", self._on_opacity)
        app_card.pack_start(
            self._labeled("BG Opacity:", self._opacity_scale), False, False, 0
        )

        # Master Scale slider
        scale_val = float(self._cfg.get("canvas.scale") or 1.0)
        adj_scale = Gtk.Adjustment(value=scale_val, lower=0.5, upper=2.5, step_increment=0.05)
        self._scale_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_scale
        )
        self._scale_slider.set_digits(2)
        self._scale_slider.set_hexpand(True)
        self._scale_slider.connect("value-changed", self._on_scale)
        app_card.pack_start(
            self._labeled("Master Scale:", self._scale_slider), False, False, 0
        )

        # Independent Element Scaling switch
        indep_row = Gtk.Box(spacing=8)
        indep_lbl = Gtk.Label(label="Independent Element Scaling", xalign=0)
        indep_lbl.set_hexpand(True)
        self._indep_switch = Gtk.Switch()
        self._indep_switch.set_active(bool(self._cfg.get("canvas.independent_scales", False)))
        self._indep_switch.set_valign(Gtk.Align.CENTER)
        self._indep_switch.connect("notify::active", self._on_independent_scales_toggled)
        indep_row.pack_start(indep_lbl, True, True, 0)
        indep_row.pack_end(self._indep_switch, False, False, 0)
        app_card.pack_start(indep_row, False, False, 4)

        # Collapsible / Revealer container holding 3 distinct sliders
        self._revealer = Gtk.Revealer()
        self._revealer.set_transition_type(Gtk.RevealerTransitionType.SLIDE_DOWN)
        self._revealer.set_reveal_child(self._indep_switch.get_active())

        indep_vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        indep_vbox.set_margin_top(4)
        indep_vbox.set_margin_bottom(6)
        indep_vbox.set_margin_start(16)

        # Clock Scale slider (0.4x to 3.0x, step 0.05)
        clk_sc = float(self._cfg.get("canvas.clock_scale") or 1.0)
        adj_clk = Gtk.Adjustment(value=clk_sc, lower=0.4, upper=3.0, step_increment=0.05)
        self._clock_scale_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_clk
        )
        self._clock_scale_slider.set_digits(2)
        self._clock_scale_slider.set_hexpand(True)
        self._clock_scale_slider.connect("value-changed", lambda s: self._on_elem_scale("clock_scale", s))
        indep_vbox.pack_start(
            self._labeled("Clock Scale:", self._clock_scale_slider), False, False, 0
        )

        # Date Scale slider (0.4x to 3.0x, step 0.05)
        dt_sc = float(self._cfg.get("canvas.date_scale") or 1.0)
        adj_dt = Gtk.Adjustment(value=dt_sc, lower=0.4, upper=3.0, step_increment=0.05)
        self._date_scale_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_dt
        )
        self._date_scale_slider.set_digits(2)
        self._date_scale_slider.set_hexpand(True)
        self._date_scale_slider.connect("value-changed", lambda s: self._on_elem_scale("date_scale", s))
        indep_vbox.pack_start(
            self._labeled("Date Scale:", self._date_scale_slider), False, False, 0
        )

        # Visualizer Scale slider (0.4x to 3.0x, step 0.05)
        vis_sc = float(self._cfg.get("canvas.visualizer_scale") or 1.0)
        adj_vis_sc = Gtk.Adjustment(value=vis_sc, lower=0.4, upper=3.0, step_increment=0.05)
        self._vis_scale_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_vis_sc
        )
        self._vis_scale_slider.set_digits(2)
        self._vis_scale_slider.set_hexpand(True)
        self._vis_scale_slider.connect("value-changed", lambda s: self._on_elem_scale("visualizer_scale", s))
        indep_vbox.pack_start(
            self._labeled("Visualizer Scale:", self._vis_scale_slider), False, False, 0
        )

        self._revealer.add(indep_vbox)
        app_card.pack_start(self._revealer, False, False, 0)

        # Visualizer Intensity slider
        vis_intensity = float(self._cfg.get("canvas.visualizer_intensity") or 0.65)
        adj_vis = Gtk.Adjustment(value=vis_intensity, lower=0.10, upper=2.0, step_increment=0.05)
        self._vis_intensity_slider = Gtk.Scale(
            orientation=Gtk.Orientation.HORIZONTAL, adjustment=adj_vis
        )
        self._vis_intensity_slider.set_digits(2)
        self._vis_intensity_slider.set_hexpand(True)
        self._vis_intensity_slider.connect("value-changed", self._on_vis_intensity)
        app_card.pack_start(
            self._labeled("Vis Intensity:", self._vis_intensity_slider), False, False, 0
        )

        vbox.pack_start(app_card, False, False, 0)

        # ── Drag / Position editor ─────────────────────────────────────
        vbox.pack_start(self._section("Component Positions"), False, False, 8)
        drag_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        drag_card.get_style_context().add_class("card")

        desc = Gtk.Label(
            label="Unlock the canvas to drag Clock, Date, and Visualizer\n"
                  "freely on the desktop. Lock to save positions.",
            xalign=0,
        )
        desc.set_line_wrap(True)
        drag_card.pack_start(desc, False, False, 0)

        self._drag_btn = Gtk.ToggleButton(label="🔓  Unlock Canvas / Drag Components")
        self._drag_btn.get_style_context().add_class("btn-drag-unlock")
        self._drag_btn.connect("toggled", self._on_drag_toggle)
        drag_card.pack_start(self._drag_btn, False, False, 0)

        vbox.pack_start(drag_card, False, False, 0)

    # ------------------------------------------------------------------
    # Widget helpers
    # ------------------------------------------------------------------

    def _section(self, text: str) -> Gtk.Label:
        lbl = Gtk.Label(label=text.upper(), xalign=0)
        lbl.get_style_context().add_class("section-label")
        return lbl

    def _labeled(self, label: str, widget: Gtk.Widget) -> Gtk.Box:
        row = Gtk.Box(spacing=8)
        lbl = Gtk.Label(label=label, xalign=0)
        lbl.set_size_request(120, -1)
        row.pack_start(lbl, False, False, 0)
        row.pack_start(widget, True, True, 0)
        return row

    # ------------------------------------------------------------------
    # Callbacks
    # ------------------------------------------------------------------

    def _on_theme(self, combo) -> None:
        name = combo.get_active_id() or "Original Cursive"
        if not self._building:
            self._ctrl.apply_theme(name)

    def _toggle_canvas(self, key: str, chk: Gtk.CheckButton) -> None:
        self._cfg.set(f"canvas.{key}", chk.get_active())
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_clock_color(self, btn: Gtk.ColorButton) -> None:
        rgba = btn.get_rgba()
        hex_c = "#{:02X}{:02X}{:02X}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        self._cfg.set("canvas.clock_color", hex_c)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_date_color(self, btn: Gtk.ColorButton) -> None:
        rgba = btn.get_rgba()
        hex_c = "#{:02X}{:02X}{:02X}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        self._cfg.set("canvas.date_color", hex_c)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_vis_color(self, btn: Gtk.ColorButton) -> None:
        rgba = btn.get_rgba()
        hex_c = "#{:02X}{:02X}{:02X}".format(
            int(rgba.red * 255), int(rgba.green * 255), int(rgba.blue * 255)
        )
        self._cfg.set("canvas.visualizer_color", hex_c)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_opacity(self, scale: Gtk.Scale) -> None:
        val = round(scale.get_value(), 2)
        self._cfg.set("canvas.background_opacity", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_scale(self, scale: Gtk.Scale) -> None:
        val = round(scale.get_value(), 2)
        self._cfg.set("canvas.scale", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_independent_scales_toggled(self, switch: Gtk.Switch, _param) -> None:
        active = switch.get_active()
        self._revealer.set_reveal_child(active)
        self._cfg.set("canvas.independent_scales", active)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_elem_scale(self, key: str, scale: Gtk.Scale) -> None:
        val = round(scale.get_value(), 2)
        self._cfg.set(f"canvas.{key}", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.redraw_canvas()

    def _on_vis_intensity(self, scale: Gtk.Scale) -> None:
        val = round(scale.get_value(), 2)
        self._cfg.set("canvas.visualizer_intensity", val)
        if not self._building:
            self._cfg.save()
            self._ctrl.audio.set_intensity(val)
            self._ctrl.redraw_canvas()

    def _on_drag_toggle(self, btn: Gtk.ToggleButton) -> None:
        active = btn.get_active()
        if active:
            btn.set_label("🔒  Lock Positions (Save)")
            btn.get_style_context().remove_class("btn-drag-unlock")
            btn.get_style_context().add_class("btn-drag-lock")
        else:
            btn.set_label("🔓  Unlock Canvas / Drag Components")
            btn.get_style_context().remove_class("btn-drag-lock")
            btn.get_style_context().add_class("btn-drag-unlock")
        self._ctrl.toggle_canvas_edit_mode()


# ===========================================================================
# Control Center Window
# ===========================================================================

class ControlCenterWindow(Gtk.Window):
    """
    Tabbed dark-themed Control Center window.

    Contains :class:`WallpaperTab` and :class:`CanvasTab`.
    """

    def __init__(self, ctrl: AppController) -> None:
        super().__init__(title="Desktop Suite — Control Center")
        self._ctrl = ctrl

        # Apply dark CSS.
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(_DARK_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        self.get_style_context().add_class("control-center")

        self.set_default_size(520, 660)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("preferences-desktop-wallpaper")
        # Hide window on close rather than destroying so widgets and tray keep running
        self.connect("delete-event", lambda w, e: w.hide_on_delete())

        # Header bar.
        header = Gtk.HeaderBar()
        header.set_show_close_button(True)
        header.set_title("Desktop Suite")
        header.set_subtitle("Control Center")
        self.set_titlebar(header)

        # Notebook.
        notebook = Gtk.Notebook()
        notebook.set_tab_pos(Gtk.PositionType.TOP)

        tab1 = WallpaperTab(ctrl)
        tab1_label = Gtk.Label(label="🎬  Live Wallpaper")
        notebook.append_page(tab1, tab1_label)

        tab2 = CanvasTab(ctrl)
        tab2_label = Gtk.Label(label="🕐  Clock & Canvas")
        notebook.append_page(tab2, tab2_label)

        self.add(notebook)
        self.show_all()


# ===========================================================================
# System Tray
# ===========================================================================

class SystemTray:
    """
    System tray icon using ``Gtk.StatusIcon`` (fallback — no AppIndicator3).

    Menu
    ----
    * Open Control Center
    * Toggle Live Wallpaper
    * Toggle Canvas Edit Mode
    * Reload Desktop Canvas
    * ─────────────────────
    * Quit Desktop Suite
    """

    def __init__(self, ctrl: AppController) -> None:
        self._ctrl = ctrl

        self._icon = Gtk.StatusIcon()
        self._icon.set_from_icon_name("preferences-desktop-wallpaper")
        self._icon.set_title("Desktop Suite")
        self._icon.set_tooltip_text("Desktop Suite")
        self._icon.set_visible(True)

        # Both left-click and right-click open the menu for discoverability.
        self._icon.connect("activate",      self._on_left_click)
        self._icon.connect("popup-menu",    self._on_right_click)

    # ------------------------------------------------------------------
    # Click handlers
    # ------------------------------------------------------------------

    def _on_left_click(self, icon) -> None:
        self._ctrl.show_control_center()

    def _on_right_click(self, icon, button, activate_time) -> None:
        menu = self._build_menu()
        menu.show_all()
        menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    # ------------------------------------------------------------------
    # Menu construction
    # ------------------------------------------------------------------

    def _build_menu(self) -> Gtk.Menu:
        menu = Gtk.Menu()

        def item(label: str, callback) -> Gtk.MenuItem:
            it = Gtk.MenuItem(label=label)
            it.connect("activate", lambda w: callback())
            return it

        menu.append(item("⚙  Open Control Center",     self._ctrl.show_control_center))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(item("🎬  Toggle Live Wallpaper",   self._toggle_wallpaper))
        menu.append(item("🔓  Toggle Canvas Edit Mode", self._ctrl.toggle_canvas_edit_mode))
        menu.append(item("🔄  Reload Desktop Canvas",   self._ctrl.reload_canvas))
        menu.append(Gtk.SeparatorMenuItem())
        menu.append(item("✕   Quit Desktop Suite",      self._ctrl.quit))

        return menu

    def _toggle_wallpaper(self) -> None:
        if self._ctrl.engine.is_running:
            self._ctrl.stop_wallpaper()
        else:
            self._ctrl.start_wallpaper()


# ===========================================================================
# Entry point
# ===========================================================================

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="desktop-suite",
        description="Desktop Suite — live wallpaper + canvas overlay controller",
    )
    parser.add_argument(
        "--daemon", "--start-all",
        dest="daemon",
        action="store_true",
        help="Start both subsystems silently without showing the GUI "
             "(for autostart / headless boot use).",
    )
    parser.add_argument(
        "--toggle-wallpaper",
        action="store_true",
        help="Directly toggle wallpaper playback (pause/resume or start if dead) "
             "via socket IPC and exit immediately (0ms GUI overhead).",
    )
    parser.add_argument(
        "--kill-wallpaper",
        action="store_true",
        help="Instantly terminate the mpv/wallpaper process group and exit cleanly.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version="Desktop Suite 0.1.0",
    )
    return parser.parse_args()


def main() -> None:
    # Ignore SIGHUP so terminal closures don't kill background process
    import signal
    try:
        signal.signal(signal.SIGHUP, signal.SIG_IGN)
    except (AttributeError, ValueError):
        pass

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s  %(name)-30s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S",
    )

    args = _parse_args()

    # Fast CLI actions if invoked without short-circuiting at top of module
    if args.kill_wallpaper:
        from src.wallpaper.engine import WallpaperEngine
        engine = WallpaperEngine()
        engine.stop()
        print("[Desktop Suite] Live wallpaper killed.")
        sys.exit(0)

    if args.toggle_wallpaper:
        from src.wallpaper.ipc import MpvIPC
        ipc = MpvIPC()
        if ipc.is_alive():
            is_paused = ipc.get_property("pause")
            if is_paused is True:
                ipc.resume()
                print("[Desktop Suite] Wallpaper resumed.")
            else:
                ipc.pause()
                print("[Desktop Suite] Wallpaper paused.")
        else:
            from src.core.config import ConfigManager
            from src.wallpaper.engine import WallpaperEngine
            cfg = ConfigManager()
            wp = cfg.get("wallpaper") or {}
            path = wp.get("video_path", "")
            if path and Path(path).is_file():
                engine = WallpaperEngine()
                started = engine.start(
                    video_path   = path,
                    speed        = float(wp.get("playback_speed", 1.0)),
                    volume       = int(wp.get("volume", 50)),
                    mute         = bool(wp.get("mute", True)),
                    fit_mode     = wp.get("fit_mode", "fill"),
                    fps_limit    = wp.get("fps_limit", "native"),
                    autopause    = wp.get("autopause", "focus"),
                )
                if started:
                    print(f"[Desktop Suite] Wallpaper started ({path}).")
                else:
                    print("[Desktop Suite] Failed to start wallpaper engine.")
            else:
                print("[Desktop Suite] Cannot start wallpaper: no valid video_path configured.")
        sys.exit(0)

    # If --daemon is requested from an interactive terminal, fork into background
    if args.daemon and sys.stdin.isatty():
        pid = os.fork()
        if pid > 0:
            print(f"[Desktop Suite] Daemon started in background (PID {pid}).")
            sys.exit(0)
        os.setsid()

    # Instantiate the central controller (loads config, creates subsystems).
    ctrl = AppController()

    def _sig_handler(signum, frame):
        ctrl.quit()

    try:
        signal.signal(signal.SIGINT, _sig_handler)
        signal.signal(signal.SIGTERM, _sig_handler)
    except (AttributeError, ValueError):
        pass

    # Always start the canvas overlay.
    ctrl.start_canvas()

    # Always start the wallpaper if a video is configured.
    ctrl.start_wallpaper()

    # System tray — always present regardless of GUI mode.
    tray = SystemTray(ctrl)

    if not args.daemon:
        # Full GUI mode: open the Control Center window immediately.
        ctrl.show_control_center()

    log.info(
        "Desktop Suite running (mode=%s)",
        "daemon" if args.daemon else "gui",
    )

    try:
        Gtk.main()
    except KeyboardInterrupt:
        pass
    finally:
        ctrl.engine.stop()
        ctrl.audio.stop()


if __name__ == "__main__":
    main()
