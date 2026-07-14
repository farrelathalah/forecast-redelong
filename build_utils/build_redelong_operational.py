"""Build the operator-facing PLTA Redelong rainfall products.

This module is intentionally kept separate from the legacy forecast engine.  It
consumes the engine's source-level CSV, applies transparent quality control,
aggregates the provisional GPM1--GPM6 analysis area, and publishes compact CSV,
JSON and HTML products.  BMKG remains official categorical guidance and is not
used as a quantitative rainfall member.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from datetime import datetime
from html import escape
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
POINTS_CSV = ROOT / "data" / "redelong" / "catchment_points.csv"
WIB = ZoneInfo("Asia/Jakarta")

# Independent quantitative products currently available through the existing
# Open-Meteo adapters.  Equal weighting is deliberate until local verification
# supports a different scheme.
QUANTITATIVE_SOURCES = (
    "CMA",
    "ECMWF",
    "GFS",
    "ICON",
    "METEOFRANCE",
    "UKMO",
)
BMKG_SOURCE = "BMKG"
MAX_PLAUSIBLE_HOURLY_RAIN_MM = 300.0
MIN_AREA_COVERAGE = 0.80
MIN_WINDOW_HOUR_COVERAGE = 0.80
MIN_MODELS = 3


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input forecast tidak ditemukan: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ya"}


def _json_value(value):
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    return value


def _records(frame: pd.DataFrame) -> list[dict]:
    return [
        {key: _json_value(value) for key, value in row.items()}
        for row in frame.to_dict(orient="records")
    ]


def _load_issue_time(outputs: Path) -> pd.Timestamp:
    summary_path = outputs / "forecast_batch_summary.json"
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8-sig"))
            parsed = pd.Timestamp(payload.get("generated_at"))
            if parsed.tzinfo is None:
                parsed = parsed.tz_localize(WIB)
            return parsed.tz_convert(WIB)
        except Exception:
            pass
    return pd.Timestamp.now(tz=WIB)


def _load_points() -> pd.DataFrame:
    points = pd.read_csv(POINTS_CSV, encoding="utf-8-sig")
    points["location_slug"] = (
        points["point_name"]
        .astype(str)
        .str.lower()
        .str.replace(r"[^a-z0-9]+", "_", regex=True)
        .str.strip("_")
    )
    points.loc[points["point_id"] == "plta", "location_slug"] = "plta_redelong"
    points.loc[points["point_name"] == "GPM Grid TamaTue", "location_slug"] = "gpm_grid_tamatue"
    points["weight_km2"] = pd.to_numeric(points["weight_km2"], errors="coerce").fillna(0.0)
    points["include_in_catchment"] = points["include_in_catchment"].map(_as_bool)
    return points


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def _prepare_raw(raw: pd.DataFrame) -> pd.DataFrame:
    required = {"location_slug", "target_date", "target_jam", "source_id", "rain_mm"}
    missing = sorted(required - set(raw.columns))
    if missing:
        raise ValueError(f"Kolom forecast kurang: {', '.join(missing)}")

    out = raw.copy()
    out["valid_time_wib"] = pd.to_datetime(
        out["target_date"].astype(str) + " " + out["target_jam"].astype(str),
        errors="coerce",
    ).dt.tz_localize(WIB, ambiguous="NaT", nonexistent="NaT")
    for col in ["rain_mm", "suhu_C", "RH_%", "wind_kmh"]:
        if col in out.columns:
            out[col] = pd.to_numeric(out[col], errors="coerce")
    out["rain_valid"] = (
        out["rain_mm"].notna()
        & out["rain_mm"].between(0.0, MAX_PLAUSIBLE_HOURLY_RAIN_MM)
    )
    return out.dropna(subset=["valid_time_wib"])


def _model_consensus(frame: pd.DataFrame, value_col: str, group_cols: list[str]) -> pd.DataFrame:
    rows: list[dict] = []
    for keys, group in frame.groupby(group_cols, dropna=False, sort=True):
        if not isinstance(keys, tuple):
            keys = (keys,)
        values = pd.to_numeric(group[value_col], errors="coerce").dropna()
        sources = sorted(group.loc[values.index, "source_id"].astype(str).unique()) if len(values) else []
        row = dict(zip(group_cols, keys))
        row.update(
            {
                "rain_mean_mm": values.mean() if len(values) else np.nan,
                "rain_median_mm": values.median() if len(values) else np.nan,
                "rain_p10_mm": values.quantile(0.10) if len(values) else np.nan,
                "rain_p90_mm": values.quantile(0.90) if len(values) else np.nan,
                "model_spread_mm": values.max() - values.min() if len(values) else np.nan,
                "model_count": int(len(values)),
                "model_list": ",".join(sources),
                "model_agreement_rain_pct": float((values >= 0.1).mean() * 100) if len(values) else np.nan,
                "data_status": "cukup" if len(values) >= MIN_MODELS else "data_tidak_cukup",
            }
        )
        rows.append(row)
    return pd.DataFrame(rows)


def _catchment_source_hourly(raw: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    included = points.loc[points["include_in_catchment"]].copy()
    total_area = included["weight_km2"].sum()
    data = raw[
        raw["source_id"].isin(QUANTITATIVE_SOURCES)
        & raw["location_slug"].isin(included["location_slug"])
        & raw["rain_valid"]
    ].merge(
        included[["location_slug", "point_name", "weight_km2"]],
        on="location_slug",
        how="inner",
    )

    # One value per model, point and valid hour.  Mean only resolves accidental
    # duplicate rows; it is not a spatial or model weighting operation.
    data = (
        data.groupby(
            ["valid_time_wib", "source_id", "location_slug", "point_name", "weight_km2"],
            as_index=False,
        )["rain_mm"]
        .mean()
    )

    rows: list[dict] = []
    for (valid_time, source), group in data.groupby(["valid_time_wib", "source_id"], sort=True):
        area_available = group["weight_km2"].sum()
        area_coverage = area_available / total_area if total_area else 0.0
        if area_available <= 0 or area_coverage < MIN_AREA_COVERAGE:
            continue
        basin_rain = float(np.average(group["rain_mm"], weights=group["weight_km2"]))
        rows.append(
            {
                "valid_time_wib": valid_time,
                "source_id": source,
                "rain_mm": basin_rain,
                "area_available_km2": area_available,
                "area_coverage_pct": area_coverage * 100,
            }
        )
    return pd.DataFrame(rows)


def _three_hour(source_hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if source_hourly.empty:
        return pd.DataFrame(), pd.DataFrame()
    data = source_hourly.copy()
    data["period_start_wib"] = data["valid_time_wib"].dt.floor("3h")
    source_3h = (
        data.groupby(["period_start_wib", "source_id"], as_index=False)
        .agg(rain_3h_mm=("rain_mm", "sum"), hours_available=("rain_mm", "count"))
    )
    source_3h["period_end_wib"] = source_3h["period_start_wib"] + pd.Timedelta(hours=3)
    source_3h["period_complete"] = source_3h["hours_available"] >= 3
    consensus = _model_consensus(source_3h, "rain_3h_mm", ["period_start_wib", "period_end_wib"])
    completeness = source_3h.groupby("period_start_wib")["period_complete"].mean()
    consensus["hour_coverage_pct"] = consensus["period_start_wib"].map(completeness).fillna(0) * 100
    consensus.loc[consensus["hour_coverage_pct"] < 80, "data_status"] = "periode_tidak_lengkap"
    return source_3h, consensus


def _window_totals(
    source_hourly: pd.DataFrame,
    forecast_start: pd.Timestamp,
    horizons: tuple[int, ...] = (24, 48, 72),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    source_rows: list[dict] = []
    for horizon in horizons:
        end = forecast_start + pd.Timedelta(hours=horizon)
        subset = source_hourly[
            (source_hourly["valid_time_wib"] >= forecast_start)
            & (source_hourly["valid_time_wib"] < end)
        ]
        for source, group in subset.groupby("source_id"):
            hours_available = int(group["valid_time_wib"].nunique())
            coverage = hours_available / horizon
            if coverage < MIN_WINDOW_HOUR_COVERAGE:
                continue
            source_rows.append(
                {
                    "window_start_wib": forecast_start,
                    "window_end_wib": end,
                    "horizon_hours": horizon,
                    "source_id": source,
                    "rain_total_mm": group["rain_mm"].sum(),
                    "hours_available": hours_available,
                    "hour_coverage_pct": coverage * 100,
                }
            )
    source_frame = pd.DataFrame(source_rows)
    if source_frame.empty:
        consensus = pd.DataFrame(
            [
                {
                    "window_start_wib": forecast_start,
                    "window_end_wib": forecast_start + pd.Timedelta(hours=h),
                    "horizon_hours": h,
                    "rain_mean_mm": np.nan,
                    "rain_median_mm": np.nan,
                    "rain_p10_mm": np.nan,
                    "rain_p90_mm": np.nan,
                    "model_spread_mm": np.nan,
                    "model_count": 0,
                    "model_list": "",
                    "model_agreement_rain_pct": np.nan,
                    "data_status": "data_tidak_cukup",
                }
                for h in horizons
            ]
        )
        return source_frame, consensus
    consensus = _model_consensus(
        source_frame,
        "rain_total_mm",
        ["window_start_wib", "window_end_wib", "horizon_hours"],
    )
    return source_frame, consensus


def _calendar_daily(source_hourly: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    if source_hourly.empty:
        return pd.DataFrame(), pd.DataFrame()
    data = source_hourly.copy()
    data["date_wib"] = data["valid_time_wib"].dt.date.astype(str)
    source_daily = (
        data.groupby(["date_wib", "source_id"], as_index=False)
        .agg(rain_daily_mm=("rain_mm", "sum"), hours_available=("rain_mm", "count"))
    )
    source_daily["hour_coverage_pct"] = source_daily["hours_available"] / 24 * 100
    daily = _model_consensus(source_daily, "rain_daily_mm", ["date_wib"])
    daily_coverage = source_daily.groupby("date_wib")["hour_coverage_pct"].mean()
    daily["hour_coverage_pct"] = daily["date_wib"].map(daily_coverage)
    daily.loc[daily["hour_coverage_pct"] < 80, "data_status"] = "hari_tidak_lengkap"
    return source_daily, daily


def _point_products(
    raw: pd.DataFrame,
    points: pd.DataFrame,
    forecast_start: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    data = raw[
        raw["source_id"].isin(QUANTITATIVE_SOURCES)
        & raw["rain_valid"]
        & raw["location_slug"].isin(points["location_slug"])
    ].copy()
    source_hourly = (
        data.groupby(["valid_time_wib", "source_id", "location_slug"], as_index=False)["rain_mm"]
        .mean()
    )
    hourly = _model_consensus(source_hourly, "rain_mm", ["valid_time_wib", "location_slug"])

    window_end = forecast_start + pd.Timedelta(hours=24)
    subset = source_hourly[
        (source_hourly["valid_time_wib"] >= forecast_start)
        & (source_hourly["valid_time_wib"] < window_end)
    ]
    rows: list[dict] = []
    for (location, source), group in subset.groupby(["location_slug", "source_id"]):
        count = int(group["valid_time_wib"].nunique())
        if count / 24 < MIN_WINDOW_HOUR_COVERAGE:
            continue
        rows.append(
            {
                "location_slug": location,
                "source_id": source,
                "rain_24h_mm": group["rain_mm"].sum(),
                "hours_available": count,
            }
        )
    point_source_24h = pd.DataFrame(rows)
    if point_source_24h.empty:
        point_24h = pd.DataFrame(columns=["location_slug", "rain_mean_mm", "rain_p10_mm", "rain_p90_mm", "model_count", "data_status"])
    else:
        point_24h = _model_consensus(point_source_24h, "rain_24h_mm", ["location_slug"])
    return hourly, point_24h


def _bmkg_guidance(raw: pd.DataFrame) -> pd.DataFrame:
    bmkg = raw[(raw["source_id"] == BMKG_SOURCE) & (raw["location_slug"] == "plta_redelong")].copy()
    if bmkg.empty:
        return pd.DataFrame()
    # BMKG guidance is categorical and can be published on a cadence that does
    # not land exactly on this system's target hours.  Preserve BMKG's own
    # valid timestamp instead of presenting the nearest target hour as if it
    # were the source timestamp.
    if "source_datetime" in bmkg.columns:
        def to_wib(value):
            parsed = pd.to_datetime(value, errors="coerce")
            if pd.isna(parsed):
                return pd.NaT
            if parsed.tzinfo is None:
                return parsed.tz_localize(WIB)
            return parsed.tz_convert(WIB)

        source_time = bmkg["source_datetime"].map(to_wib)
        bmkg.loc[source_time.notna(), "valid_time_wib"] = source_time[source_time.notna()]
    columns = [
        c
        for c in ["valid_time_wib", "source_datetime", "kategori", "suhu_C", "RH_%", "wind_kmh", "raw_condition"]
        if c in bmkg.columns
    ]
    if "source_datetime" in bmkg.columns:
        bmkg = bmkg.sort_values("valid_time_wib").drop_duplicates("source_datetime")
    return bmkg[columns].sort_values("valid_time_wib")


def _source_qc(raw: pd.DataFrame, source_hourly: pd.DataFrame, points: pd.DataFrame) -> pd.DataFrame:
    expected_points = int(points["include_in_catchment"].sum())
    # Operational contract is a continuous 72-hour horizon.  Comparing against
    # the hours that merely happened to arrive would make a sparse run look
    # falsely complete.
    expected_hours = 72
    rows: list[dict] = []
    for source in QUANTITATIVE_SOURCES:
        source_raw = raw[
            (raw["source_id"] == source)
            & raw["location_slug"].isin(points.loc[points["include_in_catchment"], "location_slug"])
        ]
        valid_rows = int(source_raw["rain_valid"].sum())
        expected_rows = expected_points * expected_hours
        completeness = valid_rows / expected_rows if expected_rows else 0.0
        basin_hours = int(source_hourly.loc[source_hourly["source_id"] == source, "valid_time_wib"].nunique())
        rows.append(
            {
                "source_id": source,
                "purpose": "multi-model_consensus_kuantitatif",
                "qc_status": "valid" if completeness >= 0.80 and basin_hours else "data_tidak_cukup",
                "valid_rows": valid_rows,
                "expected_rows": expected_rows,
                "completeness_pct": completeness * 100,
                "catchment_hours_available": basin_hours,
                "note": "Bobot sama; nilai kosong tidak dianggap 0 mm.",
            }
        )
    bmkg_rows = raw[(raw["source_id"] == BMKG_SOURCE) & (raw["location_slug"] == "plta_redelong")]
    rows.append(
        {
            "source_id": BMKG_SOURCE,
            "purpose": "panduan_resmi_kategoris",
            "qc_status": "tersedia" if len(bmkg_rows) else "tidak_tersedia",
            "valid_rows": len(bmkg_rows),
            "expected_rows": np.nan,
            "completeness_pct": np.nan,
            "catchment_hours_available": np.nan,
            "note": "Tidak dicampur sebagai rain_mm numerik.",
        }
    )
    rows.extend(
        [
            {
                "source_id": "KMA",
                "purpose": "dinonaktifkan",
                "qc_status": "nonaktif",
                "valid_rows": 0,
                "expected_rows": np.nan,
                "completeness_pct": np.nan,
                "catchment_hours_available": np.nan,
                "note": "Dinonaktifkan karena data operasional kosong/tidak tersedia.",
            },
            {
                "source_id": "METNO",
                "purpose": "dinonaktifkan_dari_consensus",
                "qc_status": "nonaktif",
                "valid_rows": 0,
                "expected_rows": np.nan,
                "completeness_pct": np.nan,
                "catchment_hours_available": np.nan,
                "note": "Tidak dihitung sebagai model independen dari ECMWF untuk wilayah global.",
            },
        ]
    )
    return pd.DataFrame(rows)


def _write_csv(frame: pd.DataFrame, path: Path) -> None:
    output = frame.copy()
    for col in output.columns:
        if "time" in col and pd.api.types.is_datetime64_any_dtype(output[col]):
            output[col] = output[col].map(lambda value: value.isoformat() if pd.notna(value) else "")
    output.to_csv(path, index=False, encoding="utf-8-sig")


def _fmt(value, digits: int = 1, suffix: str = "") -> str:
    try:
        if value is None or pd.isna(value):
            return "Data belum cukup"
        return f"{float(value):.{digits}f}{suffix}"
    except Exception:
        return "Data belum cukup"


def _metric_from_window(windows: pd.DataFrame, horizon: int, column: str = "rain_mean_mm"):
    row = windows.loc[windows["horizon_hours"] == horizon]
    if row.empty:
        return np.nan
    return row.iloc[0].get(column, np.nan)


def _rain_color(value) -> str:
    if value is None or pd.isna(value):
        return "#94a3b8"
    if value < 5:
        return "#38bdf8"
    if value < 20:
        return "#2563eb"
    if value < 50:
        return "#7c3aed"
    return "#be123c"


def _status_label(value) -> str:
    key = str(value or "").strip().lower()
    labels = {
        "cukup": "Data cukup",
        "valid": "Valid",
        "tersedia": "Tersedia",
        "hari_lengkap": "Hari lengkap",
        "periode_lengkap": "Periode lengkap",
        "data_tidak_cukup": "Data belum cukup",
        "hari_tidak_lengkap": "Hari belum lengkap",
        "periode_tidak_lengkap": "Periode belum lengkap",
        "nonaktif": "Nonaktif",
    }
    return labels.get(key, key.replace("_", " ").capitalize() or "Belum tersedia")


def _status_tone(value) -> str:
    key = str(value or "").strip().lower()
    if key in {"cukup", "valid", "tersedia", "hari_lengkap", "periode_lengkap"}:
        return "ok"
    if key == "nonaktif":
        return "muted"
    return "warn"


def _date_label(value) -> tuple[str, str]:
    try:
        date = pd.Timestamp(value)
    except Exception:
        return str(value), ""
    days = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
    months = [
        "Januari", "Februari", "Maret", "April", "Mei", "Juni",
        "Juli", "Agustus", "September", "Oktober", "November", "Desember",
    ]
    return days[date.weekday()], f"{date.day} {months[date.month - 1]} {date.year}"


def _three_hour_chart_svg(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "<div class='empty-state'><div class='empty-icon'>∿</div><b>Data 3 jam belum tersedia</b><span>Grafik akan muncul setelah run per-jam selesai.</span></div>"

    chart = frame.head(24).copy()
    if "data_status" in chart.columns:
        chart = chart[chart["data_status"].astype(str).eq("cukup")]
    chart["rain_mean_mm"] = pd.to_numeric(chart.get("rain_mean_mm"), errors="coerce")
    chart["rain_p10_mm"] = pd.to_numeric(chart.get("rain_p10_mm"), errors="coerce")
    chart["rain_p90_mm"] = pd.to_numeric(chart.get("rain_p90_mm"), errors="coerce")
    chart = chart.dropna(subset=["rain_mean_mm"])
    if len(chart) < 2:
        return "<div class='empty-state'><div class='empty-icon'>∿</div><b>Coverage belum cukup untuk digrafikkan</b><span>Nilai parsial tidak ditampilkan agar tidak disalahartikan sebagai akumulasi 3 jam lengkap.</span></div>"

    width, height = 960.0, 300.0
    left, right, top, bottom = 56.0, 18.0, 20.0, 54.0
    plot_w, plot_h = width - left - right, height - top - bottom
    means = chart["rain_mean_mm"].astype(float).tolist()
    p10 = chart["rain_p10_mm"].fillna(chart["rain_mean_mm"]).astype(float).tolist()
    p90 = chart["rain_p90_mm"].fillna(chart["rain_mean_mm"]).astype(float).tolist()
    ymax = max(max(p90), max(means), 1.0) * 1.12
    count = len(chart)

    def x_at(index: int) -> float:
        return left + (plot_w * index / max(count - 1, 1))

    def y_at(value: float) -> float:
        return top + plot_h - (max(value, 0.0) / ymax * plot_h)

    upper = [(x_at(i), y_at(value)) for i, value in enumerate(p90)]
    lower = [(x_at(i), y_at(value)) for i, value in enumerate(p10)]
    mean_points = [(x_at(i), y_at(value)) for i, value in enumerate(means)]
    band_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in [*upper, *reversed(lower)])
    line_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in mean_points)

    grid = []
    for fraction in [0.0, 0.25, 0.5, 0.75, 1.0]:
        y = top + plot_h - fraction * plot_h
        label = ymax * fraction
        grid.append(
            f"<line x1='{left:.0f}' y1='{y:.1f}' x2='{width-right:.0f}' y2='{y:.1f}' stroke='#dbe7f2' stroke-width='1'/>"
            f"<text x='{left-10:.0f}' y='{y+4:.1f}' text-anchor='end' fill='#71839a' font-size='11'>{label:.1f}</text>"
        )

    x_labels = []
    label_step = max(1, math.ceil(count / 8))
    for i, (_, row) in enumerate(chart.iterrows()):
        if i % label_step and i != count - 1:
            continue
        stamp = pd.Timestamp(row["period_end_wib"])
        x_labels.append(
            f"<text x='{x_at(i):.1f}' y='{height-25:.0f}' text-anchor='middle' fill='#71839a' font-size='10'>"
            f"<tspan x='{x_at(i):.1f}'>{stamp.strftime('%d/%m')}</tspan>"
            f"<tspan x='{x_at(i):.1f}' dy='13'>{stamp.strftime('%H:%M')}</tspan></text>"
        )

    dots = []
    for i, ((x, y), value) in enumerate(zip(mean_points, means)):
        stamp = pd.Timestamp(chart.iloc[i]["period_end_wib"]).strftime("%d/%m/%Y %H:%M WIB")
        dots.append(
            f"<circle cx='{x:.1f}' cy='{y:.1f}' r='4.5' fill='#ffffff' stroke='#0284c7' stroke-width='3'>"
            f"<title>{escape(stamp)} · mean {value:.2f} mm · P10–P90 {p10[i]:.2f}–{p90[i]:.2f} mm</title></circle>"
        )

    return (
        "<div class='chart-legend'><span><i class='legend-line'></i>Mean</span>"
        "<span><i class='legend-band'></i>Rentang P10–P90 antar-model</span></div>"
        f"<svg class='rain-chart' viewBox='0 0 {width:.0f} {height:.0f}' role='img' aria-label='Grafik akumulasi hujan area tiga jam'>"
        + "".join(grid)
        + f"<polygon points='{band_points}' fill='#bae6fd' fill-opacity='.62'/>"
        + f"<polyline points='{line_points}' fill='none' stroke='#0284c7' stroke-width='4' stroke-linejoin='round' stroke-linecap='round'/>"
        + "".join(dots)
        + "".join(x_labels)
        + f"<text x='14' y='{top + plot_h/2:.1f}' transform='rotate(-90 14 {top + plot_h/2:.1f})' fill='#71839a' font-size='11' text-anchor='middle'>Hujan (mm/3 jam)</text>"
        + "</svg>"
    )


def _build_geojson(points: pd.DataFrame, point_24h: pd.DataFrame) -> dict:
    merged = points.merge(
        point_24h[["location_slug", "rain_mean_mm", "rain_p10_mm", "rain_p90_mm", "model_count", "data_status"]],
        on="location_slug",
        how="left",
    )
    plta = points.loc[points["location_slug"] == "plta_redelong"].iloc[0]
    features = []
    for _, row in merged.iterrows():
        distance = _haversine_km(float(plta["lat"]), float(plta["lon"]), float(row["lat"]), float(row["lon"]))
        props = {
            "location_slug": row["location_slug"],
            "name": row["point_name"],
            "operational_role": row["operational_role"],
            "include_in_catchment": bool(row["include_in_catchment"]),
            "area_km2": _json_value(row["weight_km2"]),
            "distance_from_plta_km": round(distance, 2),
            "rain_24h_mean_mm": _json_value(row.get("rain_mean_mm")),
            "rain_24h_p10_mm": _json_value(row.get("rain_p10_mm")),
            "rain_24h_p90_mm": _json_value(row.get("rain_p90_mm")),
            "model_count": _json_value(row.get("model_count")),
            "data_status": row.get("data_status") if isinstance(row.get("data_status"), str) else "data_tidak_cukup",
            "note": row.get("note", ""),
        }
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [float(row["lon"]), float(row["lat"])]},
                "properties": props,
            }
        )
    return {"type": "FeatureCollection", "features": features}


def _map_html(geojson: dict) -> str:
    data = json.dumps(geojson, ensure_ascii=False).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Peta area analisis Redelong</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<style>
:root{{--navy:#0b2545;--blue:#0ea5e9;--amber:#f59e0b;--ink:#17324d;--muted:#64748b}}
html,body,#map{{height:100%;margin:0}}body{{font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif;background:#dce8f3}}
.map-title{{position:absolute;z-index:650;left:16px;top:16px;max-width:280px;background:rgba(255,255,255,.94);backdrop-filter:blur(16px);padding:13px 15px;border:1px solid rgba(255,255,255,.85);border-radius:16px;box-shadow:0 14px 38px rgba(11,37,69,.18)}}
.map-title span{{display:block;color:#0284c7;font-size:10px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;margin-bottom:4px}}.map-title b{{font-size:15px;color:var(--ink)}}.map-title small{{display:block;color:var(--muted);line-height:1.45;margin-top:5px}}
.legend{{background:rgba(255,255,255,.95);backdrop-filter:blur(14px);padding:12px 14px;border:1px solid rgba(255,255,255,.9);border-radius:14px;box-shadow:0 12px 32px rgba(11,37,69,.16);line-height:1.75;font-size:11px;color:var(--ink)}}.legend strong{{display:block;font-size:12px;margin-bottom:3px}}.legend i{{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:7px;box-shadow:0 0 0 3px rgba(255,255,255,.8)}}
.leaflet-popup-content-wrapper{{border-radius:16px;box-shadow:0 16px 42px rgba(11,37,69,.22)}}.leaflet-popup-content{{line-height:1.55;color:var(--ink);min-width:210px}}.leaflet-popup-content b{{font-size:14px}}
.leaflet-interactive{{filter:drop-shadow(0 4px 5px rgba(11,37,69,.28))}}.point-label{{border:0;background:rgba(11,37,69,.88);color:#fff;font-size:9px;font-weight:750;padding:3px 6px;border-radius:6px;box-shadow:none}}.point-label:before{{display:none}}
.leaflet-control-zoom{{border:0!important;box-shadow:0 8px 24px rgba(11,37,69,.16)!important}}.leaflet-control-zoom a{{color:var(--ink)!important;border:0!important}}
@media(max-width:620px){{.map-title{{left:10px;top:10px;right:58px;max-width:none}}.map-title small{{display:none}}.legend{{font-size:10px}}}}
</style></head>
<body><div id="map"></div><div class="map-title"><span>Area analisis</span><b>GPM1–GPM6 dan PLTA Redelong</b><small>TamaTue tetap terlihat sebagai pembanding eksternal, tetapi tidak masuk agregasi hujan.</small></div><script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script><script>
const data={data};
const map=L.map('map',{{zoomControl:false}}).setView([4.77,96.94],11);
L.control.zoom({{position:'topright'}}).addTo(map);
L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png',{{maxZoom:18,attribution:'&copy; OpenStreetMap contributors'}}).addTo(map);
const colors={{provisional_catchment:'#0ea5e9',external_comparison:'#f59e0b',outlet_reference:'#0b2545'}};
const bounds=[]; let plta=null,tama=null;
data.features.forEach(f=>{{
 const p=f.properties, latlng=[f.geometry.coordinates[1],f.geometry.coordinates[0]]; bounds.push(latlng);
 const marker=L.circleMarker(latlng,{{radius:p.include_in_catchment?10:9,color:'#fff',weight:3,fillColor:colors[p.operational_role]||'#64748b',fillOpacity:.96}}).addTo(map);
 const rain=p.rain_24h_mean_mm==null?'Data belum cukup':p.rain_24h_mean_mm.toFixed(1)+' mm';
 const role=p.operational_role==='provisional_catchment'?'Area analisis provisional':p.operational_role==='external_comparison'?'Titik pembanding eksternal':'Titik PLTA';
 marker.bindPopup(`<b>${{p.name}}</b><br>${{role}}<br>Jarak dari PLTA: ${{p.distance_from_plta_km.toFixed(1)}} km<br>Hujan 24 jam: <b>${{rain}}</b><br>Luas bobot: ${{p.area_km2.toFixed(2)}} km²<br><small>${{p.note||''}}</small>`);
 marker.bindTooltip(p.name,{{permanent:true,direction:'top',offset:[0,-10],className:'point-label'}});
 if(p.location_slug==='plta_redelong')plta=latlng;if(p.location_slug==='gpm_grid_tamatue')tama=latlng;
}});
if(plta&&tama)L.polyline([plta,tama],{{color:'#f59e0b',dashArray:'8 8',weight:2.5,opacity:.9}}).addTo(map).bindTooltip('TamaTue ±17,8 km dari PLTA; tidak masuk agregasi');
map.fitBounds(bounds,{{paddingTopLeft:[32,100],paddingBottomRight:[32,32]}});
L.control({{position:'bottomright'}}).onAdd=function(){{const d=L.DomUtil.create('div','legend');d.innerHTML='<strong>Status spasial</strong><i style="background:#0ea5e9"></i>GPM1–GPM6 · dihitung<br><i style="background:#f59e0b"></i>TamaTue · pembanding<br><i style="background:#0b2545"></i>PLTA · referensi';return d}}.addTo(map);
</script></body></html>"""


