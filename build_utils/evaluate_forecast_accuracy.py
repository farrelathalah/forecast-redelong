from __future__ import annotations

import math
import json
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
OBS_PATH = ROOT / "data" / "redelong" / "observations" / "rain_observed_daily.csv"
PROXY_OBS_PATH = ROOT / "data" / "redelong" / "observations" / "rain_proxy_daily.csv"
FORECAST_PATH = OUTPUTS / "forecast_all_locations.csv"
ARCHIVE_ROOT = OUTPUTS / "archive"
WIB = timezone(timedelta(hours=7))
QUANTITATIVE_SOURCES = {
    "CMA",
    "ECMWF",
    "GFS",
    "ICON",
    "METEOFRANCE",
    "UKMO",
}
MIN_HOURS_PER_SOURCE_DAY = 20
MIN_MODELS_PER_DAY = 3
MIN_DATES_FOR_PRELIMINARY_FIELD_CLAIM = 30
MIN_EVENT_DATES_FOR_PRELIMINARY_FIELD_CLAIM = 10

JOINED_COLUMNS = [
    "date",
    "location_slug",
    "rain_mm_observed",
    "observation_points",
    "observation_source",
    "observation_type",
    "rain_forecast_mean",
    "rain_forecast_p90",
    "rain_forecast_max",
    "forecast_models",
    "minimum_hours_per_model",
    "issue_time_wib",
    "issue_date",
    "lead_day",
]

METRIC_COLUMNS = [
    "scope",
    "lead_day",
    "forecast_metric",
    "n_samples",
    "mae_mm",
    "rmse_mm",
    "bias_mm",
    "mean_observed_mm",
    "mean_forecast_mm",
    "event_accuracy_ge_1mm",
    "pod_ge_1mm",
    "far_ge_1mm",
    "csi_ge_1mm",
    "hit_ge_1mm",
    "miss_ge_1mm",
    "false_alarm_ge_1mm",
    "correct_negative_ge_1mm",
    "event_accuracy_ge_10mm",
    "pod_ge_10mm",
    "far_ge_10mm",
    "csi_ge_10mm",
    "hit_ge_10mm",
    "miss_ge_10mm",
    "false_alarm_ge_10mm",
    "correct_negative_ge_10mm",
]


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame()


def pick_col(df: pd.DataFrame, candidates: list[str], contains: list[str] | None = None) -> str | None:
    for col in candidates:
        if col in df.columns:
            return col

    if contains:
        for col in df.columns:
            lower = col.lower()
            if any(key in lower for key in contains):
                return col

    return None


def pick_rain_col(df: pd.DataFrame) -> str | None:
    preferred = []
    fallback = []

    for col in df.columns:
        lower = col.lower()
        if any(k in lower for k in ["rain", "precip", "hujan"]):
            numeric = pd.to_numeric(df[col], errors="coerce")
            if not numeric.notna().any():
                continue

            if any(k in lower for k in ["prob", "chance", "pct", "percent"]):
                fallback.append(col)
            else:
                preferred.append(col)

    return preferred[0] if preferred else (fallback[0] if fallback else None)


def pick_date_col(df: pd.DataFrame) -> str | None:
    candidates = [
        "target_date",
        "date",
        "tanggal",
        "valid_date",
        "local_date",
        "datetime",
        "time",
        "target_datetime",
        "local_datetime",
    ]

    for col in candidates:
        if col in df.columns:
            return col

    for col in df.columns:
        lower = col.lower()
        if "date" in lower or "tanggal" in lower or "time" in lower:
            return col

    return None


def normalize_date(series: pd.Series) -> pd.Series:
    dt = pd.to_datetime(series, errors="coerce")
    return dt.dt.strftime("%Y-%m-%d")


def event_metrics(y_true: np.ndarray, y_pred: np.ndarray, threshold: float) -> dict:
    obs_event = y_true >= threshold
    pred_event = y_pred >= threshold

    hit = int(np.logical_and(obs_event, pred_event).sum())
    miss = int(np.logical_and(obs_event, ~pred_event).sum())
    false_alarm = int(np.logical_and(~obs_event, pred_event).sum())
    correct_neg = int(np.logical_and(~obs_event, ~pred_event).sum())
    total = int(len(y_true))

    event_accuracy = (hit + correct_neg) / total if total else np.nan
    pod = hit / (hit + miss) if (hit + miss) else np.nan
    far = false_alarm / (hit + false_alarm) if (hit + false_alarm) else np.nan
    csi = hit / (hit + miss + false_alarm) if (hit + miss + false_alarm) else np.nan

    return {
        f"event_accuracy_ge_{threshold:g}mm": event_accuracy,
        f"pod_ge_{threshold:g}mm": pod,
        f"far_ge_{threshold:g}mm": far,
        f"csi_ge_{threshold:g}mm": csi,
        f"hit_ge_{threshold:g}mm": hit,
        f"miss_ge_{threshold:g}mm": miss,
        f"false_alarm_ge_{threshold:g}mm": false_alarm,
        f"correct_negative_ge_{threshold:g}mm": correct_neg,
    }


