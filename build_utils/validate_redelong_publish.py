#!/usr/bin/env python3
"""Block deployment when a new Forecast Redelong run is incomplete.

The last successfully deployed GitHub Pages site remains online when this
validator exits non-zero.  It checks the operational rainfall contract, portal
date/hour semantics, TamaTue's comparison-only role, and inline JavaScript.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any


QUANTITATIVE_SOURCES = {"CMA", "ECMWF", "GFS", "ICON", "METEOFRANCE", "UKMO"}
EXPECTED_LOCATIONS = {
    "plta_redelong",
    "gpm1",
    "gpm2",
    "gpm3",
    "gpm4",
    "gpm5",
    "gpm6",
    "gpm_grid_tamatue",
}
MIN_MODELS = 3
MIN_VALID_PORTAL_HOURS = 20


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_json(path: Path, default: Any = None) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return default


def number(value: Any) -> float | None:
    try:
        parsed = float(value)
        return parsed if parsed == parsed else None
    except (TypeError, ValueError):
        return None


def is_date(value: Any) -> bool:
    try:
        dt.date.fromisoformat(str(value))
        return True
    except (TypeError, ValueError):
        return False


def is_hour(value: Any) -> bool:
    try:
        dt.datetime.strptime(str(value), "%H:%M")
        return True
    except (TypeError, ValueError):
        return False


def check_forecast_contract(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    path = outputs / "forecast_all_locations.csv"
    rows = read_csv(path)
    if not rows:
        errors.append("forecast_all_locations.csv tidak ada atau kosong")
        return

    locations = {row.get("location_slug", "") for row in rows}
    missing_locations = sorted(EXPECTED_LOCATIONS - locations)
    if missing_locations:
        errors.append("Lokasi forecast kurang: " + ", ".join(missing_locations))

    bad_time_rows = sum(
        not is_date(row.get("target_date")) or not is_hour(row.get("target_jam"))
        for row in rows
    )
    if bad_time_rows:
        errors.append(f"Ada {bad_time_rows} baris dengan target_date/target_jam tidak valid")

    sources = {row.get("source_id", "") for row in rows}
    missing_sources = sorted(QUANTITATIVE_SOURCES - sources)
    found_sources = sorted(sources & QUANTITATIVE_SOURCES)
    if len(found_sources) < MIN_MODELS:
        errors.append(
            "Model kuantitatif yang ditemukan kurang dari "
            f"{MIN_MODELS}: {', '.join(found_sources) or 'tidak ada'}"
        )

    metrics["forecast_rows"] = len(rows)
    metrics["locations_found"] = len(locations & EXPECTED_LOCATIONS)
    metrics["quantitative_sources_found"] = found_sources
    metrics["quantitative_source_count"] = len(found_sources)
    metrics["quantitative_sources_missing"] = missing_sources


def check_operational_products(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    source_rows = read_csv(outputs / "operational_source_status.csv")
    by_source = {row.get("source_id"): row for row in source_rows}
    valid_sources = []
    invalid_sources: dict[str, str] = {}
    for source in sorted(QUANTITATIVE_SOURCES):
        row = by_source.get(source)
        if not row:
            invalid_sources[source] = "quality control tidak ditemukan"
            continue
        completeness = number(row.get("completeness_pct")) or 0.0
        if row.get("qc_status") != "valid" or completeness < 80.0:
            invalid_sources[source] = (
                f"status={row.get('qc_status')}, completeness={completeness:.1f}%"
            )
        else:
            valid_sources.append(source)
    if len(valid_sources) < MIN_MODELS:
        detail = "; ".join(f"{source}: {reason}" for source, reason in invalid_sources.items())
        errors.append(
            f"Hanya {len(valid_sources)} model kuantitatif lolos quality control; "
            f"minimum {MIN_MODELS}. {detail}"
        )
    metrics["operational_sources_valid"] = valid_sources
    metrics["operational_sources_not_valid"] = invalid_sources

    window_rows = read_csv(outputs / "operational_windows.csv")
    by_horizon = {int(float(row["horizon_hours"])): row for row in window_rows if number(row.get("horizon_hours")) is not None}
    for horizon in (24, 48, 72):
        row = by_horizon.get(horizon)
        if not row:
            errors.append(f"Horizon operasional {horizon} jam tidak ditemukan")
            continue
        models = int(number(row.get("model_count")) or 0)
        rain = number(row.get("rain_mean_mm"))
        if row.get("data_status") != "cukup" or models < MIN_MODELS or rain is None:
            errors.append(
                f"Horizon {horizon} jam belum layak publish: status={row.get('data_status')}, model={models}"
            )

    for name in [
        "redelong_operational.html",
        "redelong_operational.json",
        "operational_3hour.csv",
        "operational_per_point_24h.csv",
        "bmkg_guidance.csv",
    ]:
        path = outputs / name
        if not path.exists() or path.stat().st_size == 0:
            errors.append(f"Produk operasional hilang/kosong: {name}")


def check_spatial_contract(outputs: Path, errors: list[str]) -> None:
    payload = read_json(outputs / "redelong_operational_points.geojson", {}) or {}
    features = payload.get("features", []) if isinstance(payload, dict) else []
    tama = next(
        (
            feature.get("properties", {})
            for feature in features
            if feature.get("properties", {}).get("location_slug") == "gpm_grid_tamatue"
        ),
        None,
    )
    if not tama:
        errors.append("Titik TamaTue tidak ditemukan pada GeoJSON operasional")
        return
    if tama.get("include_in_catchment") is not False or tama.get("operational_role") != "external_comparison":
        errors.append("TamaTue harus tetap external_comparison dan tidak masuk agregasi catchment")


def check_portal_semantics(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    portal_summary: dict[str, Any] = {}
    for slug in sorted(EXPECTED_LOCATIONS):
        api_path = outputs / slug / "redelong_api_v1.json"
        payload = read_json(api_path, {}) or {}
        days = payload.get("days", []) if isinstance(payload, dict) else []
        if len(days) < 3:
            errors.append(f"{slug}: API portal tidak memiliki 3 hari")
            continue
        dates = []
        day_counts = []
        for index, day in enumerate(days[:3], start=1):
            date_iso = day.get("date_iso")
            if not is_date(date_iso):
                errors.append(f"{slug} hari-{index}: date_iso tidak valid ({date_iso!r})")
            dates.append(date_iso)
            hours = day.get("hours", []) if isinstance(day, dict) else []
            hour_values = [item.get("hour") for item in hours if isinstance(item, dict)]
            if any(not is_hour(value) for value in hour_values):
                errors.append(f"{slug} hari-{index}: ada jam yang tidak valid")
            if len(hour_values) != len(set(hour_values)):
                errors.append(f"{slug} hari-{index}: jam forecast duplikat")
            valid_points = int(number(day.get("valid_points")) or 0)
            if valid_points < MIN_VALID_PORTAL_HOURS or day.get("risk_class") == "limited":
                errors.append(
                    f"{slug} {date_iso}: portal hanya {valid_points}/24 jam valid atau berstatus data terbatas"
                )
            day_counts.append(valid_points)
        if len(set(dates)) != len(dates):
            errors.append(f"{slug}: tanggal pada API portal berulang")
        portal_summary[slug] = {"dates": dates, "valid_points": day_counts}
    metrics["portal"] = portal_summary


SCRIPT_RE = re.compile(r"<script\b([^>]*)>(.*?)</script\s*>", re.I | re.S)


def check_inline_javascript(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    node = shutil.which("node")
    if not node:
        errors.append("Node.js tidak tersedia untuk memeriksa sintaks JavaScript")
        return

    html_files = sorted(outputs.glob("*.html")) + sorted(outputs.glob("*/*.html"))
    checked = 0
    for path in html_files:
        content = path.read_text(encoding="utf-8", errors="replace")
        if "window.Forecast Redelong_CONFIG" in content or "window.LANGIT_CONFIG" in content:
            errors.append(f"{path.relative_to(outputs)}: identifier konfigurasi JavaScript rusak/lama")
        scripts = []
        for attributes, body in SCRIPT_RE.findall(content):
            lowered = attributes.lower()
            if "src=" in lowered or "application/json" in lowered or "application/ld+json" in lowered:
                continue
            if body.strip():
                scripts.append(body)
        if not scripts:
            continue
        result = subprocess.run(
            [node, "--check"],
            input="\n".join(scripts),
            text=True,
            capture_output=True,
            check=False,
        )
        checked += 1
        if result.returncode:
            detail = (result.stderr or result.stdout).strip().splitlines()
            errors.append(
                f"{path.relative_to(outputs)}: sintaks JavaScript gagal ({detail[-1] if detail else 'unknown error'})"
            )
    metrics["html_javascript_files_checked"] = checked


def validate(outputs: Path) -> tuple[bool, dict[str, Any]]:
    errors: list[str] = []
    metrics: dict[str, Any] = {}
    check_forecast_contract(outputs, errors, metrics)
    check_operational_products(outputs, errors, metrics)
    check_spatial_contract(outputs, errors)
    check_portal_semantics(outputs, errors, metrics)
    check_inline_javascript(outputs, errors, metrics)
    report = {
        "schema_version": "forecast-redelong-publish-gate-v2",
        "status": "pass" if not errors else "fail",
        "errors": errors,
        "metrics": metrics,
    }
    outputs.mkdir(parents=True, exist_ok=True)
    (outputs / "publish_validation.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return not errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Forecast Redelong before GitHub Pages deploy")
    parser.add_argument("--outputs", default="outputs")
    args = parser.parse_args()
    ok, report = validate(Path(args.outputs))
    if ok:
        print("PASS: Forecast Redelong memenuhi publish quality gate.")
        return 0
    print("BLOCKED: hasil run tidak menggantikan dashboard terakhir yang baik.")
    for error in report["errors"]:
        print(f" - {error}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