def _dashboard_html(
    issue_time: pd.Timestamp,
    forecast_start: pd.Timestamp,
    points: pd.DataFrame,
    windows: pd.DataFrame,
    three_hour: pd.DataFrame,
    daily: pd.DataFrame,
    point_24h: pd.DataFrame,
    source_qc: pd.DataFrame,
) -> str:
    area = points.loc[points["include_in_catchment"], "weight_km2"].sum()
    rain24 = _metric_from_window(windows, 24)
    rain48 = _metric_from_window(windows, 48)
    rain24low = _metric_from_window(windows, 24, "rain_p10_mm")
    rain24high = _metric_from_window(windows, 24, "rain_p90_mm")
    rain72 = _metric_from_window(windows, 72)
    model24 = _metric_from_window(windows, 24, "model_count")
    gross_volume = rain24 * area * 1000 if pd.notna(rain24) else np.nan
    forecast_end = forecast_start + pd.Timedelta(hours=72)

    window_24 = windows.loc[windows["horizon_hours"] == 24]
    status_24 = window_24.iloc[0].get("data_status", "data_tidak_cukup") if not window_24.empty else "data_tidak_cukup"
    status_24_label = _status_label(status_24)
    status_24_tone = _status_tone(status_24)
    snapshot_value_class = " missing" if pd.isna(rain24) else ""
    chart_html = _three_hour_chart_svg(three_hour)
    scenario_24_note = (
        f"Skenario P10–P90 {_fmt(rain24low,1)}–{_fmt(rain24high,1)} mm"
        if pd.notna(rain24low) and pd.notna(rain24high)
        else "Menunggu coverage per-jam yang lengkap"
    )

    included_24 = point_24h.merge(
        points.loc[points["include_in_catchment"], ["location_slug", "point_name"]],
        on="location_slug",
        how="inner",
    )
    if included_24.empty or included_24["rain_mean_mm"].isna().all():
        wettest = "Data belum cukup"
    else:
        wet = included_24.loc[included_24["rain_mean_mm"].idxmax()]
        wettest = f"{wet['point_name']} · {_fmt(wet['rain_mean_mm'], 1, ' mm')}"

    daily_cards = []
    for _, row in daily.iterrows():
        day_name, date_text = _date_label(row.get("date_wib"))
        status = row.get("data_status", "data_tidak_cukup")
        tone = _status_tone(status)
        daily_cards.append(
            f"<article class='day-card'><div class='day-top'><div><span>{escape(day_name)}</span><b>{escape(date_text)}</b></div>"
            f"<em class='pill {tone}'>{escape(_status_label(status))}</em></div>"
            f"<strong>{_fmt(row.get('rain_mean_mm'),1,' mm')}</strong><small>Mean hujan area</small>"
            f"<div class='day-meta'><span>P10–P90 <b>{_fmt(row.get('rain_p10_mm'),1)}–{_fmt(row.get('rain_p90_mm'),1)} mm</b></span>"
            f"<span>Model <b>{int(row.get('model_count') or 0)}</b></span></div></article>"
        )
    daily_html = "".join(daily_cards) or "<div class='empty-state compact'><b>Ringkasan harian belum tersedia</b><span>Menunggu run per-jam pertama.</span></div>"

    purpose_labels = {
        "multi-model_consensus_kuantitatif": "Konsensus kuantitatif",
        "panduan_resmi_kategoris": "Panduan resmi kategoris",
        "dinonaktifkan": "Dinonaktifkan",
        "dinonaktifkan_dari_consensus": "Tidak masuk konsensus",
    }
    source_rows = []
    for _, row in source_qc.iterrows():
        completeness = row.get("completeness_pct")
        progress = 0.0 if pd.isna(completeness) else max(0.0, min(float(completeness), 100.0))
        completeness_text = "—" if pd.isna(completeness) else f"{float(completeness):.0f}%"
        status = row.get("qc_status", "data_tidak_cukup")
        purpose = purpose_labels.get(str(row.get("purpose", "")), str(row.get("purpose", "")).replace("_", " ").capitalize())
        source_rows.append(
            f"<tr><td><div class='source-name'><span>{escape(str(row['source_id'])[:2])}</span><b>{escape(str(row['source_id']))}</b></div></td>"
            f"<td>{escape(purpose)}</td><td><span class='pill {_status_tone(status)}'>{escape(_status_label(status))}</span></td>"
            f"<td><div class='coverage'><div><i style='width:{progress:.0f}%'></i></div><b>{completeness_text}</b></div></td>"
            f"<td class='note-cell'>{escape(str(row['note']))}</td></tr>"
        )
    source_rows_html = "".join(source_rows)

    downloads = [
        ("CSV", "Forecast 3 jam", "Timing dan rentang antar-model", "operational_3hour.csv", "primary"),
        ("CSV", "Akumulasi 24/48/72 jam", "Ringkasan horizon operasi", "operational_windows.csv", ""),
        ("CSV", "Per area GPM", "Perbandingan setiap titik", "operational_per_point_24h.csv", ""),
        ("CSV", "Status sumber", "Kelengkapan dan quality control", "operational_source_status.csv", ""),
        ("CSV", "Panduan BMKG", "Kategori resmi tanpa rain proxy", "bmkg_guidance.csv", ""),
        ("JSON", "API operasional", "Payload untuk integrasi lanjutan", "redelong_operational.json", ""),
        ("QC", "Status validasi", "Aturan dan kesiapan evaluasi", "validation_status.html", ""),
        ("PORTAL", "Dashboard utama", "Kembali ke peta, overview, dan dashboard per titik", "index.html", ""),
    ]
    download_html = "".join(
        f"<a class='download-card {tone}' href='{href}'><span>{kind}</span><div><b>{escape(title)}</b><small>{escape(note)}</small></div><em>↗</em></a>"
        for kind, title, note, href, tone in downloads
    )

    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Forecast Operasional PLTA Redelong</title><meta name="theme-color" content="#082f49"><style>