def fmt(v, digits=2) -> str:
    try:
        if pd.isna(v):
            return "-"
        return f"{float(v):.{digits}f}"
    except Exception:
        return "-"


def build_daily_forecast(fc: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Build comparable 24-hour rainfall totals from source-level forecasts.

    Forecast Redelong stores one row per source, location, and valid hour.  A
    daily observation must therefore be compared with a daily sum for each
    quantitative model first, followed by an across-model consensus.  Averaging
    raw source-hour rows would mix time and model dimensions and understate the
    daily rainfall total.
    """

    if fc.empty:
        return pd.DataFrame(), "Forecast belum tersedia."

    loc_col = pick_col(fc, ["location_slug", "slug", "location_id", "location"], ["location"])
    date_col = pick_date_col(fc)
    hour_col = pick_col(
        fc,
        ["target_jam", "hour", "jam", "target_time", "local_time"],
        ["jam", "hour"],
    )
    source_col = pick_col(fc, ["source_id", "source", "model"], ["source", "model"])
    rain_col = pick_col(
        fc,
        ["rain_mm", "precipitation_mm", "precipitation", "hujan_mm"],
        ["rain", "precip", "hujan"],
    )

    required = {
        "lokasi forecast": loc_col,
        "tanggal forecast": date_col,
        "jam forecast": hour_col,
        "sumber forecast": source_col,
        "hujan forecast": rain_col,
    }
    missing = [label for label, value in required.items() if value is None]
    if missing:
        return pd.DataFrame(), "Kolom forecast tidak lengkap: " + ", ".join(missing)

    work = fc[[loc_col, date_col, hour_col, source_col, rain_col]].copy()
    work.columns = ["location_slug", "date", "hour", "source_id", "rain_mm"]
    work["location_slug"] = work["location_slug"].astype(str).str.strip()
    work["source_id"] = work["source_id"].astype(str).str.upper().str.strip()
    work["date"] = normalize_date(work["date"])
    work["valid_time"] = pd.to_datetime(
        work["date"].astype(str) + " " + work["hour"].astype(str),
        errors="coerce",
    )
    work["rain_mm"] = pd.to_numeric(work["rain_mm"], errors="coerce")
    work = work[
        work["source_id"].isin(QUANTITATIVE_SOURCES)
        & work["rain_mm"].between(0.0, 300.0)
    ].dropna(subset=["location_slug", "date", "valid_time", "rain_mm"])

    if work.empty:
        return pd.DataFrame(), "Belum ada data hujan numerik dari model kuantitatif."

    # Resolve accidental duplicate rows without double-counting an hour.
    hourly = (
        work.groupby(
            ["location_slug", "date", "source_id", "valid_time"],
            as_index=False,
        )["rain_mm"]
        .mean()
    )
    source_daily = (
        hourly.groupby(["location_slug", "date", "source_id"], as_index=False)
        .agg(
            rain_daily_mm=("rain_mm", "sum"),
            hours_available=("valid_time", "nunique"),
        )
    )
    source_daily = source_daily[
        source_daily["hours_available"] >= MIN_HOURS_PER_SOURCE_DAY
    ]
    if source_daily.empty:
        return (
            pd.DataFrame(),
            "Belum ada forecast harian dengan sedikitnya "
            f"{MIN_HOURS_PER_SOURCE_DAY}/24 jam per model.",
        )

    daily = (
        source_daily.groupby(["location_slug", "date"], as_index=False)
        .agg(
            rain_forecast_mean=("rain_daily_mm", "mean"),
            rain_forecast_p90=(
                "rain_daily_mm",
                lambda values: float(np.nanquantile(values, 0.90)),
            ),
            rain_forecast_max=("rain_daily_mm", "max"),
            forecast_models=("source_id", "nunique"),
            minimum_hours_per_model=("hours_available", "min"),
        )
    )
    daily = daily[daily["forecast_models"] >= MIN_MODELS_PER_DAY]
    if daily.empty:
        return (
            pd.DataFrame(),
            "Forecast harian belum memiliki sedikitnya "
            f"{MIN_MODELS_PER_DAY} model lengkap pada tanggal dan lokasi yang sama.",
        )
    return daily, None


def build_archive_daily_forecasts(archive_root: Path) -> tuple[pd.DataFrame, dict]:
    """Build one morning-style forecast sample per issue date and target day.

    Manual retries on the same date must not inflate the validation sample.  We
    therefore retain the earliest archived issue for each issue-date, target,
    and location.  Lead day is a calendar-day lead in WIB (H+1, H+2, H+3).
    """

    frames: list[pd.DataFrame] = []
    runs_found = 0
    runs_eligible = 0
    if archive_root.exists():
        for metadata_path in sorted(archive_root.rglob("archive_metadata.json")):
            forecast_path = metadata_path.parent / "forecast_all_locations.csv"
            if not forecast_path.exists():
                continue
            runs_found += 1
            try:
                metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
                issue = pd.Timestamp(metadata.get("issue_time_wib"))
                forecast_end = pd.to_datetime(
                    metadata.get("forecast_end_wib"), errors="coerce"
                )
            except Exception:
                continue
            if pd.isna(issue):
                continue
            if issue.tzinfo is None:
                issue = issue.tz_localize(WIB)
            else:
                issue = issue.tz_convert(WIB)
            archived_fc = read_csv(forecast_path)
            date_col = pick_date_col(archived_fc)
            hour_col = pick_col(
                archived_fc,
                ["target_jam", "hour", "jam", "target_time", "local_time"],
                ["jam", "hour"],
            )
            if date_col and hour_col:
                valid_time = pd.to_datetime(
                    archived_fc[date_col].astype(str)
                    + " "
                    + archived_fc[hour_col].astype(str),
                    errors="coerce",
                )
                issue_local_naive = issue.tz_localize(None)
                valid_mask = valid_time >= issue_local_naive
                if not pd.isna(forecast_end):
                    if forecast_end.tzinfo is not None:
                        forecast_end = forecast_end.tz_convert(WIB).tz_localize(None)
                    valid_mask &= valid_time <= forecast_end
                archived_fc = archived_fc.loc[valid_mask].copy()
            daily, _ = build_daily_forecast(archived_fc)
            if daily.empty:
                continue
            daily = daily.copy()
            daily["issue_time_wib"] = issue.isoformat()
            daily["issue_date"] = issue.strftime("%Y-%m-%d")
            target_dates = pd.to_datetime(daily["date"], errors="coerce")
            daily["lead_day"] = (
                target_dates - pd.Timestamp(issue.strftime("%Y-%m-%d"))
            ).dt.days
            daily = daily[daily["lead_day"].between(1, 3)]
            if daily.empty:
                continue
            runs_eligible += 1
            frames.append(daily)

    if not frames:
        return pd.DataFrame(), {
            "archive_runs_found": runs_found,
            "archive_runs_eligible": runs_eligible,
            "eligible_archive_daily_rows_before_dedup": 0,
            "eligible_archive_daily_rows": 0,
            "selection_policy": "earliest issue per issue-date, target-date, and location",
        }

    combined = pd.concat(frames, ignore_index=True)
    before = len(combined)
    combined["_issue_sort"] = pd.to_datetime(combined["issue_time_wib"], errors="coerce", utc=True)
    combined = (
        combined.sort_values("_issue_sort")
        .drop_duplicates(["issue_date", "date", "location_slug"], keep="first")
        .drop(columns="_issue_sort")
        .reset_index(drop=True)
    )
    return combined, {
        "archive_runs_found": runs_found,
        "archive_runs_eligible": runs_eligible,
        "eligible_archive_daily_rows_before_dedup": before,
        "eligible_archive_daily_rows": len(combined),
        "selection_policy": "earliest issue per issue-date, target-date, and location",
    }


def prepare_observations(obs: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    if obs.empty:
        return pd.DataFrame(), "Data observasi yang sesuai belum tersedia."
    loc_col = pick_col(obs, ["location_slug", "slug", "location_id", "location"], ["location"])
    date_col = pick_col(obs, ["date", "tanggal", "observed_date"], ["date", "tanggal"])
    rain_col = pick_col(obs, ["rain_mm_observed", "observed_rain_mm", "rain_mm", "hujan_mm"], ["rain"])
    missing = [
        label
        for label, value in {
            "observation location": loc_col,
            "observation date": date_col,
            "observation rain": rain_col,
        }.items()
        if value is None
    ]
    if missing:
        return pd.DataFrame(), "Kolom tidak lengkap: " + ", ".join(missing)

    columns = [loc_col, date_col, rain_col]
    source_col = pick_col(obs, ["source", "observation_source"], ["source"])
    type_col = pick_col(obs, ["observation_type", "type"], ["observation_type"])
    for optional in (source_col, type_col):
        if optional and optional not in columns:
            columns.append(optional)
    work = obs[columns].copy()
    rename = {
        loc_col: "location_slug",
        date_col: "date",
        rain_col: "rain_mm_observed",
    }
    if source_col:
        rename[source_col] = "observation_source"
    if type_col:
        rename[type_col] = "observation_type"
    work = work.rename(columns=rename)
    if "observation_source" not in work:
        work["observation_source"] = "unspecified"
    if "observation_type" not in work:
        work["observation_type"] = "unspecified"
    work["location_slug"] = work["location_slug"].astype(str).str.strip()
    work["date"] = normalize_date(work["date"])
    work["rain_mm_observed"] = pd.to_numeric(work["rain_mm_observed"], errors="coerce")
    work = work.dropna(subset=["location_slug", "date", "rain_mm_observed"])
    if work.empty:
        return pd.DataFrame(), "Data observasi belum memiliki nilai hujan yang valid."
    daily = (
        work.groupby(["location_slug", "date"], as_index=False)
        .agg(
            rain_mm_observed=("rain_mm_observed", "mean"),
            observation_points=("rain_mm_observed", "count"),
            observation_source=("observation_source", lambda x: ", ".join(sorted(set(map(str, x))))),
            observation_type=("observation_type", lambda x: ", ".join(sorted(set(map(str, x))))),
        )
    )
    return daily, None


def calculate_metrics(joined: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict] = []
    groups: list[tuple[str, int | None, pd.DataFrame]] = [("overall", None, joined)]
    if "lead_day" in joined.columns:
        for lead, frame in joined.groupby("lead_day", dropna=True):
            groups.append(("lead_day", int(lead), frame))
    for scope, lead, frame in groups:
        for forecast_col in ["rain_forecast_mean", "rain_forecast_p90", "rain_forecast_max"]:
            y_true = frame["rain_mm_observed"].to_numpy(dtype=float)
            y_pred = frame[forecast_col].to_numpy(dtype=float)
            err = y_pred - y_true
            row = {
                "scope": scope,
                "lead_day": lead,
                "forecast_metric": forecast_col,
                "n_samples": len(frame),
                "mae_mm": float(np.nanmean(np.abs(err))),
                "rmse_mm": float(math.sqrt(np.nanmean(err ** 2))),
                "bias_mm": float(np.nanmean(err)),
                "mean_observed_mm": float(np.nanmean(y_true)),
                "mean_forecast_mm": float(np.nanmean(y_pred)),
            }
            row.update(event_metrics(y_true, y_pred, threshold=1.0))
            row.update(event_metrics(y_true, y_pred, threshold=10.0))
            rows.append(row)
    return pd.DataFrame(rows, columns=METRIC_COLUMNS)


def validation_status(
    obs_mode: str,
    archive_stats: dict,
    forecast_rows: int,
    observation_rows: int,
    joined: pd.DataFrame,
    generated: str,
    observation_sources: list[str] | None = None,
) -> dict:
    n = int(len(joined))
    observed_events = int((joined.get("rain_mm_observed", pd.Series(dtype=float)) >= 1.0).sum())
    matched_dates = int(joined.get("date", pd.Series(dtype=str)).nunique())
    event_dates = 0
    if not joined.empty and {"date", "rain_mm_observed"}.issubset(joined.columns):
        event_dates = int(
            (joined.groupby("date")["rain_mm_observed"].max() >= 1.0).sum()
        )
    field_mode = obs_mode == "field_observation"
    can_claim = bool(
        field_mode
        and matched_dates >= MIN_DATES_FOR_PRELIMINARY_FIELD_CLAIM
        and event_dates >= MIN_EVENT_DATES_FOR_PRELIMINARY_FIELD_CLAIM
    )
    proxy_reference_mode = obs_mode == "proxy_observation"
    source_names = observation_sources or []
    proxy_reference = (
        "proxy_gridded_weather_analysis"
        if any("Open-Meteo Historical Weather" in source for source in source_names)
        else "proxy_satellite_gridded"
    )
    can_report_preliminary_proxy_skill = bool(
        proxy_reference_mode
        and matched_dates >= MIN_DATES_FOR_PRELIMINARY_FIELD_CLAIM
        and event_dates >= MIN_EVENT_DATES_FOR_PRELIMINARY_FIELD_CLAIM
    )
    if n == 0:
        state = "menunggu_pasangan"
    elif can_claim:
        state = "validasi_lapangan_awal"
    elif field_mode:
        state = "indikatif_sampel_terbatas"
    elif can_report_preliminary_proxy_skill:
        state = "validasi_proxy_awal"
    else:
        state = "validasi_proxy_sampel_terbatas"
    reason = (
        "Belum ada pasangan forecast arsip dan observasi yang telah matang."
        if n == 0
        else (
            "Metrik berbasis proxy hanya menilai kesesuaian terhadap produk gridded, bukan akurasi lapangan."
            if not field_mode
            else "Sampel lapangan belum memenuhi ambang awal."
        )
    )
    return {
        "schema_version": "forecast-redelong-validation-v2",
        "generated_at_wib": generated,
        "state": state,
        "observation_mode": obs_mode,
        "observation_reference": proxy_reference if proxy_reference_mode else "site_gauge",
        "observation_sources": source_names,
        "site_gauge_required": False,
        "can_claim_field_accuracy": can_claim,
        "can_report_preliminary_proxy_skill": can_report_preliminary_proxy_skill,
        "reason": reason,
        "archive": archive_stats,
        "eligible_forecast_daily_rows": int(forecast_rows),
        "observation_daily_rows": int(observation_rows),
        "matched_location_days": n,
        "matched_unique_dates": matched_dates,
        "observed_events_ge_1mm": observed_events,
        "observed_event_dates_ge_1mm": event_dates,
        "minimum_field_dates_for_preliminary_claim": MIN_DATES_FOR_PRELIMINARY_FIELD_CLAIM,
        "minimum_field_event_dates_for_preliminary_claim": MIN_EVENT_DATES_FOR_PRELIMINARY_FIELD_CLAIM,
        "limitations": [
            "IMERG, CHIRPS, dan Open-Meteo Historical Weather adalah referensi gridded, bukan penakar hujan di site.",
            "Metrik yang diterbitkan adalah skill terhadap produk referensi, bukan akurasi lapangan.",
            "Satu issue awal per hari dipilih agar retry manual tidak menggandakan sampel.",
            "Ambang klaim awal dihitung dari tanggal unik, bukan jumlah titik yang saling berkorelasi.",
            "Hanya total harian dengan sedikitnya 20/24 jam per model dan minimal tiga model dihitung.",
            "TamaTue tetap pembanding eksternal dan tidak masuk agregasi catchment.",
        ],
    }


def write_validation_files(
    outputs: Path,
    joined: pd.DataFrame,
    metrics: pd.DataFrame,
    status: dict,
) -> None:
    joined.reindex(columns=JOINED_COLUMNS).to_csv(
        outputs / "evaluation_joined_daily.csv", index=False
    )
    metrics.reindex(columns=METRIC_COLUMNS).to_csv(
        outputs / "evaluation_metrics.csv", index=False
    )
    (outputs / "evaluation_status.json").write_text(
        json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(
    outputs: Path = OUTPUTS,
    forecast_path: Path = FORECAST_PATH,
    observation_path: Path = OBS_PATH,
    proxy_observation_path: Path | None = None,
    archive_root: Path | None = None,
) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    archive_root = archive_root or (outputs / "archive")
    if proxy_observation_path is None:
        proxy_candidates = [
            outputs / "validation_archive" / "rain_proxy_daily_primary.csv",
            outputs / "validation_archive" / "rain_proxy_daily_imerg.csv",
            outputs / "validation_archive" / "rain_proxy_daily_chirps.csv",
            PROXY_OBS_PATH,
        ]
        proxy_observation_path = next(
            (path for path in proxy_candidates if path.exists()), PROXY_OBS_PATH
        )
    fc = read_csv(forecast_path)
    obs = read_csv(observation_path)
    obs_mode = "field_observation"
    if (
        obs.empty
        or "rain_mm_observed" not in obs.columns
        or not pd.to_numeric(obs.get("rain_mm_observed"), errors="coerce").notna().any()
    ):
        obs = read_csv(proxy_observation_path)
        obs_mode = "proxy_observation"
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    archive_daily, archive_stats = build_archive_daily_forecasts(archive_root)
    fc_daily, forecast_message = build_daily_forecast(fc)
    if not archive_daily.empty:
        evaluation_forecast = archive_daily
    elif not fc_daily.empty:
        evaluation_forecast = fc_daily.copy()
        evaluation_forecast["issue_time_wib"] = ""
        evaluation_forecast["issue_date"] = ""
        evaluation_forecast["lead_day"] = np.nan
    else:
        evaluation_forecast = pd.DataFrame()

    obs_daily, observation_message = prepare_observations(obs)
    observation_sources = []
    if "observation_source" in obs_daily:
        observation_sources = sorted(
            {
                str(value)
                for value in obs_daily["observation_source"].dropna()
                if str(value).strip()
            }
        )
    if not evaluation_forecast.empty and not obs_daily.empty:
        joined = pd.merge(
            obs_daily,
            evaluation_forecast,
            on=["location_slug", "date"],
            how="inner",
        )
    else:
        joined = pd.DataFrame(columns=JOINED_COLUMNS)

    metrics = calculate_metrics(joined) if not joined.empty else pd.DataFrame(columns=METRIC_COLUMNS)
    status = validation_status(
        obs_mode=obs_mode,
        archive_stats=archive_stats,
        forecast_rows=len(evaluation_forecast),
        observation_rows=len(obs_daily),
        joined=joined,
        generated=generated,
        observation_sources=observation_sources,
    )
    write_validation_files(outputs, joined, metrics, status)

    if evaluation_forecast.empty:
        write_empty_page(
            forecast_message or "Data forecast belum tersedia. Jalankan forecast terlebih dahulu.",
            generated,
            outputs,
            status,
        )
        return
    if obs_daily.empty:
        write_empty_page(
            observation_message
            or "Data observasi yang sesuai belum tersedia. Metrik akan ditampilkan setelah pasangan matang tersedia.",
            generated,
            outputs,
            status,
        )
        return
    if joined.empty:
        write_empty_page(
            "Belum ada tanggal dan lokasi yang cocok antara forecast arsip 24 jam lengkap dan observasi yang telah matang.",
            generated,
            outputs,
            status,
        )
        return

    write_page(joined, metrics, generated, obs_mode, outputs, status)


def write_empty_page(
    message: str,
    generated: str,
    outputs: Path = OUTPUTS,
    status: dict | None = None,
) -> None:
    status = status or {}
    archive = status.get("archive", {})
    matched = int(status.get("matched_location_days", 0))
    eligible = int(status.get("eligible_forecast_daily_rows", 0))
    observations = int(status.get("observation_daily_rows", 0))
    runs = int(archive.get("archive_runs_found", 0))
    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Status Validasi, Forecast Redelong</title>
  <style>
    body{{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:#eff8ff;background:#04111e}}
    .topbar{{display:flex;align-items:center;padding:18px min(5vw,64px);border-bottom:1px solid rgba(255,255,255,.15);background:rgba(3,11,20,.78)}}
    .brand{{display:flex;align-items:center;gap:12px;color:inherit;text-decoration:none}}
    .brand-mark{{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#06b6d4,#8b5cf6 55%,#10b981);display:grid;place-items:center;color:#fff;font-size:11px;font-weight:900;letter-spacing:-.04em}}
    .brand-copy{{display:flex;flex-direction:column;line-height:1.08}}
    .brand-copy strong{{font-size:18px}}
    .brand-copy span{{color:#9fb4c9;font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-top:3px}}
    main{{max-width:980px;margin:0 auto;padding:70px 22px}}
    .panel{{border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);border-radius:28px;padding:28px}}
    .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin:22px 0}}.metric{{padding:16px;border:1px solid rgba(255,255,255,.12);border-radius:18px;background:rgba(0,0,0,.15)}}.metric b{{display:block;font-size:26px}}.metric span{{color:#9fb4c9;font-size:12px}}
    .notice{{padding:14px 16px;border-radius:16px;background:#2b1d08;border:1px solid #7c5515;color:#ffe4a3}}
    a{{color:#45e0d0}}
    p{{color:#9fb4c9;line-height:1.7}}
    @media(max-width:700px){{.grid{{grid-template-columns:1fr 1fr}}}}
  </style>
</head>
<body>
  <header class="topbar">
    <a class="brand" href="index.html">
      <span class="brand-mark" aria-hidden="true">FR</span>
      <span class="brand-copy"><strong>Forecast Redelong</strong><span>Evaluasi Forecast</span></span>
    </a>
  </header>
  <main>
    <div class="panel">
      <h1>Status Validasi Forecast Redelong</h1>
      <p class="notice"><strong>Validasi proxy belum memiliki pasangan matang yang cukup.</strong> {escape(message)}</p>
      <div class="grid">
        <div class="metric"><b>{runs}</b><span>run forecast diarsipkan</span></div>
        <div class="metric"><b>{eligible}</b><span>forecast harian layak dibandingkan</span></div>
        <div class="metric"><b>{observations}</b><span>observasi/proxy harian</span></div>
        <div class="metric"><b>{matched}</b><span>pasangan lokasi-hari</span></div>
      </div>
      <p>Karena site tidak memiliki penakar hujan, evaluasi berjalan otomatis terhadap referensi satelit gridded. Sistem hanya menghitung total 24 jam yang sebanding, memilih satu issue awal per hari agar retry tidak menggandakan sampel, dan tidak menyebut hasilnya sebagai akurasi lapangan.</p>
      <p><a href="index.html">Kembali ke Home</a></p>
      <p>Generated {escape(generated)}</p>
    </div>
  </main>
</body>
</html>
"""
    (outputs / "evaluation_summary.html").write_text(html, encoding="utf-8")
    (outputs / "validation_status.html").write_text(html, encoding="utf-8")
    print("WARNING:", message)


def write_page(
    joined: pd.DataFrame,
    metrics: pd.DataFrame,
    generated: str,
    obs_mode: str,
    outputs: Path = OUTPUTS,
    status: dict | None = None,
) -> None:
    status = status or {}
    overall = metrics[metrics.get("scope", "overall") == "overall"] if "scope" in metrics else metrics
    best = overall.sort_values("mae_mm").iloc[0]
    source_label = ", ".join(status.get("observation_sources", [])) or "proxy gridded"

    metric_rows = ""
    for _, row in metrics.iterrows():
        scope_label = "Keseluruhan" if row.get("scope") == "overall" else f"H+{int(row['lead_day'])}"
        metric_rows += f"""
        <tr>
          <td>{escape(scope_label)}</td>
          <td>{escape(str(row["forecast_metric"]))}</td>
          <td>{int(row["n_samples"])}</td>
          <td>{fmt(row["mae_mm"])}</td>
          <td>{fmt(row["rmse_mm"])}</td>
          <td>{fmt(row["bias_mm"])}</td>
          <td>{fmt(row["event_accuracy_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["pod_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["far_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["csi_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["event_accuracy_ge_10mm"] * 100)}%</td>
        </tr>
        """

    sample_rows = ""
    for _, row in joined.head(40).iterrows():
        sample_rows += f"""
        <tr>
          <td>{escape(str(row["date"]))}</td>
          <td>{escape(str(row["location_slug"]))}</td>
          <td>{escape(str(row.get("issue_date", "-")))}</td>
          <td>{"H+" + str(int(row["lead_day"])) if pd.notna(row.get("lead_day")) else "-"}</td>
          <td>{fmt(row["rain_mm_observed"])}</td>
          <td>{fmt(row["rain_forecast_mean"])}</td>
          <td>{fmt(row["rain_forecast_p90"])}</td>
          <td>{fmt(row["rain_forecast_max"])}</td>
          <td>{int(row["forecast_models"])}</td>
          <td>{int(row["minimum_hours_per_model"])}/24</td>
        </tr>
        """

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Validasi Forecast, Forecast Redelong</title>
  <style>
    :root{{--bg:#040c16;--panel:rgba(255,255,255,.08);--line:rgba(255,255,255,.15);--text:#eff8ff;--muted:#9fb4c9;--cyan:#45e0d0;--blue:#74a9ff}}
    body{{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--text);background:radial-gradient(circle at 20% 10%,rgba(69,224,208,.22),transparent 32%),linear-gradient(135deg,#04111e,#08253a 45%,#11183a)}}
    a{{color:inherit;text-decoration:none}}
    nav{{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:18px min(5vw,64px);background:rgba(3,11,20,.78);border-bottom:1px solid var(--line);position:sticky;top:0;backdrop-filter:blur(14px)}}
    .brand{{display:flex;align-items:center;gap:12px}}.brand-mark{{width:38px;height:38px;border-radius:12px;background:linear-gradient(135deg,#06b6d4,#8b5cf6 55%,#10b981);display:grid!important;place-items:center;color:#fff!important;font-size:11px!important;font-weight:900;letter-spacing:-.04em!important}}.brand-copy{{display:flex!important;flex-direction:column;line-height:1.08}}.brand-copy strong{{display:block;font-size:18px}}.brand-copy span{{display:block;color:var(--muted);font-size:12px;letter-spacing:.8px;text-transform:uppercase;margin-top:3px}}
    .links{{display:flex;gap:10px;flex-wrap:wrap}}.links a{{border:1px solid var(--line);background:rgba(255,255,255,.075);padding:10px 14px;border-radius:999px;font-size:14px;font-weight:650}}
    main{{max-width:1180px;margin:0 auto;padding:58px 22px 70px}}
    .panel{{border:1px solid var(--line);background:linear-gradient(180deg,rgba(255,255,255,.10),rgba(255,255,255,.045));border-radius:30px;padding:28px;margin-bottom:18px;box-shadow:0 28px 90px rgba(0,0,0,.22)}}
    h1{{font-size:clamp(38px,5vw,68px);line-height:.98;letter-spacing:-2px;margin:0}}h2{{font-size:28px;margin:0 0 14px}}
    p{{color:var(--muted);line-height:1.72}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:14px;margin-top:22px}}
    .metric{{border:1px solid var(--line);background:rgba(0,0,0,.14);border-radius:22px;padding:18px}}
    .label{{color:var(--muted);text-transform:uppercase;font-size:12px;letter-spacing:1px;font-weight:800}}.value{{margin-top:8px;font-size:30px;font-weight:850}}
    .table-wrap{{overflow:auto;border:1px solid var(--line);border-radius:22px;background:rgba(0,0,0,.12)}}table{{border-collapse:collapse;width:100%;font-size:13px}}th,td{{padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.08);white-space:nowrap}}th{{text-align:left;color:#bafff8;background:rgba(255,255,255,.06)}}
    @media(max-width:850px){{.grid{{grid-template-columns:1fr 1fr}}nav{{align-items:flex-start;flex-direction:column}}}}
    @media(max-width:520px){{.grid{{grid-template-columns:1fr}}}}
  </style>
</head>
<body>
  <nav>
    <a class="brand" href="index.html">
      <span class="brand-mark" aria-hidden="true">FR</span>
      <span class="brand-copy"><strong>Forecast Redelong</strong><span>Evaluasi Forecast</span></span>
    </a>
    <div class="links">
      <a href="index.html">Home</a>
      <a href="redelong_rain_map.html">Peta Hujan</a>
      <a href="redelong_overview.html">Overview</a>
    </div>
  </nav>

  <main>
    <section class="panel">
      <h1>Validasi terhadap referensi proxy.</h1>
      <p><strong>Mode evaluasi:</strong> {escape(obs_mode)}</p>
      <p><strong>Sumber referensi:</strong> {escape(source_label)}</p>
      <p><strong>Status:</strong> {escape(str(status.get('state', 'indikatif')))}. {escape(str(status.get('reason', '')))}</p>
      <p>
        Halaman ini membandingkan akumulasi forecast 24 jam dengan referensi
        gridded pada tanggal dan lokasi yang sama. Ini bukan pengukuran
        langsung di site. Forecast harian dihitung dengan
        menjumlahkan setiap model lebih dahulu, lalu membentuk konsensus antar-model.
        BMKG kategoris, model kosong, dan hari dengan coverage kurang dari
        {MIN_HOURS_PER_SOURCE_DAY}/24 jam tidak masuk perhitungan.
      </p>
      <div class="grid">
        <div class="metric"><div class="label">Sampel Evaluasi</div><div class="value">{int(best["n_samples"])}</div></div>
        <div class="metric"><div class="label">Tanggal unik</div><div class="value">{int(status.get("matched_unique_dates", 0))}</div></div>
        <div class="metric"><div class="label">Akurasi kejadian ≥1 mm</div><div class="value">{fmt(best["event_accuracy_ge_1mm"] * 100)}%</div></div>
        <div class="metric"><div class="label">Akurasi kejadian ≥10 mm</div><div class="value">{fmt(best["event_accuracy_ge_10mm"] * 100)}%</div></div>
        <div class="metric"><div class="label">MAE jumlah hujan</div><div class="value">{fmt(best["mae_mm"])} mm</div></div>
        <div class="metric"><div class="label">Bias jumlah hujan</div><div class="value">{fmt(best["bias_mm"])} mm</div></div>
      </div>
    </section>

    <section class="panel">
      <h2>Cara membaca metrik</h2>
      <p><strong>MAE</strong> adalah rata-rata besar selisih forecast; lebih kecil lebih baik. <strong>RMSE</strong> memberi penalti lebih besar pada kesalahan ekstrem. <strong>Bias</strong> positif berarti forecast cenderung terlalu basah, sedangkan bias negatif berarti terlalu kering.</p>
      <p><strong>POD</strong> menunjukkan bagian kejadian hujan yang berhasil terdeteksi; lebih tinggi lebih baik. <strong>FAR</strong> adalah bagian alarm hujan yang ternyata tidak terjadi; lebih rendah lebih baik. <strong>CSI</strong> merangkum hit, miss, dan false alarm; lebih tinggi lebih baik.</p>
      <p><strong>Mean</strong> adalah konsensus rata-rata antar-model. <strong>P90</strong> adalah skenario tinggi antar-model, bukan peluang 90%. Baris <strong>H+1/H+2/H+3</strong> memisahkan hasil berdasarkan jarak hari dari waktu forecast diterbitkan.</p>
    </section>

    <section class="panel">
      <h2>Metrik evaluasi</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Cakupan</th>
              <th>Forecast Metric</th>
              <th>N</th>
              <th>MAE mm</th>
              <th>RMSE mm</th>
              <th>Bias mm</th>
              <th>Klasifikasi benar ≥1mm</th>
              <th>POD ≥1mm</th>
              <th>FAR ≥1mm</th>
              <th>CSI ≥1mm</th>
              <th>Akurasi kejadian ≥10mm</th>
            </tr>
          </thead>
          <tbody>{metric_rows}</tbody>
        </table>
      </div>
    </section>

    <section class="panel">
      <h2>Data yang dibandingkan</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Tanggal</th>
              <th>Lokasi</th>
              <th>Issue</th>
              <th>Lead</th>
              <th>Observed mm</th>
              <th>Forecast Mean</th>
              <th>Forecast P90</th>
              <th>Forecast Max</th>
              <th>Model valid</th>
              <th>Coverage minimum</th>
            </tr>
          </thead>
          <tbody>{sample_rows}</tbody>
        </table>
      </div>
    </section>

    <p>Generated {escape(generated)}</p>
  </main>
</body>
</html>
"""

    (outputs / "evaluation_summary.html").write_text(html, encoding="utf-8")
    (outputs / "validation_status.html").write_text(html, encoding="utf-8")
    print("SUCCESS")
    print("Evaluation written:")
    print("-", outputs / "evaluation_metrics.csv")
    print("-", outputs / "evaluation_summary.html")


if __name__ == "__main__":
    main()
