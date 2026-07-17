"""Build a provisional rainfall-to-discharge forecast for PLTA Redelong.

The model is deliberately small and auditable.  It is an ARX(1) daily routing
model calibrated against GloFAS simulated discharge and area-weighted
GPM1--GPM6 historical rainfall.  Operational forcing comes only from the
existing multi-model catchment rainfall forecast.  It must not be presented as
field-calibrated inflow until site discharge/AWLR observations are available.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
HISTORY_RAIN = ROOT / "data" / "redelong" / "history" / "gpm_daily_history.csv"
POINTS = ROOT / "data" / "redelong" / "catchment_points.csv"
MIN_HOURS_PER_24H_WINDOW = 19


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Input hidrologi tidak ditemukan: {path}")
    return pd.read_csv(path, encoding="utf-8-sig")


def _as_bool(value) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ya"}


def area_weighted_history() -> pd.DataFrame:
    rain = _read_csv(HISTORY_RAIN)
    points = _read_csv(POINTS)
    points["include_in_catchment"] = points["include_in_catchment"].map(_as_bool)
    points = points.loc[points["include_in_catchment"], ["point_name", "weight_km2"]].copy()
    points["location_slug"] = points["point_name"].str.lower().str.replace(r"[^a-z0-9]+", "_", regex=True)
    rain = rain.merge(points[["location_slug", "weight_km2"]], on="location_slug", how="inner")
    rain["weighted_rain"] = rain["rain_mm"] * rain["weight_km2"]
    daily = rain.groupby("date", as_index=False).agg(
        weighted_rain=("weighted_rain", "sum"),
        represented_area_km2=("weight_km2", "sum"),
        zone_count=("location_slug", "nunique"),
    )
    daily["rain_mm"] = daily["weighted_rain"] / daily["represented_area_km2"]
    return daily[["date", "rain_mm", "represented_area_km2", "zone_count"]]


def prepare_calibration(rain: pd.DataFrame, discharge: pd.DataFrame, issue_time: pd.Timestamp) -> pd.DataFrame:
    frame = rain.merge(discharge[["date", "river_discharge"]], on="date", how="inner")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame["rain_mm"] = pd.to_numeric(frame["rain_mm"], errors="coerce")
    frame["river_discharge"] = pd.to_numeric(frame["river_discharge"], errors="coerce")
    frame = frame.dropna(subset=["date", "rain_mm", "river_discharge"]).sort_values("date")
    # Do not calibrate with the current year's seamless values, which may
    # already contain forecast rather than consolidated reanalysis.
    frame = frame[frame["date"] < pd.Timestamp(year=issue_time.year, month=1, day=1)].copy()
    frame["previous_discharge"] = frame["river_discharge"].shift(1)
    frame = frame.dropna(subset=["previous_discharge"])
    return frame.reset_index(drop=True)


def fit_arx(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame, pd.DataFrame]:
    if len(frame) < 3650:
        raise ValueError("Seri kalibrasi debit kurang dari 10 tahun")
    last_year = int(frame["date"].dt.year.max())
    validation_start_year = last_year - 6
    train = frame[frame["date"].dt.year < validation_start_year].copy()
    validation = frame[frame["date"].dt.year >= validation_start_year].copy()
    if len(train) < 3650 or len(validation) < 365:
        raise ValueError("Pembagian train/validation debit tidak mencukupi")

    matrix = np.column_stack(
        [np.ones(len(train)), train["previous_discharge"], train["rain_mm"]]
    )
    target = train["river_discharge"].to_numpy(dtype=float)
    intercept, recession, rainfall_response = np.linalg.lstsq(matrix, target, rcond=None)[0]
    if not (0.0 <= recession < 1.0 and rainfall_response >= 0.0):
        raise ValueError(
            "Koefisien model tidak fisik; hentikan publikasi debit sampai konfigurasi ditinjau"
        )
    parameters = {
        "intercept_m3s": float(intercept),
        "recession_coefficient": float(recession),
        "rainfall_response_m3s_per_mm": float(rainfall_response),
        "training_start": train["date"].min().date().isoformat(),
        "training_end": train["date"].max().date().isoformat(),
        "training_rows": int(len(train)),
        "validation_start": validation["date"].min().date().isoformat(),
        "validation_end": validation["date"].max().date().isoformat(),
        "validation_rows": int(len(validation)),
    }
    return parameters, train, validation


def _metrics(observed: np.ndarray, predicted: np.ndarray) -> dict:
    observed = np.asarray(observed, dtype=float)
    predicted = np.asarray(predicted, dtype=float)
    error = predicted - observed
    denominator = np.sum((observed - observed.mean()) ** 2)
    nse = 1.0 - np.sum(error**2) / denominator if denominator else np.nan
    correlation = np.corrcoef(observed, predicted)[0, 1] if len(observed) > 1 else np.nan
    alpha = predicted.std() / observed.std() if observed.std() else np.nan
    beta = predicted.mean() / observed.mean() if observed.mean() else np.nan
    kge = 1.0 - math.sqrt((correlation - 1) ** 2 + (alpha - 1) ** 2 + (beta - 1) ** 2)
    return {
        "n_samples": int(len(observed)),
        "mae_m3s": float(np.mean(np.abs(error))),
        "rmse_m3s": float(np.sqrt(np.mean(error**2))),
        "bias_m3s": float(np.mean(error)),
        "nse": float(nse),
        "kge": float(kge),
        "correlation": float(correlation),
    }


def rolling_hindcast(validation: pd.DataFrame, parameters: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows: list[dict] = []
    data = validation.reset_index(drop=True)
    c = parameters["intercept_m3s"]
    a = parameters["recession_coefficient"]
    b = parameters["rainfall_response_m3s_per_mm"]
    for issue_index in range(len(data)):
        previous = float(data.iloc[issue_index]["previous_discharge"])
        issue_date = pd.Timestamp(data.iloc[issue_index]["date"]) - pd.Timedelta(days=1)
        for lead in (1, 2, 3):
            target_index = issue_index + lead - 1
            if target_index >= len(data):
                break
            target = data.iloc[target_index]
            predicted = max(0.0, c + a * previous + b * float(target["rain_mm"]))
            rows.append(
                {
                    "issue_date": issue_date.date().isoformat(),
                    "valid_date": pd.Timestamp(target["date"]).date().isoformat(),
                    "lead_day": lead,
                    "rain_mm": float(target["rain_mm"]),
                    "discharge_proxy_observed_m3s": float(target["river_discharge"]),
                    "discharge_modelled_m3s": predicted,
                }
            )
            previous = predicted
    pairs = pd.DataFrame(rows)
    metric_rows = []
    for lead, group in pairs.groupby("lead_day"):
        metric_rows.append(
            {
                "lead_day": int(lead),
                **_metrics(
                    group["discharge_proxy_observed_m3s"].to_numpy(),
                    group["discharge_modelled_m3s"].to_numpy(),
                ),
            }
        )
    return pairs, pd.DataFrame(metric_rows)


def forecast_rain_windows(outputs: Path, forecast_start: pd.Timestamp) -> pd.DataFrame:
    hourly = _read_csv(outputs / "operational_source_hourly.csv")
    hourly["valid_time_wib"] = pd.to_datetime(hourly["valid_time_wib"], errors="coerce", utc=True).dt.tz_convert("Asia/Jakarta")
    hourly["rain_mm"] = pd.to_numeric(hourly["rain_mm"], errors="coerce")
    hourly = hourly.dropna(subset=["valid_time_wib", "rain_mm"])
    hourly["lead_day"] = ((hourly["valid_time_wib"] - forecast_start).dt.total_seconds() // 86400 + 1).astype(int)
    hourly = hourly[hourly["lead_day"].between(1, 3)]
    source = hourly.groupby(["lead_day", "source_id"], as_index=False).agg(
        rain_mm=("rain_mm", "sum"), hours_available=("valid_time_wib", "nunique")
    )
    source = source[source["hours_available"] >= MIN_HOURS_PER_24H_WINDOW]
    rows = []
    for lead, group in source.groupby("lead_day"):
        values = group["rain_mm"].dropna()
        start = forecast_start + pd.Timedelta(days=int(lead) - 1)
        rows.append(
            {
                "lead_day": int(lead),
                "window_start_wib": start.isoformat(),
                "window_end_wib": (start + pd.Timedelta(days=1)).isoformat(),
                "rain_mean_mm": float(values.mean()),
                "rain_p10_mm": float(values.quantile(0.10)),
                "rain_p90_mm": float(values.quantile(0.90)),
                "model_count": int(len(values)),
                "model_list": ",".join(sorted(group["source_id"].astype(str).unique())),
            }
        )
    result = pd.DataFrame(rows)
    if set(result.get("lead_day", [])) != {1, 2, 3}:
        raise ValueError("Forecast hujan 24 jam untuk lead 1-3 belum lengkap")
    return result.sort_values("lead_day").reset_index(drop=True)


def make_discharge_forecast(
    rain_windows: pd.DataFrame,
    current_reference: pd.DataFrame,
    forecast_start: pd.Timestamp,
    parameters: dict,
    metrics: pd.DataFrame,
) -> pd.DataFrame:
    current = current_reference.copy()
    current["date"] = pd.to_datetime(current["date"], errors="coerce")
    initial_candidates = current[current["date"] < forecast_start.tz_localize(None).normalize()]
    if initial_candidates.empty:
        raise ValueError("GloFAS tidak menyediakan initial discharge sebelum forecast")
    initial = initial_candidates.dropna(subset=["river_discharge"]).iloc[-1]
    previous_scenarios = {
        "mean": float(initial["river_discharge"]),
        "low": float(initial["river_discharge"]),
        "high": float(initial["river_discharge"]),
    }
    c = parameters["intercept_m3s"]
    a = parameters["recession_coefficient"]
    b = parameters["rainfall_response_m3s_per_mm"]
    rows = []
    for _, rain in rain_windows.iterrows():
        lead = int(rain["lead_day"])
        predictions = {}
        for scenario, column in [("mean", "rain_mean_mm"), ("low", "rain_p10_mm"), ("high", "rain_p90_mm")]:
            predictions[scenario] = max(
                0.0, c + a * previous_scenarios[scenario] + b * float(rain[column])
            )
            previous_scenarios[scenario] = predictions[scenario]
        metric = metrics.loc[metrics["lead_day"] == lead].iloc[0]
        valid_date = forecast_start.tz_localize(None).normalize() + pd.Timedelta(days=lead - 1)
        reference_row = current[current["date"] == valid_date]
        reference = reference_row.iloc[0] if not reference_row.empty else pd.Series(dtype=float)
        rmse = float(metric["rmse_m3s"])
        rows.append(
            {
                **rain.to_dict(),
                "valid_date": valid_date.date().isoformat(),
                "initial_discharge_proxy_m3s": float(initial["river_discharge"]),
                "discharge_forecast_m3s": predictions["mean"],
                "discharge_scenario_low_m3s": max(0.0, predictions["low"] - rmse),
                "discharge_scenario_high_m3s": predictions["high"] + rmse,
                "glofas_reference_m3s": reference.get("river_discharge_mean", reference.get("river_discharge", np.nan)),
                "glofas_reference_p25_m3s": reference.get("river_discharge_p25", np.nan),
                "glofas_reference_p75_m3s": reference.get("river_discharge_p75", np.nan),
                "hindcast_rmse_m3s": rmse,
                "status": "provisional_proxy_calibrated",
            }
        )
    return pd.DataFrame(rows)


def evaluate_archived_forecasts(
    outputs: Path,
    history_reference: pd.DataFrame,
    current_reference: pd.DataFrame,
    current_issue: pd.Timestamp,
) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """Evaluate matured archived forecasts without confusing them with hindcast skill."""
    frames: list[pd.DataFrame] = []
    for path in sorted((outputs / "archive").glob("*/*/*/redelong_discharge_forecast.csv")):
        payload_path = path.with_name("redelong_discharge.json")
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8-sig"))
            issue = pd.Timestamp(payload["issue_time_wib"])
            frame = pd.read_csv(path, encoding="utf-8-sig")
        except Exception:
            continue
        frame["issue_time_wib"] = issue.isoformat()
        frame["issue_date"] = issue.date().isoformat()
        frames.append(frame)
    columns = [
        "issue_time_wib",
        "issue_date",
        "valid_date",
        "lead_day",
        "discharge_forecast_m3s",
        "discharge_proxy_observed_m3s",
    ]
    if not frames:
        return pd.DataFrame(columns=columns), pd.DataFrame(), "collecting_archive"

    forecast = pd.concat(frames, ignore_index=True)
    forecast["valid_date"] = pd.to_datetime(forecast["valid_date"], errors="coerce")
    forecast["issue_time_parsed"] = pd.to_datetime(forecast["issue_time_wib"], errors="coerce", utc=True)
    forecast = forecast[
        forecast["valid_date"] < current_issue.tz_localize(None).normalize()
    ].dropna(subset=["valid_date", "issue_time_parsed", "discharge_forecast_m3s"])
    forecast = forecast.sort_values("issue_time_parsed").drop_duplicates(
        ["issue_date", "valid_date", "lead_day"], keep="first"
    )

    reference = pd.concat(
        [
            history_reference[["date", "river_discharge"]],
            current_reference[["date", "river_discharge"]],
        ],
        ignore_index=True,
    )
    reference["valid_date"] = pd.to_datetime(reference["date"], errors="coerce")
    reference["discharge_proxy_observed_m3s"] = pd.to_numeric(
        reference["river_discharge"], errors="coerce"
    )
    reference = reference.dropna(subset=["valid_date", "discharge_proxy_observed_m3s"])
    reference = reference.drop_duplicates("valid_date", keep="last")
    pairs = forecast.merge(
        reference[["valid_date", "discharge_proxy_observed_m3s"]],
        on="valid_date",
        how="inner",
    )
    if pairs.empty:
        return pd.DataFrame(columns=columns), pd.DataFrame(), "collecting_archive"
    pairs["valid_date"] = pairs["valid_date"].dt.date.astype(str)
    pairs = pairs[columns]
    metric_rows = []
    for lead, group in pairs.groupby("lead_day"):
        metric_rows.append(
            {
                "lead_day": int(lead),
                **_metrics(
                    group["discharge_proxy_observed_m3s"].to_numpy(),
                    group["discharge_forecast_m3s"].to_numpy(),
                ),
            }
        )
    metrics = pd.DataFrame(metric_rows)
    minimum = int(metrics["n_samples"].min()) if not metrics.empty else 0
    status = "preliminary_proxy_skill" if minimum >= 30 else "limited_sample"
    return pairs, metrics, status


def _fmt(value, digits: int = 1) -> str:
    return "—" if value is None or pd.isna(value) else f"{float(value):.{digits}f}"


def dashboard_html(forecast: pd.DataFrame, metrics: pd.DataFrame, metadata: dict, parameters: dict) -> str:
    cards = []
    rows = []
    max_q = max(float(forecast["discharge_scenario_high_m3s"].max()), 1.0)
    bars = []
    for _, row in forecast.iterrows():
        lead = int(row["lead_day"])
        cards.append(
            f"<article class='card'><span>Lead {lead} · {escape(str(row['valid_date']))}</span>"
            f"<strong>{_fmt(row['discharge_forecast_m3s'])} m³/s</strong>"
            f"<small>Skenario {_fmt(row['discharge_scenario_low_m3s'])}–{_fmt(row['discharge_scenario_high_m3s'])} m³/s · GloFAS {_fmt(row['glofas_reference_m3s'])} m³/s</small>"
            f"<em>Hujan area {_fmt(row['rain_mean_mm'])} mm/24 jam</em></article>"
        )
        metric = metrics.loc[metrics["lead_day"] == lead].iloc[0]
        rows.append(
            f"<tr><td>{lead}</td><td>{int(metric['n_samples']):,}</td><td>{_fmt(metric['mae_m3s'],2)}</td>"
            f"<td>{_fmt(metric['rmse_m3s'],2)}</td><td>{_fmt(metric['bias_m3s'],2)}</td>"
            f"<td>{_fmt(metric['nse'],3)}</td><td>{_fmt(metric['kge'],3)}</td></tr>"
        )
        width = max(2.0, float(row["discharge_forecast_m3s"]) / max_q * 100)
        low = float(row["discharge_scenario_low_m3s"]) / max_q * 100
        high = float(row["discharge_scenario_high_m3s"]) / max_q * 100
        bars.append(
            f"<div class='bar-row'><b>Lead {lead}</b><div class='track'><i style='left:{low:.1f}%;width:{max(high-low,1):.1f}%'></i>"
            f"<span style='width:{width:.1f}%'></span></div><strong>{_fmt(row['discharge_forecast_m3s'])}</strong></div>"
        )
    selected = metadata["selected_grid_coordinate"]
    return f"""<!doctype html><html lang='id'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='forecast-hydro-page' content='forecast-redelong-discharge-v1'><title>Forecast Debit · PLTA Redelong</title><style>
