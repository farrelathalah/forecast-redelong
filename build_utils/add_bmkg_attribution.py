from pathlib import Path

OUTPUTS = Path("outputs")

NOTE = """
<div style="
  max-width:1180px;
  margin:32px auto 0;
  padding:14px 22px;
  color:rgba(239,248,255,.72);
  font-family:Inter,Segoe UI,Arial,sans-serif;
  font-size:12px;
  line-height:1.6;
">
  Sumber data prakiraan mencakup BMKG (Badan Meteorologi, Klimatologi, dan Geofisika)
  serta model prakiraan numerik multi-source yang tersedia pada pipeline Forecast Redelong.
</div>
"""

def patch(path: Path) -> None:
    if not path.exists():
        return

    html = path.read_text(encoding="utf-8")

    if "Sumber data prakiraan mencakup BMKG" in html:
        return

    if "</body>" in html:
        html = html.replace("</body>", NOTE + "\n</body>")
    else:
        html += NOTE

    path.write_text(html, encoding="utf-8")
    print("patched:", path)

targets = [
    OUTPUTS / "index.html",
    OUTPUTS / "redelong_rain_map.html",
    OUTPUTS / "redelong_overview.html",
]

for path in OUTPUTS.glob("*/rain_dashboard.html"):
    targets.append(path)

for path in targets:
    patch(path)

print("SUCCESS")
