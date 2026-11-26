"""
tests.test_win_audio_structs
============================
Verifies packed C memory layout for Win32 WAVEFORMATEX / WAVEFORMATEXTENSIBLE
and font GDI ctypes scoping (no UnboundLocalError).
"""

from __future__ import annotations

import ctypes
from pathlib import Path
import sys
import unittest

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    np = None
    _HAS_NUMPY = False


class TestWinAudioStructsAndFonts(unittest.TestCase):
    @unittest.skipUnless(sys.platform == "win32" and _HAS_NUMPY, "Requires win32 + numpy")
    def test_waveformatextensible_packed_offsets(self):
        from src.canvas import win_audio

        self.assertEqual(ctypes.sizeof(win_audio.WAVEFORMATEX), 18)
        self.assertEqual(ctypes.sizeof(win_audio.WAVEFORMATEXTENSIBLE), 40)
        self.assertEqual(win_audio.WAVEFORMATEXTENSIBLE.Samples.offset, 18)
        self.assertEqual(win_audio.WAVEFORMATEXTENSIBLE.dwChannelMask.offset, 20)
        self.assertEqual(win_audio.WAVEFORMATEXTENSIBLE.SubFormat.offset, 24)

        # Simulate hardware 32-bit 48kHz stereo IEEE_FLOAT WAVEFORMATEXTENSIBLE bytes
        raw = bytearray(40)
        raw[0:2] = (0xFFFE).to_bytes(2, "little")     # wFormatTag
        raw[2:4] = (2).to_bytes(2, "little")          # nChannels
        raw[4:8] = (48000).to_bytes(4, "little")      # nSamplesPerSec
        raw[8:12] = (384000).to_bytes(4, "little")    # nAvgBytesPerSec
        raw[12:14] = (8).to_bytes(2, "little")        # nBlockAlign
        raw[14:16] = (32).to_bytes(2, "little")       # wBitsPerSample
        raw[16:18] = (22).to_bytes(2, "little")       # cbSize
        raw[18:20] = (32).to_bytes(2, "little")       # Samples.wValidBitsPerSample
        raw[20:24] = (3).to_bytes(4, "little")        # dwChannelMask (stereo)
        raw[24:40] = bytes(win_audio.KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)

        ext = win_audio.WAVEFORMATEXTENSIBLE.from_buffer_copy(raw)
        self.assertEqual(ext.Format.wFormatTag, 0xFFFE)
        self.assertEqual(ext.Format.cbSize, 22)
        self.assertEqual(ext.Samples, 32)
        self.assertEqual(ext.dwChannelMask, 3)
        self.assertEqual(ext.SubFormat, win_audio.KSDATAFORMAT_SUBTYPE_IEEE_FLOAT)


try:
    import cairo as _cairo  # noqa: F401
    from PyQt5.QtGui import QImage, QPainter
    from PyQt5.QtWidgets import QApplication
    _HAS_CAIRO_QT = True
except Exception:
    _HAS_CAIRO_QT = False


