#!/usr/bin/env python3
"""Rev.3 publish gate layered over the retained legacy quality checks.

The legacy validator remains unchanged in validate_redelong_publish_legacy.py.
This module updates only the Besai catchment contract and adds optional checks
for the final Rev.3 synchronization artifact.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from build_utils import validate_redelong_publish_legacy as legacy

QUANTITATIVE_SOURCES = legacy.QUANTITATIVE_SOURCES
EXPECTED_LOCATIONS = legacy.EXPECTED_LOCATIONS
EXPECTED_MULTISITE_FORECAST_LOCATIONS = legacy.EXPECTED_MULTISITE_FORECAST_LOCATIONS
MIN_MODELS = legacy.MIN_MODELS
MIN_VALID_PORTAL_HOURS = legacy.MIN_VALID_PORTAL_HOURS
GLOBAL_EXPERIENCE_MARKER = legacy.GLOBAL_EXPERIENCE_MARKER
PUBLIC_HTML_FR_EXCEPTIONS = legacy.PUBLIC_HTML_FR_EXCEPTIONS

# Preserve the internal import surface used by existing tests and utilities.
for _legacy_name in dir(legacy):
    if _legacy_name.startswith("check_") and _legacy_name not in globals():
        globals()[_legacy_name] = getattr(legacy, _legacy_name)

LEGACY_BESAI_STATUS_ERROR = "Status DAS Besai harus menyatakan trace indikatif berbasis FS"
REV3_CATCHMENT_STATUS = "technical_indicative_area_constrained_delineation"
REV3_BOUNDARY_ROLE = "technical_indicative_delineation"
REV3_SYNC_SCHEMA = "rev3-content-sync-v1"


def _read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def _validate_rev3_catchment(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> bool:
    catalog = _read_json(outputs / "site_catalog.json", {}) or {}
    site = (catalog.get("sites") or {}).get("pltm_besai_kemu", {})
    catchment = site.get("catchment", {}) if isinstance(site, dict) else {}
    boundary = _read_json(outputs / "besai_kemu_catchment.geojson", {}) or {}
    features = boundary.get("features", []) if isinstance(boundary, dict) else []
    feature = features[0] if features else {}
    props = feature.get("properties", {}) if isinstance(feature, dict) else {}

    valid = True
    if catchment.get("status") != REV3_CATCHMENT_STATUS:
        errors.append("Status DAS Besai harus menyatakan delineasi teknis indikatif yang dikontrol terhadap luas dokumen")
        valid = False
    if props.get("role") != REV3_BOUNDARY_ROLE:
        errors.append("GeoJSON DAS Besai harus memakai role technical_indicative_delineation")
        valid = False
    if props.get("status") != "indicative_not_survey_boundary":
        errors.append("GeoJSON DAS Besai harus eksplisit bukan batas survei/legal/as-built")
        valid = False
    note = str(catchment.get("note", "")).lower()
    if "bukan batas legal" not in note or "dem" not in note:
        errors.append("Catatan DAS Besai harus menyebut batas legal dan kebutuhan delineasi DEM final")
        valid = False
    if site.get("operational_status") != "commercial_operation_since_2024_01_08":
        errors.append("Status operasional PLTM Besai Kemu belum disinkronkan ke 8 Januari 2024")
        valid = False

    metrics["multisite_besai_boundary_status"] = catchment.get("status")
    metrics["multisite_besai_boundary_method"] = props.get("role")
    metrics["multisite_besai_operational_status"] = site.get("operational_status")
    return valid


def _validate_rev3_sync(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    sync = _read_json(outputs / "rev3_sync.json", {}) or {}
    if sync.get("schema_version") != REV3_SYNC_SCHEMA or sync.get("status") != "complete":
        errors.append("rev3_sync.json belum membuktikan sinkronisasi konten final")
        return
    patched = set(sync.get("patched_files") or [])
    required = {
        "besai_kemu.html",
        "besai_kemu_map.html",
        "besai_kemu_discharge.html",
        "site_network.html",
        "evaluation_summary.html",
        "validation_status.html",
        "redelong_operational.html",
        "evaluation_status.json",
    }
    missing = sorted(required - patched)
    if missing:
        errors.append("Sinkronisasi Rev.3 belum mencakup: " + ", ".join(missing))

    validation = _read_json(outputs / "evaluation_status.json", {}) or {}
    qualitative = validation.get("qualitative_field_checks", {})
    if qualitative.get("performed") is not True:
        errors.append("Validasi lapangan kualitatif belum tercatat pada evaluation_status.json")
    if qualitative.get("quantitative_metrics_eligible") is not False:
        errors.append("Validasi kualitatif tidak boleh masuk metrik akurasi numerik")

    page_checks = {
        "besai_kemu.html": ["8 Januari 2024", "0,5–20 mm/hari"],
        "validation_status.html": ["Validasi lapangan kualitatif"],
        "redelong_operational.html": ["Kategori perhatian meteorologis"],
        "besai_kemu_discharge.html": ["release upstream", "debit proxy"],
    }
    for name, tokens in page_checks.items():
        path = outputs / name
        content = path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
        for token in tokens:
            if token not in content:
                errors.append(f"{name} belum memuat konteks Rev.3: {token}")

    metrics["rev3_sync_status"] = sync.get("status")
    metrics["rev3_sync_patched_files"] = sorted(patched)
    metrics["qualitative_field_validation_recorded"] = qualitative.get("performed") is True
    metrics["qualitative_field_validation_in_numeric_accuracy"] = qualitative.get("quantitative_metrics_eligible") is not False


def validate(outputs: Path, require_rev3: bool = False) -> tuple[bool, dict[str, Any]]:
    _, report = legacy.validate(outputs)
    errors = list(report.get("errors") or [])
    metrics = dict(report.get("metrics") or {})

    rev3_contract_errors: list[str] = []
    rev3_contract_valid = _validate_rev3_catchment(outputs, rev3_contract_errors, metrics)
    if rev3_contract_valid:
        errors = [error for error in errors if error != LEGACY_BESAI_STATUS_ERROR]
    errors.extend(error for error in rev3_contract_errors if error not in errors)

    if require_rev3:
        _validate_rev3_sync(outputs, errors, metrics)

    report = {
        "schema_version": "forecast-hydro-publish-gate-v7",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "metrics": metrics,
        "legacy_gate_schema": "forecast-hydro-publish-gate-v6",
        "rev3_required": require_rev3,
    }
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "publish_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Forecast Redelong before GitHub Pages deploy")
    parser.add_argument("--outputs", default="outputs")
    parser.add_argument(
        "--allow-missing-rev3",
        action="store_true",
        help="Compatibility mode for isolated legacy fixtures; production builds require Rev.3.",
    )
    args = parser.parse_args()
    ok, report = validate(
        Path(args.outputs),
        require_rev3=not args.allow_missing_rev3,
    )
    if ok:
        print("PASS: Forecast Redelong memenuhi publish quality gate Rev.3.")
        return 0
    print("BLOCKED: hasil run tidak menggantikan dashboard terakhir yang baik.")
    for error in report["errors"]:
        print(f" - {error}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
