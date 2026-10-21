"""
tests.test_all_themes_headless
==============================
Automated headless Cairo verification test across ALL registered themes in DesktopSuite.
Verifies:
1. All 26 themes are loaded and registered in REGISTRY.
2. Every theme cleanly renders draw_background, draw_clock, draw_date, and draw_visualizer
   under both Standard Scale mode and Independent Component Scales mode.
3. Zero exceptions, zero missing-font crashes, and zero Cairo errors.
"""

from __future__ import annotations

import sys
import unittest
import numpy as np
import cairo

from src.core.fonts import register_bundled_fonts
from src.themes.base import TimeData
from src.themes.registry import REGISTRY


class TestAllThemesHeadless(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # Ensure bundled fonts are registered
        registered = register_bundled_fonts()
        assert registered, "Failed to register bundled fonts"

    def test_theme_count(self):
        theme_names = REGISTRY.names()
        print(f"\n[INFO] Found {len(theme_names)} registered themes in REGISTRY:")
        for name in sorted(theme_names):
            print(f"  * {name}")
        self.assertGreaterEqual(len(theme_names), 26, "Expected at least 26 themes in REGISTRY")

    def test_all_themes_render_standard_and_independent(self):
        time_data = TimeData.now(is_24h=False)
        dummy_audio = np.linspace(0.1, 0.9, 64)

        theme_names = REGISTRY.names()
        for name in theme_names:
            theme = REGISTRY.get(name)
            self.assertIsNotNone(theme, f"Could not retrieve theme '{name}'")

            # ---------------------------------------------------------
            # Mode A: Standard Scale
            # ---------------------------------------------------------
            cfg_standard = {
                "scale": 1.0,
                "independent_scales": False,
                "clock_color": "#FFFFFF",
                "date_color": "#D0D0D0",
                "visualizer_color": "#00FFCC",
                "visualizer_intensity": 0.65,
                "background_opacity": 0.1,
            }

            surf_a = cairo.ImageSurface(cairo.FORMAT_ARGB32, 600, 300)
            ctx_a = cairo.Context(surf_a)

            try:
                theme.draw_background(ctx_a, 600, 300, cfg_standard)
                theme.draw_clock(ctx_a, 430, 100, cfg_standard, time_data)
                theme.draw_date(ctx_a, 430, 95, cfg_standard, time_data)
                theme.draw_visualizer(ctx_a, 430, 60, cfg_standard, dummy_audio)
            except Exception as e:
                self.fail(f"Theme '{name}' failed under Standard Scale: {e}")

            # ---------------------------------------------------------
            # Mode B: Independent Scales & Custom Decoupled Colors
            # ---------------------------------------------------------
            cfg_independent = {
                "scale": 1.25,
                "independent_scales": True,
                "clock_scale": 1.3,
                "date_scale": 0.85,
                "visualizer_scale": 1.15,
                "clock_color": "#FF2A85",
                "date_color": "#FFE600",
                "visualizer_color": "#00F0FF",
                "visualizer_intensity": 1.4,
                "background_opacity": 0.25,
            }

            surf_b = cairo.ImageSurface(cairo.FORMAT_ARGB32, 700, 400)
            ctx_b = cairo.Context(surf_b)

            try:
                theme.draw_background(ctx_b, 700, 400, cfg_independent)
                clk_w = int(float(getattr(theme, "clock_base_width", 430.0)) * 1.25 * 1.3)
                clk_h = int(float(getattr(theme, "clock_base_height", 100.0)) * 1.25 * 1.3)
                theme.draw_clock(ctx_b, clk_w, clk_h, cfg_independent, time_data)

                dt_w = int(float(getattr(theme, "date_base_width", 430.0)) * 1.25 * 0.85)
                dt_h = int(float(getattr(theme, "date_base_height", 95.0)) * 1.25 * 0.85)
                theme.draw_date(ctx_b, dt_w, dt_h, cfg_independent, time_data)

                vis_w = int(float(getattr(theme, "vis_base_width", 430.0)) * 1.25 * 1.15)
                vis_h = int(float(getattr(theme, "vis_base_height", 60.0)) * 1.25 * 1.15)
                theme.draw_visualizer(ctx_b, vis_w, vis_h, cfg_independent, dummy_audio)
            except Exception as e:
                self.fail(f"Theme '{name}' failed under Independent Scales: {e}")

            print(f"  [PASS] {name:<22} rendered cleanly in both modes.")


if __name__ == "__main__":
    unittest.main()
