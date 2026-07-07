from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
from html import escape
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
OUTPUTS = ROOT / "outputs"
LOCATIONS_JSON = ROOT / "locations.json"

WIB = timezone(timedelta(hours=7))


def read_locations() -> dict:
    if not LOCATIONS_JSON.exists():
        return {}
    data = json.loads(LOCATIONS_JSON.read_text(encoding="utf-8"))
    return data.get("locations", {})


def fmt_num(value, digits=1) -> str:
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return "-"


def find_rain_columns(df: pd.DataFrame) -> list[str]:
    cols = []
    for col in df.columns:
        lower = col.lower()
        if any(key in lower for key in ["rain", "precip", "hujan"]):
            if pd.api.types.is_numeric_dtype(df[col]):
                cols.append(col)
    return cols


def guess_source_count() -> str:
    path = OUTPUTS / "source_status_all_locations.csv"
    if not path.exists():
        return "-"
    try:
        df = pd.read_csv(path)
    except Exception:
        return "-"

    for col in ["source_id", "source", "sumber", "model"]:
        if col in df.columns:
            return str(df[col].dropna().astype(str).nunique())

    return str(len(df))


def guess_forecast_stats() -> dict:
    path = OUTPUTS / "forecast_all_locations.csv"
    stats = {
        "rows": "-",
        "rain_max": "-",
        "rain_mean": "-",
        "rain_col": "-",
    }

    if not path.exists():
        return stats

    try:
        df = pd.read_csv(path)
    except Exception:
        return stats

    stats["rows"] = str(len(df))

    rain_cols = find_rain_columns(df)
    if rain_cols:
        col = rain_cols[0]
        series = pd.to_numeric(df[col], errors="coerce").dropna()
        if len(series) > 0:
            stats["rain_col"] = col
            stats["rain_max"] = fmt_num(series.max(), 1)
            stats["rain_mean"] = fmt_num(series.mean(), 1)

    return stats


