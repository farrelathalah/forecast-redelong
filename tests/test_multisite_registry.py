from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from build_utils.apply_rev3_content import MARKER, apply as apply_rev3
from build_utils.build_besai_portal import build as build_besai_portal
from build_utils.build_multisite_catalog import build


ROOT = Path(__file__).resolve().parents[1]


class MultisiteRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = json.loads(
            (ROOT / "config/sites.json").read_text(encoding="utf-8")
        )

    def test_registry_has_redelong_and_besai_kemu(self) -> None:
        sites = self.registry["sites"]
        self.assertIn("plta_redelong", sites)
        self.assertIn("pltm_besai_kemu", sites)
        self.assertEqual(self.registry["default_site"], "plta_redelong")

    def test_all_sites_have_valid_coordinates_and_wib(self) -> None:
        for slug, site in self.registry["sites"].items():
            with self.subTest(site=slug):
                self.assertTrue(-90 <= float(site["latitude"]) <= 90)
                self.assertTrue(-180 <= float(site["longitude"]) <= 180)
                self.assertEqual(site["timezone"], "Asia/Jakarta")
                self.assertRegex(site["adm4"], r"^\d{2}\.\d{2}\.\d{2}\.\d{4}$")
                self.assertGreaterEqual(len(site["forecast_sources"]), 3)

    def test_besai_uses_documented_area_with_indicative_delineation(self) -> None:
        site = self.registry["sites"]["pltm_besai_kemu"]
        self.assertTrue(site["site_status"].startswith("engineering_document_reference"))
        self.assertEqual(site["operational_status"], "commercial_operation_since_2024_01_08")
        self.assertEqual(
            site["catchment"]["status"],
            "technical_indicative_area_constrained_delineation",
        )
        self.assertAlmostEqual(site["catchment"]["area_km2"], 496.74, places=2)
        self.assertIn("bukan batas legal", site["catchment"]["note"])
        boundary = json.loads(
            (ROOT / site["catchment"]["boundary_file"]).read_text(encoding="utf-8")
        )["features"][0]
        self.assertEqual(boundary["geometry"]["type"], "Polygon")
        self.assertEqual(boundary["properties"]["role"], "technical_indicative_delineation")
        self.assertEqual(boundary["properties"]["status"], "indicative_not_survey_boundary")
        self.assertAlmostEqual(boundary["properties"]["trace_area_km2"], 496.74, places=2)
        self.assertGreaterEqual(len(site["additional_forecast_points"]), 3)

    def test_feature_pushes_validate_without_deploying(self) -> None:
        workflow = (ROOT / ".github/workflows/main.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('"feature/**"', workflow)
        self.assertRegex(workflow, r"(?m)^\s+- main\s*$")
        self.assertIn("github.event_name == 'push'", workflow)
        self.assertIn("python -m unittest discover -s tests -v", workflow)
        self.assertIn("python build_utils/apply_rev3_content.py --outputs outputs", workflow)
        deploy_condition = next(
            line.strip()
            for line in workflow.splitlines()
            if "github.event_name == 'schedule'" in line
        )
        self.assertNotIn("github.event_name != 'workflow_dispatch'", deploy_condition)
        self.assertIn("github.ref == 'refs/heads/main'", deploy_condition)

    def test_catalog_builder_creates_network_globe_and_home_link(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "index.html").write_text(
                "<html><head></head><body><a href='index.html'>FR</a></body></html>",
                encoding="utf-8",
            )
            build(outputs)
            page = (outputs / "site_network.html").read_text(encoding="utf-8")
            home = (outputs / "index.html").read_text(encoding="utf-8")
            self.assertIn("forecast-hydro-multisite-network-v1", page)
            self.assertIn("PLTA Redelong", page)
            self.assertIn("PLTM Besai Kemu", page)
            self.assertIn("type:'globe'", page)
            self.assertIn("BESAI_CATCHMENT", page)
            self.assertIn("besai-catchment-outline", page)
            self.assertIn("site_network.html", home)

    def test_catalog_removes_legacy_multisite_choice_when_primary_globe_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            (outputs / "index.html").write_text(
                '<html><head><style id="fr-sites-entry-style">x</style></head><body>'
                '<a id="fr-globe-entry" href="site_network.html">Globe Forecast Site</a>'
                '<a id="fr-sites-entry" href="site_network.html">Semua Site</a>'
                '</body></html>',
                encoding="utf-8",
            )
            build(outputs)
            home = (outputs / "index.html").read_text(encoding="utf-8")
            self.assertIn('id="fr-globe-entry"', home)
            self.assertNotIn('id="fr-sites-entry"', home)
            self.assertNotIn('id="fr-sites-entry-style"', home)

    def test_location_builder_adds_besai_without_redelong_catchment_weight(self) -> None:
        subprocess.run(
            [sys.executable, "build_utils/make_redelong_locations.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        subprocess.run(
            [sys.executable, "build_utils/fix_redelong_adm4.py"],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        payload = json.loads((ROOT / "locations.json").read_text(encoding="utf-8"))
        besai = payload["locations"]["pltm_besai_kemu"]
        self.assertEqual(besai["adm4"], "18.08.03.2017")
        self.assertFalse(besai["include_in_catchment"])
        self.assertEqual(besai["weight_km2"], 0.0)
        self.assertEqual(besai["operational_role"], "independent_site_reference")
        self.assertAlmostEqual(besai["latitude"], -4.862591667, places=6)
        for slug in [
            "pltm_besai_kemu_headpond",
            "pltm_besai_kemu_powerhouse",
            "pltm_besai_kemu_sumberjaya",
        ]:
            self.assertIn(slug, payload["locations"])
            self.assertEqual(payload["locations"][slug]["site_scope"], "pltm_besai_kemu")

    def test_besai_builder_publishes_history_with_proxy_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            build_besai_portal(outputs)
            page = (outputs / "besai_kemu.html").read_text(encoding="utf-8")
            history = json.loads(
                (outputs / "besai_kemu_history.json").read_text(encoding="utf-8")
            )
            self.assertIn("forecast-besai-kemu-history-v1", page)
            self.assertIn("Referensi engineering tersedia", page)
            self.assertIn("bukan observasi alat", page)
            self.assertGreaterEqual(history["daily_rows"], 16000)
            self.assertEqual(history["observation_type"], "gridded_meteorological_proxy")
            self.assertEqual(len(history["engineering_gauge_reference"]["annual"]), 29)
            self.assertTrue((outputs / "besai_kemu_map.html").is_file())
            self.assertTrue((outputs / "besai_kemu_catchment.geojson").is_file())
            self.assertTrue((outputs / "besai_kemu_fdc_2018.csv").is_file())

    def test_rev3_patch_is_idempotent_and_machine_readable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            base = "<html><head></head><body><main><p>content</p></main></body></html>"
            for name in [
                "besai_kemu.html",
                "besai_kemu_discharge.html",
                "evaluation_summary.html",
                "validation_status.html",
                "redelong_operational.html",
            ]:
                (outputs / name).write_text(base, encoding="utf-8")
            (outputs / "besai_kemu_map.html").write_text(base, encoding="utf-8")
            (outputs / "site_network.html").write_text(
                base.replace("content", "Referensi engineering"), encoding="utf-8"
            )
            (outputs / "evaluation_status.json").write_text(
                json.dumps({"limitations": []}), encoding="utf-8"
            )

            first = apply_rev3(outputs)
            second = apply_rev3(outputs)
            self.assertEqual(first["status"], "complete")
            self.assertEqual(second["status"], "complete")
            page = (outputs / "besai_kemu.html").read_text(encoding="utf-8")
            self.assertEqual(page.count(f'id="{MARKER}-besai"'), 1)
            self.assertIn("8 Januari 2024", page)
            self.assertIn("0,5–20 mm/hari", page)
            status = json.loads((outputs / "evaluation_status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["qualitative_field_checks"]["performed"])
            self.assertFalse(status["qualitative_field_checks"]["quantitative_metrics_eligible"])
            sync = json.loads((outputs / "rev3_sync.json").read_text(encoding="utf-8"))
            self.assertEqual(sync["schema_version"], MARKER)
            self.assertEqual(sync["catchment_status"], "technical_indicative_area_constrained_not_legal_or_as_built")


if __name__ == "__main__":
    unittest.main()
