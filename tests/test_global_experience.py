from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from build_utils.apply_global_experience import (
    EXPERIENCE_MARKER,
    apply_all,
    apply_to_html,
    normalize_public_separators,
)


class GlobalExperienceTest(unittest.TestCase):
    def test_nested_monogram_spins_and_generic_page_gets_rain(self) -> None:
        source = """<!doctype html><html><head><title>X</title></head><body>
        <a class="brand" href="index.html"><span class="mark">FR</span><b>Forecast Redelong</b></a>
        </body></html>"""
        result, brands, rain_mode = apply_to_html(source)

        self.assertEqual(brands, 1)
        self.assertEqual(rain_mode, "global")
        self.assertIn(EXPERIENCE_MARKER, result)
        self.assertIn('data-fr-global-brand="true"', result)
        self.assertIn('data-fr-spin-target="true"', result)
        self.assertIn('id="fr-global-rain"', result)
        self.assertIn("prefers-reduced-motion", result)

    def test_plain_map_button_is_the_spin_target(self) -> None:
        source = """<html><head></head><body>
        <a class="map-brand" href="../index.html">FR</a><canvas id="particle-canvas"></canvas>
        </body></html>"""
        result, brands, rain_mode = apply_to_html(source)

        self.assertEqual(brands, 1)
        self.assertEqual(rain_mode, "native+global")
        self.assertRegex(
            result,
            r'<a[^>]+data-fr-global-brand="true"[^>]+data-fr-spin-target="true"[^>]*>FR</a>',
        )
        self.assertIn('id="fr-global-rain"', result)
        self.assertIn("rain=native+global", result)

    def test_apply_all_requires_fr_and_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            page = outputs / "index.html"
            page.write_text(
                '<html><head></head><body><a href="index.html"><span>FR</span> Home</a></body></html>',
                encoding="utf-8",
            )
            first = apply_all(outputs)
            first_content = page.read_text(encoding="utf-8")
            second = apply_all(outputs)
            second_content = page.read_text(encoding="utf-8")

            self.assertEqual(first["pages"], 1)
            self.assertEqual(second["pages"], 1)
            self.assertEqual(first_content, second_content)

    def test_middle_dot_separators_are_replaced_with_commas(self) -> None:
        source = "Hari ini • Kamis · 16 Juli &middot; WIB &bull; selesai"
        result, count = normalize_public_separators(source)

        self.assertEqual(count, 4)
        self.assertEqual(result, "Hari ini, Kamis, 16 Juli, WIB, selesai")


if __name__ == "__main__":
    unittest.main()