def location_card(slug: str, loc: dict) -> str:
    name = escape(str(loc.get("location_name", slug)))
    lat = escape(str(loc.get("latitude", "-")))
    lon = escape(str(loc.get("longitude", "-")))

    folder = OUTPUTS / slug
    links = []

    candidates = [
        ("Dashboard", "redelong_app.html"),
        ("3 Hari", "redelong_3day.html"),
        ("Aktivitas", "redelong_activity.html"),
        ("Planner", "redelong_planner.html"),
    ]

    for label, filename in candidates:
        if (folder / filename).exists():
            links.append(f'<a href="{slug}/{filename}">{label}</a>')

    if not links:
        links.append('<span class="muted">Output belum tersedia</span>')

    return f"""
    <article class="loc-card">
      <div>
        <h3>{name}</h3>
        <p class="coord">Lat {lat} · Lon {lon}</p>
      </div>
      <div class="loc-links">
        {"".join(links)}
      </div>
    </article>
    """


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    locations = read_locations()
    stats = guess_forecast_stats()
    source_count = guess_source_count()
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    location_cards = "\n".join(
        location_card(slug, loc)
        for slug, loc in locations.items()
        if (OUTPUTS / slug).exists()
    )

    if not location_cards:
        location_cards = """
        <article class="loc-card">
          <h3>Output lokasi belum ditemukan</h3>
          <p>Jalankan forecast terlebih dahulu sebelum membuka portal.</p>
        </article>
        """

    map_link = "redelong_portal_map.html" if (OUTPUTS / "redelong_portal_map.html").exists() else "#"

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forecast Redelong Forecast Portal</title>
  <style>
    :root {{
      --bg: #06111f;
      --panel: rgba(255,255,255,0.075);
      --panel2: rgba(255,255,255,0.11);
      --text: #eef7ff;
      --muted: #9fb3c8;
      --line: rgba(255,255,255,0.14);
      --accent: #38d5c8;
      --accent2: #72a7ff;
      --warn: #ffd166;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at 20% 10%, rgba(56,213,200,.24), transparent 32%),
        radial-gradient(circle at 80% 20%, rgba(114,167,255,.20), transparent 30%),
        linear-gradient(135deg, #06111f, #092133 45%, #101735);
      min-height: 100vh;
    }}
    a {{ color: inherit; text-decoration: none; }}
    .wrap {{ max-width: 1180px; margin: 0 auto; padding: 32px 22px 56px; }}
    .topbar {{
      display: flex; justify-content: space-between; align-items: center;
      padding: 14px 0 30px; gap: 16px;
    }}
    .brand {{ display: flex; align-items: center; gap: 14px; }}
    .logo {{
      width: 44px; height: 44px; border-radius: 14px;
      background: linear-gradient(135deg, var(--accent), var(--accent2));
      box-shadow: 0 0 32px rgba(56,213,200,.28);
    }}
    .brand strong {{ font-size: 18px; letter-spacing: .2px; }}
    .brand span {{ display: block; color: var(--muted); font-size: 12px; margin-top: 2px; }}
    .nav {{ display: flex; gap: 10px; flex-wrap: wrap; }}
    .nav a, .button {{
      border: 1px solid var(--line);
      background: var(--panel);
      padding: 10px 14px;
      border-radius: 999px;
      color: var(--text);
      font-size: 14px;
    }}
    .nav a:hover, .button:hover {{ background: var(--panel2); }}
    .hero {{
      display: grid;
      grid-template-columns: 1.4fr .9fr;
      gap: 22px;
      align-items: stretch;
      margin-top: 12px;
    }}
    .hero-main, .panel, .loc-card {{
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.095), rgba(255,255,255,.045));
      backdrop-filter: blur(14px);
      border-radius: 26px;
      box-shadow: 0 20px 70px rgba(0,0,0,.25);
    }}
    .hero-main {{ padding: 34px; }}
    .kicker {{
      color: var(--accent);
      text-transform: uppercase;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 1.4px;
      margin-bottom: 14px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(34px, 5vw, 62px);
      line-height: 1.02;
      letter-spacing: -1.6px;
    }}
    .subtitle {{
      margin: 18px 0 0;
      color: var(--muted);
      font-size: 17px;
      line-height: 1.65;
      max-width: 800px;
    }}
    .hero-actions {{ display: flex; gap: 12px; flex-wrap: wrap; margin-top: 26px; }}
    .primary {{
      background: linear-gradient(135deg, rgba(56,213,200,.95), rgba(114,167,255,.95));
      color: #04111e;
      font-weight: 750;
      border: none;
    }}
    .side {{ padding: 24px; display: grid; gap: 14px; }}
    .metric {{
      border: 1px solid var(--line);
      background: rgba(0,0,0,.13);
      border-radius: 18px;
      padding: 16px;
    }}
    .metric .label {{ color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .9px; }}
    .metric .value {{ font-size: 28px; font-weight: 780; margin-top: 5px; }}
    .grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
      margin-top: 22px;
    }}
    .section {{ margin-top: 28px; }}
    .section h2 {{ font-size: 24px; margin: 0 0 14px; }}
    .locations {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
    }}
    .loc-card {{ padding: 18px; display: flex; justify-content: space-between; gap: 16px; align-items: center; }}
    .loc-card h3 {{ margin: 0 0 6px; font-size: 18px; }}
    .coord, .muted {{ color: var(--muted); margin: 0; font-size: 13px; }}
    .loc-links {{ display: flex; gap: 8px; flex-wrap: wrap; justify-content: flex-end; }}
    .loc-links a {{
      background: rgba(56,213,200,.12);
      border: 1px solid rgba(56,213,200,.28);
      color: #b8fff7;
      padding: 8px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 650;
    }}
    .panel {{ padding: 22px; }}
    .panel p {{ color: var(--muted); line-height: 1.7; margin: 0; }}
    .downloads {{ display: flex; flex-wrap: wrap; gap: 10px; }}
    .downloads a {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.07);
      padding: 11px 13px;
      border-radius: 14px;
      color: var(--text);
    }}
    .footer {{ color: var(--muted); margin-top: 34px; font-size: 13px; line-height: 1.6; }}
    @media (max-width: 860px) {{
      .hero {{ grid-template-columns: 1fr; }}
      .grid {{ grid-template-columns: repeat(2, 1fr); }}
      .locations {{ grid-template-columns: 1fr; }}
      .topbar {{ align-items: flex-start; flex-direction: column; }}
    }}
    @media (max-width: 520px) {{
      .grid {{ grid-template-columns: 1fr; }}
      .loc-card {{ flex-direction: column; align-items: flex-start; }}
      .loc-links {{ justify-content: flex-start; }}
    }}
  </style>
