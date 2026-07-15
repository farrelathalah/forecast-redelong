from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import pandas as pd

from build_utils.evaluate_forecast_accuracy import (
    QUANTITATIVE_SOURCES,
    build_daily_forecast,
    main,
)


class RedelongEvaluationTest(unittest.TestCase):
    def _forecast_rows(self) -> list[dict]:
        rows: list[dict] = []
        rates = dict(zip(sorted(QUANTITATIVE_SOURCES), [0.5, 0.8, 1.0, 1.2, 1.5, 2.0]))
        for valid in pd.date_range("2026-07-15 00:00", periods=24, freq="h"):
            for source, rate in rates.items():
                rows.append(
                    {
                        "location_slug": "plta_redelong",
                        "target_date": valid.strftime("%Y-%m-%d"),
                        "target_jam": valid.strftime("%H:%M"),
                        "source_id": source,
                        "rain_mm": rate,
                    }
                )
            rows.append(
                {
                    "location_slug": "plta_redelong",
                    "target_date": valid.strftime("%Y-%m-%d"),
                    "target_jam": valid.strftime("%H:%M"),
                    "source_id": "BMKG",
                    "rain_mm": 100.0,
                }
            )
        # A sparse source must not become a daily member.
        for valid in pd.date_range("2026-07-15 00:00", periods=5, freq="h"):
            rows.append(
                {
                    "location_slug": "plta_redelong",
                    "target_date": valid.strftime("%Y-%m-%d"),
                    "target_jam": valid.strftime("%H:%M"),
                    "source_id": "KMA",
                    "rain_mm": 250.0,
                }
            )
        return rows

    def test_daily_forecast_sums_time_before_model_consensus(self) -> None:
        frame = pd.DataFrame(self._forecast_rows())
        daily, message = build_daily_forecast(frame)

        self.assertIsNone(message)
        self.assertEqual(len(daily), 1)
        row = daily.iloc[0]
        expected_mean = sum([0.5, 0.8, 1.0, 1.2, 1.5, 2.0]) / 6 * 24
        self.assertAlmostEqual(row["rain_forecast_mean"], expected_mean)
        self.assertEqual(int(row["forecast_models"]), 6)
        self.assertEqual(int(row["minimum_hours_per_model"]), 24)
        self.assertLess(row["rain_forecast_max"], 100.0)

    def test_evaluator_writes_metrics_only_for_comparable_daily_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / "outputs"
            outputs.mkdir()
            forecast = outputs / "forecast_all_locations.csv"
            observation = root / "rain_observed_daily.csv"
            proxy = root / "rain_proxy_daily.csv"

            pd.DataFrame(self._forecast_rows()).to_csv(forecast, index=False)
            pd.DataFrame(
                [
                    {
                        "date": "2026-07-15",
                        "location_slug": "plta_redelong",
                        "rain_mm_observed": 24.0,
                        "source": "test gauge",
                    }
                ]
            ).to_csv(observation, index=False)
            pd.DataFrame(
                columns=["date", "location_slug", "rain_mm_observed", "source"]
            ).to_csv(proxy, index=False)

            main(outputs, forecast, observation, proxy)

            joined = pd.read_csv(outputs / "evaluation_joined_daily.csv")
            metrics = pd.read_csv(outputs / "evaluation_metrics.csv")
            html = (outputs / "evaluation_summary.html").read_text(encoding="utf-8")
            self.assertEqual(int(joined.iloc[0]["forecast_models"]), 6)
            self.assertEqual(set(metrics["n_samples"]), {1})
            self.assertIn("menjumlahkan setiap model lebih dahulu", html)
            self.assertIn("24/24", html)

    def test_evaluator_explains_when_only_observations_are_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            outputs = root / "outputs"
            outputs.mkdir()
            forecast = outputs / "forecast_all_locations.csv"
            observation = root / "rain_observed_daily.csv"
            proxy = root / "rain_proxy_daily.csv"

            pd.DataFrame(self._forecast_rows()).to_csv(forecast, index=False)
            pd.DataFrame(columns=["date", "location_slug", "rain_mm_observed"]).to_csv(
                observation, index=False
            )
            pd.DataFrame(columns=["date", "location_slug", "rain_mm_observed"]).to_csv(
                proxy, index=False
            )

            main(outputs, forecast, observation, proxy)

            html = (outputs / "evaluation_summary.html").read_text(encoding="utf-8")
            self.assertIn("Data observasi yang sesuai belum tersedia", html)
            self.assertNotIn("Forecast atau observasi belum tersedia", html)


if __name__ == "__main__":
    unittest.main()