class TestSharedCairoQtSurface(unittest.TestCase):
    @unittest.skipUnless(
        sys.platform == "win32" and _HAS_NUMPY and _HAS_CAIRO_QT,
        "Requires win32 + PyQt5 + cairo + numpy",
    )
    def test_shared_surface_preserves_cairo_strokes_across_clears(self):
        from src.core.win7_font_engine import BundledFontRegistry, SharedCairoQtSurface
        from src.themes.base import TimeData
        from src.themes.registry import OriginalCursiveTheme

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        surface = SharedCairoQtSurface(500, 120, BundledFontRegistry())
        try:
            theme = OriginalCursiveTheme()
            cfg = {
                "clock_color": "#FF0000",
                "date_color": "#D0D0D0",
                "visualizer_color": "#FF0000",
                "scale": 1.0,
                "visualizer_intensity": 0.65,
            }
            td = TimeData(is_24h=False)
            bars = np.ones(27, dtype=np.float32)

            def _render_once() -> None:
                surface.clear_transparent()
                ctx = surface.create_context()
                theme.draw_clock(ctx, 500, 120, cfg, td)
                theme.draw_visualizer(ctx, 500, 120, cfg, bars)

            for _ in range(3):
                _render_once()

            blit_img = surface.get_blit_qimage()
            self.assertEqual(int(blit_img.constBits()), surface._buf_addr)
            self.assertEqual(blit_img.pixelColor(0, 0).alpha(), 0)

            vis_px = blit_img.pixelColor(215, 108)
            self.assertGreater(vis_px.alpha(), 150)
            self.assertGreater(vis_px.red(), 150)
            self.assertEqual(vis_px.green(), 0)
            self.assertEqual(vis_px.blue(), 0)

            # Simulate WinCanvasWindow.paintEvent blitting onto a Qt surface, then re-render
            dest = QImage(500, 120, QImage.Format_ARGB32_Premultiplied)
            dest.fill(0)
            painter = QPainter(dest)
            try:
                painter.drawImage(0, 0, blit_img)
            finally:
                painter.end()
            del blit_img

            blitted_px = dest.pixelColor(215, 108)
            self.assertGreater(blitted_px.alpha(), 150)
            self.assertGreater(blitted_px.red(), 150)

            for _ in range(3):
                _render_once()
            blit_img2 = surface.get_blit_qimage()
            self.assertEqual(int(blit_img2.constBits()), surface._buf_addr)
            vis_px2 = blit_img2.pixelColor(215, 108)
            self.assertGreater(vis_px2.alpha(), 150)
            self.assertGreater(vis_px2.red(), 150)
            del blit_img2

            # Verify cached QFontMetricsF lookup + partial surface rect copy
            reg = surface.font_registry
            p1 = reg.resolve_qfont_with_metrics("Bebas Neue", 0, 0, 24.0)
            p2 = reg.resolve_qfont_with_metrics("Bebas Neue", 0, 0, 24.0)
            self.assertIs(p1, p2)
        finally:
            surface.dispose()

    @unittest.skipUnless(
        sys.platform == "win32" and _HAS_NUMPY and _HAS_CAIRO_QT,
        "Requires win32 + PyQt5 + cairo + numpy",
    )
    def test_win_canvas_static_cache_and_app_icon(self):
        from src.canvas.win_window import WinDesktopCanvasWindow
        from src.themes.registry import OriginalCursiveTheme
        from src.windows.app import load_app_icon

        app = QApplication.instance() or QApplication([])
        self.assertIsNotNone(app)

        icon = load_app_icon()
        self.assertFalse(icon.isNull())
        self.assertGreaterEqual(len(icon.availableSizes()), 3)

        class _MemCfg:
            def __init__(self) -> None:
                self.data = {
                    "canvas.active_theme": "Original Cursive",
                    "canvas.clock_color": "#FF0000",
                    "canvas.date_color": "#D0D0D0",
                    "canvas.visualizer_color": "#FF0000",
                    "canvas.visualizer_intensity": 0.65,
                    "canvas.scale": 1.0,
                }

            def get(self, key: str, default=None):
                return self.data.get(key, default)

            def set(self, key: str, val) -> None:
                self.data[key] = val

            def save(self) -> None:
                pass

        class _DummyAudio:
            def __init__(self) -> None:
                import threading
                self.lock = threading.Lock()
                self.bars = np.zeros(27, dtype=np.float32)

        audio = _DummyAudio()
        win = WinDesktopCanvasWindow(_MemCfg(), OriginalCursiveTheme(), audio_stream=audio)
        try:
            win._timer.stop()
            win._on_tick()
            self.assertEqual(win._static_rebuilds, 1)
            win.repaint()
            first_paints = win._paint_count

            # Idle & silent tick should skip full repaints and never rebuild static text
            win._on_tick()
            self.assertEqual(win._static_rebuilds, 1)

            # Audio bars arriving should animate visualizer without rebuilding static text
            with audio.lock:
                audio.bars[:] = 1.0
            win._on_tick()
            self.assertEqual(win._static_rebuilds, 1)
            self.assertFalse(win._vis_dirty_rect.isEmpty())
            win.repaint(win._vis_dirty_rect)
            self.assertGreater(win._paint_count, first_paints)
            self.assertEqual(win._static_rebuilds, 1)
        finally:
            win.stop()
            app.processEvents()


if __name__ == "__main__":
    unittest.main()
