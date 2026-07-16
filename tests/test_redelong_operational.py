from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from build_utils.build_redelong_operational import QUANTITATIVE_SOURCES, build


class OperationalBuilderTest(unittest.TestCase):
    def test_tamatue_and_bmkg_do_not_enter_catchment_rainfall(self) -> None:
        issue = pd.Timestamp("2026-07-13T06:30:00+07:00")
        valid_times = pd.date_range("2026-07-13 00:00", periods=96, freq="h")
        locations = [
            "plta_redelong",
            "gpm1",
            "gpm2",
            "gpm3",
            "gpm4",
            "gpm5",
            "gpm6",
            "gpm_grid_tamatue",
        ]
        source_rates = dict(zip(QUANTITATIVE_SOURCES, [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]))
        rows = []
        for valid in valid_times:
            for location in locations:
                for source, rate in source_rates.items():
                    rain = 100.0 if location == "gpm_grid_tamatue" else rate
                    rows.append(
                        {
                            "location_slug": location,
                            "target_date": valid.strftime("%Y-%m-%d"),
                            "target_jam": valid.strftime("%H:%M"),
                            "source_id": source,
                            "rain_mm": rain,
                            "suhu_C": 20.0,
                            "RH_%": 80.0,
                            "wind_kmh": 5.0,
                            "kategori": "Berawan",
                            "source_datetime": valid.strftime("%Y-%m-%d %H:%M:%S"),
                        }
                    )
                rows.append(
                    {
                        "location_slug": location,
                        "target_date": valid.strftime("%Y-%m-%d"),
                        "target_jam": valid.strftime("%H:%M"),
                        "source_id": "BMKG",
                        "rain_mm": 250.0,
                        "suhu_C": 20.0,
                        "RH_%": 80.0,
                        "wind_kmh": 5.0,
                        "kategori": "Hujan Lebat",
                        "source_datetime": (valid.floor("3h") + pd.Timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S"),
                    }
                )

        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            pd.DataFrame(rows).to_csv(outputs / "forecast_all_locations.csv", index=False)
            (outputs / "forecast_batch_summary.json").write_text(
                json.dumps({"generated_at": issue.isoformat()}), encoding="utf-8"
            )
            (outputs / "index.html").write_text("legacy", encoding="utf-8")
            plta_dir = outputs / "plta_redelong"
            plta_dir.mkdir()
            (plta_dir / "redelong_3day.html").write_text("interactive-three-day", encoding="utf-8")

            result = build(outputs)

            windows = pd.read_csv(outputs / "operational_windows.csv")
            next_24h = windows.loc[windows["horizon_hours"] == 24].iloc[0]
            expected = sum(source_rates.values()) / len(source_rates) * 24
            self.assertAlmostEqual(next_24h["rain_mean_mm"], expected, places=6)
            self.assertAlmostEqual(next_24h["provisional_area_km2"], 137.80034533369645, places=6)
            self.assertEqual(int(next_24h["model_count"]), 6)

            point_24h = pd.read_csv(outputs / "operational_per_point_24h.csv")
            tama = point_24h.loc[point_24h["location_slug"] == "gpm_grid_tamatue"].iloc[0]
            self.assertEqual(tama["rain_mean_mm"], 2400.0)

            status = pd.read_csv(outputs / "operational_source_status.csv")
            self.assertEqual(status.loc[status["source_id"] == "KMA", "qc_status"].iloc[0], "nonaktif")
            self.assertEqual(status.loc[status["source_id"] == "METNO", "qc_status"].iloc[0], "nonaktif")
            bmkg = pd.read_csv(outputs / "bmkg_guidance.csv")
            self.assertEqual(pd.Timestamp(bmkg.iloc[0]["valid_time_wib"]), pd.Timestamp("2026-07-13 08:00:00+07:00"))
            self.assertEqual(bmkg.iloc[0]["source_datetime"], "2026-07-13 08:00:00")
            spatial = json.loads((outputs / "redelong_operational_points.geojson").read_text(encoding="utf-8"))
            tama_feature = next(
                feature
                for feature in spatial["features"]
                if feature["properties"]["location_slug"] == "gpm_grid_tamatue"
            )
            self.assertEqual(tama_feature["properties"]["operational_role"], "external_comparison")
            self.assertFalse(tama_feature["properties"]["include_in_catchment"])
            dashboard = (outputs / "redelong_operational.html").read_text(encoding="utf-8")
            self.assertIn("tidak dimasukkan", dashboard)
            self.assertIn("Ringkasan Operasional DAS", dashboard)
            self.assertIn("class='rain-chart'", dashboard)
            self.assertNotRegex(dashboard.lower(), r"\bnan\b")
            self.assertEqual((outputs / "index.html").read_text(encoding="utf-8"), "legacy")
            self.assertEqual(
                (outputs / "plta_redelong" / "redelong_3day.html").read_text(encoding="utf-8"),
                "interactive-three-day",
            )
            self.assertTrue(Path(result["archive_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
