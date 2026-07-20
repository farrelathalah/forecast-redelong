#!/usr/bin/env python3
"""Build a defensible Besai Kemu rainfall-to-discharge proxy product.

The model deliberately separates three things:
1. multi-point rainfall forecast at documented engineering references;
2. a daily ARX transform calibrated to GloFAS simulated discharge;
3. an indicative plant-water scenario after documented irrigation and ecological
   releases.

PLTA Besai 1 release data are not available in the automated feed.  The output
must therefore remain a proxy scenario and must not be called measured inflow.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import shutil
from pathlib import Path

import numpy as np
import pandas as pd

try:
    from build_utils.build_redelong_discharge import (
        make_discharge_forecast,
        prepare_calibration,
        rolling_hindcast,
    )
except ModuleNotFoundError:  # direct script execution from repository root
    from build_redelong_discharge import (
        make_discharge_forecast,
        prepare_calibration,
        rolling_hindcast,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
SITE_DATA = ROOT / "data" / "sites" / "pltm_besai_kemu"
HISTORY = SITE_DATA / "nasa_power_daily_1981_2025.csv.gz"
ENGINEERING = SITE_DATA / "engineering_parameters.json"


def rainfall_history() -> pd.DataFrame:
    with gzip.open(HISTORY, "rt", encoding="utf-8", newline="") as handle:
        frame = pd.read_csv(handle)
    frame["rain_mm"] = pd.to_numeric(frame["rain_mm"], errors="coerce")
    return frame[["date", "rain_mm"]].dropna()


def fit_regulated_arx(frame: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    """Fit an auditable constrained ARX model for a regulated downstream river."""
    if len(frame) < 3650:
        raise ValueError("Seri kalibrasi Besai kurang dari 10 tahun")
    last_year = int(frame["date"].dt.year.max())
    validation_start_year = last_year - 6
    train = frame[frame["date"].dt.year < validation_start_year].copy()
    validation = frame[frame["date"].dt.year >= validation_start_year].copy()
    if len(train) < 3650 or len(validation) < 365:
        raise ValueError("Pembagian train/validation Besai tidak mencukupi")

    matrix = np.column_stack(
        [np.ones(len(train)), train["previous_discharge"], train["rain_mm"]]
    )
    target = train["river_discharge"].to_numpy(dtype=float)
    intercept, recession, rainfall_response = np.linalg.lstsq(matrix, target, rcond=None)[0]

    # Regulation can obscure or invert the same-day rainfall signal.  Keep the
    # public model physical and disclose when the rainfall coefficient is zero.
    recession = float(np.clip(recession, 0.0, 0.995))
    rainfall_response = float(max(0.0, rainfall_response))
    intercept = float(
        max(
            0.0,
            np.mean(
                target
                - recession * train["previous_discharge"].to_numpy(dtype=float)
                - rainfall_response * train["rain_mm"].to_numpy(dtype=float)
            ),
        )
    )
    parameters = {
        "intercept_m3s": intercept,
        "recession_coefficient": recession,
        "rainfall_response_m3s_per_mm": rainfall_response,
        "training_start": train["date"].min().date().isoformat(),
        "training_end": train["date"].max().date().isoformat(),
        "training_rows": int(len(train)),
        "validation_start": validation["date"].min().date().isoformat(),
        "validation_end": validation["date"].max().date().isoformat(),
        "validation_rows": int(len(validation)),
        "regulation_signal": (
            "rainfall_response_retained"
            if rainfall_response > 0
            else "rainfall_response_clipped_to_zero_upstream_operation_dominant"
        ),
    }
    return parameters, validation


def forecast_rain(outputs: Path, forecast_start: pd.Timestamp) -> pd.DataFrame:
    """Aggregate rolling 24-hour, multi-point and multi-model rainfall windows."""
    hourly = pd.read_csv(outputs / "forecast_all_locations.csv", encoding="utf-8-sig")
    hourly = hourly[
        hourly["location_slug"].astype(str).str.startswith("pltm_besai_kemu")
        & hourly["source_id"].astype(str).str.upper().isin(
            {"CMA", "ECMWF", "GFS", "ICON", "METEOFRANCE", "UKMO"}
        )
    ].copy()
    hourly["rain_mm"] = pd.to_numeric(hourly["rain_mm"], errors="coerce")
    valid = pd.to_datetime(
        hourly["target_date"].astype(str) + " " + hourly["target_jam"].astype(str),
        errors="coerce",
    )
    hourly["valid_time_wib"] = valid.dt.tz_localize("Asia/Jakarta")
    start = forecast_start.tz_convert("Asia/Jakarta") if forecast_start.tzinfo else forecast_start.tz_localize("Asia/Jakarta")
    hourly["lead_day"] = (
        (hourly["valid_time_wib"] - start).dt.total_seconds() // 86400 + 1
    ).astype("Int64")
    hourly = hourly.dropna(subset=["rain_mm", "valid_time_wib", "lead_day"])
    hourly = hourly[hourly["lead_day"].between(1, 3)]
    point_source = hourly.groupby(
        ["lead_day", "source_id", "location_slug"], as_index=False
    ).agg(rain_mm=("rain_mm", "sum"), hours=("valid_time_wib", "nunique"))
    point_source = point_source[point_source["hours"] >= 19]
    source = point_source.groupby(["lead_day", "source_id"], as_index=False).agg(
        rain_mm=("rain_mm", "mean"),
        point_count=("location_slug", "nunique"),
    )
    source = source[source["point_count"] >= 3]
    rows = []
    for lead, group in source.groupby("lead_day"):
        values = group["rain_mm"].dropna()
        window_start = start + pd.Timedelta(days=int(lead) - 1)
        rows.append(
            {
                "lead_day": int(lead),
                "window_start_wib": window_start.isoformat(),
                "window_end_wib": (window_start + pd.Timedelta(days=1)).isoformat(),
                "rain_mean_mm": float(values.mean()),
                "rain_p10_mm": float(values.quantile(0.10)),
                "rain_p90_mm": float(values.quantile(0.90)),
                "model_count": int(len(values)),
                "model_list": ",".join(sorted(group["source_id"].astype(str).unique())),
                "spatial_point_count": int(group["point_count"].min()),
            }
        )
    result = pd.DataFrame(rows)
    if set(result.get("lead_day", [])) != {1, 2, 3}:
        raise ValueError("Forecast hujan rolling 24 jam Besai untuk H+1 sampai H+3 belum lengkap")
    return result.sort_values("lead_day").reset_index(drop=True)


def add_engineering_scenario(forecast: pd.DataFrame, engineering: dict) -> pd.DataFrame:
    result = forecast.copy()
    irrigation = engineering["hydrology"]["irrigation_release_m3s"]
    ecological = float(engineering["hydrology"]["ecological_release_m3s"])
    design = float(engineering["hydrology"]["adopted_design_discharge_m3s"])
    month_names = [
        "january", "february", "march", "april", "may", "june",
        "july", "august", "september", "october", "november", "december",
    ]
    release = []
    available = []
    for _, row in result.iterrows():
        month = pd.Timestamp(row["valid_date"]).month
        irrigation_m3s = float(irrigation[month_names[month - 1]])
        release.append(irrigation_m3s)
        available.append(
            min(
                design,
                max(0.0, float(row["discharge_forecast_m3s"]) - irrigation_m3s - ecological),
            )
        )
    result["irrigation_reference_m3s"] = release
    result["ecological_release_reference_m3s"] = ecological
    result["indicative_plant_available_m3s"] = available
    result["design_discharge_m3s"] = design
    result["engineering_scenario_status"] = "indicative_without_upstream_release_schedule"
    return result


def dashboard_html(
    forecast: pd.DataFrame,
    metrics: pd.DataFrame,
    parameters: dict,
    metadata: dict,
    engineering: dict,
) -> str:
    cards = []
    for _, row in forecast.iterrows():
        cards.append(
            f"<article class='card'><span>H+{int(row['lead_day'])}, {row['valid_date']}</span>"
            f"<strong>{row['discharge_forecast_m3s']:.1f} m³/s</strong>"
            f"<small>Skenario {row['discharge_scenario_low_m3s']:.1f} sampai {row['discharge_scenario_high_m3s']:.1f} m³/s</small>"
            f"<em>Indikatif tersedia untuk PLTM {row['indicative_plant_available_m3s']:.1f} m³/s</em></article>"
        )
    metric_rows = "".join(
        f"<tr><td>H+{int(row.lead_day)}</td><td>{int(row.n_samples):,}</td>"
        f"<td>{row.mae_m3s:.2f}</td><td>{row.rmse_m3s:.2f}</td>"
        f"<td>{row.bias_m3s:.2f}</td><td>{row.nse:.3f}</td><td>{row.kge:.3f}</td></tr>"
        for row in metrics.itertuples()
    )
    grid = metadata.get("selected_grid_coordinate", [None, None])
    area = engineering["catchment"]["area_km2"]
    design = engineering["hydrology"]["adopted_design_discharge_m3s"]
    ecology = engineering["hydrology"]["ecological_release_m3s"]
    return f"""<!doctype html><html lang='id'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<meta name='forecast-hydro-page' content='forecast-besai-discharge-v1'><title>Forecast Debit Besai Kemu</title><style>
