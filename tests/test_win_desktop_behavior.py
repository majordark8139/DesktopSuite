"""
tests.test_win_desktop_behavior
===============================
Unit tests for Windows desktop Z-order anchoring helpers (Aero Peek / Show Desktop),
WinWallpaperEngine command flags (--vo=gpu, --gpu-context=angle, no mpv 0.37+ --profile=fast),
and child/WorkerW window transparency styles.
"""

from __future__ import annotations

import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


class _FakeUser32ZOrder:
    """Minimal stateful Win32 user32 stub modeling a top -> bottom HWND Z-order list."""

    def __init__(self, z_order: list[int], children: dict[int, dict[str, int]], progman: int = 0) -> None:
        self.z_order = list(z_order)
        self.children = dict(children)
        self.progman = progman

    def FindWindowExW(self, parent: int, child_after: int, cls_name: str, _title) -> int:
        if parent == 0 and cls_name == "WorkerW":
            worker_hwnds = [h for h in self.z_order if self.children.get(h, {}).get("_class") == "WorkerW"]
            if child_after == 0:
                return worker_hwnds[0] if worker_hwnds else 0
            if child_after in worker_hwnds:
                idx = worker_hwnds.index(child_after)
                return worker_hwnds[idx + 1] if idx + 1 < len(worker_hwnds) else 0
            return 0
        if parent != 0 and child_after == 0:
            return self.children.get(parent, {}).get(cls_name, 0)
        return 0

    def FindWindowW(self, cls_name: str, _title) -> int:
        if cls_name == "Progman":
            return self.progman
        return 0

    def GetWindow(self, hwnd: int, cmd: int) -> int:
        if hwnd not in self.z_order:
            return 0
        idx = self.z_order.index(hwnd)
        if cmd == 2:  # GW_HWNDNEXT
            return self.z_order[idx + 1] if idx + 1 < len(self.z_order) else 0
        if cmd == 3:  # GW_HWNDPREV
            return self.z_order[idx - 1] if idx > 0 else 0
        return 0


class TestWinWallpaperEngineCommands(unittest.TestCase):
    def test_build_cmd_gpu_backends_mpv036_compatible_and_angle(self):
        from src.wallpaper.win_engine import WinWallpaperEngine

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("src.wallpaper.win_engine.get_log_dir", return_value=Path(tmp)):
                eng = WinWallpaperEngine()

        self.assertTrue(eng.stderr_log_path.endswith("mpv_stderr_latest.log"))

        for backend in ("gpu-d3d11", "gpu-angle", "gpu-gl-win"):
            cmd = eng._build_cmd(
                "mpv.exe", "DesktopSuiteBgMpv_test", "video.mp4",
                backend=backend, speed=1.0, volume=50, mute=True,
                fit_mode="fill", fps_limit="24", screen_w=1366, screen_h=768,
            )
            self.assertNotIn("--profile=fast", cmd, f"{backend} must omit mpv 0.37+ --profile=fast")
            self.assertIn("--vo=gpu", cmd)
            self.assertIn("--cursor-autohide=no", cmd)
            self.assertIn("--input-media-keys=no", cmd)
            self.assertIn("--msg-level=all=v", cmd)
            self.assertIn("--vf=fps=24", cmd)

        cmd_angle = eng._build_cmd(
            "mpv.exe", "t", "v.mp4", "gpu-angle",
            1.0, 50, True, "fill", "native", 1366, 768,
        )
        self.assertIn("--gpu-api=opengl", cmd_angle)
        self.assertIn("--gpu-context=angle", cmd_angle)
        self.assertIn("--hwdec=auto", cmd_angle)

        cmd_d3d = eng._build_cmd(
            "mpv.exe", "t", "v.mp4", "direct3d",
            1.0, 50, True, "fill", "native", 1366, 768,
        )
        self.assertIn("--vo=direct3d", cmd_d3d)
        self.assertIn("--hwdec=dxva2-copy", cmd_d3d)
        self.assertIn("--msg-level=all=warn,vo=v,hwdec=v", cmd_d3d)
        self.assertIn("--cursor-autohide=no", cmd_d3d)

    @unittest.skipUnless(sys.platform == "win32", "Windows style test")
    def test_apply_mpv_child_styles_enforces_transparent_noactivate_noparentnotify(self):
        from src.wallpaper import win_engine

        calls: dict[int, int] = {}
        fake_user32 = mock.MagicMock()
        fake_user32.GetWindowLongPtrW.side_effect = (
            lambda _h, idx: 0x14020000 | win_engine.WS_POPUP | win_engine.WS_CAPTION if idx == win_engine.GWL_STYLE else win_engine.WS_EX_APPWINDOW
        )
        fake_user32.SetWindowLongPtrW.side_effect = lambda _h, idx, val: calls.__setitem__(idx, val) or 1
        fake_kernel32 = mock.MagicMock()
        fake_kernel32.GetLastError.return_value = 0

        with mock.patch.object(win_engine, "user32", fake_user32), mock.patch.object(
            win_engine, "kernel32", fake_kernel32
        ):
            _os, new_st, _es, _oe, new_ex, _ee = win_engine.WinWallpaperEngine._apply_mpv_child_styles(
                0x1234, strip_visible=True
            )

        self.assertTrue(new_st & win_engine.WS_CHILD)
        self.assertFalse(new_st & (win_engine.WS_POPUP | win_engine.WS_CAPTION | win_engine.WS_MINIMIZEBOX | win_engine.WS_VISIBLE))
        self.assertTrue(new_ex & win_engine.WS_EX_TOOLWINDOW)
        self.assertTrue(new_ex & win_engine.WS_EX_NOACTIVATE)
        self.assertTrue(new_ex & win_engine.WS_EX_TRANSPARENT)
        self.assertTrue(new_ex & win_engine.WS_EX_NOPARENTNOTIFY)
        self.assertFalse(new_ex & win_engine.WS_EX_APPWINDOW)


