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
FORECAST_PATH = OUTPUTS / "forecast_all_locations.csv"
WIB = timezone(timedelta(hours=7))


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


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    fc = read_csv(FORECAST_PATH)
    obs = read_csv(OBS_PATH)

    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    if fc.empty or obs.empty:
        write_empty_page("Forecast atau observasi belum tersedia.", generated)
        return

    loc_col_fc = pick_col(fc, ["location_slug", "slug", "location_id", "location"], ["location"])
    date_col_fc = pick_date_col(fc)
    rain_col_fc = pick_rain_col(fc)

    loc_col_obs = pick_col(obs, ["location_slug", "slug", "location_id", "location"], ["location"])
    date_col_obs = pick_col(obs, ["date", "tanggal", "observed_date"], ["date", "tanggal"])
    rain_col_obs = pick_col(obs, ["rain_mm_observed", "observed_rain_mm", "rain_mm", "hujan_mm"], ["rain"])

    required = {
        "forecast location": loc_col_fc,
        "forecast date": date_col_fc,
        "forecast rain": rain_col_fc,
        "observation location": loc_col_obs,
        "observation date": date_col_obs,
        "observation rain": rain_col_obs,
    }

    missing = [k for k, v in required.items() if v is None]
    if missing:
        write_empty_page("Kolom tidak lengkap: " + ", ".join(missing), generated)
        return

    fc_work = fc[[loc_col_fc, date_col_fc, rain_col_fc]].copy()
    fc_work.columns = ["location_slug", "date", "rain_mm_forecast"]
    fc_work["date"] = normalize_date(fc_work["date"])
    fc_work["rain_mm_forecast"] = pd.to_numeric(fc_work["rain_mm_forecast"], errors="coerce")

    obs_work = obs[[loc_col_obs, date_col_obs, rain_col_obs]].copy()
    obs_work.columns = ["location_slug", "date", "rain_mm_observed"]
    obs_work["date"] = normalize_date(obs_work["date"])
    obs_work["rain_mm_observed"] = pd.to_numeric(obs_work["rain_mm_observed"], errors="coerce")

    fc_daily = (
        fc_work
        .dropna(subset=["location_slug", "date", "rain_mm_forecast"])
        .groupby(["location_slug", "date"], as_index=False)
        .agg(
            rain_forecast_mean=("rain_mm_forecast", "mean"),
            rain_forecast_p90=("rain_mm_forecast", lambda x: float(np.nanquantile(x, 0.90))),
            rain_forecast_max=("rain_mm_forecast", "max"),
            forecast_points=("rain_mm_forecast", "count"),
        )
    )

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
        write_empty_page("Belum ada tanggal dan lokasi yang match antara forecast dan observasi.", generated)
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

    joined.to_csv(OUTPUTS / "evaluation_joined_daily.csv", index=False)
    metrics.to_csv(OUTPUTS / "evaluation_metrics.csv", index=False)

    write_page(joined, metrics, generated)


def write_empty_page(message: str, generated: str) -> None:
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
    (OUTPUTS / "evaluation_summary.html").write_text(html, encoding="utf-8")
    print("WARNING:", message)


def write_page(joined: pd.DataFrame, metrics: pd.DataFrame, generated: str) -> None:
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
      <p>
        Halaman ini membandingkan forecast hujan harian dengan data observasi aktual.
        Angka akurasi hanya dihitung dari pasangan tanggal dan lokasi yang memiliki
        data forecast serta observasi.
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

    (OUTPUTS / "evaluation_summary.html").write_text(html, encoding="utf-8")
    print("SUCCESS")
    print("Evaluation written:")
    print("-", OUTPUTS / "evaluation_metrics.csv")
    print("-", OUTPUTS / "evaluation_summary.html")


if __name__ == "__main__":
    main()
