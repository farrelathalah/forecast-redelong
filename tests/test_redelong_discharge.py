from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import pandas as pd

from build_utils.build_redelong_discharge import (
    fit_arx,
    forecast_rain_windows,
    make_discharge_forecast,
    evaluate_archived_forecasts,
    rolling_hindcast,
)
from build_utils.fetch_glofas_discharge import _daily_frame
from build_utils.validate_redelong_publish import check_discharge_products


class RedelongDischargeTest(unittest.TestCase):
    def _calibration(self) -> pd.DataFrame:
        dates = pd.date_range("2000-01-01", "2025-12-31", freq="D")
        rng = np.random.default_rng(42)
        rain = rng.gamma(1.2, 5.0, len(dates))
        discharge = np.zeros(len(dates))
        discharge[0] = 20.0
        for index in range(1, len(dates)):
            discharge[index] = max(0.0, 0.5 + 0.94 * discharge[index - 1] + 0.15 * rain[index])
        return pd.DataFrame(
            {
                "date": dates,
                "rain_mm": rain,
                "river_discharge": discharge,
                "previous_discharge": np.r_[np.nan, discharge[:-1]],
            }
        ).dropna()

    def test_fit_and_hindcast_keep_leads_separate(self) -> None:
        parameters, _, validation = fit_arx(self._calibration())
        pairs, metrics = rolling_hindcast(validation, parameters)
        self.assertEqual(set(metrics["lead_day"]), {1, 2, 3})
        self.assertGreater(len(pairs), 7000)
        self.assertTrue((metrics["nse"] > 0.99).all())
        self.assertGreaterEqual(parameters["recession_coefficient"], 0)
        self.assertGreaterEqual(parameters["rainfall_response_m3s_per_mm"], 0)

    def test_forecast_windows_use_rolling_24_hour_periods(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            start = pd.Timestamp("2026-07-17 07:00:00+07:00")
            rows = []
            for source, rain in [("ECMWF", 1.0), ("GFS", 2.0), ("ICON", 3.0)]:
                for stamp in pd.date_range(start, periods=72, freq="h"):
                    rows.append({"valid_time_wib": stamp.isoformat(), "source_id": source, "rain_mm": rain})
            pd.DataFrame(rows).to_csv(outputs / "operational_source_hourly.csv", index=False)
            windows = forecast_rain_windows(outputs, start)
            self.assertEqual(list(windows["lead_day"]), [1, 2, 3])
            self.assertTrue((windows["rain_mean_mm"] == 48.0).all())
            self.assertTrue((windows["model_count"] == 3).all())

    def test_forecast_is_initialized_from_previous_glofas_day(self) -> None:
        start = pd.Timestamp("2026-07-17 07:00:00+07:00")
        rain = pd.DataFrame(
            [
                {"lead_day": lead, "window_start_wib": "x", "window_end_wib": "y", "rain_mean_mm": 10.0, "rain_p10_mm": 5.0, "rain_p90_mm": 15.0, "model_count": 3, "model_list": "a,b,c"}
                for lead in (1, 2, 3)
            ]
        )
        current = pd.DataFrame(
            {
                "date": ["2026-07-16", "2026-07-17", "2026-07-18", "2026-07-19"],
                "river_discharge": [20.0, 21.0, 22.0, 23.0],
                "river_discharge_mean": [20.0, 21.0, 22.0, 23.0],
                "river_discharge_p25": [19.0, 20.0, 21.0, 22.0],
                "river_discharge_p75": [21.0, 22.0, 23.0, 24.0],
            }
        )
        parameters = {"intercept_m3s": 0.5, "recession_coefficient": 0.9, "rainfall_response_m3s_per_mm": 0.1}
        metrics = pd.DataFrame([{"lead_day": lead, "rmse_m3s": 1.0} for lead in (1, 2, 3)])
        forecast = make_discharge_forecast(rain, current, start, parameters, metrics)
        self.assertTrue((forecast["initial_discharge_proxy_m3s"] == 20.0).all())
        self.assertAlmostEqual(float(forecast.iloc[0]["discharge_forecast_m3s"]), 19.5)
        self.assertTrue((forecast["discharge_scenario_low_m3s"] <= forecast["discharge_forecast_m3s"]).all())
        self.assertTrue((forecast["discharge_forecast_m3s"] <= forecast["discharge_scenario_high_m3s"]).all())

    def test_glofas_payload_is_explicitly_gridded(self) -> None:
        frame = _daily_frame(
            {"daily": {"time": ["2026-07-17"], "river_discharge": [12.3]}},
            ["river_discharge"],
        )
        self.assertEqual(float(frame.iloc[0]["river_discharge"]), 12.3)

    def test_end_to_end_validation_waits_for_mature_archive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            history = pd.DataFrame({"date": ["2026-07-15"], "river_discharge": [10.0]})
            current = pd.DataFrame({"date": ["2026-07-16"], "river_discharge": [11.0]})
            pairs, metrics, status = evaluate_archived_forecasts(
                outputs, history, current, pd.Timestamp("2026-07-17 06:30:00+07:00")
            )
            self.assertTrue(pairs.empty)
            self.assertTrue(metrics.empty)
            self.assertEqual(status, "collecting_archive")

    def test_publish_gate_rejects_field_accuracy_claim(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "hydrology").mkdir()
            forecast = [
                {"lead_day": lead, "discharge_scenario_low_m3s": 1, "discharge_forecast_m3s": 2, "discharge_scenario_high_m3s": 3}
                for lead in (1, 2, 3)
            ]
            validation = [{"lead_day": lead, "n_samples": 1000} for lead in (1, 2, 3)]
            (outputs / "redelong_discharge.json").write_text(
                json.dumps({"status": "provisional_proxy_calibrated", "can_claim_field_accuracy": True, "forecast": forecast, "validation": validation}),
                encoding="utf-8",
            )
            for name in ["redelong_discharge_forecast.csv", "redelong_discharge_validation.csv", "redelong_discharge_hindcast_pairs.csv"]:
                (outputs / name).write_text("x\n", encoding="utf-8")
            for name in [
                "redelong_discharge_end_to_end_pairs.csv",
                "redelong_discharge_end_to_end_validation.csv",
            ]:
                (outputs / name).write_text("lead_day,n_samples\n", encoding="utf-8")
            (outputs / "redelong_discharge.html").write_text("forecast-redelong-discharge-v1 Belum field-calibrated", encoding="utf-8")
            (outputs / "redelong_operational.html").write_text("redelong_discharge.html", encoding="utf-8")
            (outputs / "hydrology" / "glofas_discharge_metadata.json").write_text(
                json.dumps({"observation_type": "simulated_gridded_discharge_proxy", "history_rows": 9000}), encoding="utf-8"
            )
            errors: list[str] = []
            check_discharge_products(outputs, errors, {})
            self.assertTrue(any("akurasi lapangan" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