try:
    import cairo as _cairo  # noqa: F401
    import numpy as _np  # noqa: F401
    from PyQt5.QtWidgets import QApplication  # noqa: F401
    _HAS_CANVAS_STACK = True
except Exception:
    _HAS_CANVAS_STACK = False


class TestWinDesktopCanvasZOrderHelpers(unittest.TestCase):
    @unittest.skipUnless(_HAS_CANVAS_STACK, "Requires PyQt5 + cairo + numpy")
    def test_zorder_anchor_and_insert_after(self):
        from src.canvas.win_window import (
            _compute_desktop_insert_after,
            _find_desktop_anchor_hwnd,
            _is_window_above,
        )

        # Typical Win7 Z-order: Taskbar(0x10) -> Chrome(0x20) -> Canvas(0x30) -> WorkerW#1(0x40) -> WorkerW#2(0x50) -> Progman(0x60)
        stub = _FakeUser32ZOrder(
            z_order=[0x10, 0x20, 0x30, 0x40, 0x50, 0x60],
            children={
                0x40: {"_class": "WorkerW", "SHELLDLL_DefView": 0x41},
                0x50: {"_class": "WorkerW"},
            },
            progman=0x60,
        )
        self.assertEqual(_find_desktop_anchor_hwnd(stub), 0x40)
        self.assertTrue(_is_window_above(0x30, 0x40, stub))
        self.assertFalse(_is_window_above(0x50, 0x40, stub))
        # Immediately above WorkerW#1 (0x40), skipping Canvas itself (0x30), lands after Chrome (0x20)
        self.assertEqual(_compute_desktop_insert_after(0x30, 0x40, stub), 0x20)

        # Fallback to Progman when no WorkerW hosts SHELLDLL_DefView
        stub_no_ww = _FakeUser32ZOrder(z_order=[0x10, 0x20, 0x60], children={}, progman=0x60)
        self.assertEqual(_find_desktop_anchor_hwnd(stub_no_ww), 0x60)


if __name__ == "__main__":
    unittest.main()
