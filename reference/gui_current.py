#!/usr/bin/env python3
import gi
gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GLib
import os, json, shutil, subprocess

WALL_DIR = os.path.expanduser("~/Videos/Wallpapers")
J_CONF = os.path.expanduser("~/.config/live-wallpaper-settings.json")
B_CONF = os.path.expanduser("~/.config/live-wallpaper.conf")
DAEMON = os.path.expanduser("~/.local/bin/live-wallpaper-daemon.sh")
TOGGLE_SCRIPT = os.path.expanduser("~/.local/bin/live-wallpaper-toggle.sh")
AUTOSTART = os.path.expanduser("~/.config/autostart/live-wallpaper.desktop")
EXTS = ('.mp4', '.mkv', '.webm', '.mov', '.avi', '.gif')

SHORTCUT_MAP = {
    "Super + W": "<Super>w",
    "Ctrl + Alt + W": "<Primary><Alt>w",
    "Super + F12": "<Super>F12",
    "F12": "F12",
    "Disabled": ""
}

class WallpaperGUI(Gtk.Window):
    def __init__(self):
        super().__init__(title="Live Wallpaper Manager")
        self.set_default_size(640, 450)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_border_width(10)
        os.makedirs(WALL_DIR, exist_ok=True)

        self.cfg = {
            "video": "", "autopause": "focus", "fps": "native", "fit": "fill",
            "speed": 1.0, "mute": True, "vol": 50,
            "autostart": False, "shortcut": "Super + W"
        }
        if os.path.exists(J_CONF):
            try:
                with open(J_CONF) as f: self.cfg.update(json.load(f))
            except Exception: pass

        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.add(vbox)

        # Top Bar
        top = Gtk.Box(spacing=6)
        lbl = Gtk.Label(xalign=0)
        lbl.set_markup(f"<b>Folder:</b> <tt>{WALL_DIR}</tt>")
        b_open = Gtk.Button(label="Open Folder")
        b_open.connect("clicked", lambda w: subprocess.Popen(["xdg-open", WALL_DIR]))
        b_imp = Gtk.Button(label="Import...")
        b_imp.connect("clicked", self.import_vid)
        b_ref = Gtk.Button(label="Refresh")
        b_ref.connect("clicked", lambda w: self.reload_list())
        top.pack_start(lbl, True, True, 0)
        for b in (b_ref, b_imp, b_open): top.pack_end(b, False, False, 0)
        vbox.pack_start(top, False, False, 0)

        # Middle Split
        hbox = Gtk.Box(spacing=10)
        vbox.pack_start(hbox, True, True, 0)

        # Video List
        sc = Gtk.ScrolledWindow()
        sc.set_size_request(260, -1)
        self.store = Gtk.ListStore(str, str, str)
        self.tree = Gtk.TreeView(model=self.store)
        self.tree.connect("row-activated", lambda t, p, c: self.apply_wall(None))
        self.tree.get_selection().connect("changed", self.on_select)
        r = Gtk.CellRendererText()
        c1 = Gtk.TreeViewColumn("Wallpaper File", r, text=0); c1.set_expand(True)
        c2 = Gtk.TreeViewColumn("Size", r, text=1)
        self.tree.append_column(c1); self.tree.append_column(c2)
        sc.add(self.tree)
        hbox.pack_start(sc, True, True, 0)

        # Settings Grid
        grid = Gtk.Grid(row_spacing=8, column_spacing=8)
        hbox.pack_start(grid, False, False, 0)

        def add_combo(row, title, items, active):
            grid.attach(Gtk.Label(label=title, xalign=0), 0, row, 1, 1)
            c = Gtk.ComboBoxText()
            for k, v in items: c.append(k, v)
            c.set_active_id(active)
            grid.attach(c, 1, row, 1, 1)
            return c

        self.c_pause = add_combo(0, "Auto-Pause:", [("focus", "Any Window Focused"), ("maximized", "Maximized Only"), ("off", "Never Pause")], self.cfg["autopause"])
        self.c_fps = add_combo(1, "FPS Limit:", [("native", "Native FPS"), ("30", "30 FPS (Cool)"), ("24", "24 FPS (Ultra Cool)")], self.cfg["fps"])
        self.c_fit = add_combo(2, "Screen Fit:", [("fill", "Zoom / Fill"), ("fit", "Fit Inside"), ("stretch", "Stretch")], self.cfg["fit"])

        # Global Shortcut Row
        grid.attach(Gtk.Label(label="Toggle Key:", xalign=0), 0, 3, 1, 1)
        self.c_shortcut = Gtk.ComboBoxText()
        for k in SHORTCUT_MAP.keys():
            self.c_shortcut.append(k, k)
        self.c_shortcut.set_active_id(self.cfg.get("shortcut", "Super + W"))
        grid.attach(self.c_shortcut, 1, 3, 1, 1)

        def add_scale(row, title, val, lo, hi, step, digits):
            grid.attach(Gtk.Label(label=title, xalign=0), 0, row, 1, 1)
            s = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=Gtk.Adjustment(value=val, lower=lo, upper=hi, step_increment=step))
            s.set_digits(digits); s.set_hexpand(True)
            grid.attach(s, 1, row, 1, 1)
            return s

        self.s_spd = add_scale(4, "Speed:", self.cfg["speed"], 0.25, 2.0, 0.05, 2)
        self.s_vol = add_scale(5, "Volume:", self.cfg["vol"], 0, 100, 5, 0)

        self.k_mute = Gtk.CheckButton(label="Mute Video Audio")
        self.k_mute.set_active(self.cfg["mute"])
        grid.attach(self.k_mute, 0, 6, 2, 1)

        self.k_auto = Gtk.CheckButton(label="Start Wallpaper on Boot")
        self.k_auto.set_active(os.path.exists(AUTOSTART))
        grid.attach(self.k_auto, 0, 7, 2, 1)

        # Bottom Bar
        bot = Gtk.Box(spacing=8)
        self.status = Gtk.Label(xalign=0)

        b_kill = Gtk.Button(label="Kill / Stop Wallpaper")
        b_kill.connect("clicked", self.kill_wall)

        b_start = Gtk.Button(label="Apply & Start")
        b_start.get_style_context().add_class("suggested-action")
        b_start.connect("clicked", self.apply_wall)

        bot.pack_start(self.status, True, True, 0)
        bot.pack_end(b_start, False, False, 0)
        bot.pack_end(b_kill, False, False, 0)
        vbox.pack_start(bot, False, False, 0)

        self.reload_list()
        self.check_status()
        GLib.timeout_add_seconds(2, self.check_status)

    def on_select(self, sel):
        m, it = sel.get_selected()
        if it: self.cfg["video"] = m[it][2]

    def reload_list(self):
        self.store.clear()
        sel_it = None
        for f in sorted(os.listdir(WALL_DIR)):
            if f.lower().endswith(EXTS):
                p = os.path.join(WALL_DIR, f)
                if os.path.isfile(p):
                    sz = f"{os.path.getsize(p)/(1024*1024):.1f} MB"
                    it = self.store.append([f, sz, p])
                    if p == self.cfg.get("video"): sel_it = it
        if sel_it: self.tree.get_selection().select_iter(sel_it)
        elif len(self.store) > 0: self.tree.get_selection().select_iter(self.store.get_iter_first())

    def import_vid(self, w):
        d = Gtk.FileChooserDialog(title="Import Video", parent=self, action=Gtk.FileChooserAction.OPEN)
        d.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        if d.run() == Gtk.ResponseType.OK:
            src = d.get_filename()
            dst = os.path.join(WALL_DIR, os.path.basename(src))
            if os.path.abspath(src) != os.path.abspath(dst): shutil.copy2(src, dst)
            self.cfg["video"] = dst
            self.reload_list()
        d.destroy()

    def set_system_shortcut(self, new_key_label):
        old_key_label = self.cfg.get("shortcut", "")
        old_val = SHORTCUT_MAP.get(old_key_label, "")
        if old_val:
            subprocess.call(f'xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/{old_val}" -r 2>/dev/null', shell=True)

        new_val = SHORTCUT_MAP.get(new_key_label, "")
        if new_val:
            subprocess.call(f'xfconf-query -c xfce4-keyboard-shortcuts -p "/commands/custom/{new_val}" -n -t string -s "{TOGGLE_SCRIPT}" 2>/dev/null', shell=True)

    def apply_wall(self, w):
        chosen_shortcut = self.c_shortcut.get_active_id() or "Super + W"
        self.set_system_shortcut(chosen_shortcut)

        self.cfg.update({
            "autopause": self.c_pause.get_active_id() or "focus",
            "fps": self.c_fps.get_active_id() or "native",
            "fit": self.c_fit.get_active_id() or "fill",
            "shortcut": chosen_shortcut,
            "speed": round(self.s_spd.get_value(), 2),
            "vol": int(self.s_vol.get_value()),
            "mute": self.k_mute.get_active(),
            "autostart": self.k_auto.get_active()
        })
        with open(J_CONF, "w") as f: json.dump(self.cfg, f)

        m_str = "yes" if self.cfg["mute"] else "no"
        with open(B_CONF, "w") as f:
            f.write(f'VIDEO="{self.cfg["video"]}"\nAUTOPAUSE="{self.cfg["autopause"]}"\nFPS="{self.cfg["fps"]}"\n')
            f.write(f'FIT="{self.cfg["fit"]}"\nSPEED="{self.cfg["speed"]}"\nMUTE="{m_str}"\n')
            f.write(f'VOL="{self.cfg["vol"]}"\n')

        os.makedirs(os.path.dirname(AUTOSTART), exist_ok=True)
        if self.cfg["autostart"]:
            with open(AUTOSTART, "w") as f:
                f.write(f"[Desktop Entry]\nType=Application\nName=Live Wallpaper Daemon\n")
                f.write(f"Exec=sh -c 'sleep 3 && {DAEMON}'\n")
                f.write("Terminal=false\nX-GNOME-Autostart-enabled=true\n")
        elif os.path.exists(AUTOSTART):
            os.remove(AUTOSTART)

        if self.cfg["video"] and os.path.exists(self.cfg["video"]):
            subprocess.Popen([DAEMON], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            GLib.timeout_add(400, self.check_status)

    def kill_wall(self, w):
        subprocess.call("killall xwinwrap 2>/dev/null; pkill -f 'mpv-livewal.sock' 2>/dev/null; pkill -f 'live-wallpaper-daemon.sh' 2>/dev/null; rm -f /tmp/mpv-livewal.sock", shell=True)
        self.check_status()

    def check_status(self):
        run = subprocess.call("pgrep -f 'mpv-livewal.sock' >/dev/null 2>&1", shell=True) == 0
        self.status.set_markup("<b>Status:</b> <span foreground='#4ade80'>Running</span>" if run else "<b>Status:</b> Stopped (0 MB RAM)")
        return True

win = WallpaperGUI()
win.connect("destroy", Gtk.main_quit)
win.show_all()
Gtk.main()
