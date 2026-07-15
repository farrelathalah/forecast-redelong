from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
IN_CSV = ROOT / "data" / "redelong" / "catchment_points.csv"
OUT_JSON = ROOT / "locations.json"


def slugify(text: str) -> str:
    text = str(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("_")
    return text or "unknown"


def pick_column(df: pd.DataFrame, candidates: list[str]) -> str:
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    raise RuntimeError(
        f"Tidak menemukan kolom dari kandidat {candidates}. "
        f"Kolom tersedia: {list(df.columns)}"
    )


def optional_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    lower_map = {c.lower(): c for c in df.columns}
    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def as_bool(value, default: bool = False) -> bool:
    if pd.isna(value):
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "ya"}


def main() -> None:
    if not IN_CSV.exists():
        raise FileNotFoundError(f"Tidak ada file: {IN_CSV}")

    df = pd.read_csv(IN_CSV)

    name_col = pick_column(df, ["point_name", "name", "location_name", "lokasi", "Location", "Nama"])
    lat_col = pick_column(df, ["latitude", "lat", "Latitude", "LAT", "y", "Y"])
    lon_col = pick_column(df, ["longitude", "lon", "Longitude", "LON", "lng", "x", "X"])
    weight_col = optional_column(df, ["weight_km2", "area_km2", "luas_km2"])
    role_col = optional_column(df, ["operational_role", "role", "peran"])
    include_col = optional_column(df, ["include_in_catchment", "included", "digunakan"])
    source_col = optional_column(df, ["source", "sumber"])
    note_col = optional_column(df, ["note", "catatan"])

    locations = {}
    default_multi_locations = []

    for i, row in df.iterrows():
        name = str(row[name_col]).strip()
        lat = float(row[lat_col])
        lon = float(row[lon_col])

        if not name:
            name = f"Catchment Point {i + 1}"

        slug = slugify(name)

        if slug in locations:
            slug = f"{slug}_{i + 1}"

        locations[slug] = {
            "location_name": name,
            "adm4": "",
            "latitude": lat,
            "longitude": lon,
            "timezone": "Asia/Jakarta",
            "bmkg_point_name": name,
            "area_level": str(row[role_col]).strip() if role_col else "catchment_point",
            "is_proxy_bmkg": True,
            "weight_km2": float(row[weight_col]) if weight_col and not pd.isna(row[weight_col]) else 0.0,
            "include_in_catchment": as_bool(row[include_col]) if include_col else False,
            "operational_role": str(row[role_col]).strip() if role_col else "reference_point",
            "spatial_source": str(row[source_col]).strip() if source_col else "",
            "spatial_note": str(row[note_col]).strip() if note_col and not pd.isna(row[note_col]) else "",
            "note": "PLTA Redelong representative point. BMKG ADM4 code not assigned yet."
        }

        default_multi_locations.append(slug)

    payload = {
        "default_multi_locations": default_multi_locations,
        "locations": locations
    }

    OUT_JSON.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )

    print("SUCCESS")
    print(f"Input: {IN_CSV}")
    print(f"Output: {OUT_JSON}")
    print(f"Jumlah lokasi: {len(locations)}")
    print("Locations:")
    for slug in default_multi_locations:
        loc = locations[slug]
        print(f"- {slug}: {loc['location_name']} ({loc['latitude']}, {loc['longitude']})")


if __name__ == "__main__":
    main()
