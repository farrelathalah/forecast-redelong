from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GlobalBrandHeaderTest(unittest.TestCase):
    def test_public_generators_use_fr_monogram(self):
        portal = (ROOT / "redelong_portal_rebuild.py").read_text(encoding="utf-8")
        site = (ROOT / "build_utils/make_forecast_redelong_site.py").read_text(encoding="utf-8")
        overview = (ROOT / "build_utils/make_forecast_redelong_overview.py").read_text(encoding="utf-8")
        evaluation = (ROOT / "build_utils/evaluate_forecast_accuracy.py").read_text(encoding="utf-8")
        operational = (ROOT / "build_utils/build_redelong_operational.py").read_text(encoding="utf-8")

        self.assertIn('class="nav-logo" aria-hidden="true">FR</span>', portal)
        self.assertGreaterEqual(site.count(">FR</div>"), 2)
        self.assertIn(">FR</div>", overview)
        self.assertGreaterEqual(evaluation.count(">FR</span>"), 2)
        self.assertIn('class="brand-mark">FR</span>', operational)

    def test_public_subtitles_are_page_specific(self):
        portal = (ROOT / "redelong_portal_rebuild.py").read_text(encoding="utf-8")
        site = (ROOT / "build_utils/make_forecast_redelong_site.py").read_text(encoding="utf-8")
        overview = (ROOT / "build_utils/make_forecast_redelong_overview.py").read_text(encoding="utf-8")
        evaluation = (ROOT / "build_utils/evaluate_forecast_accuracy.py").read_text(encoding="utf-8")
        operational = (ROOT / "build_utils/build_redelong_operational.py").read_text(encoding="utf-8")

        self.assertIn('subtitle = "Monitoring Hujan PLTA Redelong"', portal)
        self.assertIn("Monitoring Hujan PLTA Redelong", site)
        self.assertIn("Overview Teknis", overview)
        self.assertIn("Evaluasi Forecast", evaluation)
        self.assertIn("Ringkasan Operasional DAS", operational)

    def test_fullscreen_maps_and_validation_status_have_home_linked_fr(self):
        portal = (ROOT / "redelong_portal_rebuild.py").read_text(encoding="utf-8")
        operational = (ROOT / "build_utils/build_redelong_operational.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('class="map-brand" data-fr-brand="true"', portal)
        self.assertIn('"../index.html",', portal)
        self.assertIn('data-fr-brand="true" href="index.html"', operational)
        self.assertIn("Forecast Redelong</b><small>Status Validasi", operational)

    def test_obsolete_anemos_sentinel_pages_are_not_published(self):
        patcher = (ROOT / "build_utils/patch_redelong_branding.py").read_text(
            encoding="utf-8"
        )

        self.assertIn('"Forecast_x_report.html"', patcher)
        self.assertIn('"command_center_Forecast_x.html"', patcher)
        self.assertIn("removed obsolete public HTML", patcher)


if __name__ == "__main__":
    unittest.main()
