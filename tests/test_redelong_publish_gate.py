from __future__ import annotations

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_utils.apply_global_experience import apply_all
from build_utils.build_besai_portal import build as build_besai_portal
from build_utils.build_multisite_catalog import build as build_multisite_catalog
from build_utils.build_redelong_globe_history import patch_homepage as patch_globe_homepage
from build_utils.validate_redelong_publish import (
    EXPECTED_LOCATIONS,
    QUANTITATIVE_SOURCES,
    validate,
)


def write_csv(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def branded_html(href: str, script: str = "") -> str:
    return (
        '<!doctype html><html lang="id"><head><meta name="viewport" content="width=device-width,initial-scale=1"><title>Forecast Site</title></head><body>'
        f'<a data-fr-brand="true" href="{href}"><span>FR</span>'
        "<b>Forecast Site</b></a>"
        f"{script}</body></html>"
    )


class RedelongPublishGateTest(unittest.TestCase):
    def test_validator_cli_imports_from_repository_root(self) -> None:
        validator = Path(__file__).resolve().parents[1] / "build_utils" / "validate_redelong_publish.py"
        result = subprocess.run(
            [sys.executable, str(validator), "--help"],
            cwd=validator.parents[1],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def make_valid_outputs(self, root: Path) -> None:
        besai_points = {
            "pltm_besai_kemu",
            "pltm_besai_kemu_headpond",
            "pltm_besai_kemu_powerhouse",
            "pltm_besai_kemu_sumberjaya",
        }
        forecast_rows = [
            {
                "location_slug": location,
                "target_date": "2026-07-13",
                "target_jam": "00:00",
                "source_id": source,
            }
            for location in sorted(EXPECTED_LOCATIONS | besai_points)
            for source in sorted(QUANTITATIVE_SOURCES)
        ]
        for row in forecast_rows:
            row["rain_mm"] = 1.0
        write_csv(root / "forecast_all_locations.csv", forecast_rows)
        write_csv(
            root / "dim_sources.csv",
            [
                {"source_id": source, "base_weight": 1.0}
                for source in sorted(QUANTITATIVE_SOURCES)
            ],
        )
        write_csv(
            root / "operational_source_status.csv",
            [
                {"source_id": source, "qc_status": "valid", "completeness_pct": 100.0}
                for source in sorted(QUANTITATIVE_SOURCES)
            ],
        )
        write_csv(
            root / "operational_windows.csv",
            [
                {
                    "horizon_hours": horizon,
                    "data_status": "cukup",
                    "model_count": 6,
                    "rain_mean_mm": 5.0,
                }
                for horizon in (24, 48, 72)
            ],
        )
        for name in [
            "redelong_operational.html",
            "redelong_operational.json",
            "operational_3hour.csv",
            "operational_per_point_24h.csv",
            "bmkg_guidance.csv",
        ]:
            content = branded_html("index.html") if name.endswith(".html") else "ok"
            (root / name).write_text(content, encoding="utf-8")

        (root / "redelong_operational_points.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [96.977344, 4.748139]},
                            "properties": {
                                "location_slug": "plta_redelong",
                                "operational_role": "outlet_reference",
                                "include_in_catchment": False,
                            },
                        },
                        {
                            "type": "Feature",
                            "geometry": {"type": "Point", "coordinates": [96.85, 4.65]},
                            "properties": {
                                "location_slug": "gpm_grid_tamatue",
                                "operational_role": "external_comparison",
                                "include_in_catchment": False,
                            },
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )

        for slug in EXPECTED_LOCATIONS:
            directory = root / slug
            directory.mkdir()
            days = []
            for day in (13, 14, 15):
                days.append(
                    {
                        "date_iso": f"2026-07-{day:02d}",
                        "risk_class": "watch",
                        "valid_points": 24,
                        "hours": [{"hour": f"{hour:02d}:00"} for hour in range(24)],
                    }
                )
            (directory / "redelong_api_v1.json").write_text(
                json.dumps({"days": days}), encoding="utf-8"
            )
            (directory / "redelong_app.html").write_text(
                branded_html(
                    "../index.html",
                    "<script>window.REDELONG_CONFIG = {}; (() => { const ok = true; })();</script>",
                ),
                encoding="utf-8",
            )
            (directory / "redelong_map_room.html").write_text(
                branded_html("../index.html"), encoding="utf-8"
            )
        (root / "index.html").write_text(
            branded_html(
                "index.html",
                '<a href="redelong_globe.html">Globe</a><script>(() => { const portal = true; })();</script>',
            ),
            encoding="utf-8",
        )
        (root / "redelong_portal_map.html").write_text(
            branded_html("index.html"), encoding="utf-8"
        )
        (root / "validation_status.html").write_text(
            branded_html("index.html"), encoding="utf-8"
        )
        (root / "evaluation_summary.html").write_text(
            branded_html("index.html"), encoding="utf-8"
        )
        (root / "redelong_globe.html").write_text(
            branded_html(
                "index.html",
                "<meta name='forecast-redelong-page' content='forecast-redelong-globe-history-v1'><script>(() => { const projection = {type:'globe'}; })();</script>",
            ),
            encoding="utf-8",
        )
        zone_features = [
            {
                "type": "Feature",
                "properties": {
                    "name": f"GPM{index}",
                    "area_km2": 137.8 / 6,
                    "include_in_catchment": True,
                    "role": "catchment_zone",
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            }
            for index in range(1, 7)
        ]
        zone_features.append(
            {
                "type": "Feature",
                "properties": {
                    "name": "GPM Grid TamaTue",
                    "area_km2": 122.5,
                    "include_in_catchment": False,
                    "role": "external_comparison",
                },
                "geometry": {"type": "Polygon", "coordinates": []},
            }
        )
        (root / "redelong_analysis_zones.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": zone_features}),
            encoding="utf-8",
        )
        (root / "redelong_historical_stations.geojson").write_text(
            json.dumps(
                {
                    "type": "FeatureCollection",
                    "features": [
                        {
                            "type": "Feature",
                            "properties": {"publication": "metadata_only"},
                            "geometry": {"type": "Point", "coordinates": [97, 5]},
                        }
                        for _ in range(7)
                    ],
                }
            ),
            encoding="utf-8",
        )
        history_sources = {f"gpm{index}": {} for index in range(1, 7)}
        history_annual = [
            {"location_slug": slug, "year": year, "complete": True}
            for slug in history_sources
            for year in range(2000, 2024)
        ]
        (root / "gpm_history_summary.json").write_text(
            json.dumps({"sources": history_sources, "annual": history_annual}),
            encoding="utf-8",
        )
        (root / "gpm_daily_history.csv").write_text(
            "date,location_slug,rain_mm\n", encoding="utf-8"
        )
        (root / "evaluation_status.json").write_text(
            json.dumps(
                {
                    "schema_version": "forecast-redelong-validation-v2",
                    "state": "menunggu_pasangan",
                    "observation_mode": "proxy_observation",
                    "observation_reference": "proxy_satellite_gridded",
                    "observation_sources": [],
                    "site_gauge_required": False,
                    "matched_location_days": 0,
                    "can_claim_field_accuracy": False,
                    "end_to_end_validation": {
                        "status": "collecting_archive",
                        "matched_pairs": 0,
                    },
                    "can_report_preliminary_proxy_skill": False,
                }
            ),
            encoding="utf-8",
        )
        (root / "evaluation_joined_daily.csv").write_text(
            "date,location_slug\n", encoding="utf-8"
        )
        (root / "evaluation_metrics.csv").write_text(
            "scope,forecast_metric,n_samples\n", encoding="utf-8"
        )
        (root / "validation_archive").mkdir()
        (root / "validation_archive" / "proxy_refresh_status.json").write_text(
            json.dumps({"status": "no_eligible_archive", "missing_pairs": 0}),
            encoding="utf-8",
        )
        discharge_forecast = [
            {
                "lead_day": lead,
                "discharge_scenario_low_m3s": 5.0,
                "discharge_forecast_m3s": 7.0,
                "discharge_scenario_high_m3s": 10.0,
            }
            for lead in (1, 2, 3)
        ]
        discharge_validation = [
            {"lead_day": lead, "n_samples": 1000, "nse": 0.7}
            for lead in (1, 2, 3)
        ]
        (root / "redelong_discharge.json").write_text(
            json.dumps(
                {
                    "status": "provisional_proxy_calibrated",
                    "can_claim_field_accuracy": False,
                    "forecast": discharge_forecast,
                    "validation": discharge_validation,
                }
            ),
            encoding="utf-8",
        )
        write_csv(root / "redelong_discharge_forecast.csv", discharge_forecast)
        write_csv(root / "redelong_discharge_validation.csv", discharge_validation)
        write_csv(
            root / "redelong_discharge_hindcast_pairs.csv",
            [{"lead_day": 1, "discharge_proxy_observed_m3s": 7, "discharge_modelled_m3s": 7}],
        )
        (root / "redelong_discharge_end_to_end_pairs.csv").write_text(
            "issue_time_wib,valid_date,lead_day\n", encoding="utf-8"
        )
        (root / "redelong_discharge_end_to_end_validation.csv").write_text(
            "lead_day,n_samples\n", encoding="utf-8"
        )
        (root / "redelong_discharge.html").write_text(
            branded_html("index.html").replace(
                "</head>",
                "<meta name='forecast-hydro-page' content='forecast-redelong-discharge-v1'></head>",
            ).replace("</body>", "<p>Belum field-calibrated</p></body>"),
            encoding="utf-8",
        )
        hydrology = root / "hydrology"
        hydrology.mkdir()
        (hydrology / "glofas_discharge_metadata.json").write_text(
            json.dumps(
                {
                    "source": "GloFAS v4 via Open-Meteo Flood API",
                    "observation_type": "simulated_gridded_discharge_proxy",
                    "history_rows": 9000,
                    "selected_grid_coordinate": [4.725006, 96.975006],
                }
            ),
            encoding="utf-8",
        )
        operational_path = root / "redelong_operational.html"
        operational_path.write_text(
            operational_path.read_text(encoding="utf-8").replace(
                "</body>", '<a href="redelong_discharge.html">Forecast debit</a></body>'
            ),
            encoding="utf-8",
        )
        build_besai_portal(root)
        besai_discharge_forecast = [
            {
                "lead_day": lead,
                "discharge_scenario_low_m3s": 5.0,
                "discharge_forecast_m3s": 7.0,
                "discharge_scenario_high_m3s": 10.0,
                "indicative_plant_available_m3s": 3.4,
            }
            for lead in (1, 2, 3)
        ]
        besai_discharge_validation = [
            {"lead_day": lead, "n_samples": 1000, "nse": 0.6}
            for lead in (1, 2, 3)
        ]
        (root / "besai_kemu_discharge.json").write_text(
            json.dumps(
                {
                    "status": "provisional_regulated_proxy",
                    "can_claim_field_accuracy": False,
                    "can_claim_operational_inflow": False,
                    "upstream_release_schedule_available": False,
                    "forecast": besai_discharge_forecast,
                    "validation": besai_discharge_validation,
                }
            ),
            encoding="utf-8",
        )
        write_csv(root / "besai_kemu_discharge_forecast.csv", besai_discharge_forecast)
        write_csv(root / "besai_kemu_discharge_validation.csv", besai_discharge_validation)
        write_csv(
            root / "besai_kemu_discharge_hindcast_pairs.csv",
            [{"lead_day": 1, "discharge_proxy_observed_m3s": 7, "discharge_modelled_m3s": 7}],
        )
        (root / "besai_kemu_discharge.html").write_text(
            branded_html("besai_kemu.html").replace(
                "</head>",
                "<meta name='forecast-hydro-page' content='forecast-besai-discharge-v1'></head>",
            ).replace("</body>", "<p>Belum field-calibrated</p></body>"),
            encoding="utf-8",
        )
        (hydrology / "besai_glofas_discharge_metadata.json").write_text(
            json.dumps(
                {
                    "source": "GloFAS v4 via Open-Meteo Flood API",
                    "observation_type": "simulated_gridded_discharge_proxy",
                    "history_rows": 9000,
                    "selected_grid_coordinate": [-4.875, 104.525],
                    "grid_selection_status": "screened_proxy_pending_glofas_map_confirmation",
                    "selected_proxy_q40_m3s": 25.0,
                }
            ),
            encoding="utf-8",
        )
        patch_globe_homepage(root)
        build_multisite_catalog(root)
        apply_all(root)

    def test_valid_run_passes_and_broken_javascript_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)

            ok, report = validate(outputs)
            self.assertTrue(ok, report["errors"])
            self.assertEqual(report["status"], "pass")

            (outputs / "index.html").write_text(
                "<script>window.Forecast Redelong_CONFIG = {};</script>", encoding="utf-8"
            )
            ok, report = validate(outputs)
            self.assertFalse(ok)
            self.assertTrue(any("JavaScript" in error for error in report["errors"]))

    def test_tamatue_cannot_enter_catchment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)
            geo_path = outputs / "redelong_operational_points.geojson"
            payload = json.loads(geo_path.read_text(encoding="utf-8"))
            tama = next(
                feature
                for feature in payload["features"]
                if feature["properties"]["location_slug"] == "gpm_grid_tamatue"
            )
            tama["properties"]["include_in_catchment"] = True
            geo_path.write_text(json.dumps(payload), encoding="utf-8")

            ok, report = validate(outputs)
            self.assertFalse(ok)
            self.assertTrue(any("TamaTue" in error for error in report["errors"]))

    def test_three_valid_models_can_publish_when_other_sources_are_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)
            retained = sorted(QUANTITATIVE_SOURCES)[:3]

            forecast_rows = []
            with (outputs / "forecast_all_locations.csv").open(
                "r", encoding="utf-8", newline=""
            ) as handle:
                forecast_rows = [
                    row for row in csv.DictReader(handle) if row["source_id"] in retained
                ]
            write_csv(outputs / "forecast_all_locations.csv", forecast_rows)
            write_csv(
                outputs / "operational_source_status.csv",
                [
                    {
                        "source_id": source,
                        "qc_status": "valid" if source in retained else "data_tidak_cukup",
                        "completeness_pct": 100.0 if source in retained else 0.0,
                    }
                    for source in sorted(QUANTITATIVE_SOURCES)
                ],
            )
            write_csv(
                outputs / "operational_windows.csv",
                [
                    {
                        "horizon_hours": horizon,
                        "data_status": "cukup",
                        "model_count": 3,
                        "rain_mean_mm": 5.0,
                    }
                    for horizon in (24, 48, 72)
                ],
            )

            ok, report = validate(outputs)

            self.assertTrue(ok, report["errors"])
            self.assertEqual(report["metrics"]["operational_sources_valid"], retained)
            self.assertEqual(len(report["metrics"]["quantitative_sources_missing"]), 3)

    def test_unequal_weights_and_bad_branding_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)
            write_csv(
                outputs / "dim_sources.csv",
                [
                    {
                        "source_id": source,
                        "base_weight": 1.2 if source == "ECMWF" else 1.0,
                    }
                    for source in sorted(QUANTITATIVE_SOURCES)
                ],
            )
            (outputs / "index.html").write_text(
                "<h1>Forecast Redelong Redelong.1</h1>", encoding="utf-8"
            )

            ok, report = validate(outputs)

            self.assertFalse(ok)
            self.assertTrue(any("Bobot awal" in error for error in report["errors"]))
            self.assertTrue(any("Branding rusak" in error for error in report["errors"]))

    def test_missing_fr_and_obsolete_public_brands_are_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)
            (outputs / "legacy.html").write_text(
                "<h1>ANEMOS Sentinel X</h1>", encoding="utf-8"
            )

            ok, report = validate(outputs)

            self.assertFalse(ok)
            self.assertTrue(any("Monogram FR" in error for error in report["errors"]))
            self.assertTrue(any("ANEMOS" in error for error in report["errors"]))
            self.assertTrue(any("Sentinel" in error for error in report["errors"]))

    def test_map_room_and_validation_brand_links_are_enforced(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            self.make_valid_outputs(outputs)
            (outputs / "gpm4" / "redelong_map_room.html").write_text(
                branded_html("redelong_app.html"), encoding="utf-8"
            )
            (outputs / "validation_status.html").write_text(
                branded_html("missing-home.html"), encoding="utf-8"
