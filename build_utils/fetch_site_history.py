#!/usr/bin/env python3
"""Download a reproducible gridded daily history for a registered site.

NASA POWER is used as a public meteorological reference, not as an on-site
rain gauge.  The downloaded CSV is committed so the public build is stable and
does not need to fetch four decades of data on every daily forecast run.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import urllib.parse
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "sites.json"
PARAMETERS = ["PRECTOTCORR", "T2M", "T2M_MAX", "T2M_MIN", "WS2M", "RH2M"]


def fetch(slug: str, start: str, end: str, destination: Path) -> int:
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    site = registry["sites"][slug]
    query = urllib.parse.urlencode(
        {
            "parameters": ",".join(PARAMETERS),
            "community": "AG",
            "longitude": site["longitude"],
            "latitude": site["latitude"],
            "start": start.replace("-", ""),
            "end": end.replace("-", ""),
            "format": "JSON",
        }
    )
    url = f"https://power.larc.nasa.gov/api/temporal/daily/point?{query}"
    request = urllib.request.Request(url, headers={"User-Agent": "Forecast-Hydro/1.0"})
    with urllib.request.urlopen(request, timeout=120) as response:
        payload = json.load(response)

    values = payload["properties"]["parameter"]
    dates = sorted(values[PARAMETERS[0]])
    destination.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "date",
        "rain_mm",
        "temperature_mean_c",
        "temperature_max_c",
        "temperature_min_c",
        "wind_speed_2m_mps",
        "relative_humidity_2m_pct",
        "source",
        "observation_type",
    ]
    count = 0
    opener = gzip.open if destination.name.endswith(".gz") else open
    with opener(destination, "wt", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for key in dates:
            raw = [values[name].get(key) for name in PARAMETERS]
            clean = [None if value in (-999, -999.0) else value for value in raw]
            if clean[0] is None:
                continue
            writer.writerow(
                {
                    "date": f"{key[:4]}-{key[4:6]}-{key[6:]}",
                    "rain_mm": clean[0],
                    "temperature_mean_c": clean[1],
                    "temperature_max_c": clean[2],
                    "temperature_min_c": clean[3],
                    "wind_speed_2m_mps": clean[4],
                    "relative_humidity_2m_pct": clean[5],
                    "source": "NASA POWER Daily",
                    "observation_type": "gridded_meteorological_proxy",
                }
            )
            count += 1

    metadata = {
        "schema_version": "forecast-hydro-site-history-v1",
        "site_slug": slug,
        "site_name": site["display_name"],
        "latitude": site["latitude"],
        "longitude": site["longitude"],
        "period": {"start": start, "end": end},
        "rows": count,
        "source": "NASA POWER Daily API",
        "source_url": "https://power.larc.nasa.gov/docs/services/api/temporal/daily/",
        "observation_type": "gridded_meteorological_proxy",
        "disclaimer": "Not an on-site rain gauge and not direct site observation.",
    }
    metadata_name = destination.name.removesuffix(".csv.gz").removesuffix(".csv")
    destination.with_name(metadata_name + ".metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--site", default="pltm_besai_kemu")
    parser.add_argument("--start", default="1981-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "data/sites/pltm_besai_kemu/nasa_power_daily_1981_2025.csv.gz",
    )
    args = parser.parse_args()
    rows = fetch(args.site, args.start, args.end, args.output)
    print(f"SUCCESS: {rows} daily rows -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
