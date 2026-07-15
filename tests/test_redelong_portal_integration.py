from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import build_utils.make_forecast_redelong_site as site
import build_utils.make_forecast_redelong_overview as overview
import redelong_portal_rebuild as portal


class RedelongPortalIntegrationTest(unittest.TestCase):
    def test_portal_keeps_interactivity_and_marks_tamatue_as_comparison(self) -> None:
        locations = {
            "plta_redelong": {
                "location_name": "PLTA Redelong",
                "latitude": 4.748139,
                "longitude": 96.977344,
                "operational_role": "outlet_reference",
                "include_in_catchment": False,
                "spatial_note": "Titik referensi PLTA.",
            },
            "gpm1": {
                "location_name": "GPM1",
                "latitude": 4.81572,
                "longitude": 96.877105,
                "operational_role": "provisional_catchment",
                "include_in_catchment": True,
                "spatial_note": "Area analisis provisional.",
            },
            "gpm_grid_tamatue": {
                "location_name": "GPM Grid TamaTue",
                "latitude": 4.649903,
                "longitude": 96.850179,
                "operational_role": "external_comparison",
                "include_in_catchment": False,
                "spatial_note": "Hanya titik pembanding.",
            },
        }
        rows = [
            {"location_slug": slug, "source_id": "ECMWF", "rain_mm": 2.0}
            for slug in locations
        ]

        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            for slug in locations:
                (outputs / slug).mkdir()

            with patch.object(site, "OUTPUTS", outputs):
                frame = pd.DataFrame(rows)
                site.make_index(locations, frame, "location_slug", "rain_mm", "source_id")
                site.make_rain_map(locations, frame, "location_slug", "rain_mm", "source_id")

            portal = (outputs / "index.html").read_text(encoding="utf-8")
            self.assertIn("Prakiraan Interaktif", portal)
            self.assertIn("redelong_operational.html", portal)
            self.assertIn("Pembanding eksternal", portal)
            self.assertIn("Masuk Agregasi Catchment</div><div class=\"value\">1", portal)

            rain_map = (outputs / "redelong_rain_map.html").read_text(encoding="utf-8")
            self.assertIn("TamaTue · pembanding eksternal", rain_map)
            self.assertIn("comparisonLayer", rain_map)
            self.assertIn("if (!isExternal) bounds.push", rain_map)
            self.assertIn("Agregasi catchment", rain_map)

    def test_fresh_interactive_page_replaces_stale_alias(self) -> None:
        script = Path(__file__).resolve().parents[1] / "build_utils" / "patch_redelong_branding.py"
        with tempfile.TemporaryDirectory() as tmp:
            workdir = Path(tmp)
            location = workdir / "outputs" / "plta_redelong"
            location.mkdir(parents=True)
            (location / "langit_3day.html").write_text(
                "<html>fresh interactive LANGIT page<script>window.LANGIT_CONFIG = {}; const config = window.LANGIT_CONFIG || {};</script></html>", encoding="utf-8"
            )
            (location / "redelong_3day.html").write_text(
                "<html>stale blank page</html>", encoding="utf-8"
            )

            result = subprocess.run(
                [sys.executable, str(script)],
                cwd=workdir,
                check=False,
                capture_output=True,
                text=True,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            target = location / "redelong_3day.html"
            target_text = target.read_text(encoding="utf-8")
            self.assertIn("fresh interactive Forecast Redelong page", target_text)
            self.assertIn("window.REDELONG_CONFIG", target_text)
            self.assertNotIn("window.Forecast Redelong_CONFIG", target_text)
            self.assertNotIn("window.LANGIT_CONFIG", target_text)
            self.assertFalse((location / "langit_3day.html").exists())

    def test_portal_uses_actual_dates_hours_and_ensemble_quality(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location = Path(tmp) / "plta_redelong"
            location.mkdir()
            for day in pd.date_range("2026-07-13", periods=3, freq="D"):
                rows = []
                for hour in range(24):
                    rows.append(
                        {
                            "target_date": day.strftime("%Y-%m-%d"),
                            "jam": f"{hour:02d}:00",
                            "temp_p50": 20.0,
                            "rh_p50": 85.0,
                            "prob_rain": 30.0,
                            "wind_p50": 5.0,
                            "rain_threat_score": 30.0,
                            "dominant_category": "Berawan",
                            "sources_used": 7,
                            "coverage_fraction": 1.0,
                            "trust_level": "HIGHLY_TRUSTED",
                            "operational_status": "GREEN",
                        }
                    )
                pd.DataFrame(rows).to_csv(
                    location / f"sentinel_x_{day.strftime('%Y%m%d')}.csv", index=False
                )

            api = portal.load_location_api(
                location,
                {"slug": "plta_redelong", "location_name": "PLTA Redelong"},
            )

            self.assertEqual([day["date_iso"] for day in api["days"]], ["2026-07-13", "2026-07-14", "2026-07-15"])
            for day in api["days"]:
                self.assertEqual(len(day["hours"]), 24)
                self.assertEqual(day["valid_points"], 24)
                self.assertNotEqual(day["risk_class"], "limited")
                self.assertEqual(day["hours"][23]["hour"], "23:00")

    def test_portal_never_marks_single_source_day_safe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            location = Path(tmp) / "plta_redelong"
            location.mkdir()
            rows = [
                {
                    "target_date": "2026-07-13",
                    "jam": f"{hour:02d}:00",
                    "temp_p50": 20.0,
                    "rh_p50": 85.0,
                    "prob_rain": 0.0,
                    "sources_used": 1,
                    "coverage_fraction": 0.143,
                    "trust_level": "DO_NOT_TRUST",
                    "operational_status": "BLACK",
                }
                for hour in range(24)
            ]
            pd.DataFrame(rows).to_csv(location / "sentinel_x_20260713.csv", index=False)

            api = portal.load_location_api(
                location,
                {"slug": "plta_redelong", "location_name": "PLTA Redelong"},
            )

            self.assertEqual(api["today"]["date_iso"], "2026-07-13")
            self.assertEqual(api["today"]["valid_points"], 0)
            self.assertEqual(api["today"]["risk_class"], "limited")
            self.assertEqual(api["today"]["risk_label"], "Data terbatas")
            self.assertTrue(all(hour["risk_class"] == "limited" for hour in api["today"]["hours"]))

    def test_overview_matches_current_source_and_spatial_semantics(self) -> None:
        enhancer = Path(__file__).resolve().parents[1] / "build_utils" / "enhance_forecast_redelong_overview.py"
        locations = {
            "locations": {
                "plta_redelong": {
                    "location_name": "PLTA Redelong",
                    "operational_role": "outlet_reference",
                    "include_in_catchment": False,
                },
                "gpm1": {
                    "location_name": "GPM1",
                    "operational_role": "provisional_catchment",
                    "include_in_catchment": True,
                },
                "gpm_grid_tamatue": {
                    "location_name": "GPM Grid TamaTue",
                    "operational_role": "external_comparison",
                    "include_in_catchment": False,
                },
            }
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / "outputs"
            outputs.mkdir()
            locations_path = root / "locations.json"
            locations_path.write_text(json.dumps(locations), encoding="utf-8")
            pd.DataFrame(
                [{"source_id": "ECMWF", "success": True}, {"source_id": "BMKG", "success": True}]
            ).to_csv(outputs / "source_status_all_locations.csv", index=False)

            with patch.object(overview, "OUTPUTS", outputs), patch.object(
                overview, "LOCATIONS_JSON", locations_path
            ):
                overview.main()

            result = subprocess.run(
                [sys.executable, str(enhancer)],
                cwd=root,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            html = (outputs / "redelong_overview.html").read_text(encoding="utf-8")
            self.assertIn("BMKG aktif · kategoris", html)
            self.assertIn("TamaTue dipertahankan hanya sebagai pembanding eksternal", html)
            self.assertIn("Volume hujan bruto yang ditampilkan bukan prediksi debit", html)
            self.assertNotIn("BMKG belum aktif", html)


if __name__ == "__main__":
    unittest.main()
