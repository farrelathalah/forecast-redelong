from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

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

    def test_provisional_besai_boundary_cannot_claim_area_or_discharge(self) -> None:
        site = self.registry["sites"]["pltm_besai_kemu"]
        self.assertIn("provisional", site["site_status"])
        self.assertEqual(site["catchment"]["status"], "not_yet_delineated")
        self.assertIsNone(site["catchment"]["area_km2"])
        self.assertIn("Do not publish", site["catchment"]["note"])

    def test_feature_pushes_validate_without_deploying(self) -> None:
        workflow = (ROOT / ".github/workflows/main.yml").read_text(
            encoding="utf-8-sig"
        )
        self.assertIn('"feature/**"', workflow)
        self.assertIn("github.event_name == 'push'", workflow)
        deploy_condition = next(
            line.strip()
            for line in workflow.splitlines()
            if "github.event_name == 'schedule'" in line
        )
        self.assertNotIn("github.event_name != 'workflow_dispatch'", deploy_condition)

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
            self.assertIn("site_network.html", home)

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

    def test_besai_builder_publishes_history_with_proxy_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            outputs = Path(tmp)
            build_besai_portal(outputs)
            page = (outputs / "besai_kemu.html").read_text(encoding="utf-8")
            history = json.loads(
                (outputs / "besai_kemu_history.json").read_text(encoding="utf-8")
            )
            self.assertIn("forecast-besai-kemu-history-v1", page)
            self.assertIn("Status provisional", page)
            self.assertIn("bukan observasi alat", page)
            self.assertGreaterEqual(history["daily_rows"], 16000)
            self.assertEqual(history["observation_type"], "gridded_meteorological_proxy")


if __name__ == "__main__":
    unittest.main()
