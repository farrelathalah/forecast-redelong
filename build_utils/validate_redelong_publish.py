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
import math
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit


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
EXPECTED_MULTISITE_FORECAST_LOCATIONS = EXPECTED_LOCATIONS | {"pltm_besai_kemu"}
MIN_MODELS = 3
MIN_VALID_PORTAL_HOURS = 20
GLOBAL_EXPERIENCE_MARKER = "fr-global-experience-v1"

# Every retained public HTML page currently needs an interactive FR monogram.
# Keep any future exception here with a specific rationale so it is visible in
# publish_validation.json and reviewable in source control.
PUBLIC_HTML_FR_EXCEPTIONS: dict[str, str] = {}


class _AnchorTextParser(HTMLParser):
    """Collect anchor hrefs and their visible text using only the stdlib."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[dict[str, Any]] = []
        self._open_links: list[dict[str, Any]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        link: dict[str, Any] = {
            "href": dict(attrs).get("href") or "",
            "text": [],
        }
        self.links.append(link)
        self._open_links.append(link)

    def handle_data(self, data: str) -> None:
        for link in self._open_links:
            link["text"].append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "a" and self._open_links:
            self._open_links.pop()


def public_html_files(outputs: Path) -> list[Path]:
    return sorted(path for path in outputs.rglob("*.html") if path.is_file())


def fr_link_hrefs(content: str) -> list[str]:
    parser = _AnchorTextParser()
    parser.feed(content)
    return [
        str(link["href"])
        for link in parser.links
        if re.search(r"\bFR\b", " ".join(link["text"]), flags=re.I)
    ]


def local_href_target(page: Path, href: str) -> Path | None:
    parsed = urlsplit(href.strip())
    if parsed.scheme or parsed.netloc or not parsed.path:
        return None
    path_text = unquote(parsed.path)
    if path_text.startswith("/"):
        return None
    target = page.parent / path_text
    if path_text.endswith("/"):
        target = target / "index.html"
    return target.resolve()


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
    missing_locations = sorted(EXPECTED_MULTISITE_FORECAST_LOCATIONS - locations)
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
    metrics["locations_found"] = len(locations & EXPECTED_MULTISITE_FORECAST_LOCATIONS)
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


def check_spatial_contract(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
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
    plta_feature = next(
        (
            feature
            for feature in features
            if feature.get("properties", {}).get("location_slug") == "plta_redelong"
        ),
        None,
    )
    tama_feature = next(
        (
            feature
            for feature in features
            if feature.get("properties", {}).get("location_slug") == "gpm_grid_tamatue"
        ),
        None,
    )
    distance = None
    try:
        plta_lon, plta_lat = plta_feature["geometry"]["coordinates"]
        tama_lon, tama_lat = tama_feature["geometry"]["coordinates"]
        p1, p2 = math.radians(plta_lat), math.radians(tama_lat)
        dp = math.radians(tama_lat - plta_lat)
        dl = math.radians(tama_lon - plta_lon)
        a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
        distance = 2 * 6371.0088 * math.asin(math.sqrt(a))
    except (TypeError, KeyError, ValueError):
        errors.append("Jarak PLTA–TamaTue tidak dapat diverifikasi dari GeoJSON operasional")
    metrics["plta_tamatue_straight_line_km"] = round(distance, 2) if distance is not None else None
    metrics["tamatue_role"] = tama.get("operational_role")
    metrics["tamatue_in_catchment"] = tama.get("include_in_catchment")


def check_evaluation_status(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    required = [
        "evaluation_summary.html",
        "evaluation_status.json",
        "evaluation_joined_daily.csv",
        "evaluation_metrics.csv",
        "validation_archive/proxy_refresh_status.json",
    ]
    missing = [name for name in required if not (outputs / name).is_file()]
    if missing:
        errors.append("Produk validasi hilang: " + ", ".join(missing))
        return
    status = read_json(outputs / "evaluation_status.json", {}) or {}
    proxy_refresh = read_json(
        outputs / "validation_archive" / "proxy_refresh_status.json", {}
    ) or {}
    if status.get("schema_version") != "forecast-redelong-validation-v2":
        errors.append("evaluation_status.json tidak memakai schema validasi v2")
    mode = status.get("observation_mode")
    matched = int(number(status.get("matched_location_days")) or 0)
    matched_dates = int(number(status.get("matched_unique_dates")) or 0)
    event_dates = int(number(status.get("observed_event_dates_ge_1mm")) or 0)
    can_claim = status.get("can_claim_field_accuracy") is True
    can_report_proxy = status.get("can_report_preliminary_proxy_skill") is True
    if can_claim and mode != "field_observation":
        errors.append("Validasi proxy tidak boleh mengklaim akurasi lapangan")
    if mode == "proxy_observation":
        if status.get("observation_reference") not in {
            "proxy_satellite_gridded",
            "proxy_gridded_weather_analysis",
        }:
            errors.append(
                "Validasi proxy harus mendokumentasikan referensi gridded yang digunakan"
            )
        if status.get("site_gauge_required") is not False:
            errors.append("Validasi proxy tidak boleh bergantung pada penakar hujan site")
    if can_claim and matched_dates < 30:
        errors.append("Klaim awal akurasi lapangan memerlukan sedikitnya 30 tanggal unik")
    if can_claim and event_dates < 10:
        errors.append("Klaim awal akurasi lapangan memerlukan sedikitnya 10 tanggal hujan")
    if can_report_proxy and matched_dates < 30:
        errors.append("Status skill proxy awal memerlukan sedikitnya 30 tanggal unik")
    if can_report_proxy and event_dates < 10:
        errors.append("Status skill proxy awal memerlukan sedikitnya 10 tanggal hujan")
    metric_rows = read_csv(outputs / "evaluation_metrics.csv")
    joined_rows = read_csv(outputs / "evaluation_joined_daily.csv")
    joined_sources = sorted(
        {
            str(row.get("observation_source", "")).strip()
            for row in joined_rows
            if str(row.get("observation_source", "")).strip()
        }
    )
    if len(joined_sources) > 1:
        errors.append("Satu evaluasi tidak boleh mencampur beberapa sumber proxy")
    if matched == 0 and metric_rows:
        errors.append("Metrik evaluasi tidak boleh terisi tanpa pasangan forecast–observation")
    if matched > 0:
        overall = [row for row in metric_rows if row.get("scope") == "overall"]
        if len(overall) < 3:
            errors.append("Metrik overall mean/P90/max belum lengkap")
        if any(int(number(row.get("n_samples")) or 0) != matched for row in overall):
            errors.append("Jumlah sampel metrik overall tidak konsisten dengan status validasi")
    metrics["evaluation_state"] = status.get("state")
    metrics["evaluation_observation_mode"] = mode
    metrics["evaluation_matched_location_days"] = matched
    metrics["evaluation_matched_unique_dates"] = matched_dates
    metrics["evaluation_can_claim_field_accuracy"] = can_claim
    metrics["evaluation_can_report_preliminary_proxy_skill"] = can_report_proxy
    metrics["evaluation_observation_sources"] = status.get("observation_sources", [])
    metrics["evaluation_joined_observation_sources"] = joined_sources
    metrics["validation_proxy_refresh_status"] = proxy_refresh.get("status")
    metrics["validation_proxy_missing_pairs"] = proxy_refresh.get("missing_pairs")


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


def check_public_branding(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    html_files = public_html_files(outputs)
    missing_fr: list[str] = []
    broken_fr_links: list[str] = []
    anemos_files: list[str] = []
    sentinel_files: list[str] = []
    legacy_brand_files: list[str] = []
    forecast_site_missing: list[str] = []
    branded_files: list[str] = []
    experience_missing: list[str] = []
    spin_missing: list[str] = []
    rain_missing: list[str] = []
    decorative_separator_files: list[str] = []
    output_root = outputs.resolve()

    for path in html_files:
        relative = path.relative_to(outputs).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"[•·]|&(?:bull|middot);", content, flags=re.I):
            decorative_separator_files.append(relative)
        hrefs = fr_link_hrefs(content)
        if hrefs:
            branded_files.append(relative)
        elif relative not in PUBLIC_HTML_FR_EXCEPTIONS:
            missing_fr.append(relative)

        for href in hrefs:
            target = local_href_target(path, href)
            if target is None:
                broken_fr_links.append(f"{relative} -> {href or '(kosong)'}")
                continue
            try:
                target.relative_to(output_root)
            except ValueError:
                broken_fr_links.append(f"{relative} -> {href} (di luar outputs)")
                continue
            if not target.is_file():
                broken_fr_links.append(f"{relative} -> {href} (target tidak ada)")

        if "anemos" in relative.lower() or re.search(r"\bANEMOS\b", content, flags=re.I):
            anemos_files.append(relative)
        if re.search(r"\bSentinel(?:\s+X)?\b", content, flags=re.I):
            sentinel_files.append(relative)
        if "Forecast Redelong" in content:
            legacy_brand_files.append(relative)
        if "Forecast Site" not in content:
            forecast_site_missing.append(relative)

        if GLOBAL_EXPERIENCE_MARKER not in content or "data-fr-global-brand" not in content:
            experience_missing.append(relative)
        if "data-fr-spin-target" not in content:
            spin_missing.append(relative)
        native_rain = bool(
            re.search(r'id=["\'](?:atmo-canvas|particle-canvas)["\']', content, flags=re.I)
        )
        global_rain = (
            'id="fr-global-rain"' in content
            and 'data-fr-rain-effect="true"' in content
        )
        if not global_rain:
            rain_missing.append(relative)

    if missing_fr:
        errors.append(
            "Monogram FR interaktif belum ada pada: " + ", ".join(missing_fr[:20])
        )
    if broken_fr_links:
        errors.append(
            "Link monogram FR tidak valid pada: " + ", ".join(broken_fr_links[:20])
        )
    if anemos_files:
        errors.append(
            "Brand ANEMOS masih muncul pada output publik: " + ", ".join(anemos_files[:20])
        )
    if sentinel_files:
        errors.append(
            "Brand Sentinel masih muncul pada output publik: " + ", ".join(sentinel_files[:20])
        )
    if legacy_brand_files:
        errors.append(
            "Brand lama Forecast Redelong masih muncul pada output publik: "
            + ", ".join(legacy_brand_files[:20])
        )
    if forecast_site_missing:
        errors.append(
            "Brand Forecast Site belum konsisten pada output publik: "
            + ", ".join(forecast_site_missing[:20])
        )
    if experience_missing:
        errors.append(
            "Global FR experience belum diterapkan pada: "
            + ", ".join(experience_missing[:20])
        )
    if spin_missing:
        errors.append(
            "Target animasi putar FR belum ada pada: " + ", ".join(spin_missing[:20])
        )
    if rain_missing:
        errors.append(
            "Efek atmosfer hujan belum ada pada: " + ", ".join(rain_missing[:20])
        )
    if decorative_separator_files:
        errors.append(
            "Pemisah titik tengah masih muncul pada output publik: "
            + ", ".join(decorative_separator_files[:20])
        )

    expected_map_homes = {
        "redelong_portal_map.html": "index.html",
        **{
            f"{slug}/redelong_map_room.html": "../index.html"
            for slug in sorted(EXPECTED_LOCATIONS)
        },
    }
    map_brand_errors: list[str] = []
    for relative, expected_href in expected_map_homes.items():
        path = outputs / relative
        if not path.is_file():
            map_brand_errors.append(f"{relative} (halaman tidak ada)")
            continue
        hrefs = fr_link_hrefs(path.read_text(encoding="utf-8", errors="replace"))
        if expected_href not in hrefs:
            map_brand_errors.append(
                f"{relative} (FR harus menuju {expected_href})"
            )
    if map_brand_errors:
        errors.append(
            "Brand/back-link halaman peta tidak valid: " + ", ".join(map_brand_errors)
        )

    validation_path = outputs / "validation_status.html"
    validation_brand_ok = False
    if validation_path.is_file():
        validation_content = validation_path.read_text(encoding="utf-8", errors="replace")
        validation_brand_ok = (
            "Forecast Site" in validation_content
            and "index.html" in fr_link_hrefs(validation_content)
        )
    if not validation_brand_ok:
        errors.append(
            "validation_status.html harus memakai brand Forecast Site dan FR menuju index.html"
        )

    metrics["public_html_count"] = len(html_files)
    metrics["public_html_fr_branded_count"] = len(branded_files)
    metrics["public_html_fr_exceptions"] = PUBLIC_HTML_FR_EXCEPTIONS
    metrics["public_html_missing_fr"] = missing_fr
    metrics["public_html_broken_fr_links"] = broken_fr_links
    metrics["public_html_anemos_files"] = anemos_files
    metrics["public_html_sentinel_files"] = sentinel_files
    metrics["public_html_legacy_brand_files"] = legacy_brand_files
    metrics["public_html_forecast_site_missing"] = forecast_site_missing
    metrics["public_html_experience_missing"] = experience_missing
    metrics["public_html_spin_missing"] = spin_missing
    metrics["public_html_rain_missing"] = rain_missing
    metrics["public_html_decorative_separator_files"] = decorative_separator_files
    metrics["global_experience_ok"] = not (
        experience_missing or spin_missing or rain_missing
    )
    metrics["map_room_branding_ok"] = not map_brand_errors
    metrics["validation_status_branding_ok"] = validation_brand_ok


def check_branding_and_weights(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    bad_brand_tokens = {
        "Forecast Redelong Redelong.1",
        "Forecast Redelong Redelong",
    }
    bad_brand_files: list[str] = []
    for path in public_html_files(outputs):
        content = path.read_text(encoding="utf-8", errors="replace")
        if any(token in content for token in bad_brand_tokens):
            bad_brand_files.append(str(path.relative_to(outputs)))
    if bad_brand_files:
        errors.append(
            "Branding rusak masih ditemukan pada: " + ", ".join(bad_brand_files[:10])
        )
    metrics["branding_bad_file_count"] = len(bad_brand_files)

    source_rows = read_csv(outputs / "dim_sources.csv")
    by_source = {row.get("source_id"): row for row in source_rows}
    unequal: dict[str, Any] = {}
    for source in sorted(QUANTITATIVE_SOURCES):
        weight = number((by_source.get(source) or {}).get("base_weight"))
        if weight is None or abs(weight - 1.0) > 1e-9:
            unequal[source] = weight
    if unequal:
        errors.append(
            "Bobot awal model kuantitatif belum sama 1.0: "
            + ", ".join(f"{source}={weight}" for source, weight in unequal.items())
        )
    metrics["quantitative_base_weights"] = {
        source: number((by_source.get(source) or {}).get("base_weight"))
        for source in sorted(QUANTITATIVE_SOURCES)
    }


def check_usability_basics(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    missing_language: list[str] = []
    missing_viewport: list[str] = []
    missing_title: list[str] = []
    inaccessible_fr: list[str] = []
    for path in public_html_files(outputs):
        relative = path.relative_to(outputs).as_posix()
        content = path.read_text(encoding="utf-8", errors="replace")
        if not re.search(r"<html\b[^>]*\blang=[\"']id[\"']", content, flags=re.I):
            missing_language.append(relative)
        if not re.search(r"<meta\b[^>]*\bname=[\"']viewport[\"']", content, flags=re.I):
            missing_viewport.append(relative)
        title = re.search(r"<title\b[^>]*>(.*?)</title\s*>", content, flags=re.I | re.S)
        if not title or not re.sub(r"<[^>]+>", "", title.group(1)).strip():
            missing_title.append(relative)
        for anchor in re.finditer(
            r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>",
            content,
            flags=re.I | re.S,
        ):
            visible = re.sub(r"<[^>]+>", " ", anchor.group("body"))
            if re.search(r"\bFR\b", visible, flags=re.I) and not re.search(
                r"\baria-label\s*=", anchor.group("attrs"), flags=re.I
            ):
                inaccessible_fr.append(relative)
                break
    for label, files in [
        ("atribut bahasa Indonesia", missing_language),
        ("meta viewport mobile", missing_viewport),
        ("judul halaman", missing_title),
        ("label aksesibel pada FR", inaccessible_fr),
    ]:
        if files:
            errors.append(f"Audit kemudahan pakai: {label} belum ada pada " + ", ".join(files[:20]))
    metrics["usability_missing_language"] = missing_language
    metrics["usability_missing_viewport"] = missing_viewport
    metrics["usability_missing_title"] = missing_title
    metrics["usability_inaccessible_fr"] = inaccessible_fr
    metrics["usability_basics_ok"] = not (
        missing_language or missing_viewport or missing_title or inaccessible_fr
    )


def check_inline_javascript(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    node = shutil.which("node")
    if not node:
        errors.append("Node.js tidak tersedia untuk memeriksa sintaks JavaScript")
        return

    html_files = public_html_files(outputs)
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


def check_geospatial_history(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    required = [
        "redelong_globe.html",
        "redelong_analysis_zones.geojson",
        "redelong_historical_stations.geojson",
        "gpm_history_summary.json",
        "gpm_daily_history.csv",
    ]
    missing = [name for name in required if not (outputs / name).is_file()]
    if missing:
        errors.append("Produk globe/histori hilang: " + ", ".join(missing))
        return

    globe = (outputs / "redelong_globe.html").read_text(
        encoding="utf-8", errors="replace"
    )
    if "forecast-redelong-globe-history-v1" not in globe or "type:'globe'" not in globe:
        errors.append("redelong_globe.html tidak memuat kontrak globe 3D")
    home = (outputs / "index.html").read_text(encoding="utf-8", errors="replace")
    primary_globe = re.search(
        r'id=["\']fr-globe-entry["\'][^>]*href=["\']site_network\.html["\']',
        home,
    )
    if not primary_globe or "Globe Forecast Site" not in home:
        errors.append("Tombol globe utama homepage belum mengarah ke seluruh site")

    zones = read_json(outputs / "redelong_analysis_zones.geojson", {}) or {}
    features = zones.get("features", []) if isinstance(zones, dict) else []
    included = [
        feature
        for feature in features
        if feature.get("properties", {}).get("include_in_catchment") is True
    ]
    external = [
        feature
        for feature in features
        if feature.get("properties", {}).get("role") == "external_comparison"
    ]
    area = sum(
        float(feature.get("properties", {}).get("area_km2") or 0)
        for feature in included
    )
    if len(included) != 6 or not 137.0 <= area <= 139.0:
        errors.append("Globe harus memuat enam zona Redelong dengan luas sekitar 137,80 km²")
    if not any(
        feature.get("properties", {}).get("name") == "GPM Grid TamaTue"
        and feature.get("properties", {}).get("include_in_catchment") is False
        for feature in external
    ):
        errors.append("Layer globe harus mempertahankan TamaTue sebagai pembanding eksternal")

    history = read_json(outputs / "gpm_history_summary.json", {}) or {}
    sources = history.get("sources", {}) if isinstance(history, dict) else {}
    annual = history.get("annual", []) if isinstance(history, dict) else []
    complete_years = {
        slug: sum(
            1
            for row in annual
            if row.get("location_slug") == slug and row.get("complete") is True
        )
        for slug in sorted(sources)
    }
    if sorted(sources) != [f"gpm{index}" for index in range(1, 7)]:
        errors.append("Histori publik harus mencakup GPM1 sampai GPM6")
    if any(years < 24 for years in complete_years.values()):
        errors.append("Setiap zona GPM harus memiliki sedikitnya 24 tahun histori lengkap")

    stations = read_json(outputs / "redelong_historical_stations.geojson", {}) or {}
    station_features = stations.get("features", []) if isinstance(stations, dict) else []
    if len(station_features) < 7:
        errors.append("Katalog globe harus memuat metadata stasiun BMKG dan PU")
    if any(
        feature.get("properties", {}).get("publication") != "metadata_only"
        for feature in station_features
    ):
        errors.append("Globe publik tidak boleh menerbitkan ulang data mentah BMKG/PU")

    metrics["geospatial_history_zones"] = len(features)
    metrics["geospatial_history_catchment_zones"] = len(included)
    metrics["geospatial_history_catchment_area_km2"] = round(area, 3)
    metrics["geospatial_history_complete_years"] = complete_years
    metrics["geospatial_history_station_metadata_count"] = len(station_features)


def check_multisite_catalog(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    required = [
        "site_catalog.json",
        "site_network.html",
        "besai_kemu.html",
        "besai_kemu_history.json",
        "besai_kemu_forecast.json",
        "besai_kemu_history_daily.csv",
    ]
    missing = [name for name in required if not (outputs / name).is_file()]
    if missing:
        errors.append("Produk jaringan multi-site hilang: " + ", ".join(missing))
        return

    catalog = read_json(outputs / "site_catalog.json", {}) or {}
    sites = catalog.get("sites", {}) if isinstance(catalog, dict) else {}
    expected = {"plta_redelong", "pltm_besai_kemu"}
    absent = sorted(expected - set(sites))
    if absent:
        errors.append("Katalog multi-site belum memuat: " + ", ".join(absent))

    besai = sites.get("pltm_besai_kemu", {})
    catchment = besai.get("catchment", {}) if isinstance(besai, dict) else {}
    if not str(besai.get("site_status", "")).startswith("provisional"):
        errors.append("Besai Kemu harus tetap berstatus provisional sebelum verifikasi engineering")
    if catchment.get("area_km2") is not None:
        errors.append("Besai Kemu belum boleh memuat luas DAS sebelum delineasi terverifikasi")
    if catchment.get("status") != "not_yet_delineated":
        errors.append("Status batas DAS Besai Kemu harus not_yet_delineated")

    network = (outputs / "site_network.html").read_text(
        encoding="utf-8", errors="replace"
    )
    if "forecast-hydro-multisite-network-v1" not in network or "type:'globe'" not in network:
        errors.append("Halaman jaringan belum menggunakan globe multi-site yang aktif")
    if "PLTA Redelong" not in network or "PLTM Besai Kemu" not in network:
        errors.append("Halaman jaringan belum menampilkan kedua site")
    if 'href="index.html"' not in network:
        errors.append("Halaman jaringan belum memiliki link kembali ke homepage")

    homepage = (outputs / "index.html").read_text(encoding="utf-8", errors="replace")
    if 'href="site_network.html"' not in homepage:
        errors.append("Homepage belum memiliki tautan ke globe jaringan site")

    history = read_json(outputs / "besai_kemu_history.json", {}) or {}
    if history.get("observation_type") != "gridded_meteorological_proxy":
        errors.append("Histori Besai harus dilabeli sebagai proxy meteorologi gridded")
    history_rows = int(number(history.get("daily_rows")) or 0)
    if history_rows < 16000:
        errors.append("Histori Besai belum memuat sedikitnya 16.000 hari")

    forecast = read_json(outputs / "besai_kemu_forecast.json", []) or []
    if not isinstance(forecast, list) or not forecast:
        errors.append("Forecast publik Besai Kemu belum tersedia")
    elif any(int(number(day.get("model_count")) or 0) < MIN_MODELS for day in forecast):
        errors.append("Forecast Besai Kemu memiliki hari dengan kurang dari tiga model")

    metrics["multisite_catalog_sites"] = len(sites)
    metrics["multisite_besai_status"] = besai.get("site_status")
    metrics["multisite_besai_boundary_status"] = catchment.get("status")
    metrics["multisite_besai_history_days"] = history_rows
    metrics["multisite_besai_forecast_days"] = len(forecast) if isinstance(forecast, list) else 0


def check_discharge_products(outputs: Path, errors: list[str], metrics: dict[str, Any]) -> None:
    required = [
        "redelong_discharge.html",
        "redelong_discharge.json",
        "redelong_discharge_forecast.csv",
        "redelong_discharge_validation.csv",
        "redelong_discharge_hindcast_pairs.csv",
        "redelong_discharge_end_to_end_pairs.csv",
        "redelong_discharge_end_to_end_validation.csv",
        "hydrology/glofas_discharge_metadata.json",
    ]
    missing = [name for name in required if not (outputs / name).is_file()]
    if missing:
        errors.append("Produk forecast debit hilang: " + ", ".join(missing))
        return

    payload = read_json(outputs / "redelong_discharge.json", {}) or {}
    if payload.get("status") != "provisional_proxy_calibrated":
        errors.append("Forecast debit harus berstatus provisional_proxy_calibrated")
    if payload.get("can_claim_field_accuracy") is not False:
        errors.append("Forecast debit proxy tidak boleh mengklaim akurasi lapangan")
    end_to_end = payload.get("end_to_end_validation", {})
    if end_to_end.get("status") == "preliminary_proxy_skill" and int(
        number(end_to_end.get("matched_pairs")) or 0
    ) < 30:
        errors.append("Skill debit end-to-end memerlukan sedikitnya 30 pasangan matang")
    forecast = payload.get("forecast", []) if isinstance(payload, dict) else []
    leads = {int(number(row.get("lead_day")) or 0) for row in forecast}
    if leads != {1, 2, 3}:
        errors.append("Forecast debit harus memuat lead 1, 2, dan 3 hari")
    for row in forecast:
        low = number(row.get("discharge_scenario_low_m3s"))
        mean = number(row.get("discharge_forecast_m3s"))
        high = number(row.get("discharge_scenario_high_m3s"))
        if low is None or mean is None or high is None or not (0 <= low <= mean <= high):
            errors.append("Rentang forecast debit tidak valid atau tidak monoton")
            break

    validation = payload.get("validation", []) if isinstance(payload, dict) else []
    validation_leads = {int(number(row.get("lead_day")) or 0) for row in validation}
    if validation_leads != {1, 2, 3}:
        errors.append("Validasi debit harus dipisahkan untuk lead 1-3 hari")
    if any(int(number(row.get("n_samples")) or 0) < 365 for row in validation):
        errors.append("Validasi debit memerlukan sedikitnya 365 sampel per lead")

    metadata = read_json(outputs / "hydrology" / "glofas_discharge_metadata.json", {}) or {}
    if metadata.get("observation_type") != "simulated_gridded_discharge_proxy":
        errors.append("Referensi GloFAS harus dilabeli sebagai simulated gridded proxy")
    if int(number(metadata.get("history_rows")) or 0) < 8000:
        errors.append("Seri GloFAS untuk kalibrasi debit kurang dari 8.000 hari")

    page = (outputs / "redelong_discharge.html").read_text(encoding="utf-8", errors="replace")
    if "forecast-redelong-discharge-v1" not in page or "Belum field-calibrated" not in page:
        errors.append("Halaman debit belum memuat kontrak dan disclaimer proxy")
    operational = (outputs / "redelong_operational.html").read_text(encoding="utf-8", errors="replace")
    if "redelong_discharge.html" not in operational:
        errors.append("Dashboard operasional belum menautkan forecast debit")

    metrics["discharge_status"] = payload.get("status")
    metrics["discharge_forecast_leads"] = sorted(leads)
    metrics["discharge_validation_samples"] = {
        str(row.get("lead_day")): int(number(row.get("n_samples")) or 0)
        for row in validation
    }
    metrics["discharge_reference"] = metadata.get("source")
    metrics["discharge_reference_grid"] = metadata.get("selected_grid_coordinate")


def validate(outputs: Path) -> tuple[bool, dict[str, Any]]:
    errors: list[str] = []
    metrics: dict[str, Any] = {}
    check_forecast_contract(outputs, errors, metrics)
    check_operational_products(outputs, errors, metrics)
    check_spatial_contract(outputs, errors, metrics)
    check_portal_semantics(outputs, errors, metrics)
    check_public_branding(outputs, errors, metrics)
    check_branding_and_weights(outputs, errors, metrics)
    check_usability_basics(outputs, errors, metrics)
    check_evaluation_status(outputs, errors, metrics)
    check_geospatial_history(outputs, errors, metrics)
    check_multisite_catalog(outputs, errors, metrics)
    check_discharge_products(outputs, errors, metrics)
    check_inline_javascript(outputs, errors, metrics)
    report = {
        "schema_version": "forecast-hydro-publish-gate-v6",
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
