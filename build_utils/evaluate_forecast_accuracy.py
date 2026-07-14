from __future__ import annotations

import math
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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
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


def main(
    outputs: Path = OUTPUTS,
    forecast_path: Path = FORECAST_PATH,
    observation_path: Path = OBS_PATH,
    proxy_observation_path: Path = PROXY_OBS_PATH,
) -> None:
    outputs.mkdir(parents=True, exist_ok=True)

    fc = read_csv(forecast_path)
    obs = read_csv(observation_path)
    obs_mode = "field_observation"

    if obs.empty or "rain_mm_observed" not in obs.columns or not pd.to_numeric(obs.get("rain_mm_observed"), errors="coerce").notna().any():
        obs = read_csv(proxy_observation_path)
        obs_mode = "proxy_observation"
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    if fc.empty:
        write_empty_page(
            "Data forecast belum tersedia. Jalankan forecast terlebih dahulu.",
            generated,
            outputs,
        )
        return
    if obs.empty:
        write_empty_page(
            "Data observasi yang sesuai belum tersedia. Metrik evaluasi akan "
            "ditampilkan setelah tersedia pasangan forecast dan observasi pada "
            "tanggal serta lokasi yang sama.",
            generated,
            outputs,
        )
        return

    loc_col_obs = pick_col(obs, ["location_slug", "slug", "location_id", "location"], ["location"])
    date_col_obs = pick_col(obs, ["date", "tanggal", "observed_date"], ["date", "tanggal"])
    rain_col_obs = pick_col(obs, ["rain_mm_observed", "observed_rain_mm", "rain_mm", "hujan_mm"], ["rain"])

    required = {
        "observation location": loc_col_obs,
        "observation date": date_col_obs,
        "observation rain": rain_col_obs,
    }

    missing = [k for k, v in required.items() if v is None]
    if missing:
        write_empty_page("Kolom tidak lengkap: " + ", ".join(missing), generated, outputs)
        return

    fc_daily, forecast_message = build_daily_forecast(fc)
    if fc_daily.empty:
        write_empty_page(forecast_message or "Forecast harian belum tersedia.", generated, outputs)
        return

    obs_work = obs[[loc_col_obs, date_col_obs, rain_col_obs]].copy()
    obs_work.columns = ["location_slug", "date", "rain_mm_observed"]
    obs_work["date"] = normalize_date(obs_work["date"])
    obs_work["rain_mm_observed"] = pd.to_numeric(obs_work["rain_mm_observed"], errors="coerce")

    obs_daily = (
        obs_work
        .dropna(subset=["location_slug", "date", "rain_mm_observed"])
        .groupby(["location_slug", "date"], as_index=False)
        .agg(
            rain_mm_observed=("rain_mm_observed", "mean"),
            observation_points=("rain_mm_observed", "count"),
        )
    )

    joined = pd.merge(obs_daily, fc_daily, on=["location_slug", "date"], how="inner")

    if joined.empty:
        write_empty_page(
            "Belum ada tanggal dan lokasi yang match antara forecast 24 jam lengkap dan observasi.",
            generated,
            outputs,
        )
        return

    metrics_rows = []

    for forecast_col in ["rain_forecast_mean", "rain_forecast_p90", "rain_forecast_max"]:
        y_true = joined["rain_mm_observed"].to_numpy(dtype=float)
        y_pred = joined[forecast_col].to_numpy(dtype=float)
        err = y_pred - y_true

        row = {
            "forecast_metric": forecast_col,
            "n_samples": len(joined),
            "mae_mm": float(np.nanmean(np.abs(err))),
            "rmse_mm": float(math.sqrt(np.nanmean(err ** 2))),
            "bias_mm": float(np.nanmean(err)),
            "mean_observed_mm": float(np.nanmean(y_true)),
            "mean_forecast_mm": float(np.nanmean(y_pred)),
        }

        row.update(event_metrics(y_true, y_pred, threshold=1.0))
        row.update(event_metrics(y_true, y_pred, threshold=10.0))

        metrics_rows.append(row)

    metrics = pd.DataFrame(metrics_rows)

    joined.to_csv(outputs / "evaluation_joined_daily.csv", index=False)
    metrics.to_csv(outputs / "evaluation_metrics.csv", index=False)

    write_page(joined, metrics, generated, obs_mode, outputs)


