import unittest
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pandas as pd

import weather_ensemble_multi_location as forecast
from build_utils.make_forecast_redelong_site import metrics_for


class ForecastSourceSemanticsTest(unittest.TestCase):
    def test_bmkg_category_is_not_converted_to_numeric_rain(self):
        payload = {
            "data": [
                {
                    "cuaca": [
                        [
                            {
                                "local_datetime": "2026-07-13 06:00:00",
                                "t": 20,
                                "hu": 90,
                                "ws": 5,
                                "weather_desc": "Hujan Ringan",
                            }
                        ]
                    ]
                }
            ]
        }
        args = SimpleNamespace(timezone="Asia/Jakarta")

        points = forecast.extract_bmkg_points(forecast.parse_iso_date("2026-07-13"), payload, args)

        self.assertIn("06:00", points)
        self.assertIsNone(points["06:00"].rain_mm)
        self.assertEqual("Hujan Ringan", points["06:00"].category)

    def test_active_quantitative_sources_use_equal_base_weights(self):
        for source in {"CMA", "ECMWF", "GFS", "ICON", "METEOFRANCE", "UKMO"}:
            self.assertEqual(1.0, forecast.SOURCE_BASE_WEIGHTS[source], source)

    def test_open_meteo_preview_requests_requested_forecast_range(self):
        args = SimpleNamespace(
            latitude=4.748139,
            longitude=96.977344,
            timezone="Asia/Jakarta",
            forecast_range_days=4,
        )
        config = {
            "kind": "open_meteo",
            "endpoint": "https://example.test/v1/forecast",
            "models": "ecmwf_ifs025",
        }

        query = parse_qs(urlparse(forecast.preview_request_url(config, args)).query)

        self.assertEqual(["4"], query["forecast_days"])

    def test_public_site_metrics_exclude_categorical_and_inactive_sources(self):
        frame = pd.DataFrame(
            [
                {"source_id": "ECMWF", "rain_mm": 2.0},
                {"source_id": "GFS", "rain_mm": 4.0},
                {"source_id": "BMKG", "rain_mm": 100.0},
                {"source_id": "KMA", "rain_mm": 200.0},
            ]
        )

        metrics = metrics_for(frame, "rain_mm", "source_id")

        self.assertEqual(metrics["sources"], "2")
        self.assertEqual(metrics["rain_max"], "4.0")
        self.assertEqual(metrics["rain_mean"], "3.0")


if __name__ == "__main__":
    unittest.main()
