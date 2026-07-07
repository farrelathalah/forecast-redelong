import json
from pathlib import Path

path = Path("locations.json")
data = json.loads(path.read_text(encoding="utf-8"))

for loc in data["locations"].values():
    loc["adm4"] = "11.17.00.0000"
    loc["note"] = (
        "PLTA Redelong catchment representative point. "
        "ADM4 placeholder only; BMKG source not active in this run."
    )

path.write_text(
    json.dumps(data, indent=2, ensure_ascii=False),
    encoding="utf-8"
)

print("SUCCESS")
print("ADM4 placeholder sudah dipasang ke semua lokasi.")