:root{{--ink:#102a43;--muted:#6b7c93;--line:#dce6f0;--blue:#0284c7;--sky:#0ea5e9;--cyan:#22d3ee;--navy:#082f49;--deep:#061f33;--surface:#f3f7fb;--white:#fff;--amber:#d97706;--green:#15803d;--shadow:0 18px 55px rgba(8,47,73,.09)}}
*{{box-sizing:border-box}}html{{scroll-behavior:smooth}}body{{margin:0;background:radial-gradient(circle at 8% 0,rgba(14,165,233,.10),transparent 28%),radial-gradient(circle at 92% 8%,rgba(34,211,238,.08),transparent 26%),var(--surface);color:var(--ink);font-family:Inter,ui-sans-serif,system-ui,-apple-system,Segoe UI,sans-serif}}a{{color:inherit}}.shell{{max-width:1380px;margin:auto;padding:0 28px 38px}}
.topbar{{height:78px;display:flex;align-items:center;justify-content:space-between;gap:24px}}.brand{{display:flex;align-items:center;gap:12px;text-decoration:none}}.brand-mark{{width:42px;height:42px;border-radius:13px;background:linear-gradient(145deg,#075985,#0ea5e9 65%,#67e8f9);display:grid;place-items:center;color:#fff;font-weight:900;letter-spacing:-.04em;box-shadow:0 10px 24px rgba(2,132,199,.25)}}.brand b{{display:block;font-size:15px}}.brand small{{display:block;color:var(--muted);font-size:10px;letter-spacing:.12em;text-transform:uppercase;margin-top:2px}}.nav{{display:flex;align-items:center;gap:6px}}.nav a{{text-decoration:none;color:#48627a;font-size:12px;font-weight:700;padding:9px 11px;border-radius:10px}}.nav a:hover{{background:#fff;color:var(--blue)}}.live{{display:flex;align-items:center;gap:7px;background:#e8f7ee;color:#166534;border:1px solid #cdebd8;border-radius:999px;padding:8px 11px;font-size:11px;font-weight:800}}.live i{{width:7px;height:7px;border-radius:50%;background:#22c55e;box-shadow:0 0 0 5px rgba(34,197,94,.12)}}
.hero{{position:relative;overflow:hidden;background:linear-gradient(130deg,#061f33 0%,#0b4465 57%,#087da5 100%);color:#fff;border-radius:30px;padding:46px;box-shadow:0 28px 72px rgba(8,47,73,.24)}}.hero:before{{content:"";position:absolute;width:420px;height:420px;border:1px solid rgba(255,255,255,.11);border-radius:50%;right:-140px;top:-210px;box-shadow:0 0 0 58px rgba(255,255,255,.035),0 0 0 118px rgba(255,255,255,.025)}}.hero:after{{content:"";position:absolute;inset:0;background:linear-gradient(115deg,transparent 58%,rgba(103,232,249,.09));pointer-events:none}}.hero-grid{{position:relative;z-index:1;display:grid;grid-template-columns:minmax(0,1.45fr) minmax(320px,.55fr);gap:42px;align-items:center}}.eyebrow{{display:flex;align-items:center;gap:9px;color:#a5f3fc;font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:800}}.eyebrow i{{width:22px;height:2px;background:#67e8f9}}h1{{font-size:clamp(38px,5vw,68px);line-height:1.01;letter-spacing:-.045em;margin:14px 0 16px;max-width:780px}}.hero-copy>p{{max-width:740px;color:#d9eef8;font-size:16px;line-height:1.72;margin:0}}.meta{{display:flex;flex-wrap:wrap;gap:9px;margin-top:24px}}.chip{{background:rgba(255,255,255,.09);border:1px solid rgba(255,255,255,.14);padding:8px 10px;border-radius:9px;font-size:11px;color:#e5f7ff}}.hero-actions{{display:flex;gap:10px;flex-wrap:wrap;margin-top:26px}}.button{{display:inline-flex;align-items:center;gap:8px;text-decoration:none;padding:11px 14px;border-radius:11px;font-size:12px;font-weight:800;border:1px solid rgba(255,255,255,.16)}}.button.primary{{background:#fff;color:#075985;border-color:#fff}}.button.secondary{{background:rgba(255,255,255,.08);color:#fff}}
.snapshot{{background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.16);border-radius:22px;padding:22px;backdrop-filter:blur(14px);box-shadow:inset 0 1px rgba(255,255,255,.08)}}.snapshot-top{{display:flex;justify-content:space-between;gap:12px;align-items:start}}.snapshot-top span{{display:block;color:#b9deed;font-size:10px;text-transform:uppercase;letter-spacing:.12em;font-weight:800}}.snapshot-top b{{display:block;font-size:15px;margin-top:5px}}.snapshot-value{{font-size:clamp(32px,4vw,52px);font-weight:850;letter-spacing:-.04em;margin:22px 0 3px}}.snapshot-value.missing{{font-size:27px;line-height:1.15;letter-spacing:-.025em}}.snapshot>small{{color:#cde8f3}}.snapshot-grid{{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:20px}}.snapshot-grid div{{background:rgba(2,31,51,.24);border:1px solid rgba(255,255,255,.09);padding:12px;border-radius:13px}}.snapshot-grid span{{display:block;color:#b9deed;font-size:9px;text-transform:uppercase;letter-spacing:.09em}}.snapshot-grid b{{display:block;margin-top:5px;font-size:14px}}
.notice{{display:grid;grid-template-columns:auto 1fr auto;gap:14px;align-items:center;margin:18px 0 0;background:#fffaf0;border:1px solid #fde7bd;border-radius:18px;padding:15px 17px;box-shadow:0 8px 25px rgba(180,83,9,.05)}}.notice-icon{{width:38px;height:38px;border-radius:12px;background:#fff0cf;color:#b45309;display:grid;place-items:center;font-weight:900}}.notice b{{display:block;font-size:13px}}.notice p{{margin:3px 0 0;color:#7c5a26;line-height:1.5;font-size:12px}}.notice-tag{{background:#fff0cf;color:#9a4d08;border-radius:999px;padding:7px 10px;font-size:10px;font-weight:850;white-space:nowrap}}
.section{{margin-top:38px}}.section-head{{display:flex;align-items:end;justify-content:space-between;gap:24px;margin-bottom:16px}}.section-kicker{{display:block;color:var(--blue);font-size:10px;letter-spacing:.14em;text-transform:uppercase;font-weight:850;margin-bottom:6px}}h2{{font-size:clamp(24px,3vw,34px);letter-spacing:-.035em;margin:0}}.section-head p{{max-width:520px;color:var(--muted);font-size:12px;line-height:1.55;margin:0;text-align:right}}
.kpi-grid{{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));gap:13px}}.metric-card{{position:relative;overflow:hidden;background:#fff;border:1px solid var(--line);border-radius:19px;padding:17px;box-shadow:0 10px 32px rgba(8,47,73,.055);transition:transform .2s,box-shadow .2s}}.metric-card:hover{{transform:translateY(-3px);box-shadow:var(--shadow)}}.metric-card:after{{content:"";position:absolute;right:-24px;top:-32px;width:90px;height:90px;border-radius:50%;background:rgba(14,165,233,.055)}}.metric-icon{{width:36px;height:36px;border-radius:11px;background:#e8f6fc;color:#036b9f;display:grid;place-items:center;font-size:10px;font-weight:900;letter-spacing:.03em;margin-bottom:19px}}.metric-card>span{{display:block;color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.1em;font-weight:800}}.metric-card>strong{{display:block;font-size:clamp(20px,2.1vw,29px);letter-spacing:-.035em;margin:7px 0 5px;min-height:35px}}.metric-card>small{{display:block;color:var(--muted);line-height:1.45;font-size:10px}}
.panel{{background:#fff;border:1px solid var(--line);border-radius:22px;box-shadow:0 12px 38px rgba(8,47,73,.06);padding:20px}}.analytics{{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(360px,.7fr);gap:14px}}.panel-head{{display:flex;justify-content:space-between;gap:16px;align-items:start;margin-bottom:14px}}.panel-head span{{display:block;color:var(--blue);font-size:9px;text-transform:uppercase;letter-spacing:.12em;font-weight:850;margin-bottom:5px}}.panel-head h3{{margin:0;font-size:20px;letter-spacing:-.025em}}.panel-head p{{margin:0;color:var(--muted);font-size:10px;text-align:right;line-height:1.5}}.chart-wrap{{min-height:330px;display:flex;flex-direction:column;justify-content:center}}.rain-chart{{width:100%;height:auto;min-height:285px}}.chart-legend{{display:flex;justify-content:flex-end;gap:16px;color:var(--muted);font-size:10px;margin:3px 8px 0}}.chart-legend span{{display:flex;align-items:center;gap:6px}}.legend-line{{width:20px;height:3px;background:#0284c7;border-radius:99px}}.legend-band{{width:20px;height:9px;background:#bae6fd;border-radius:3px}}.map-frame{{width:100%;height:400px;border:0;border-radius:16px;background:#dce8f3}}
.empty-state{{min-height:285px;border:1px dashed #cbdce9;border-radius:16px;background:linear-gradient(145deg,#f8fbfd,#f1f7fb);display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center;padding:28px;color:var(--muted)}}.empty-state b{{color:var(--ink);font-size:14px;margin-bottom:6px}}.empty-state span{{max-width:430px;font-size:11px;line-height:1.55}}.empty-icon{{font-size:42px;color:#38bdf8;line-height:1;margin-bottom:11px}}.empty-state.compact{{min-height:150px;grid-column:1/-1}}
.day-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:13px}}.day-card{{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px;box-shadow:0 9px 28px rgba(8,47,73,.05)}}.day-top{{display:flex;justify-content:space-between;gap:10px;align-items:start}}.day-top span{{display:block;color:var(--blue);font-size:10px;font-weight:850;text-transform:uppercase;letter-spacing:.1em}}.day-top b{{display:block;font-size:12px;margin-top:4px}}.day-card>strong{{display:block;font-size:26px;letter-spacing:-.04em;margin:21px 0 2px}}.day-card>small{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.08em}}.day-meta{{display:flex;justify-content:space-between;gap:12px;border-top:1px solid #edf2f7;margin-top:15px;padding-top:12px}}.day-meta span{{color:var(--muted);font-size:9px}}.day-meta b{{display:block;color:var(--ink);margin-top:3px;font-size:10px}}
.pill{{display:inline-flex;align-items:center;border-radius:999px;padding:5px 8px;font-style:normal;font-size:9px;font-weight:850;white-space:nowrap}}.pill.ok{{background:#e8f7ee;color:#166534}}.pill.warn{{background:#fff4dd;color:#9a4d08}}.pill.muted{{background:#edf2f7;color:#64748b}}
.table-wrap{{overflow:auto;border:1px solid #e5edf4;border-radius:15px}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{text-align:left;padding:12px 11px;border-bottom:1px solid #edf2f7;vertical-align:middle}}th{{background:#f8fafc;color:#71839a;font-size:8px;text-transform:uppercase;letter-spacing:.1em;white-space:nowrap}}tr:last-child td{{border-bottom:0}}.source-name{{display:flex;align-items:center;gap:8px}}.source-name span{{width:29px;height:29px;border-radius:9px;background:#e8f6fc;color:#036b9f;display:grid;place-items:center;font-size:8px;font-weight:900}}.source-name b{{font-size:11px}}.coverage{{display:flex;align-items:center;gap:8px;min-width:120px}}.coverage>div{{height:6px;flex:1;background:#e9f0f6;border-radius:99px;overflow:hidden}}.coverage i{{display:block;height:100%;background:linear-gradient(90deg,#38bdf8,#0284c7);border-radius:99px}}.coverage b{{font-size:9px;min-width:27px}}.note-cell{{max-width:380px;color:var(--muted);line-height:1.45}}
.download-grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:11px}}.download-card{{display:grid;grid-template-columns:auto 1fr auto;align-items:center;gap:11px;text-decoration:none;background:#fff;border:1px solid var(--line);border-radius:16px;padding:13px;transition:.2s;box-shadow:0 7px 20px rgba(8,47,73,.04)}}.download-card:hover{{transform:translateY(-2px);border-color:#8ed4f0;box-shadow:0 12px 28px rgba(8,47,73,.09)}}.download-card>span{{width:38px;height:38px;border-radius:10px;background:#eef6fb;color:#075985;display:grid;place-items:center;font-size:8px;font-weight:900}}.download-card b{{display:block;font-size:11px}}.download-card small{{display:block;color:var(--muted);font-size:9px;line-height:1.4;margin-top:3px}}.download-card em{{font-style:normal;color:#7c95aa;font-size:14px}}.download-card.primary{{background:linear-gradient(135deg,#075985,#0284c7);border-color:#075985;color:#fff}}.download-card.primary>span{{background:rgba(255,255,255,.14);color:#fff}}.download-card.primary small,.download-card.primary em{{color:#d8f2fd}}
.foot{{margin:26px 2px 0;padding-top:20px;border-top:1px solid #dbe6ef;color:var(--muted);font-size:9px;line-height:1.6;display:flex;justify-content:space-between;gap:24px}}.foot b{{color:var(--ink)}}
@media(max-width:1080px){{.hero-grid{{grid-template-columns:1fr}}.snapshot{{max-width:520px}}.kpi-grid{{grid-template-columns:repeat(3,1fr)}}.analytics{{grid-template-columns:1fr}}.day-grid,.download-grid{{grid-template-columns:repeat(2,1fr)}}}}
@media(max-width:720px){{.shell{{padding:0 14px 24px}}.topbar{{height:68px}}.nav{{display:none}}.hero{{padding:27px 20px;border-radius:22px}}.hero-grid{{gap:25px}}h1{{font-size:39px}}.notice{{grid-template-columns:auto 1fr}}.notice-tag{{grid-column:1/-1;justify-self:start;margin-left:52px}}.section-head{{align-items:start;flex-direction:column;gap:8px}}.section-head p{{text-align:left}}.kpi-grid{{grid-template-columns:repeat(2,1fr)}}.day-grid,.download-grid{{grid-template-columns:1fr}}.panel{{padding:14px}}.panel-head{{flex-direction:column}}.panel-head p{{text-align:left}}.map-frame{{height:360px}}.foot{{flex-direction:column}}}}
@media(max-width:430px){{.kpi-grid{{grid-template-columns:1fr}}.snapshot-grid{{grid-template-columns:1fr}}.live{{display:none}}h1{{font-size:34px}}}}
@media(prefers-reduced-motion:no-preference){{.metric-card,.download-card{{will-change:transform}}}}
</style></head><body><div class="shell">
<header class="topbar"><a class="brand" href="index.html"><span class="brand-mark">FR</span><span><b>Forecast Redelong</b><small>Engineering weather intelligence</small></span></a><nav class="nav"><a href="index.html">Portal utama</a><a href="#ringkasan">Ringkasan</a><a href="#analisis">Analisis</a><a href="#harian">Harian</a><a href="#quality">Quality control</a><a href="#unduh">Unduh</a></nav><span class="live"><i></i> Prototype operasional</span></header>
<main id="top">
<section class="hero"><div class="hero-grid"><div class="hero-copy"><div class="eyebrow"><i></i>Engineering · Decision Support</div><h1>Hujan yang relevan untuk keputusan operasi.</h1><p>Prakiraan multi-model untuk area analisis provisional GPM1–GPM6, disusun dalam horizon 24/48/72 jam dengan ketidakpastian yang terlihat dan quality control setiap sumber.</p><div class="meta"><span class="chip">Issue {issue_time.strftime('%d/%m/%Y %H:%M')} WIB</span><span class="chip">Valid hingga {forecast_end.strftime('%d/%m/%Y %H:%M')} WIB</span><span class="chip">Area {area:.2f} km² · provisional</span><span class="chip">Bobot model sama</span></div><div class="hero-actions"><a class="button primary" href="#ringkasan">Lihat ringkasan <span>↓</span></a><a class="button secondary" href="redelong_operational_map.html">Buka peta penuh <span>↗</span></a></div></div><aside class="snapshot"><div class="snapshot-top"><div><span>Status horizon</span><b>Forecast 24 jam</b></div><em class="pill {status_24_tone}">{escape(status_24_label)}</em></div><div class="snapshot-value{snapshot_value_class}">{_fmt(rain24,1,' mm')}</div><small>{'Skenario P10–P90 ' + _fmt(rain24low,1) + '–' + _fmt(rain24high,1) + ' mm' if pd.notna(rain24) else 'Menunggu coverage per-jam yang lengkap'}</small><div class="snapshot-grid"><div><span>Model valid</span><b>{_fmt(model24,0)}</b></div><div><span>Area analisis</span><b>{area:.2f} km²</b></div></div></aside></div></section>
<div class="notice"><span class="notice-icon">!</span><div><b>Keputusan spasial sementara</b><p>Grid TamaTue berjarak sekitar 17,8 km dan tidak dimasukkan ke agregasi catchment sampai batas DAS atau konektivitas alirannya dikonfirmasi. Sistem belum memberikan label aman/bahaya tanpa threshold operasi yang disetujui.</p></div><span class="notice-tag">TamaTue · pembanding</span></div>

<section class="section" id="ringkasan"><div class="section-head"><div><span class="section-kicker">01 · Ringkasan operasi</span><h2>Snapshot horizon utama</h2></div><p>Nilai kosong berarti data belum memenuhi coverage minimum—bukan berarti hujan 0 mm.</p></div><div class="kpi-grid">
<article class="metric-card"><span class="metric-icon">24H</span><span>Hujan area 24 jam</span><strong>{_fmt(rain24,1,' mm')}</strong><small>{escape(scenario_24_note)}</small></article>
<article class="metric-card"><span class="metric-icon">48H</span><span>Hujan area 48 jam</span><strong>{_fmt(rain48,1,' mm')}</strong><small>Akumulasi sejak awal forecast</small></article>
<article class="metric-card"><span class="metric-icon">72H</span><span>Hujan area 72 jam</span><strong>{_fmt(rain72,1,' mm')}</strong><small>Horizon keputusan menengah</small></article>
<article class="metric-card"><span class="metric-icon">GPM</span><span>Area terbasah 24 jam</span><strong>{escape(wettest)}</strong><small>Di antara GPM1–GPM6</small></article>
<article class="metric-card"><span class="metric-icon">m³</span><span>Volume hujan bruto</span><strong>{_fmt(gross_volume/1_000_000 if pd.notna(gross_volume) else np.nan,2,' juta m³')}</strong><small>Bukan prediksi debit atau inflow</small></article>
</div></section>

<section class="section" id="analisis"><div class="section-head"><div><span class="section-kicker">02 · Analisis waktu dan ruang</span><h2>Kapan dan di mana hujan diperkirakan?</h2></div><p>Mean ditampilkan bersama rentang P10–P90 antar-model deterministik. Rentang ini belum terkalibrasi sebagai probabilitas.</p></div><div class="analytics"><article class="panel"><div class="panel-head"><div><span>Akumulasi 3 jam</span><h3>Perkembangan hujan area</h3></div><p>WIB · hanya periode dengan coverage lengkap</p></div><div class="chart-wrap">{chart_html}</div></article><article class="panel"><div class="panel-head"><div><span>Spasial</span><h3>Area analisis & pembanding</h3></div><p>GPM1–GPM6 dihitung<br>TamaTue tidak dihitung</p></div><iframe class="map-frame" src="redelong_operational_map.html" title="Peta area analisis Forecast Redelong"></iframe></article></div></section>

<section class="section" id="harian"><div class="section-head"><div><span class="section-kicker">03 · Ringkasan harian</span><h2>Forecast per hari kalender WIB</h2></div><p>Hari pertama dan terakhir dapat parsial karena horizon dimulai dari jam penerbitan.</p></div><div class="day-grid">{daily_html}</div></section>

<section class="section" id="quality"><div class="section-head"><div><span class="section-kicker">04 · Quality control</span><h2>Status setiap sumber</h2></div><p>BMKG disajikan sebagai panduan kategoris resmi dan tidak dicampur menjadi rain_mm numerik.</p></div><article class="panel"><div class="table-wrap"><table><thead><tr><th>Sumber</th><th>Peran</th><th>Status</th><th>Kelengkapan</th><th>Catatan</th></tr></thead><tbody>{source_rows_html}</tbody></table></div></article></section>

<section class="section" id="unduh"><div class="section-head"><div><span class="section-kicker">05 · Data dan dokumentasi</span><h2>Unduh output operasional</h2></div><p>CSV diperbarui otomatis dan dapat langsung dibuka di Excel.</p></div><div class="download-grid">{download_html}</div></section>
<footer class="foot"><span><b>Forecast Redelong</b> · Prototype decision-support Engineering</span><span>Curah hujan area memakai bobot luas provisional GPM1–GPM6. Volume bruto belum memperhitungkan infiltrasi, evapotranspirasi, simpanan tanah, routing, atau operasi waduk.</span></footer>
</main></div></body></html>"""


def _validation_status_html(issue_time: pd.Timestamp, archive_dir: Path) -> str:
    return f"""<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Status Validasi Forecast Redelong</title><style>body{{margin:0;background:#f4f7fb;color:#10233f;font-family:Inter,system-ui,sans-serif}}main{{max-width:900px;margin:auto;padding:36px 20px}}section{{background:#fff;border:1px solid #dbe5ef;border-radius:20px;padding:24px;margin-bottom:16px}}h1{{font-size:38px;margin:0 0 10px}}p,li{{line-height:1.65}}.pending{{display:inline-block;background:#fff7ed;color:#9a3412;border:1px solid #fed7aa;padding:7px 10px;border-radius:999px;font-weight:700}}a{{color:#176bff}}</style></head><body><main><section><span class="pending">Belum boleh mengklaim akurasi</span><h1>Status Validasi</h1><p>Forecast operasional sudah mulai diarsipkan berdasarkan <i>issue time</i> dan <i>valid time</i>. Nilai MAE, RMSE, bias, POD, FAR, dan CSI baru akan dihitung setelah tersedia pasangan forecast–observation yang cukup dan sebanding.</p></section><section><h2>Yang sudah tersedia</h2><ul><li>Arsip forecast source-level dengan waktu penerbitan.</li><li>Forecast area GPM1–GPM6 dan forecast per titik.</li><li>Kerangka proxy observation GPM/CHIRPS.</li><li>Data PU TamaTue untuk menilai kelayakan proxy, bukan untuk langsung mengklaim skill forecast Redelong.</li></ul></section><section><h2>Aturan evaluasi</h2><ol><li>Bandingkan tanggal, waktu valid, lokasi, dan lead time yang sama.</li><li>Gunakan akumulasi yang sebanding, misalnya 24 jam forecast versus 24 jam observasi.</li><li>Pisahkan hasil observasi lapangan dan proxy satelit.</li><li>Publikasikan jumlah sampel bersama setiap metrik.</li></ol><p>Arsip run ini: <code>{escape(str(archive_dir.relative_to(archive_dir.parents[3])))}</code></p><p>Diperbarui {issue_time.strftime('%d/%m/%Y %H:%M')} WIB · <a href="index.html">Kembali ke dashboard</a></p></section></main></body></html>"""


def build(outputs: Path) -> dict:
    outputs.mkdir(parents=True, exist_ok=True)
    raw = _prepare_raw(_read_csv(outputs / "forecast_all_locations.csv"))
    points = _load_points()
    issue_time = _load_issue_time(outputs)
    forecast_start = issue_time.ceil("h")
    forecast_end = forecast_start + pd.Timedelta(hours=72)
    operational_raw = raw[
        (raw["valid_time_wib"] >= forecast_start)
        & (raw["valid_time_wib"] < forecast_end)
    ].copy()

    source_hourly = _catchment_source_hourly(operational_raw, points)
    catchment_hourly = _model_consensus(source_hourly, "rain_mm", ["valid_time_wib"])
    source_3h, three_hour = _three_hour(source_hourly)
    source_windows, windows = _window_totals(source_hourly, forecast_start)
    source_daily, daily = _calendar_daily(source_hourly)
    point_hourly, point_24h = _point_products(operational_raw, points, forecast_start)
    point_24h_output = points[
        [
            "location_slug",
            "point_name",
            "operational_role",
            "include_in_catchment",
            "weight_km2",
            "note",
        ]
    ].merge(point_24h, on="location_slug", how="left")
    bmkg = _bmkg_guidance(operational_raw)
    source_qc = _source_qc(operational_raw, source_hourly, points)

    total_area = points.loc[points["include_in_catchment"], "weight_km2"].sum()
    windows["provisional_area_km2"] = total_area
    windows["gross_rain_volume_m3"] = windows["rain_mean_mm"] * total_area * 1000
    windows["volume_note"] = "Volume hujan bruto; bukan debit/inflow."

    output_frames = {
        "operational_catchment_hourly.csv": catchment_hourly,
        "operational_source_hourly.csv": source_hourly,
        "operational_3hour.csv": three_hour,
        "operational_source_3hour.csv": source_3h,
        "operational_windows.csv": windows,
        "operational_source_windows.csv": source_windows,
        "operational_daily.csv": daily,
        "operational_source_daily.csv": source_daily,
        "operational_per_point_hourly.csv": point_hourly,
        "operational_per_point_24h.csv": point_24h_output,
        "operational_source_status.csv": source_qc,
        "bmkg_guidance.csv": bmkg,
    }
    for filename, frame in output_frames.items():
        _write_csv(frame, outputs / filename)

    geojson = _build_geojson(points, point_24h)
    (outputs / "redelong_operational_points.geojson").write_text(
        json.dumps(geojson, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (outputs / "redelong_operational_map.html").write_text(_map_html(geojson), encoding="utf-8")

    payload = {
        "schema_version": "1.0.0",
        "issue_time_wib": issue_time.isoformat(),
        "forecast_start_wib": forecast_start.isoformat(),
        "forecast_end_wib": forecast_end.isoformat(),
        "timezone": "Asia/Jakarta",
        "method": {
            "quantitative_sources": list(QUANTITATIVE_SOURCES),
            "source_weighting": "equal_weight",
            "bmkg_role": "official_categorical_guidance_only",
            "catchment_status": "provisional_GPM1_to_GPM6",
            "provisional_area_km2": total_area,
            "excluded_from_catchment": ["PLTA Redelong", "GPM Grid TamaTue"],
            "minimum_models": MIN_MODELS,
            "missing_value_policy": "exclude; never convert missing rainfall to zero",
        },
        "windows": _records(windows),
        "daily": _records(daily),
        "three_hour": _records(three_hour),
        "point_24h": _records(point_24h),
        "source_status": _records(source_qc),
        "limitations": [
            "Batas DAS resmi dan konektivitas TamaTue belum dikonfirmasi.",
            "P10/P90 merupakan rentang antar-model deterministik, bukan probabilitas terkalibrasi.",
            "Volume hujan bruto bukan forecast debit atau inflow.",
            "Akurasi forecast belum diklaim sebelum tersedia pasangan issue-time/valid-time dan observasi.",
        ],
    }
    (outputs / "redelong_operational.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    dashboard = _dashboard_html(issue_time, forecast_start, points, windows, three_hour, daily, point_24h, source_qc)
    dashboard_path = outputs / "redelong_operational.html"
    dashboard_path.write_text(dashboard, encoding="utf-8")

    issue_stamp = issue_time.strftime("%Y%m%dT%H%M%S%z")
    archive_dir = outputs / "archive" / issue_time.strftime("%Y") / issue_time.strftime("%m") / issue_stamp
    archive_dir.mkdir(parents=True, exist_ok=True)
    for filename in [
        "forecast_all_locations.csv",
        "operational_source_hourly.csv",
        "operational_catchment_hourly.csv",
        "operational_3hour.csv",
        "operational_windows.csv",
        "operational_per_point_24h.csv",
        "operational_source_status.csv",
        "redelong_operational.json",
    ]:
        source = outputs / filename
        if source.exists():
            shutil.copy2(source, archive_dir / filename)
    (archive_dir / "archive_metadata.json").write_text(
        json.dumps(
            {
                "issue_time_wib": issue_time.isoformat(),
                "forecast_start_wib": forecast_start.isoformat(),
                "forecast_end_wib": forecast_end.isoformat(),
                "archive_key": "issue_time + valid_time + location + source",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (outputs / "validation_status.html").write_text(
        _validation_status_html(issue_time, archive_dir), encoding="utf-8"
    )
    return {
        "issue_time_wib": issue_time.isoformat(),
        "forecast_rows": len(operational_raw),
        "catchment_hourly_rows": len(catchment_hourly),
        "three_hour_rows": len(three_hour),
        "archive_dir": str(archive_dir),
        "dashboard": str(dashboard_path),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build PLTA Redelong operational rainfall products")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    args = parser.parse_args()
    result = build(args.outputs.resolve())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
