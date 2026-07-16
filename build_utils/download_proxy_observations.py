from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests


ROOT = Path(__file__).resolve().parents[1]
LOCATIONS_PATH = ROOT / "locations.json"
OBS_DIR = ROOT / "data" / "redelong" / "observations"
OUTPUTS = ROOT / "outputs"

OBS_DIR.mkdir(parents=True, exist_ok=True)

CLIMATESERV_BASE = "https://climateserv.servirglobal.net/chirps"

# ClimateSERV datatype:
# 0  = Global CHIRPS
# 26 = IMERG daily
DATASETS = [
    {
        "name": "CHIRPS via ClimateSERV",
        "datatype": 0,
        "source": "CHIRPS via ClimateSERV",
        "observation_type": "proxy_satellite_gridded",
        "out": "rain_proxy_daily_chirps.csv",
    },
    {
        "name": "GPM IMERG via ClimateSERV",
        "datatype": 26,
        "source": "GPM IMERG via ClimateSERV",
        "observation_type": "proxy_satellite_near_real_time",
        "out": "rain_proxy_daily_imerg.csv",
    },
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download proxy rainfall observations for Forecast Redelong points."
    )
    parser.add_argument("--start", help="Start date YYYY-MM-DD.")
    parser.add_argument("--end", help="End date YYYY-MM-DD.")
    parser.add_argument(
        "--sleep",
        type=float,
        default=1.5,
        help="Delay between API requests in seconds.",
    )
    parser.add_argument(
        "--box-delta",
        type=float,
        default=0.025,
        help="Small polygon half-size in degrees around point.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=90,
        help="HTTP timeout seconds.",
    )
    parser.add_argument(
        "--poll-seconds",
        type=float,
        default=2.0,
        help="Polling delay for ClimateSERV request progress.",
    )
    parser.add_argument(
        "--poll-max",
        type=int,
        default=90,
        help="Maximum polling attempts per ClimateSERV request.",
    )
    parser.add_argument(
        "--allow-power-main",
        action="store_true",
        help="Allow NASA POWER to be written as rain_proxy_daily.csv if CHIRPS and IMERG are empty.",
    )
    return parser.parse_args()


def load_locations() -> pd.DataFrame:
    if not LOCATIONS_PATH.exists():
        raise FileNotFoundError(f"locations.json tidak ditemukan: {LOCATIONS_PATH}")

    data = json.loads(LOCATIONS_PATH.read_text(encoding="utf-8"))
    locs = data.get("locations", data)

    rows = []
    for slug, loc in locs.items():
        lat = loc.get("latitude")
        lon = loc.get("longitude")
        name = loc.get("location_name", slug)

        if lat is None or lon is None:
            continue

        rows.append(
            {
                "location_slug": slug,
                "location_name": name,
                "latitude": float(lat),
                "longitude": float(lon),
            }
        )

    if not rows:
        raise ValueError("Tidak ada lokasi valid di locations.json")

    return pd.DataFrame(rows)


def infer_dates_from_forecast() -> tuple[str, str] | None:
    forecast_path = OUTPUTS / "forecast_all_locations.csv"
    if not forecast_path.exists():
        return None

    df = pd.read_csv(forecast_path)
    date_col = None

    for col in ["target_date", "date", "tanggal", "valid_date"]:
        if col in df.columns:
            date_col = col
            break

    if date_col is None:
        return None

    dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
    if dates.empty:
        return None

    start = dates.min().strftime("%Y-%m-%d")
    end = dates.max().strftime("%Y-%m-%d")
    return start, end


def to_mmddyyyy(date_iso: str) -> str:
    dt = datetime.strptime(date_iso, "%Y-%m-%d")
    return dt.strftime("%m/%d/%Y")


def small_polygon(lon: float, lat: float, delta: float) -> dict[str, Any]:
    coords = [
        [lon - delta, lat + delta],
        [lon + delta, lat + delta],
        [lon + delta, lat - delta],
        [lon - delta, lat - delta],
        [lon - delta, lat + delta],
    ]
    return {"type": "Polygon", "coordinates": [coords]}


def get_json(url: str, params: dict[str, Any] | None = None, timeout: int = 90) -> Any:
    r = requests.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    text = r.text.strip()

    # ClimateSERV sometimes returns JSON string/list/object.
    try:
        return r.json()
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return text.strip('"')


def submit_climateserv_request(
    datatype: int,
    start: str,
    end: str,
    lon: float,
    lat: float,
    box_delta: float,
    timeout: int,
) -> str:
    url = f"{CLIMATESERV_BASE}/submitDataRequest/"
    params = {
        "datatype": datatype,
        "begintime": to_mmddyyyy(start),
        "endtime": to_mmddyyyy(end),
        "intervaltype": 0,      # daily
        "operationtype": 5,     # average
        "dateType_Category": "default",
        "isZip_CurrentDataType": "false",
        "geometry": json.dumps(small_polygon(lon, lat, box_delta)),
    }

    result = get_json(url, params=params, timeout=timeout)

    if isinstance(result, list) and result:
        job_id = str(result[0])
    else:
        job_id = str(result)

    job_id = job_id.strip().strip('"').strip("'")

    if not job_id or "error" in job_id.lower():
        raise RuntimeError(f"ClimateSERV submit gagal: {result}")

    return job_id


