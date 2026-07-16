import csv
import json
from pathlib import Path

locations_path = Path("locations.json")
mapping_path = Path("data/redelong/adm4_mapping.csv")

if not locations_path.exists():
    raise FileNotFoundError("locations.json tidak ditemukan. Jalankan make_redelong_locations.py dulu.")

if not mapping_path.exists():
    raise FileNotFoundError("data/redelong/adm4_mapping.csv tidak ditemukan.")

data = json.loads(locations_path.read_text(encoding="utf-8"))

mapping = {}
with mapping_path.open("r", encoding="utf-8-sig", newline="") as f:
    for row in csv.DictReader(f):
        slug = row["location_slug"].strip()
        mapping[slug] = {
            "adm4": row["adm4"].strip(),
            "bmkg_reference_name": row.get("bmkg_reference_name", "").strip(),
            "adm4_note": row.get("adm4_note", "").strip(),
        }

missing = []

for slug, loc in data["locations"].items():
    if slug not in mapping:
        # Independent sites carry their own verified/provisional ADM4 mapping
        # in config/sites.json and must not inherit Bale Redelong's code.
        if loc.get("site_scope") and loc.get("adm4"):
            continue
        missing.append(slug)
        continue

    m = mapping[slug]
    loc["adm4"] = m["adm4"]
    loc["bmkg_point_name"] = m["bmkg_reference_name"] or loc.get("location_name", slug)
    loc["note"] = (
        "Forecast Redelong representative point. "
        f"BMKG ADM4 reference: {m['adm4']} ({m['bmkg_reference_name']}). "
        f"{m['adm4_note']} "
        f"Spatial role: {loc.get('operational_role', 'reference_point')}. "
        f"{loc.get('spatial_note', '')}"
    )

if missing:
    raise ValueError(f"ADM4 mapping belum ada untuk: {', '.join(missing)}")

locations_path.write_text(
    json.dumps(data, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("SUCCESS")
print("ADM4 mapping applied from:", mapping_path)
for slug, loc in data["locations"].items():
    print(f"- {slug}: {loc.get('adm4')} / {loc.get('bmkg_point_name')}")
