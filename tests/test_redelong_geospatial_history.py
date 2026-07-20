from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from build_utils.build_redelong_globe_history import build


ROOT = Path(__file__).resolve().parents[1]


class RedelongGeospatialHistoryTest(unittest.TestCase):
    def test_committed_catchment_and_history_contract(self) -> None:
        zones = json.loads(
            (ROOT / "data/redelong/geospatial/redelong_analysis_zones.geojson").read_text(
                encoding="utf-8"
            )
        )
        included = [
            feature
            for feature in zones["features"]
            if feature["properties"]["include_in_catchment"]
        ]
        self.assertEqual(len(included), 6)
        self.assertAlmostEqual(
            sum(feature["properties"]["area_km2"] for feature in included),
            137.8,
            places=2,
        )
        tamatue = next(
            feature
            for feature in zones["features"]
            if feature["properties"]["name"] == "GPM Grid TamaTue"
        )
        self.assertFalse(tamatue["properties"]["include_in_catchment"])

        history = json.loads(
            (ROOT / "data/redelong/history/gpm_history_summary.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(sorted(history["sources"]), [f"gpm{i}" for i in range(1, 7)])
        for slug in history["sources"]:
            complete = [
                row
                for row in history["annual"]
                if row["location_slug"] == slug and row["complete"]
            ]
            self.assertGreaterEqual(len(complete), 24)

    def test_builder_creates_globe_and_home_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "index.html").write_text(
                "<html><head></head><body><a href='index.html'><span>FR</span></a></body></html>",
                encoding="utf-8",
            )
            (outputs / "operational_daily.csv").write_text(
                "date_wib,rain_mean_mm,rain_p10_mm,rain_p90_mm,model_count,data_status,hour_coverage_pct\n"
                "2026-07-17,12.5,5.0,24.0,6,cukup,100\n",
                encoding="utf-8",
            )

            build(outputs)

            globe = (outputs / "redelong_globe.html").read_text(encoding="utf-8")
            home = (outputs / "index.html").read_text(encoding="utf-8")
            self.assertIn("forecast-redelong-globe-history-v1", globe)
            self.assertIn("type:'globe'", globe)
            self.assertIn("12.5", globe)
            self.assertIn("site_network.html", home)
            self.assertIn("Globe Forecast Site", home)
            self.assertTrue((outputs / "gpm_daily_history.csv").is_file())

    def test_builder_upgrades_existing_redelong_only_globe_entry(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "index.html").write_text(
                '<html><head></head><body><a id="fr-globe-entry" href="redelong_globe.html" '
                'aria-label="Buka Globe 3D dan histori Forecast Redelong">'
                '<span>3D</span><b>Globe &amp; Histori<small>Area 137,80 km²</small></b></a>'
                '</body></html>',
                encoding="utf-8",
            )
            (outputs / "operational_daily.csv").write_text(
                "date_wib,rain_mean_mm,rain_p10_mm,rain_p90_mm,model_count,data_status,hour_coverage_pct\n"
                "2026-07-17,12.5,5.0,24.0,6,cukup,100\n",
                encoding="utf-8",
            )

            build(outputs)

            home = (outputs / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="fr-globe-entry" href="site_network.html"', home)
            self.assertIn("Globe Forecast Site", home)
            self.assertNotIn('href="redelong_globe.html"', home)


if __name__ == "__main__":
    unittest.main()
