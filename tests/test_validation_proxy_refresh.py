from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from build_utils.evaluate_forecast_accuracy import QUANTITATIVE_SOURCES, WIB
from build_utils.refresh_validation_observations import refresh


class ValidationProxyRefreshTest(unittest.TestCase):
    def test_no_archive_is_non_blocking(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            status = refresh(Path(tmp))
            self.assertEqual(status["status"], "no_eligible_archive")
            self.assertEqual(status["expected_pairs"], 0)

    def test_mature_archive_download_is_persisted_and_not_repeated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            today = datetime.now(WIB).date()
            issue_date = today - timedelta(days=2)
            target_date = issue_date + timedelta(days=1)
            run = outputs / "archive" / issue_date.strftime("%Y/%m") / "run"
            run.mkdir(parents=True)
            issue = f"{issue_date.isoformat()}T06:30:00+07:00"
            (run / "archive_metadata.json").write_text(
                json.dumps({"issue_time_wib": issue}), encoding="utf-8"
            )
            rows = []
            for hour in range(24):
                for source in sorted(QUANTITATIVE_SOURCES):
                    rows.append(
                        {
                            "location_slug": "plta_redelong",
                            "target_date": target_date.isoformat(),
                            "target_jam": f"{hour:02d}:00",
                            "source_id": source,
                            "rain_mm": 0.5,
                        }
                    )
            pd.DataFrame(rows).to_csv(run / "forecast_all_locations.csv", index=False)
            downloaded = pd.DataFrame(
                [
                    {
                        "date": target_date.isoformat(),
                        "location_slug": "plta_redelong",
                        "rain_mm_observed": 11.0,
                        "source": "GPM IMERG via ClimateSERV",
                        "observation_type": "proxy_satellite_near_real_time",
                    }
                ]
            )

            with patch(
                "build_utils.refresh_validation_observations.download_imerg",
                return_value=downloaded,
            ) as download:
                first = refresh(outputs)
                second = refresh(outputs)

            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "up_to_date")
            self.assertEqual(download.call_count, 1)
            saved = pd.read_csv(
                outputs / "validation_archive" / "rain_proxy_daily_primary.csv"
            )
            self.assertEqual(len(saved), 1)
            self.assertEqual(first["primary_proxy"], "GPM IMERG via ClimateSERV")

    def test_openmeteo_analysis_is_used_when_imerg_is_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            today = datetime.now(WIB).date()
            issue_date = today - timedelta(days=2)
            target_date = issue_date + timedelta(days=1)
            run = outputs / "archive" / issue_date.strftime("%Y/%m") / "run"
            run.mkdir(parents=True)
            (run / "archive_metadata.json").write_text(
                json.dumps(
                    {"issue_time_wib": f"{issue_date.isoformat()}T06:30:00+07:00"}
                ),
                encoding="utf-8",
            )
            rows = []
            for hour in range(24):
                for source in sorted(QUANTITATIVE_SOURCES):
                    rows.append(
                        {
                            "location_slug": "plta_redelong",
                            "target_date": target_date.isoformat(),
                            "target_jam": f"{hour:02d}:00",
                            "source_id": source,
                            "rain_mm": 0.5,
                        }
                    )
            pd.DataFrame(rows).to_csv(run / "forecast_all_locations.csv", index=False)
            openmeteo = pd.DataFrame(
                [{
                    "date": target_date.isoformat(),
                    "location_slug": "plta_redelong",
                    "rain_mm_observed": 9.0,
                    "source": "Open-Meteo Historical Weather, Best Match",
                    "observation_type": "proxy_gridded_weather_analysis",
                }]
            )

            with patch(
                "build_utils.refresh_validation_observations.download_imerg",
                return_value=pd.DataFrame(columns=openmeteo.columns),
            ), patch(
                "build_utils.refresh_validation_observations.download_openmeteo",
                return_value=openmeteo,
            ), patch(
                "build_utils.refresh_validation_observations.download_chirps"
            ) as chirps:
                status = refresh(outputs)

            self.assertEqual(status["status"], "complete")
            self.assertEqual(
                status["primary_proxy"],
                "Open-Meteo Historical Weather, Best Match",
            )
            chirps.assert_not_called()


if __name__ == "__main__":
    unittest.main()
