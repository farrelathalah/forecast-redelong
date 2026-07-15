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


if __name__ == "__main__":
    unittest.main()