def wait_climateserv_job(job_id: str, poll_seconds: float, poll_max: int, timeout: int) -> None:
    url = f"{CLIMATESERV_BASE}/getDataRequestProgress/"

    for attempt in range(1, poll_max + 1):
        result = get_json(url, params={"id": job_id}, timeout=timeout)

        # ClimateSERV kadang mengembalikan progress sebagai angka,
        # string angka, atau list seperti [98.5] / [100.0].
        raw_progress = result
        if isinstance(raw_progress, list) and raw_progress:
            raw_progress = raw_progress[0]
        if isinstance(raw_progress, dict):
            for key in ["progress", "value", "percent", "data"]:
                if key in raw_progress:
                    raw_progress = raw_progress[key]
                    break

        try:
            progress = float(raw_progress)
        except Exception:
            raise RuntimeError(f"ClimateSERV job error progress={result}")

        if progress >= 100:
            return

        if progress < 0:
            raise RuntimeError(f"ClimateSERV job error progress={result}")

        if attempt % 10 == 0:
            print(f"    progress {progress:.1f}%")

        time.sleep(poll_seconds)

    raise TimeoutError(f"ClimateSERV job belum selesai setelah {poll_max} poll: {job_id}")


def fetch_climateserv_result(job_id: str, timeout: int) -> list[dict[str, Any]]:
    url = f"{CLIMATESERV_BASE}/getDataFromRequest/"
    result = get_json(url, params={"id": job_id}, timeout=timeout)

    if isinstance(result, dict) and "data" in result:
        return result["data"]

    if isinstance(result, list):
        return result

    raise RuntimeError(f"Format ClimateSERV result tidak dikenali: {type(result)} {str(result)[:200]}")


def parse_climateserv_data(
    data: list[dict[str, Any]],
    location_slug: str,
    source: str,
    observation_type: str,
) -> pd.DataFrame:
    rows = []

    for item in data:
        date_raw = item.get("date")
        value_obj = item.get("value", {})

        if not date_raw:
            continue

        # operationtype=5 returns avg
        value = None
        if isinstance(value_obj, dict):
            for key in ["avg", "average", "value", "sum", "max"]:
                if key in value_obj:
                    value = value_obj[key]
                    break
            if value is None and value_obj:
                value = list(value_obj.values())[0]
        else:
            value = value_obj

        try:
            value = float(value)
        except Exception:
            continue

        if not math.isfinite(value) or value < -100:
            continue

        date_iso = pd.to_datetime(date_raw, errors="coerce")
        if pd.isna(date_iso):
            continue

        rows.append(
            {
                "date": date_iso.strftime("%Y-%m-%d"),
                "location_slug": location_slug,
                "rain_mm_observed": value,
                "source": source,
                "observation_type": observation_type,
            }
        )

    return pd.DataFrame(
        rows,
        columns=["date", "location_slug", "rain_mm_observed", "source", "observation_type"],
    )


def download_climateserv_dataset(
    locations: pd.DataFrame,
    dataset: dict[str, Any],
    start: str,
    end: str,
    sleep: float,
    box_delta: float,
    timeout: int,
    poll_seconds: float,
    poll_max: int,
) -> pd.DataFrame:
    all_rows = []

    print("")
    print(f"=== {dataset['name']} ===")

    for _, loc in locations.iterrows():
        slug = loc["location_slug"]
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])

        print(f"[ClimateSERV] {dataset['name']} | {slug} | {start} to {end}")

        try:
            job_id = submit_climateserv_request(
                datatype=int(dataset["datatype"]),
                start=start,
                end=end,
                lon=lon,
                lat=lat,
                box_delta=box_delta,
                timeout=timeout,
            )
            wait_climateserv_job(
                job_id=job_id,
                poll_seconds=poll_seconds,
                poll_max=poll_max,
                timeout=timeout,
            )
            raw_data = fetch_climateserv_result(job_id=job_id, timeout=timeout)

            df = parse_climateserv_data(
                raw_data,
                location_slug=slug,
                source=dataset["source"],
                observation_type=dataset["observation_type"],
            )

            print(f"    rows={len(df)}")

            if not df.empty:
                all_rows.append(df)

        except Exception as exc:
            print(f"    WARNING: gagal untuk {slug}: {exc}")

        time.sleep(sleep)

    if all_rows:
        out = pd.concat(all_rows, ignore_index=True)
    else:
        out = pd.DataFrame(
            columns=["date", "location_slug", "rain_mm_observed", "source", "observation_type"]
        )

    out_path = OBS_DIR / dataset["out"]
    out.to_csv(out_path, index=False)
    print(f"SAVED: {out_path} rows={len(out)}")
    return out


