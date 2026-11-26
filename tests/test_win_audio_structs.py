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
    import numpy as _np  # noqa: F401
    _HAS_NUMPY = True
except ImportError:
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

            for _ in range(3):
                surface.clear_transparent()
                ctx = surface.create_context()
                theme.draw_clock(ctx, 500, 120, cfg, td)
                theme.draw_visualizer(ctx, 500, 120, cfg, bars)

            blit_img = surface.get_blit_qimage()
            self.assertEqual(int(blit_img.bits()), surface._buf_addr)
            self.assertEqual(blit_img.pixelColor(0, 0).alpha(), 0)

            vis_px = blit_img.pixelColor(215, 108)
            self.assertGreater(vis_px.alpha(), 150)
            self.assertGreater(vis_px.red(), 150)
            self.assertEqual(vis_px.green(), 0)
            self.assertEqual(vis_px.blue(), 0)
            del blit_img
        finally:
            surface.dispose()


if __name__ == "__main__":
    unittest.main()