</head>
<body>
  <main class="wrap">
    <header class="topbar">
      <div class="brand">
        <div class="logo"></div>
        <div>
          <strong>Forecast Redelong</strong>
          <span>Forecast Portal · PLTA Redelong</span>
        </div>
      </div>
      <nav class="nav">
        <a href="{map_link}">Peta Portal</a>
        <a href="forecast_all_locations.csv">CSV Forecast</a>
        <a href="source_status_all_locations.csv">Status Sumber</a>
      </nav>
    </header>

    <section class="hero">
      <div class="hero-main">
        <div class="kicker">Sistem Prakiraan Hujan Ensemble</div>
        <h1>Monitoring hujan untuk dukungan operasional PLTA Redelong.</h1>
        <p class="subtitle">
          Portal ini menggabungkan prakiraan multi-source, titik pantau catchment,
          dan output berbasis web untuk membantu pemantauan risiko hujan di wilayah
          PLTA Redelong dan sekitarnya.
        </p>
        <div class="hero-actions">
          <a class="button primary" href="{map_link}">Buka Peta Portal</a>
          <a class="button" href="plta_redelong/redelong_app.html">Dashboard PLTA Redelong</a>
          <a class="button" href="plta_redelong/redelong_3day.html">Prakiraan 3 Hari</a>
        </div>
      </div>

      <aside class="side panel">
        <div class="metric">
          <div class="label">Titik Catchment</div>
          <div class="value">{len(locations)}</div>
        </div>
        <div class="metric">
          <div class="label">Sumber Aktif</div>
          <div class="value">{source_count}</div>
        </div>
        <div class="metric">
          <div class="label">Baris Forecast</div>
          <div class="value">{stats["rows"]}</div>
        </div>
        <div class="metric">
          <div class="label">Update Lokal</div>
          <div class="value" style="font-size:18px">{generated}</div>
        </div>
      </aside>
    </section>

    <section class="grid">
      <div class="metric">
        <div class="label">Rain Max</div>
        <div class="value">{stats["rain_max"]} mm</div>
      </div>
      <div class="metric">
        <div class="label">Rain Mean</div>
        <div class="value">{stats["rain_mean"]} mm</div>
      </div>
      <div class="metric">
        <div class="label">Kolom Hujan</div>
        <div class="value" style="font-size:15px">{escape(stats["rain_col"])}</div>
      </div>
      <div class="metric">
        <div class="label">Status Prototype</div>
        <div class="value" style="font-size:20px">Operasional Awal</div>
      </div>
    </section>

    <section class="section">
      <h2>Lokasi Forecast</h2>
      <div class="locations">
        {location_cards}
      </div>
    </section>

    <section class="section panel">
      <h2>Output Data</h2>
      <div class="downloads">
        <a href="forecast_all_locations.csv">forecast_all_locations.csv</a>
        <a href="ensemble_all_locations.csv">ensemble_all_locations.csv</a>
        <a href="source_status_all_locations.csv">source_status_all_locations.csv</a>
        <a href="redelong_all_locations.geojson">redelong_all_locations.geojson</a>
      </div>
    </section>

    <section class="section panel">
      <h2>Catatan Metodologi</h2>
      <p>
        Sistem ini adalah prototype prakiraan hujan ensemble untuk wilayah PLTA Redelong.
        Sumber BMKG belum diaktifkan pada versi ini karena kode ADM4 per titik catchment
        belum ditetapkan. Hasil forecast perlu divalidasi dengan observasi aktual sebelum
        digunakan sebagai dasar keputusan kritikal.
      </p>
    </section>

    <footer class="footer">
      Forecast Redelong Forecast Portal · Generated {generated}
    </footer>
  </main>
</body>
</html>
"""

    (OUTPUTS / "redelong_overview.html").write_text(html, encoding="utf-8")
    (OUTPUTS / ".nojekyll").write_text("", encoding="utf-8")

    print("SUCCESS")
    print(f"Overview operasional dibuat: {OUTPUTS / 'index.html'}")


if __name__ == "__main__":
    main()