:root{{--ink:#eaf7ff;--muted:#9bb4c8;--line:rgba(148,211,255,.16);--cyan:#22d3ee;--blue:#0ea5e9;--deep:#03111d}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 15% 0,#0b3952,transparent 38%),#03111d;color:var(--ink);font-family:Inter,system-ui,sans-serif}}a{{color:inherit}}.shell{{max-width:1180px;margin:auto;padding:22px 24px 52px}}nav{{display:flex;justify-content:space-between;align-items:center;margin-bottom:25px}}.brand{{display:flex;align-items:center;gap:12px;text-decoration:none}}.mark{{width:44px;height:44px;border-radius:14px;background:linear-gradient(145deg,#7c3aed,#22d3ee);display:grid;place-items:center;font-weight:900;box-shadow:0 12px 28px rgba(34,211,238,.18)}}.brand b,.brand small{{display:block}}.brand small{{color:var(--muted);font-size:10px;letter-spacing:.12em;text-transform:uppercase}}nav>a:last-child{{font-size:12px;text-decoration:none;color:var(--muted)}}.hero{{border:1px solid var(--line);background:linear-gradient(135deg,rgba(14,165,233,.16),rgba(3,17,29,.55));border-radius:28px;padding:42px}}.tag{{color:var(--cyan);font-size:11px;letter-spacing:.16em;text-transform:uppercase;font-weight:800}}h1{{font-size:clamp(38px,6vw,70px);letter-spacing:-.05em;line-height:1;margin:13px 0 16px}}.lead{{max-width:760px;color:#c6dbea;line-height:1.7}}.warning{{margin-top:22px;background:rgba(245,158,11,.10);border:1px solid rgba(245,158,11,.28);color:#fde6b0;padding:14px 16px;border-radius:14px;font-size:12px;line-height:1.55}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin-top:18px}}.card,.panel{{border:1px solid var(--line);background:rgba(7,31,48,.72);border-radius:20px;padding:20px}}.card span,.card small,.card em{{display:block;color:var(--muted);font-size:11px}}.card strong{{display:block;font-size:31px;margin:18px 0 5px;letter-spacing:-.04em}}.card em{{font-style:normal;color:#8be8f6;margin-top:16px}}section{{margin-top:34px}}h2{{font-size:28px;letter-spacing:-.03em;margin:0 0 14px}}.bar-row{{display:grid;grid-template-columns:62px 1fr 60px;gap:12px;align-items:center;margin:17px 0;font-size:11px}}.track{{height:12px;background:#0d2b3d;border-radius:99px;position:relative;overflow:visible}}.track span{{display:block;height:100%;background:linear-gradient(90deg,#0284c7,#22d3ee);border-radius:99px}}.track i{{position:absolute;top:-5px;height:22px;background:rgba(34,211,238,.18);border:1px solid rgba(34,211,238,.42);border-radius:99px}}table{{width:100%;border-collapse:collapse;font-size:12px}}th,td{{padding:11px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{color:var(--muted);font-size:9px;text-transform:uppercase;letter-spacing:.1em}}.method{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}.method p,.method li{{color:var(--muted);line-height:1.65;font-size:12px}}code{{color:#9ef2ff}}.downloads{{display:flex;gap:10px;flex-wrap:wrap}}.button{{padding:11px 14px;border:1px solid var(--line);border-radius:11px;text-decoration:none;font-size:12px;font-weight:800;background:#0a2b40}}@media(max-width:760px){{.shell{{padding:14px}}.hero{{padding:28px 20px}}.grid,.method{{grid-template-columns:1fr}}.panel{{overflow:auto}}}}
</style></head><body><div class='shell'><nav><a class='brand' data-fr-brand='true' href='index.html' aria-label='Kembali ke Forecast Redelong'><span class='mark'>FR</span><span><b>Forecast Redelong</b><small>Rainfall to discharge</small></span></a><a href='redelong_operational.html'>← Dashboard hujan</a></nav><main><header class='hero'><div class='tag'>Prototype hidrologi · Engineering</div><h1>Forecast debit Redelong</h1><p class='lead'>Forecast hujan area dari enam model diubah menjadi debit harian melalui model routing ARX yang dikalibrasi terhadap referensi GloFAS. Nilai GloFAS tetap ditampilkan sebagai pembanding independen.</p><div class='warning'><b>Belum field-calibrated.</b> Angka ini menilai kesesuaian terhadap debit simulasi gridded GloFAS, bukan AWLR atau pengukuran debit di PLTA. Jangan gunakan sebagai satu-satunya dasar keputusan keselamatan, bukaan pintu, atau komitmen energi.</div></header><div class='grid'>{''.join(cards)}</div>
<section><h2>Rentang skenario debit</h2><article class='panel'>{''.join(bars)}<p style='color:var(--muted);font-size:11px'>Garis utama adalah hasil hujan ensemble mean. Pita memakai variasi hujan P10–P90 antar-model dan RMSE hindcast per lead; bukan probabilitas terkalibrasi.</p></article></section>
<section><h2>Validasi transformasi hujan–debit</h2><article class='panel'><table><thead><tr><th>Lead</th><th>Sampel</th><th>MAE m³/s</th><th>RMSE m³/s</th><th>Bias m³/s</th><th>NSE</th><th>KGE</th></tr></thead><tbody>{''.join(rows)}</tbody></table><p style='color:var(--muted);font-size:11px'>Hindcast ini memakai hujan historis IMERG sebagai forcing sempurna dan GloFAS sebagai target. Ini menguji transformasi hujan–debit, bukan skill end-to-end forecast hujan. Skill end-to-end dikumpulkan terpisah dari arsip operasional yang sudah matang.</p></article></section>
<section class='method'><article class='panel'><h2>Bagaimana dihitung</h2><p><code>Q(t) = {parameters['intercept_m3s']:.3f} + {parameters['recession_coefficient']:.4f} × Q(t−1) + {parameters['rainfall_response_m3s_per_mm']:.4f} × P(t)</code></p><ul><li>P(t): hujan area berbobot GPM1–GPM6.</li><li>Q awal: debit GloFAS hari sebelum forecast.</li><li>Kalibrasi: {parameters['training_start']}–{parameters['training_end']}.</li><li>Validasi: {parameters['validation_start']}–{parameters['validation_end']}.</li></ul></article><article class='panel'><h2>Status data</h2><p>GloFAS grid yang dipakai: {selected[0]}, {selected[1]}. Produk beresolusi sekitar 5 km dapat memilih sungai yang tidak tepat; outlet dan kecocokan grid wajib diverifikasi engineering.</p><p>Besai Kemu belum memperoleh forecast debit karena batas DAS dan outlet provisional belum dikonfirmasi.</p></article></section>
<section><h2>Unduh</h2><div class='downloads'><a class='button' href='redelong_discharge_forecast.csv'>Forecast CSV</a><a class='button' href='redelong_discharge_validation.csv'>Metrik validasi CSV</a><a class='button' href='redelong_discharge.json'>API JSON</a><a class='button' href='hydrology/glofas_discharge_metadata.json'>Metadata sumber</a></div></section></main></div></body></html>"""


def _link_operational_dashboard(outputs: Path) -> None:
    path = outputs / "redelong_operational.html"
    if not path.exists():
        return
    html = path.read_text(encoding="utf-8")
    if "redelong_discharge.html" in html:
        return
    html = html.replace(
        '<a href="#analisis">Analisis</a>',
        '<a href="#analisis">Analisis</a><a href="redelong_discharge.html">Debit</a>',
        1,
    )
    html = html.replace(
        '<section class="section" id="unduh">',
        '<section class="section"><div class="section-head"><div><span class="section-kicker">05 · Hidrologi</span><h2>Dari hujan menuju debit</h2></div><p>Model proxy terkalibrasi GloFAS, terpisah dari klaim observasi lapangan.</p></div><a class="download-card primary" href="redelong_discharge.html"><span>Q</span><div><b>Buka forecast debit</b><small>Lead 1–3 hari, skenario dan validasi proxy</small></div><em>↗</em></a></section><section class="section" id="unduh">',
        1,
    )
    html = html.replace("05 · Data dan dokumentasi", "06 · Data dan dokumentasi", 1)
    path.write_text(html, encoding="utf-8")


def build(outputs: Path) -> dict:
    operational = json.loads((outputs / "redelong_operational.json").read_text(encoding="utf-8-sig"))
    issue_time = pd.Timestamp(operational["issue_time_wib"])
    forecast_start = pd.Timestamp(operational["forecast_start_wib"])
    history_discharge = _read_csv(outputs / "hydrology" / "glofas_discharge_history.csv")
    current_discharge = _read_csv(outputs / "hydrology" / "glofas_discharge_current.csv")
    metadata = json.loads((outputs / "hydrology" / "glofas_discharge_metadata.json").read_text(encoding="utf-8"))
    calibration = prepare_calibration(area_weighted_history(), history_discharge, issue_time)
    parameters, _, validation = fit_arx(calibration)
    pairs, metrics = rolling_hindcast(validation, parameters)
    rain_windows = forecast_rain_windows(outputs, forecast_start)
    forecast = make_discharge_forecast(rain_windows, current_discharge, forecast_start, parameters, metrics)
    end_to_end_pairs, end_to_end_metrics, end_to_end_status = evaluate_archived_forecasts(
        outputs, history_discharge, current_discharge, issue_time
    )

    forecast.to_csv(outputs / "redelong_discharge_forecast.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(outputs / "redelong_discharge_validation.csv", index=False, encoding="utf-8-sig")
    pairs.to_csv(outputs / "redelong_discharge_hindcast_pairs.csv", index=False, encoding="utf-8-sig")
    end_to_end_pairs.to_csv(
        outputs / "redelong_discharge_end_to_end_pairs.csv", index=False, encoding="utf-8-sig"
    )
    end_to_end_metrics.to_csv(
        outputs / "redelong_discharge_end_to_end_validation.csv", index=False, encoding="utf-8-sig"
    )
    payload = {
        "schema_version": "forecast-redelong-rainfall-discharge-v1",
        "status": "provisional_proxy_calibrated",
        "issue_time_wib": issue_time.isoformat(),
        "forecast_start_wib": forecast_start.isoformat(),
        "model": "daily ARX(1) rainfall-routing model",
        "parameters": parameters,
        "calibration_reference": metadata,
        "validation_scope": (
            "rainfall-runoff transform hindcast using historical IMERG forcing against "
            "GloFAS simulated discharge; not end-to-end forecast skill"
        ),
        "end_to_end_validation": {
            "status": end_to_end_status,
            "matched_pairs": int(len(end_to_end_pairs)),
            "minimum_samples_to_report_preliminary_skill": 30,
            "metrics": json.loads(end_to_end_metrics.to_json(orient="records")),
        },
        "can_claim_field_accuracy": False,
        "forecast": json.loads(forecast.to_json(orient="records")),
        "validation": json.loads(metrics.to_json(orient="records")),
        "limitations": [
            "No on-site AWLR or measured discharge is available.",
            "GloFAS is a gridded simulated proxy and river-grid selection needs engineering confirmation.",
            "Rainfall P10-P90 is inter-model spread, not a calibrated probability interval.",
            "Reservoir/intake operation, losses, travel time below daily scale, and turbine constraints are not modelled.",
        ],
    }
    (outputs / "redelong_discharge.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (outputs / "redelong_discharge.html").write_text(
        dashboard_html(forecast, metrics, metadata, parameters), encoding="utf-8"
    )
    _link_operational_dashboard(outputs)

    archive = Path(operational.get("archive_dir", ""))
    if not archive.is_absolute():
        archive_candidates = sorted((outputs / "archive").glob("*/*/*"))
        archive = archive_candidates[-1] if archive_candidates else outputs / "archive"
    archive.mkdir(parents=True, exist_ok=True)
    for name in [
        "redelong_discharge_forecast.csv",
        "redelong_discharge_validation.csv",
        "redelong_discharge_end_to_end_validation.csv",
        "redelong_discharge.json",
    ]:
        shutil.copy2(outputs / name, archive / name)
    return {
        "status": "provisional_proxy_calibrated",
        "forecast_rows": int(len(forecast)),
        "validation_rows": int(len(pairs)),
        "validation_metrics": metrics.to_dict(orient="records"),
        "dashboard": str(outputs / "redelong_discharge.html"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build rainfall-to-discharge forecast for Redelong")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    args = parser.parse_args()
    print(json.dumps(build(args.outputs.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
