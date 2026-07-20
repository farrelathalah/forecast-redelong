from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from build_utils.build_besai_hydrology import (
    add_engineering_scenario,
    fit_regulated_arx,
    forecast_rain,
)
from build_utils.build_redelong_discharge import prepare_calibration, rolling_hindcast


ROOT = Path(__file__).resolve().parents[1]


class BesaiHydrologyTest(unittest.TestCase):
    def test_rolling_rain_uses_multiple_engineering_points(self) -> None:
        start = pd.Timestamp("2026-07-17 06:30:00+07:00")
        rows = []
        points = [
            "pltm_besai_kemu",
            "pltm_besai_kemu_headpond",
            "pltm_besai_kemu_powerhouse",
            "pltm_besai_kemu_sumberjaya",
        ]
        for hour in pd.date_range("2026-07-17 07:00", periods=72, freq="h"):
            for source in ["ECMWF", "GFS", "ICON"]:
                for point_index, point in enumerate(points):
                    rows.append(
                        {
                            "location_slug": point,
                            "source_id": source,
                            "target_date": hour.date().isoformat(),
                            "target_jam": hour.strftime("%H:%M"),
                            "rain_mm": 1.0 + point_index / 10,
                        }
                    )
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            pd.DataFrame(rows).to_csv(outputs / "forecast_all_locations.csv", index=False)
            result = forecast_rain(outputs, start)
        self.assertEqual(set(result["lead_day"]), {1, 2, 3})
        self.assertTrue((result["model_count"] == 3).all())
        self.assertTrue((result["spatial_point_count"] == 4).all())
        self.assertTrue((result["rain_mean_mm"] > 24).all())

    def test_engineering_sources_are_versioned_and_trace_is_not_a_survey_polygon(self) -> None:
        data = ROOT / "data" / "sites" / "pltm_besai_kemu"
        engineering = json.loads((data / "engineering_parameters.json").read_text())
        structures = json.loads((data / "structures.geojson").read_text())
        self.assertAlmostEqual(engineering["catchment"]["area_km2"], 496.74, places=2)
        self.assertEqual(engineering["reference_revision"], "Review Studi Kelayakan, Januari 2020")
        self.assertEqual(len(engineering["source_documents"]), 3)
        catchment = next(
            feature for feature in structures["features"]
            if feature["properties"]["role"] == "catchment_reference"
        )
        self.assertIsNone(catchment["geometry"])
        self.assertEqual(catchment["properties"]["geometry_status"], "indicative_trace_published_separately")
        trace = json.loads((data / "besai_kemu_catchment.geojson").read_text())["features"][0]
        self.assertEqual(trace["properties"]["status"], "indicative_not_survey_boundary")
        self.assertEqual(trace["properties"]["role"], "fs_figure_area_constrained_trace")
        rainfall = pd.read_csv(data / "sumberjaya_monthly_rainfall_1979_2008.csv")
        self.assertEqual(len(rainfall), 29)
        self.assertNotIn(1999, set(rainfall["year"]))

    def test_constrained_arx_and_engineering_scenario_are_physical(self) -> None:
        dates = pd.date_range("2000-01-01", "2024-12-31", freq="D")
        rain = 4.0 + 3.0 * np.sin(np.arange(len(dates)) / 45.0)
        discharge = np.zeros(len(dates))
        discharge[0] = 18.0
        for index in range(1, len(dates)):
            discharge[index] = 0.8 + 0.94 * discharge[index - 1] + 0.08 * rain[index]
        rain_frame = pd.DataFrame({"date": dates.date.astype(str), "rain_mm": rain})
        discharge_frame = pd.DataFrame(
            {"date": dates.date.astype(str), "river_discharge": discharge}
        )
        issue = pd.Timestamp("2026-07-17 06:30:00+07:00")
        calibration = prepare_calibration(rain_frame, discharge_frame, issue)
        parameters, validation = fit_regulated_arx(calibration)
        self.assertGreaterEqual(parameters["recession_coefficient"], 0)
        self.assertLess(parameters["recession_coefficient"], 1)
        self.assertGreaterEqual(parameters["rainfall_response_m3s_per_mm"], 0)
        _, metrics = rolling_hindcast(validation, parameters)
        self.assertEqual(set(metrics["lead_day"]), {1, 2, 3})
        self.assertTrue((metrics["n_samples"] >= 365).all())

        engineering = json.loads(
            (ROOT / "data" / "sites" / "pltm_besai_kemu" / "engineering_parameters.json").read_text()
        )
        forecast = pd.DataFrame(
            [
                {
                    "valid_date": "2026-04-17",
                    "discharge_forecast_m3s": 30.0,
                },
                {
                    "valid_date": "2026-06-17",
                    "discharge_forecast_m3s": 10.0,
                },
            ]
        )
        scenario = add_engineering_scenario(forecast, engineering)
        self.assertEqual(float(scenario.iloc[0]["irrigation_reference_m3s"]), 6.03)
        self.assertEqual(float(scenario.iloc[1]["irrigation_reference_m3s"]), 3.0)
        self.assertLessEqual(float(scenario["indicative_plant_available_m3s"].max()), 22.0)
        self.assertTrue((scenario["indicative_plant_available_m3s"] >= 0).all())


if __name__ == "__main__":
    unittest.main()