def download_nasa_power(
    locations: pd.DataFrame,
    start: str,
    end: str,
    sleep: float,
    timeout: int,
) -> pd.DataFrame:
    print("")
    print("=== NASA POWER PRECTOTCORR Daily ===")

    rows = []
    start_req = start.replace("-", "")
    end_req = end.replace("-", "")

    for _, loc in locations.iterrows():
        slug = loc["location_slug"]
        lat = float(loc["latitude"])
        lon = float(loc["longitude"])

        print(f"[NASA POWER] {slug} | {start} to {end}")

        url = "https://power.larc.nasa.gov/api/temporal/daily/point"
        params = {
            "parameters": "PRECTOTCORR",
            "community": "AG",
            "longitude": lon,
            "latitude": lat,
            "start": start_req,
            "end": end_req,
            "format": "JSON",
            "time-standard": "UTC",
        }

        try:
            r = requests.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()

            values = (
                data.get("properties", {})
                .get("parameter", {})
                .get("PRECTOTCORR", {})
            )

            for yyyymmdd, value in values.items():
                if value is None:
                    continue

                value = float(value)
                if not math.isfinite(value) or value < -100:
                    continue

                rows.append(
                    {
                        "date": f"{yyyymmdd[0:4]}-{yyyymmdd[4:6]}-{yyyymmdd[6:8]}",
                        "location_slug": slug,
                        "rain_mm_observed": value,
                        "source": "NASA POWER PRECTOTCORR Daily",
                        "observation_type": "proxy_reanalysis_satellite_model",
                    }
                )

        except Exception as exc:
            print(f"    WARNING: NASA POWER gagal untuk {slug}: {exc}")

        time.sleep(sleep)

    out = pd.DataFrame(
        rows,
        columns=["date", "location_slug", "rain_mm_observed", "source", "observation_type"],
    )

    out_path = OBS_DIR / "rain_proxy_daily_power.csv"
    out.to_csv(out_path, index=False)
    print(f"SAVED: {out_path} rows={len(out)}")
    return out


def choose_main_proxy(
    chirps: pd.DataFrame,
    imerg: pd.DataFrame,
    power: pd.DataFrame,
    allow_power_main: bool = False,
) -> tuple[str, pd.DataFrame]:
    # Jangan campur beberapa proxy dalam satu metric.
    # Pilih satu sumber utama agar metrik konsisten.
    # NASA POWER default-nya tidak dijadikan main proxy karena hanya fallback sekunder.
    if not imerg.empty:
        return "IMERG", imerg
    if not chirps.empty:
        return "CHIRPS", chirps
    if allow_power_main and not power.empty:
        return "NASA_POWER", power

    empty = pd.DataFrame(
        columns=["date", "location_slug", "rain_mm_observed", "source", "observation_type"]
    )
    return "NONE", empty


def main() -> None:
    args = parse_args()

    inferred = infer_dates_from_forecast()

    if args.start and args.end:
        start, end = args.start, args.end
    elif inferred:
        start, end = inferred
        print(f"[INFO] Date range inferred from outputs/forecast_all_locations.csv: {start} to {end}")
    else:
        raise ValueError("Berikan --start dan --end karena tanggal tidak bisa diinfer dari outputs/forecast_all_locations.csv")

    locations = load_locations()
    print("")
    print("Locations:")
    print(locations.to_string(index=False))
    print("")
    print(f"Download period: {start} to {end}")

    chirps = download_climateserv_dataset(
        locations=locations,
        dataset=DATASETS[0],
        start=start,
        end=end,
        sleep=args.sleep,
        box_delta=args.box_delta,
        timeout=args.timeout,
        poll_seconds=args.poll_seconds,
        poll_max=args.poll_max,
    )

    imerg = download_climateserv_dataset(
        locations=locations,
        dataset=DATASETS[1],
        start=start,
        end=end,
        sleep=args.sleep,
        box_delta=args.box_delta,
        timeout=args.timeout,
        poll_seconds=args.poll_seconds,
        poll_max=args.poll_max,
    )

    power = download_nasa_power(
        locations=locations,
        start=start,
        end=end,
        sleep=args.sleep,
        timeout=args.timeout,
    )

    chosen, main_proxy = choose_main_proxy(chirps, imerg, power, allow_power_main=args.allow_power_main)

    main_path = OBS_DIR / "rain_proxy_daily.csv"
    main_proxy.to_csv(main_path, index=False)

    print("")
    print("DONE")
    print("Main proxy chosen:", chosen)
    print("Main proxy file:", main_path)
    print("Main proxy rows:", len(main_proxy))

    if main_proxy.empty:
        print("WARNING: Main proxy kosong.")
        print("CHIRPS dan IMERG tidak tersedia/terbaca untuk periode ini.")
        print("NASA POWER mungkin tetap tersimpan di rain_proxy_daily_power.csv, tetapi tidak dijadikan main proxy kecuali memakai --allow-power-main.")
    else:
        print(main_proxy.head(30).to_string(index=False))


if __name__ == "__main__":
    main()
