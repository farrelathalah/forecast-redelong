#!/usr/bin/env python3
"""Prepare compact geospatial and historical assets for Forecast Redelong.

The supervisor package contains an ArcGIS shapefile in WGS 84 / UTM zone 47N
and NASA Giovanni GPM daily CSV exports.  This script converts those source
files with the Python standard library so the GitHub Pages build does not need
GDAL.  It deliberately publishes NASA GPM-derived history only; BMKG and PU
station workbooks remain internal references until redistribution permission is
confirmed.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import json
import math
import struct
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUT = ROOT / "data" / "redelong"
GPM_FILES = {
    "gpm1": "GPM1RDL.csv",
    "gpm2": "GPM2RDL.csv",
    "gpm3": "GPM3RDL.csv",
    "gpm4": "GPM4RDL.csv",
    "gpm5": "GPM5RDL.csv",
    "gpm6": "GPM6RDL.csv",
}
STATION_METADATA = [
    {
        "station_id": "bmkg_96009",
        "name": "Stasiun Meteorologi Malikussaleh",
        "network": "BMKG",
        "latitude": 5.22869,
        "longitude": 96.94749,
        "elevation_m": 28,
        "history_start": "2001-10-24",
        "history_end": "2025-10-23",
        "valid_rain_days": 7176,
        "publication": "metadata_only",
    },
    {
        "station_id": "bmkg_96015",
        "name": "Stasiun Meteorologi Cut Nyak Dhien Nagan Raya",
        "network": "BMKG",
        "latitude": 4.04928,
        "longitude": 96.24796,
        "elevation_m": 3,
        "history_start": "2010-01-01",
        "history_end": "2025-10-23",
        "valid_rain_days": 5094,
        "publication": "metadata_only",
    },
    {
        "station_id": "bmkg_96017",
        "name": "Stasiun Klimatologi Aceh",
        "network": "BMKG",
        "latitude": 5.404,
        "longitude": 95.464,
        "elevation_m": 40,
        "history_start": "2001-10-24",
        "history_end": "2025-10-23",
        "valid_rain_days": 5434,
        "publication": "metadata_only",
    },
    {
        "station_id": "pu_tama_tue",
        "name": "TamaTue",
        "network": "BWS Sumatera I / PU",
        "latitude": 4.6364722222,
        "longitude": 96.83625,
        "elevation_m": 1274,
        "history_start": "2015-01-01",
        "history_end": "2019-12-31",
        "valid_rain_days": 1826,
        "publication": "metadata_only",
    },
    {
        "station_id": "pu_blang_pante",
        "name": "Blang Pante",
        "network": "Dinas Pengairan",
        "latitude": 4.9463722222,
        "longitude": 97.1620861111,
        "elevation_m": None,
        "history_start": "2014-01-01",
        "history_end": "2016-12-31",
        "valid_rain_days": 1066,
        "publication": "metadata_only",
    },
    {
        "station_id": "pu_jambo_aye",
        "name": "Jambo Aye",
        "network": "BWS Sumatera I / PU",
        "latitude": 4.9362305556,
        "longitude": 97.4696944444,
        "elevation_m": 18,
        "history_start": "2018-01-01",
        "history_end": "2019-12-31",
        "valid_rain_days": 730,
        "publication": "metadata_only",
    },
    {
        "station_id": "pu_teupin_mane",
        "name": "Kp. Teupin Mane",
        "network": "Dinas Pengairan",
        "latitude": 5.1154277778,
        "longitude": 96.701775,
        "elevation_m": None,
        "history_start": "2008-01-01",
        "history_end": "2016-12-31",
        "valid_rain_days": 1097,
        "publication": "metadata_only",
    },
]


def read_dbf(path: Path) -> list[dict[str, str]]:
    raw = path.read_bytes()
    row_count = struct.unpack_from("<I", raw, 4)[0]
    header_length = struct.unpack_from("<H", raw, 8)[0]
    row_length = struct.unpack_from("<H", raw, 10)[0]
    fields: list[tuple[str, int]] = []
    offset = 32
    while raw[offset] != 0x0D:
        descriptor = raw[offset : offset + 32]
        name = descriptor[:11].split(b"\0", 1)[0].decode("latin1")
        fields.append((name, descriptor[16]))
        offset += 32
    rows = []
    for index in range(row_count):
        record = raw[
            header_length + index * row_length : header_length + (index + 1) * row_length
        ]
        cursor = 1
        row: dict[str, str] = {}
        for name, length in fields:
            row[name] = record[cursor : cursor + length].decode(
                "latin1", errors="replace"
            ).strip()
            cursor += length
        rows.append(row)
    return rows


def read_polygon_shapefile(path: Path) -> list[list[list[tuple[float, float]]]]:
    raw = path.read_bytes()
    if struct.unpack_from("<i", raw, 32)[0] != 5:
        raise ValueError(f"{path} bukan Polygon shapefile")
    records: list[list[list[tuple[float, float]]]] = []
    offset = 100
    while offset + 8 <= len(raw):
        _, words = struct.unpack_from(">2i", raw, offset)
        offset += 8
        record = raw[offset : offset + words * 2]
        offset += words * 2
        if struct.unpack_from("<i", record, 0)[0] != 5:
            continue
        part_count, point_count = struct.unpack_from("<2i", record, 36)
        parts = list(struct.unpack_from("<" + "i" * part_count, record, 44))
        point_offset = 44 + 4 * part_count
        points = [
            struct.unpack_from("<2d", record, point_offset + index * 16)
            for index in range(point_count)
        ]
        boundaries = parts + [len(points)]
        records.append(
            [points[boundaries[i] : boundaries[i + 1]] for i in range(part_count)]
        )
    return records


def utm47n_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    semi_major = 6378137.0
    eccentricity = 0.00669438
    scale = 0.9996
    x = easting - 500000.0
    meridional = northing / scale
    mu = meridional / (
        semi_major
        * (
            1
            - eccentricity / 4
            - 3 * eccentricity**2 / 64
            - 5 * eccentricity**3 / 256
        )
    )
    e1 = (1 - math.sqrt(1 - eccentricity)) / (1 + math.sqrt(1 - eccentricity))
    footprint = (
        mu
        + (3 * e1 / 2 - 27 * e1**3 / 32) * math.sin(2 * mu)
        + (21 * e1**2 / 16 - 55 * e1**4 / 32) * math.sin(4 * mu)
        + (151 * e1**3 / 96) * math.sin(6 * mu)
        + (1097 * e1**4 / 512) * math.sin(8 * mu)
    )
    second_eccentricity = eccentricity / (1 - eccentricity)
    c1 = second_eccentricity * math.cos(footprint) ** 2
    t1 = math.tan(footprint) ** 2
    n1 = semi_major / math.sqrt(1 - eccentricity * math.sin(footprint) ** 2)
    r1 = semi_major * (1 - eccentricity) / (
        1 - eccentricity * math.sin(footprint) ** 2
    ) ** 1.5
    d = x / (n1 * scale)
    latitude = footprint - (n1 * math.tan(footprint) / r1) * (
        d**2 / 2
        - (5 + 3 * t1 + 10 * c1 - 4 * c1**2 - 9 * second_eccentricity)
        * d**4
        / 24
        + (
            61
            + 90 * t1
            + 298 * c1
            + 45 * t1**2
            - 252 * second_eccentricity
            - 3 * c1**2
        )
        * d**6
        / 720
    )
    central_meridian = math.radians(99.0)
    longitude = central_meridian + (
        d
        - (1 + 2 * t1 + c1) * d**3 / 6
        + (
            5
            - 2 * c1
            + 28 * t1
            - 3 * c1**2
            + 8 * second_eccentricity
            + 24 * t1**2
        )
        * d**5
        / 120
    ) / math.cos(footprint)
    return math.degrees(longitude), math.degrees(latitude)


def polygon_area_km2(rings: list[list[tuple[float, float]]]) -> float:
    total = 0.0
    for ring in rings:
        signed = sum(
            ring[index][0] * ring[(index + 1) % len(ring)][1]
            - ring[(index + 1) % len(ring)][0] * ring[index][1]
            for index in range(len(ring))
        ) / 2
        total += signed
    return abs(total) / 1_000_000


def build_catchment_geojson(source_dir: Path, destination: Path) -> dict[str, Any]:
    shp = source_dir / "PLTA Redelong CLIP.shp"
    dbf = source_dir / "PLTA Redelong CLIP.dbf"
    records = read_polygon_shapefile(shp)
    attributes = read_dbf(dbf)
    if len(records) != len(attributes):
        raise ValueError("Jumlah geometry dan atribut PLTA Redelong CLIP berbeda")
    features = []
    catchment_area = 0.0
    for rings, attrs in zip(records, attributes):
        name = attrs.get("name", "Area")
        include = name.upper().startswith("GPM") and "TAMATUE" not in name.upper()
        area = polygon_area_km2(rings)
        if include:
            catchment_area += area
        coordinates = []
        for ring in rings:
            converted = [utm47n_to_wgs84(x, y) for x, y in ring]
            if converted and converted[0] != converted[-1]:
                converted.append(converted[0])
            coordinates.append([[round(x, 7), round(y, 7)] for x, y in converted])
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "zone_id": name.lower().replace(" ", "_"),
                    "name": name,
                    "area_km2": round(area, 3),
                    "include_in_catchment": include,
                    "role": "catchment_zone" if include else "external_comparison",
                    "source_file": "PLTA Redelong CLIP.shp",
                },
                "geometry": {"type": "Polygon", "coordinates": coordinates},
            }
        )
    payload = {
        "type": "FeatureCollection",
        "name": "Forecast Redelong analysis zones",
        "metadata": {
            "crs_source": "WGS 84 / UTM zone 47N",
            "crs_output": "WGS 84",
            "catchment_area_km2": round(catchment_area, 3),
            "status": "provided_boundary_pending_engineering_confirmation",
            "note": "GPM1-GPM6 form the Redelong analysis area; TamaTue remains external.",
        },
        "features": features,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def load_gpm_daily(path: Path) -> tuple[list[tuple[date, float]], dict[str, str]]:
    metadata: dict[str, str] = {}
    rows: list[tuple[date, float]] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        reading_data = False
        for row in reader:
            if not row:
                continue
            if row[0].strip().lower() == "time":
                reading_data = True
                continue
            if not reading_data:
                if len(row) > 1:
                    metadata[row[0].rstrip(":").strip()] = row[1].strip()
                continue
            if len(row) < 2:
                continue
            try:
                day = datetime.strptime(row[0].strip(), "%Y-%m-%d").date()
                rain = float(row[1])
            except (TypeError, ValueError):
                continue
            if math.isfinite(rain) and rain >= 0:
                rows.append((day, rain))
    return rows, metadata


def prepare_gpm_history(source_dir: Path, destination: Path) -> dict[str, Any]:
    destination.mkdir(parents=True, exist_ok=True)
    all_daily: list[dict[str, Any]] = []
    monthly: defaultdict[tuple[str, int, int], list[float]] = defaultdict(list)
    annual: defaultdict[tuple[str, int], list[float]] = defaultdict(list)
    source_metadata: dict[str, Any] = {}
    for slug, filename in GPM_FILES.items():
        rows, metadata = load_gpm_daily(source_dir / filename)
        if not rows:
            raise ValueError(f"Data GPM kosong: {filename}")
        source_metadata[slug] = {
            "file": filename,
            "start": rows[0][0].isoformat(),
            "end": rows[-1][0].isoformat(),
            "valid_days": len(rows),
            "giovanni_url": metadata.get("URL to Reproduce Results"),
            "data_bounding_box": metadata.get("Data Bounding Box"),
        }
        for day, rain in rows:
            rounded = round(rain, 3)
            all_daily.append(
                {"date": day.isoformat(), "location_slug": slug, "rain_mm": rounded}
            )
            monthly[(slug, day.year, day.month)].append(rain)
            annual[(slug, day.year)].append(rain)

    with (destination / "gpm_daily_history.csv").open(
        "w", encoding="utf-8", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=["date", "location_slug", "rain_mm"])
        writer.writeheader()
        writer.writerows(sorted(all_daily, key=lambda row: (row["date"], row["location_slug"])))

    monthly_rows = []
    for (slug, year, month), values in sorted(monthly.items()):
        expected = calendar.monthrange(year, month)[1]
        monthly_rows.append(
            {
                "location_slug": slug,
                "year": year,
                "month": month,
                "period": f"{year:04d}-{month:02d}",
                "rain_mm": round(sum(values), 2),
                "valid_days": len(values),
                "expected_days": expected,
                "complete": len(values) == expected,
            }
        )
    annual_rows = []
    for (slug, year), values in sorted(annual.items()):
        expected = 366 if calendar.isleap(year) else 365
        annual_rows.append(
            {
                "location_slug": slug,
                "year": year,
                "rain_mm": round(sum(values), 2),
                "valid_days": len(values),
                "expected_days": expected,
                "complete": len(values) == expected,
            }
        )
    climatology_rows = []
    for slug in GPM_FILES:
        for month in range(1, 13):
            values = [
                row["rain_mm"]
                for row in monthly_rows
                if row["location_slug"] == slug
                and row["month"] == month
                and row["complete"]
            ]
            climatology_rows.append(
                {
                    "location_slug": slug,
                    "month": month,
                    "mean_rain_mm": round(sum(values) / len(values), 2) if values else None,
                    "years": len(values),
                }
            )

    history = {
        "schema_version": "forecast-redelong-history-v1",
        "source": "NASA GPM IMERG Final Daily via Giovanni",
        "variable": "daily precipitation",
        "unit": "mm",
        "daily_download": "gpm_daily_history.csv",
        "sources": source_metadata,
        "monthly": monthly_rows,
        "annual": annual_rows,
        "monthly_climatology": climatology_rows,
    }
    (destination / "gpm_history_summary.json").write_text(
        json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    return history


def build_station_geojson(destination: Path, plant_lat: float, plant_lon: float) -> dict:
    features = []
    for station in STATION_METADATA:
        properties = dict(station)
        properties["distance_to_plta_km"] = round(
            haversine_km(
                plant_lat,
                plant_lon,
                float(station["latitude"]),
                float(station["longitude"]),
            ),
            1,
        )
        lon = properties.pop("longitude")
        lat = properties.pop("latitude")
        features.append(
            {
                "type": "Feature",
                "properties": properties,
                "geometry": {"type": "Point", "coordinates": [lon, lat]},
            }
        )
    payload = {
        "type": "FeatureCollection",
        "metadata": {
            "publication": "station metadata only",
            "note": "Raw BMKG/PU rainfall is not published until redistribution permission is confirmed.",
        },
        "features": features,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return payload


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    value = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(value))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--supervisor-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    geospatial = args.output_root / "geospatial"
    history = args.output_root / "history"
    catchment = build_catchment_geojson(
        args.supervisor_root / "Data Titik Stasiun",
        geospatial / "redelong_analysis_zones.geojson",
    )
    stations = build_station_geojson(
        geospatial / "redelong_historical_stations.geojson",
        plant_lat=4.7481388889,
        plant_lon=96.9773444444,
    )
    gpm = prepare_gpm_history(
        args.supervisor_root / "Data Stasiun GPM",
        history,
    )
    report = {
        "catchment_area_km2": catchment["metadata"]["catchment_area_km2"],
        "zones": len(catchment["features"]),
        "stations": len(stations["features"]),
        "gpm_locations": len(gpm["sources"]),
        "gpm_daily_rows": sum(item["valid_days"] for item in gpm["sources"].values()),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
