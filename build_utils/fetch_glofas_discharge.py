"""Fetch a transparent GloFAS discharge reference for PLTA Redelong.

The public Open-Meteo Flood API exposes GloFAS v4 seamless data without an
account.  These values are simulated gridded discharge, not an on-site gauge.
They are therefore used only as a calibration/validation proxy and as an
independent reference next to the rainfall-derived forecast.
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
API_URL = "https://flood-api.open-meteo.com/v1/flood"
REQUEST_LATITUDE = 4.748139
REQUEST_LONGITUDE = 96.977344
TIMEZONE = "Asia/Jakarta"
USER_AGENT = "Forecast-Redelong-Hydrology/1.0"


def _request(params: dict, attempts: int = 3) -> dict:
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=120) as response:
                return json.load(response)
        except Exception as exc:  # pragma: no cover - exercised by live workflow
            error = exc
            if attempt + 1 < attempts:
                time.sleep(2**attempt)
    raise RuntimeError(f"Gagal mengambil referensi debit GloFAS: {error}")


def _daily_frame(payload: dict, columns: list[str]) -> pd.DataFrame:
    daily = payload.get("daily", {})
    times = daily.get("time", [])
    frame = pd.DataFrame({"date": times})
    for column in columns:
        values = daily.get(column, [])
        frame[column] = values if len(values) == len(frame) else pd.NA
    for column in columns:
        frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame


def fetch_history(start_date: str, end_date: str) -> tuple[pd.DataFrame, dict]:
    variables = ["river_discharge"]
    payload = _request(
        {
            "latitude": REQUEST_LATITUDE,
            "longitude": REQUEST_LONGITUDE,
            "daily": ",".join(variables),
            "start_date": start_date,
            "end_date": end_date,
            "timezone": TIMEZONE,
        }
    )
    return _daily_frame(payload, variables), payload


def fetch_recent_and_forecast(past_days: int = 14, forecast_days: int = 10) -> tuple[pd.DataFrame, dict]:
    variables = [
        "river_discharge",
        "river_discharge_mean",
        "river_discharge_median",
        "river_discharge_max",
        "river_discharge_min",
        "river_discharge_p25",
        "river_discharge_p75",
    ]
    payload = _request(
        {
            "latitude": REQUEST_LATITUDE,
            "longitude": REQUEST_LONGITUDE,
            "daily": ",".join(variables),
            "past_days": past_days,
            "forecast_days": forecast_days,
            "timezone": TIMEZONE,
        }
    )
    return _daily_frame(payload, variables), payload


def build(outputs: Path, history_start: str = "2000-01-01", history_end: str | None = None) -> dict:
    hydrology = outputs / "hydrology"
    hydrology.mkdir(parents=True, exist_ok=True)
    if history_end is None:
        history_end = (date.today() - timedelta(days=1)).isoformat()

    history, history_payload = fetch_history(history_start, history_end)
    current, current_payload = fetch_recent_and_forecast()
    history.to_csv(hydrology / "glofas_discharge_history.csv", index=False, encoding="utf-8-sig")
    current.to_csv(hydrology / "glofas_discharge_current.csv", index=False, encoding="utf-8-sig")

    selected_latitude = current_payload.get("latitude", history_payload.get("latitude"))
    selected_longitude = current_payload.get("longitude", history_payload.get("longitude"))
    metadata = {
        "schema_version": "forecast-redelong-glofas-proxy-v1",
        "source": "GloFAS v4 via Open-Meteo Flood API",
        "source_url": "https://open-meteo.com/en/docs/flood-api",
        "upstream_source": "Copernicus Emergency Management Service Global Flood Awareness System (GloFAS v4)",
        "usage_note": (
            "Open-Meteo public access is suitable for prototype/non-commercial use; "
            "confirm the applicable licence or use an approved Copernicus service "
            "before corporate production deployment."
        ),
        "observation_type": "simulated_gridded_discharge_proxy",
        "request_coordinate": [REQUEST_LATITUDE, REQUEST_LONGITUDE],
        "selected_grid_coordinate": [selected_latitude, selected_longitude],
        "selected_grid_elevation_m": current_payload.get("elevation"),
        "timezone": TIMEZONE,
        "history_start": history_start,
        "history_end": history_end,
        "history_rows": int(len(history)),
        "current_rows": int(len(current)),
        "unit": "m3/s",
        "disclaimer": (
            "GloFAS is a simulated gridded river-discharge product, not an AWLR or "
            "direct discharge observation at PLTA Redelong. Grid-to-river matching and "
            "licensing must be confirmed before production operational use."
        ),
    }
    (hydrology / "glofas_discharge_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GloFAS discharge proxy for Redelong")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    parser.add_argument("--history-start", default="2000-01-01")
    parser.add_argument("--history-end")
    args = parser.parse_args()
    print(
        json.dumps(
            build(args.outputs.resolve(), args.history_start, args.history_end),
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
