from __future__ import annotations

import json
from datetime import datetime, timezone, timedelta
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


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def status_summary() -> tuple[int, int, str]:
    df = read_csv(OUTPUTS / "source_status_all_locations.csv")
    if df.empty or "success" not in df.columns:
        return 0, 0, "-"

    total = len(df)
    success = df["success"].astype(str).str.lower().isin(["yes", "true", "1", "ok"]).sum()

    sources = "-"
    for col in ["source_id", "source", "provider"]:
        if col in df.columns:
            sources = str(df[col].dropna().astype(str).nunique())
            break

    return int(success), int(total), sources


def forecast_rows() -> int:
    df = read_csv(OUTPUTS / "forecast_all_locations.csv")
    return len(df)


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    locations = read_locations()
    success, total, source_count = status_summary()
    rows = forecast_rows()
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    location_items = "\n".join(
        f"<li><strong>{loc.get('location_name', slug)}</strong><span>{loc.get('latitude', '-')}, {loc.get('longitude', '-')}</span></li>"
        for slug, loc in locations.items()
    )

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Overview · Forecast Redelong</title>
  <style>
    :root {{
      --bg:#040c16;
      --panel:rgba(255,255,255,.08);
      --panel2:rgba(255,255,255,.12);
      --line:rgba(255,255,255,.15);
      --text:#eff8ff;
      --muted:#9fb4c9;
      --cyan:#45e0d0;
      --blue:#74a9ff;
      --gold:#ffd166;
    }}
    * {{ box-sizing:border-box; }}
    body {{
      margin:0;
      font-family:Inter,Segoe UI,Arial,sans-serif;
      color:var(--text);
      background:
        radial-gradient(circle at 12% 18%,rgba(69,224,208,.24),transparent 30%),
        radial-gradient(circle at 82% 16%,rgba(116,169,255,.20),transparent 32%),
        linear-gradient(135deg,#04111e,#08253a 45%,#11183a);
      min-height:100vh;
    }}
    a {{ color:inherit; text-decoration:none; }}
    .nav {{
      position:sticky;
      top:0;
      z-index:20;
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:18px;
      padding:18px min(5vw,64px);
      background:rgba(3,11,20,.78);
      backdrop-filter:blur(14px);
      border-bottom:1px solid var(--line);
    }}
    .brand {{
      display:flex;
      align-items:center;
      gap:14px;
    }}
    .logo {{
      width:46px;
      height:46px;
      border-radius:16px;
      background:linear-gradient(135deg,var(--cyan),var(--blue));
      box-shadow:0 0 36px rgba(69,224,208,.28);
    }}
    .brand strong {{
      display:block;
      font-size:18px;
    }}
    .brand span {{
      display:block;
      color:var(--muted);
      font-size:12px;
      margin-top:2px;
      letter-spacing:.8px;
      text-transform:uppercase;
    }}
    .nav-links {{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }}
    .nav-links a {{
      border:1px solid var(--line);
      background:rgba(255,255,255,.075);
      padding:10px 14px;
      border-radius:999px;
      font-size:14px;
      font-weight:650;
    }}
    .wrap {{
      max-width:1180px;
      margin:0 auto;
      padding:58px 22px 70px;
    }}
    .hero {{
      display:grid;
      grid-template-columns:1.25fr .75fr;
      gap:22px;
      align-items:stretch;
      margin-bottom:24px;
    }}
    .panel {{
      border:1px solid var(--line);
      background:linear-gradient(180deg,rgba(255,255,255,.10),rgba(255,255,255,.045));
      border-radius:30px;
      padding:28px;
      backdrop-filter:blur(18px);
      box-shadow:0 28px 90px rgba(0,0,0,.22);
    }}
    .kicker {{
      color:var(--cyan);
      text-transform:uppercase;
      font-size:12px;
      letter-spacing:1.4px;
      font-weight:800;
      margin-bottom:16px;
    }}
    h1 {{
      font-size:clamp(38px,5vw,68px);
      line-height:.98;
      letter-spacing:-2px;
      margin:0;
    }}
    h2 {{
      font-size:28px;
      margin:0 0 14px;
    }}
    h3 {{
      margin:0 0 8px;
      font-size:18px;
    }}
    p {{
      color:var(--muted);
      line-height:1.72;
      margin:0;
    }}
    .stats {{
      display:grid;
      gap:14px;
    }}
    .metric {{
      border:1px solid var(--line);
      background:rgba(0,0,0,.14);
      border-radius:22px;
      padding:18px;
    }}
    .metric .label {{
      color:var(--muted);
      text-transform:uppercase;
      font-size:12px;
      letter-spacing:1px;
      font-weight:800;
    }}
    .metric .value {{
      margin-top:8px;
      font-size:30px;
      font-weight:850;
    }}
    .grid {{
      display:grid;
      grid-template-columns:repeat(2,1fr);
      gap:18px;
      margin-top:18px;
    }}
    .full {{
      grid-column:1/-1;
    }}
    ul {{
      margin:12px 0 0;
      padding:0;
      list-style:none;
      display:grid;
      gap:10px;
    }}
    li {{
      border:1px solid rgba(255,255,255,.10);
      background:rgba(0,0,0,.11);
      border-radius:16px;
      padding:13px 14px;
      color:var(--text);
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:center;
    }}
    li span {{
      color:var(--muted);
      font-size:13px;
      text-align:right;
    }}
    .tag-row {{
      display:flex;
      gap:10px;
      flex-wrap:wrap;
      margin-top:14px;
    }}
    .tag {{
      border:1px solid rgba(69,224,208,.25);
      background:rgba(69,224,208,.10);
      color:#bafff8;
      padding:9px 11px;
      border-radius:999px;
      font-size:12px;
      font-weight:800;
    }}
    .warn {{
      border-color:rgba(255,209,102,.35);
      background:rgba(255,209,102,.10);
      color:#ffe3a1;
    }}
    .links {{
      display:flex;
      flex-wrap:wrap;
      gap:10px;
      margin-top:18px;
    }}
    .links a {{
      border:1px solid var(--line);
      background:rgba(255,255,255,.075);
      padding:12px 14px;
      border-radius:14px;
      font-weight:750;
    }}
    footer {{
      color:var(--muted);
      margin-top:30px;
      line-height:1.6;
      font-size:13px;
    }}
    @media(max-width:880px) {{
      .hero,.grid {{ grid-template-columns:1fr; }}
      .nav {{ align-items:flex-start; flex-direction:column; }}
      li {{ flex-direction:column; align-items:flex-start; }}
      li span {{ text-align:left; }}
    }}
  </style>
</head>
<body>
  <nav class="nav">
    <a class="brand" href="index.html">
      <div class="logo"></div>
      <div>
        <strong>Forecast Redelong</strong>
        <span>FORECAST PLTA REDELONG</span>
      </div>
    </a>
    <div class="nav-links">
      <a href="index.html">Home</a>
      <a href="redelong_rain_map.html">Peta Hujan</a>
      <a href="plta_redelong/rain_dashboard.html">Dashboard PLTA</a>
    </div>
  </nav>

  <main class="wrap">
    <section class="hero">
      <div class="panel">
        <div class="kicker">System Overview</div>
        <h1>Ringkasan teknis Forecast Redelong.</h1>
        <p style="margin-top:20px">
          Halaman ini menjelaskan fungsi sistem, sumber data, cakupan lokasi,
          cara membaca output, dan batasan validasi. Homepage dipakai sebagai
          halaman masuk, sedangkan overview ini dipakai untuk penjelasan laporan
          atau presentasi.
        </p>
        <div class="links">
          <a href="redelong_rain_map.html">Buka Peta Hujan</a>
          <a href="plta_redelong/rain_dashboard.html">Dashboard PLTA Redelong</a>
          <a href="forecast_all_locations.csv">Download Forecast CSV</a>
        </div>
      </div>

      <aside class="panel stats">
        <div class="metric">
          <div class="label">Titik Lokasi</div>
          <div class="value">{len(locations)}</div>
        </div>
        <div class="metric">
          <div class="label">Sumber Terdaftar</div>
          <div class="value">{source_count}</div>
        </div>
        <div class="metric">
          <div class="label">Status Request</div>
          <div class="value">{success}/{total}</div>
        </div>
        <div class="metric">
          <div class="label">Baris Forecast</div>
          <div class="value">{rows}</div>
        </div>
      </aside>
    </section>

    <section class="grid">
      <article class="panel">
        <h2>Tujuan sistem</h2>
        <p>
          Forecast Redelong dibuat sebagai prototype monitoring prakiraan hujan
          untuk mendukung pemantauan awal pada PLTA Redelong dan catchment
          sekitarnya. Sistem ini menyatukan hasil forecast dari beberapa sumber,
          lalu menampilkan peta hujan, dashboard per titik, dan output data.
        </p>
      </article>

      <article class="panel">
        <h2>Sumber forecast</h2>
        <p>
          Sistem menggunakan beberapa sumber prakiraan numerik non-BMKG, seperti
          ECMWF, GFS, ICON, CMA, Meteo-France, KMA, UKMO, dan MET Norway melalui
          pipeline yang tersedia. Jika satu sumber gagal, output masih dapat
          dibangun dari sumber lain yang berhasil.
        </p>
        <div class="tag-row">
          <span class="tag">ECMWF</span>
          <span class="tag">GFS</span>
          <span class="tag">ICON</span>
          <span class="tag">CMA</span>
          <span class="tag">METEOFRANCE</span>
          <span class="tag">KMA</span>
          <span class="tag">UKMO</span>
          <span class="tag">METNO</span>
        </div>
      </article>

      <article class="panel">
        <h2>Cara membaca output</h2>
        <p>
          Rain Max menunjukkan nilai hujan maksimum dari data forecast. Rain P90
          menunjukkan skenario atas atau persentil 90. Rain Mean menunjukkan
          rata-rata nilai hujan. Nilai ini dipakai untuk screening awal, bukan
          keputusan kritikal tunggal.
        </p>
      </article>

      <article class="panel">
        <h2>Status BMKG dan validasi</h2>
        <p>
          BMKG belum diaktifkan karena kode ADM4 per titik catchment masih memakai
          placeholder. Akurasi numerik belum diklaim dalam persen karena perlu
          backtesting terhadap observasi aktual, misalnya data hujan PLTA, AWS,
          GPM, atau data stasiun terdekat.
        </p>
        <div class="tag-row">
          <span class="tag warn">BMKG belum aktif</span>
          <span class="tag warn">Akurasi belum diklaim</span>
          <span class="tag warn">Perlu observasi aktual</span>
        </div>
      </article>

      <article class="panel full">
        <h2>Cakupan lokasi</h2>
        <ul>
          {location_items}
        </ul>
      </article>

      <article class="panel full">
        <h2>Output yang dihasilkan</h2>
        <p>
          Sistem menghasilkan halaman web dan data mentah yang dapat dipakai untuk
          verifikasi atau pengembangan lanjutan.
        </p>
        <div class="links">
          <a href="forecast_all_locations.csv">forecast_all_locations.csv</a>
          <a href="ensemble_all_locations.csv">ensemble_all_locations.csv</a>
          <a href="source_status_all_locations.csv">source_status_all_locations.csv</a>
          <a href="redelong_all_locations.geojson">redelong_all_locations.geojson</a>
        </div>
      </article>
    </section>

    <footer>
      Forecast Redelong · FORECAST PLTA REDELONG · Generated {generated}
    </footer>
  </main>
</body>
</html>
"""

    (OUTPUTS / "redelong_overview.html").write_text(html, encoding="utf-8")
    print("SUCCESS")
    print("Overview teknis dibuat: outputs/redelong_overview.html")


if __name__ == "__main__":
    main()