def write_empty_page(message: str, generated: str, outputs: Path = OUTPUTS) -> None:
    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <title>Evaluasi Akurasi · Forecast Redelong</title>
  <style>
    body{{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:#eff8ff;background:#04111e}}
    main{{max-width:980px;margin:0 auto;padding:70px 22px}}
    .panel{{border:1px solid rgba(255,255,255,.15);background:rgba(255,255,255,.08);border-radius:28px;padding:28px}}
    a{{color:#45e0d0}}
    p{{color:#9fb4c9;line-height:1.7}}
  </style>
</head>
<body>
  <main>
    <div class="panel">
      <h1>Evaluasi Akurasi Forecast Redelong</h1>
      <p>{escape(message)}</p>
      <p>Isi data observasi di <code>data/redelong/observations/rain_observed_daily.csv</code>, lalu jalankan workflow ulang.</p>
      <p><a href="index.html">Kembali ke Home</a></p>
      <p>Generated {escape(generated)}</p>
    </div>
  </main>
</body>
</html>
"""
    (outputs / "evaluation_summary.html").write_text(html, encoding="utf-8")
    print("WARNING:", message)


def write_page(
    joined: pd.DataFrame,
    metrics: pd.DataFrame,
    generated: str,
    obs_mode: str,
    outputs: Path = OUTPUTS,
) -> None:
    best = metrics.sort_values("mae_mm").iloc[0]

    metric_rows = ""
    for _, row in metrics.iterrows():
        metric_rows += f"""
        <tr>
          <td>{escape(str(row["forecast_metric"]))}</td>
          <td>{int(row["n_samples"])}</td>
          <td>{fmt(row["mae_mm"])}</td>
          <td>{fmt(row["rmse_mm"])}</td>
          <td>{fmt(row["bias_mm"])}</td>
          <td>{fmt(row["event_accuracy_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["pod_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["far_ge_1mm"] * 100)}%</td>
          <td>{fmt(row["csi_ge_1mm"] * 100)}%</td>
        </tr>
        """

    sample_rows = ""
    for _, row in joined.head(40).iterrows():
        sample_rows += f"""
        <tr>
          <td>{escape(str(row["date"]))}</td>
          <td>{escape(str(row["location_slug"]))}</td>
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
  <title>Evaluasi Akurasi · Forecast Redelong</title>
  <style>
    :root{{--bg:#040c16;--panel:rgba(255,255,255,.08);--line:rgba(255,255,255,.15);--text:#eff8ff;--muted:#9fb4c9;--cyan:#45e0d0;--blue:#74a9ff}}
    body{{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--text);background:radial-gradient(circle at 20% 10%,rgba(69,224,208,.22),transparent 32%),linear-gradient(135deg,#04111e,#08253a 45%,#11183a)}}
    a{{color:inherit;text-decoration:none}}
    nav{{display:flex;justify-content:space-between;gap:14px;align-items:center;padding:18px min(5vw,64px);background:rgba(3,11,20,.78);border-bottom:1px solid var(--line);position:sticky;top:0;backdrop-filter:blur(14px)}}
    .brand strong{{display:block;font-size:18px}}.brand span{{display:block;color:var(--muted);font-size:12px;letter-spacing:.8px;text-transform:uppercase}}
    .links{{display:flex;gap:10px;flex-wrap:wrap}}.links a{{border:1px solid var(--line);background:rgba(255,255,255,.075);padding:10px 14px;border-radius:999px;font-size:14px;font-weight:650}}
    main{{max-width:1180px;margin:0 auto;padding:58px 22px 70px}}
    .panel{{border:1px solid var(--line);background:linear-gradient(180deg,rgba(255,255,255,.10),rgba(255,255,255,.045));border-radius:30px;padding:28px;margin-bottom:18px;box-shadow:0 28px 90px rgba(0,0,0,.22)}}
    h1{{font-size:clamp(38px,5vw,68px);line-height:.98;letter-spacing:-2px;margin:0}}h2{{font-size:28px;margin:0 0 14px}}
    p{{color:var(--muted);line-height:1.72}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-top:22px}}
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
      <strong>Forecast Redelong</strong>
      <span>FORECAST PLTA REDELONG</span>
    </a>
    <div class="links">
      <a href="index.html">Home</a>
      <a href="redelong_rain_map.html">Peta Hujan</a>
      <a href="redelong_overview.html">Overview</a>
    </div>
  </nav>

  <main>
    <section class="panel">
      <h1>Evaluasi akurasi forecast.</h1>
      <p><strong>Mode evaluasi:</strong> {escape(obs_mode)}</p>
      <p>
        Halaman ini membandingkan akumulasi forecast 24 jam dengan data pembanding
        harian pada tanggal dan lokasi yang sama. Forecast harian dihitung dengan
        menjumlahkan setiap model lebih dahulu, lalu membentuk konsensus antar-model.
        BMKG kategoris, model kosong, dan hari dengan coverage kurang dari
        {MIN_HOURS_PER_SOURCE_DAY}/24 jam tidak masuk perhitungan.
      </p>
      <div class="grid">
        <div class="metric"><div class="label">Sampel Evaluasi</div><div class="value">{int(best["n_samples"])}</div></div>
        <div class="metric"><div class="label">Metric Terbaik</div><div class="value" style="font-size:18px">{escape(str(best["forecast_metric"]))}</div></div>
        <div class="metric"><div class="label">MAE Terbaik</div><div class="value">{fmt(best["mae_mm"])} mm</div></div>
        <div class="metric"><div class="label">Event Accuracy ≥1mm</div><div class="value">{fmt(best["event_accuracy_ge_1mm"] * 100)}%</div></div>
      </div>
    </section>

    <section class="panel">
      <h2>Metrik evaluasi</h2>
      <div class="table-wrap">
        <table>
          <thead>
            <tr>
              <th>Forecast Metric</th>
              <th>N</th>
              <th>MAE mm</th>
              <th>RMSE mm</th>
              <th>Bias mm</th>
              <th>Accuracy ≥1mm</th>
              <th>POD ≥1mm</th>
              <th>FAR ≥1mm</th>
              <th>CSI ≥1mm</th>
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
    print("SUCCESS")
    print("Evaluation written:")
    print("-", outputs / "evaluation_metrics.csv")
    print("-", outputs / "evaluation_summary.html")


if __name__ == "__main__":
    main()