:root{{--bg:#03111d;--panel:#082234;--line:rgba(103,232,249,.18);--text:#effcff;--muted:#9bb6c8;--cyan:#22d3ee;--amber:#fbbf24}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#13455d,transparent 38%),var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}}.shell{{max-width:1180px;margin:auto;padding:22px 22px 60px}}nav{{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px}}a{{color:inherit}}.brand{{display:flex;gap:11px;align-items:center;text-decoration:none}}.mark{{width:44px;height:44px;border-radius:14px;background:linear-gradient(135deg,#22d3ee,#8b5cf6,#34d399);display:grid;place-items:center;font-weight:950}}.brand b,.brand small{{display:block}}.brand small{{color:var(--muted);font-size:9px;letter-spacing:.12em;text-transform:uppercase}}nav>a:last-child{{color:var(--muted);font-size:11px}}.hero,.panel,.card{{border:1px solid var(--line);background:rgba(8,34,52,.78);border-radius:22px}}.hero{{padding:38px}}.tag{{font-size:10px;color:#67e8f9;text-transform:uppercase;letter-spacing:.16em;font-weight:850}}h1{{font-size:clamp(40px,7vw,72px);line-height:.96;letter-spacing:-.055em;margin:13px 0}}.lead{{max-width:780px;color:#c7dce8;line-height:1.7}}.warning{{margin-top:20px;border:1px solid rgba(251,191,36,.3);background:rgba(251,191,36,.08);color:#fce7ac;border-radius:14px;padding:14px;font-size:12px;line-height:1.55}}.grid{{display:grid;grid-template-columns:repeat(3,1fr);gap:12px;margin-top:16px}}.card{{padding:19px}}.card span,.card small,.card em{{display:block;font-size:10px;color:var(--muted)}}.card strong{{display:block;font-size:30px;margin:15px 0 5px}}.card em{{font-style:normal;color:#8beaf6;margin-top:14px}}section{{margin-top:32px}}h2{{font-size:27px;letter-spacing:-.03em}}.facts{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.fact{{padding:17px}}.fact span{{font-size:9px;color:var(--muted)}}.fact b{{display:block;font-size:22px;margin-top:7px}}.panel{{padding:20px;overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:11px}}th,td{{padding:10px;border-bottom:1px solid var(--line);text-align:right}}th:first-child,td:first-child{{text-align:left}}th{{font-size:8px;color:var(--muted);text-transform:uppercase}}.method{{display:grid;grid-template-columns:1fr 1fr;gap:12px}}.method p,.method li{{color:var(--muted);font-size:11px;line-height:1.65}}code{{color:#8beaf6}}.downloads{{display:flex;gap:9px;flex-wrap:wrap}}.button{{text-decoration:none;border:1px solid var(--line);background:#0b2e42;border-radius:11px;padding:10px 13px;font-size:11px;font-weight:800}}@media(max-width:760px){{.grid,.facts,.method{{grid-template-columns:1fr}}.hero{{padding:27px 19px}}}}
</style></head><body><div class='shell'><nav><a class='brand' data-fr-brand='true' href='index.html'><span class='mark'>FR</span><span><b>Forecast Besai Kemu</b><small>Rainfall to discharge</small></span></a><a href='besai_kemu.html'>Kembali ke dashboard Besai</a></nav><main><header class='hero'><div class='tag'>Skenario hidrologi engineering</div><h1>Forecast debit Besai Kemu</h1><p class='lead'>Forecast hujan pada empat titik engineering diubah menjadi debit harian menggunakan model ARX yang dikalibrasi terhadap simulasi debit GloFAS di sekitar bendung.</p><div class='warning'><b>Belum field-calibrated.</b> PLTM berada di hilir PLTA Besai 1. Jadwal release upstream belum tersedia dalam feed otomatis, sehingga hasil ini adalah proxy dan skenario indikatif, bukan debit intake terukur atau jaminan energi.</div></header><div class='grid'>{''.join(cards)}</div>
<section><h2>Parameter yang digunakan</h2><div class='facts'><article class='panel fact'><span>Luas DAS dokumen</span><b>{area:.2f} km²</b></article><article class='panel fact'><span>Debit desain</span><b>{design:.1f} m³/s</b></article><article class='panel fact'><span>Debit ekologi</span><b>{ecology:.1f} m³/s</b></article><article class='panel fact'><span>Kapasitas</span><b>2 × 3.5 MW</b></article></div></section>
<section><h2>Validasi terhadap proxy GloFAS</h2><article class='panel'><table><thead><tr><th>Lead</th><th>Sampel</th><th>MAE</th><th>RMSE</th><th>Bias</th><th>NSE</th><th>KGE</th></tr></thead><tbody>{metric_rows}</tbody></table><p style='color:var(--muted);font-size:10px'>Validasi menggunakan hujan historis NASA POWER sebagai forcing dan debit simulasi GloFAS sebagai target. Nilai ini bukan akurasi lapangan dan bukan validasi end-to-end forecast cuaca.</p></article></section>
<section class='method'><article class='panel'><h2>Persamaan</h2><p><code>Q(t) = {parameters['intercept_m3s']:.3f} + {parameters['recession_coefficient']:.4f} × Q(t−1) + {parameters['rainfall_response_m3s_per_mm']:.4f} × P(t)</code></p><p>Status sinyal regulasi: {parameters['regulation_signal']}.</p></article><article class='panel'><h2>Batas penggunaan</h2><ul><li>Grid GloFAS terpilih: {grid[0]}, {grid[1]}.</li><li>Polygon GIS DAS belum tersedia; luas {area:.2f} km² berasal dari review engineering.</li><li>Pengurangan irigasi dan ekologi hanya skenario referensi.</li><li>Keputusan bukaan, keselamatan, dan dispatch tetap memerlukan data operasi aktual.</li></ul></article></section>
<section><h2>Unduh data</h2><div class='downloads'><a class='button' href='besai_kemu_discharge_forecast.csv'>Forecast debit CSV</a><a class='button' href='besai_kemu_discharge_validation.csv'>Validasi CSV</a><a class='button' href='besai_kemu_discharge.json'>API JSON</a><a class='button' href='hydrology/besai_glofas_discharge_metadata.json'>Metadata GloFAS</a></div></section></main></div></body></html>"""


def build(outputs: Path) -> dict:
    engineering = json.loads(ENGINEERING.read_text(encoding="utf-8"))
    operational_path = outputs / "redelong_operational.json"
    if operational_path.exists():
        operational = json.loads(operational_path.read_text(encoding="utf-8-sig"))
        issue_time = pd.Timestamp(operational["issue_time_wib"])
        forecast_start = pd.Timestamp(operational["forecast_start_wib"])
    else:
        issue_time = pd.Timestamp.now(tz="Asia/Jakarta")
        forecast_start = issue_time.ceil("h")
    history_discharge = pd.read_csv(outputs / "hydrology" / "besai_glofas_discharge_history.csv")
    current_discharge = pd.read_csv(outputs / "hydrology" / "besai_glofas_discharge_current.csv")
    metadata = json.loads((outputs / "hydrology" / "besai_glofas_discharge_metadata.json").read_text(encoding="utf-8"))

    calibration = prepare_calibration(rainfall_history(), history_discharge, issue_time)
    parameters, validation = fit_regulated_arx(calibration)
    pairs, metrics = rolling_hindcast(validation, parameters)
    rain = forecast_rain(outputs, forecast_start)
    forecast = make_discharge_forecast(rain, current_discharge, forecast_start, parameters, metrics)
    forecast = add_engineering_scenario(forecast, engineering)

    forecast.to_csv(outputs / "besai_kemu_discharge_forecast.csv", index=False, encoding="utf-8-sig")
    metrics.to_csv(outputs / "besai_kemu_discharge_validation.csv", index=False, encoding="utf-8-sig")
    pairs.to_csv(outputs / "besai_kemu_discharge_hindcast_pairs.csv", index=False, encoding="utf-8-sig")
    payload = {
        "schema_version": "forecast-besai-rainfall-discharge-v1",
        "status": "provisional_regulated_proxy",
        "issue_time_wib": issue_time.isoformat(),
        "forecast_start_wib": forecast_start.isoformat(),
        "model": "constrained daily ARX(1) rainfall-routing proxy",
        "parameters": parameters,
        "engineering_reference": engineering,
        "calibration_reference": metadata,
        "can_claim_field_accuracy": False,
        "can_claim_operational_inflow": False,
        "upstream_release_schedule_available": False,
        "forecast": json.loads(forecast.to_json(orient="records")),
        "validation": json.loads(metrics.to_json(orient="records")),
        "validation_scope": "historical rainfall-to-GloFAS transform hindcast; not field or end-to-end forecast accuracy",
        "limitations": [
            "No automated PLTA Besai 1 release schedule or on-site AWLR is available.",
            "GloFAS is simulated gridded discharge and the selected river cell needs engineering confirmation.",
            "NASA POWER is a gridded meteorological proxy, not the Sumberjaya gauge record.",
            "Catchment area is documented, but the GIS boundary geometry is still pending.",
        ],
    }
    (outputs / "besai_kemu_discharge.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (outputs / "besai_kemu_discharge.html").write_text(dashboard_html(forecast, metrics, parameters, metadata, engineering), encoding="utf-8")

    archive_candidates = sorted((outputs / "archive").glob("*/*/*"))
    if archive_candidates:
        archive = archive_candidates[-1]
        for name in ["besai_kemu_discharge_forecast.csv", "besai_kemu_discharge_validation.csv", "besai_kemu_discharge.json"]:
            shutil.copy2(outputs / name, archive / name)
    return {"status": payload["status"], "forecast_rows": len(forecast), "validation_rows": len(pairs)}


def main() -> None:
    parser = argparse.ArgumentParser(description="Build Besai Kemu discharge proxy")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    args = parser.parse_args()
    print(json.dumps(build(args.outputs.resolve()), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
