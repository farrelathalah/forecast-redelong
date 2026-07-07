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


def safe_read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def find_numeric_rain_column(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        lower = col.lower()
        if any(key in lower for key in ["rain", "precip", "hujan"]):
            s = pd.to_numeric(df[col], errors="coerce")
            if s.notna().any():
                return col
    return None


def source_count() -> str:
    df = safe_read_csv(OUTPUTS / "source_status_all_locations.csv")
    if df.empty:
        return "-"

    for col in ["source_id", "source", "sumber", "model"]:
        if col in df.columns:
            return str(df[col].dropna().astype(str).nunique())

    return str(len(df))


def forecast_stats() -> dict:
    df = safe_read_csv(OUTPUTS / "forecast_all_locations.csv")
    out = {
        "rows": "-",
        "rain_max": "-",
        "rain_mean": "-",
        "rain_col": "-",
    }

    if df.empty:
        return out

    out["rows"] = f"{len(df):,}".replace(",", ".")

    rain_col = find_numeric_rain_column(df)
    if rain_col:
        s = pd.to_numeric(df[rain_col], errors="coerce").dropna()
        if len(s):
            out["rain_col"] = rain_col
            out["rain_max"] = f"{s.max():.1f}"
            out["rain_mean"] = f"{s.mean():.1f}"

    return out


def location_cards(locations: dict) -> str:
    cards = []

    for slug, loc in locations.items():
        folder = OUTPUTS / slug
        if not folder.exists():
            continue

        name = escape(str(loc.get("location_name", slug)))
        lat = escape(str(loc.get("latitude", "-")))
        lon = escape(str(loc.get("longitude", "-")))

        app = f"{slug}/redelong_app.html"
        day3 = f"{slug}/redelong_3day.html"
        activity = f"{slug}/redelong_activity.html"

        links = []
        if (folder / "redelong_app.html").exists():
            links.append(f'<a href="{app}">Dashboard</a>')
        if (folder / "redelong_3day.html").exists():
            links.append(f'<a href="{day3}">3 Hari</a>')
        if (folder / "redelong_activity.html").exists():
            links.append(f'<a href="{activity}">Aktivitas</a>')

        if not links:
            links.append('<span>Output belum tersedia</span>')

        cards.append(f"""
        <article class="location-card reveal">
          <div>
            <p class="eyebrow">Catchment Point</p>
            <h3>{name}</h3>
            <p class="muted">Lat {lat} · Lon {lon}</p>
          </div>
          <div class="card-links">
            {''.join(links)}
          </div>
        </article>
        """)

    return "\n".join(cards) or """
    <article class="location-card reveal">
      <h3>Output lokasi belum tersedia</h3>
      <p class="muted">Jalankan forecast terlebih dahulu.</p>
    </article>
    """


def main() -> None:
    OUTPUTS.mkdir(parents=True, exist_ok=True)

    locations = read_locations()
    stats = forecast_stats()
    n_sources = source_count()
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")

    map_href = "redelong_portal_map.html" if (OUTPUTS / "redelong_portal_map.html").exists() else "#"
    overview_href = "redelong_overview.html" if (OUTPUTS / "redelong_overview.html").exists() else "#"
    plta_href = "plta_redelong/redelong_app.html" if (OUTPUTS / "plta_redelong" / "redelong_app.html").exists() else "#"

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forecast Redelong Forecast Portal</title>
  <style>
    :root {{
      --bg: #030b14;
      --panel: rgba(255,255,255,0.075);
      --panel2: rgba(255,255,255,0.12);
      --line: rgba(255,255,255,0.15);
      --text: #eff8ff;
      --muted: #9fb4c9;
      --cyan: #45e0d0;
      --blue: #74a9ff;
      --gold: #ffd166;
      --danger: #ff6b6b;
    }}

    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      font-family: Inter, Segoe UI, Arial, sans-serif;
      color: var(--text);
      background: var(--bg);
      overflow-x: hidden;
    }}

    body::before {{
      content: "";
      position: fixed;
      inset: 0;
      z-index: -3;
      background:
        radial-gradient(circle at 12% 18%, rgba(69,224,208,.32), transparent 30%),
        radial-gradient(circle at 82% 18%, rgba(116,169,255,.26), transparent 32%),
        radial-gradient(circle at 50% 95%, rgba(255,209,102,.12), transparent 32%),
        linear-gradient(135deg, #04111e, #08253a 42%, #11183a);
    }}

    .noise {{
      position: fixed;
      inset: 0;
      z-index: -2;
      pointer-events: none;
      opacity: .08;
      background-image:
        linear-gradient(rgba(255,255,255,.08) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255,255,255,.08) 1px, transparent 1px);
      background-size: 64px 64px;
      mask-image: radial-gradient(circle at center, black, transparent 82%);
    }}

    .orb {{
      position: fixed;
      border-radius: 999px;
      filter: blur(12px);
      opacity: .34;
      z-index: -1;
      animation: float 11s ease-in-out infinite;
    }}
    .orb.one {{
      width: 320px; height: 320px; left: -80px; top: 120px;
      background: rgba(69,224,208,.26);
    }}
    .orb.two {{
      width: 420px; height: 420px; right: -120px; top: 240px;
      background: rgba(116,169,255,.22);
      animation-delay: -4s;
    }}
    .orb.three {{
      width: 260px; height: 260px; left: 44%; bottom: -80px;
      background: rgba(255,209,102,.12);
      animation-delay: -7s;
    }}

    @keyframes float {{
      0%, 100% {{ transform: translate3d(0,0,0) scale(1); }}
      50% {{ transform: translate3d(28px,-34px,0) scale(1.06); }}
    }}

    a {{ color: inherit; text-decoration: none; }}

    .nav {{
      position: fixed;
      top: 0;
      left: 0;
      right: 0;
      z-index: 50;
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 18px min(5vw, 64px);
      background: linear-gradient(180deg, rgba(3,11,20,.80), rgba(3,11,20,.25), transparent);
      backdrop-filter: blur(12px);
    }}

    .brand {{
      display: flex;
      align-items: center;
      gap: 14px;
    }}

    .logo {{
      width: 46px;
      height: 46px;
      border-radius: 16px;
      background: linear-gradient(135deg, var(--cyan), var(--blue));
      box-shadow: 0 0 36px rgba(69,224,208,.28);
    }}

    .brand strong {{
      display: block;
      font-size: 18px;
      letter-spacing: .2px;
    }}

    .brand span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-top: 2px;
      letter-spacing: .6px;
      text-transform: uppercase;
    }}

    .nav-links {{
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}

    .nav-links a, .button {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.075);
      padding: 10px 14px;
      border-radius: 999px;
      color: var(--text);
      font-size: 14px;
      font-weight: 650;
      backdrop-filter: blur(14px);
      transition: transform .22s ease, background .22s ease, border-color .22s ease;
    }}

    .nav-links a:hover, .button:hover {{
      transform: translateY(-2px);
      background: rgba(255,255,255,.13);
      border-color: rgba(255,255,255,.28);
    }}

    .primary {{
      background: linear-gradient(135deg, var(--cyan), var(--blue));
      color: #03111f;
      border: none;
      box-shadow: 0 16px 48px rgba(69,224,208,.18);
    }}

    .hero {{
      min-height: 100vh;
      display: grid;
      align-items: center;
      padding: 120px min(5vw, 64px) 80px;
    }}

    .hero-inner {{
      max-width: 1220px;
      margin: 0 auto;
      width: 100%;
      display: grid;
      grid-template-columns: 1.32fr .88fr;
      gap: 32px;
      align-items: center;
    }}

    .hero-copy {{
      opacity: 0;
      transform: translateY(24px);
      animation: intro .9s ease forwards .15s;
    }}

    .kicker {{
      display: inline-flex;
      gap: 9px;
      align-items: center;
      color: var(--cyan);
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: 1.5px;
      font-weight: 800;
      margin-bottom: 20px;
    }}

    .kicker::before {{
      content: "";
      width: 10px;
      height: 10px;
      border-radius: 999px;
      background: var(--cyan);
      box-shadow: 0 0 20px var(--cyan);
    }}

    h1 {{
      font-size: clamp(44px, 7vw, 92px);
      line-height: .94;
      letter-spacing: -3px;
      margin: 0;
      max-width: 980px;
    }}

    .gradient-text {{
      background: linear-gradient(135deg, #ffffff, #aeeef0 42%, #9dbdff);
      -webkit-background-clip: text;
      background-clip: text;
      color: transparent;
    }}

    .subtitle {{
      margin: 26px 0 0;
      color: var(--muted);
      font-size: clamp(17px, 2vw, 21px);
      line-height: 1.75;
      max-width: 760px;
    }}

    .actions {{
      display: flex;
      gap: 12px;
      flex-wrap: wrap;
      margin-top: 34px;
    }}

    .hero-panel {{
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.10), rgba(255,255,255,.045));
      border-radius: 34px;
      padding: 26px;
      backdrop-filter: blur(18px);
      box-shadow: 0 28px 90px rgba(0,0,0,.28);
      opacity: 0;
      transform: translateY(24px) scale(.985);
      animation: intro .9s ease forwards .34s;
    }}

    @keyframes intro {{
      to {{ opacity: 1; transform: translateY(0) scale(1); }}
    }}

    .metric {{
      border: 1px solid var(--line);
      border-radius: 22px;
      background: rgba(0,0,0,.14);
      padding: 18px;
      margin-bottom: 14px;
      transition: transform .24s ease, background .24s ease;
    }}

    .metric:hover {{
      transform: translateY(-3px);
      background: rgba(255,255,255,.09);
    }}

    .metric .label {{
      color: var(--muted);
      text-transform: uppercase;
      font-size: 12px;
      letter-spacing: 1px;
      font-weight: 800;
    }}

    .metric .value {{
      margin-top: 8px;
      font-size: 34px;
      font-weight: 850;
    }}

    .scroll-cue {{
      position: absolute;
      left: 50%;
      bottom: 28px;
      transform: translateX(-50%);
      color: rgba(255,255,255,.68);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 2px;
      animation: pulse 1.7s ease-in-out infinite;
    }}

    .scroll-cue::after {{
      content: "";
      display: block;
      width: 1px;
      height: 46px;
      margin: 12px auto 0;
      background: linear-gradient(var(--cyan), transparent);
    }}

    @keyframes pulse {{
      0%,100% {{ opacity: .45; transform: translateX(-50%) translateY(0); }}
      50% {{ opacity: 1; transform: translateX(-50%) translateY(8px); }}
    }}

    section {{
      padding: 88px min(5vw, 64px);
    }}

    .section-inner {{
      max-width: 1220px;
      margin: 0 auto;
    }}

    .section-head {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 24px;
      margin-bottom: 28px;
    }}

    h2 {{
      font-size: clamp(30px, 4vw, 54px);
      line-height: 1;
      letter-spacing: -1.8px;
      margin: 0;
    }}

    .section-head p {{
      color: var(--muted);
      line-height: 1.7;
      max-width: 520px;
      margin: 0;
    }}

    .cards {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
    }}

    .info-card, .location-card, .note {{
      border: 1px solid var(--line);
      background: linear-gradient(180deg, rgba(255,255,255,.09), rgba(255,255,255,.045));
      backdrop-filter: blur(18px);
      border-radius: 26px;
      padding: 22px;
      box-shadow: 0 20px 70px rgba(0,0,0,.20);
    }}

    .info-card h3 {{
      margin: 0 0 10px;
      font-size: 18px;
    }}

    .info-card p, .muted, .note p {{
      color: var(--muted);
      line-height: 1.65;
      margin: 0;
    }}

    .big-number {{
      font-size: 44px;
      font-weight: 900;
      letter-spacing: -1px;
      margin: 10px 0;
    }}

    .locations {{
      display: grid;
      grid-template-columns: repeat(2, 1fr);
      gap: 14px;
    }}

    .location-card {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 18px;
    }}

    .location-card h3 {{
      font-size: 22px;
      margin: 0 0 6px;
    }}

    .eyebrow {{
      color: var(--cyan);
      text-transform: uppercase;
      font-size: 11px;
      letter-spacing: 1.3px;
      font-weight: 800;
      margin: 0 0 8px;
    }}

    .card-links {{
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
      min-width: 220px;
    }}

    .card-links a {{
      border: 1px solid rgba(69,224,208,.25);
      background: rgba(69,224,208,.10);
      color: #bafff8;
      padding: 9px 11px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 800;
      transition: transform .2s ease, background .2s ease;
    }}

    .card-links a:hover {{
      transform: translateY(-2px);
      background: rgba(69,224,208,.18);
    }}

    .download-grid {{
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 14px;
    }}

    .download-grid a {{
      border: 1px solid var(--line);
      background: rgba(255,255,255,.075);
      padding: 18px;
      border-radius: 22px;
      font-weight: 800;
      transition: transform .24s ease, background .24s ease;
    }}

    .download-grid a:hover {{
      transform: translateY(-3px);
      background: rgba(255,255,255,.13);
    }}

    .reveal {{
      opacity: 0;
      transform: translateY(28px);
      transition: opacity .72s ease, transform .72s ease;
    }}

    .reveal.visible {{
      opacity: 1;
      transform: translateY(0);
    }}

    footer {{
      padding: 42px min(5vw, 64px);
      color: var(--muted);
      border-top: 1px solid var(--line);
      background: rgba(0,0,0,.16);
    }}

    .footer-inner {{
      max-width: 1220px;
      margin: 0 auto;
      display: flex;
      justify-content: space-between;
      gap: 18px;
      flex-wrap: wrap;
    }}

    @media (max-width: 980px) {{
      .hero-inner {{ grid-template-columns: 1fr; }}
      .cards, .download-grid {{ grid-template-columns: repeat(2, 1fr); }}
      .locations {{ grid-template-columns: 1fr; }}
      .section-head {{ flex-direction: column; align-items: flex-start; }}
    }}

    @media (max-width: 620px) {{
      .nav {{
        position: absolute;
        align-items: flex-start;
        flex-direction: column;
      }}
      .nav-links {{ justify-content: flex-start; }}
      .cards, .download-grid {{ grid-template-columns: 1fr; }}
      .location-card {{ flex-direction: column; align-items: flex-start; }}
      .card-links {{ min-width: 0; justify-content: flex-start; }}
      h1 {{ letter-spacing: -1.5px; }}
    }}
  </style>
</head>
<body>
  <div class="noise"></div>
  <div class="orb one"></div>
  <div class="orb two"></div>
  <div class="orb three"></div>

  <nav class="nav">
    <a class="brand" href="#top">
      <div class="logo"></div>
      <div>
        <strong>Forecast Redelong</strong>
        <span>PLTA Redelong Forecast Portal</span>
      </div>
    </a>
    <div class="nav-links">
      <a href="#lokasi">Lokasi</a>
      <a href="{map_href}">Peta</a>
      <a href="{overview_href}">Overview</a>
      <a href="{plta_href}">Dashboard</a>
    </div>
  </nav>

  <header class="hero" id="top">
    <div class="hero-inner">
      <div class="hero-copy">
        <div class="kicker">Ensemble Rainfall Monitoring</div>
        <h1><span class="gradient-text">Sistem prakiraan hujan</span> untuk PLTA Redelong.</h1>
        <p class="subtitle">
          Portal web untuk memantau prakiraan hujan multi-source pada titik PLTA Redelong,
          GPM catchment, dan grid representatif di wilayah Redelong.
        </p>
        <div class="actions">
          <a class="button primary" href="{map_href}">Masuk ke Peta Portal</a>
          <a class="button" href="{plta_href}">Dashboard PLTA Redelong</a>
          <a class="button" href="#lokasi">Lihat Titik Catchment</a>
        </div>
      </div>

      <aside class="hero-panel">
        <div class="metric">
          <div class="label">Titik Catchment</div>
          <div class="value">{len(locations)}</div>
        </div>
        <div class="metric">
          <div class="label">Sumber Aktif</div>
          <div class="value">{n_sources}</div>
        </div>
        <div class="metric">
          <div class="label">Baris Forecast</div>
          <div class="value">{stats["rows"]}</div>
        </div>
        <div class="metric">
          <div class="label">Update Lokal</div>
          <div class="value" style="font-size:20px">{generated}</div>
        </div>
      </aside>
    </div>
    <a class="scroll-cue" href="#ringkasan">Scroll</a>
  </header>

  <section id="ringkasan">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Ringkasan sistem.</h2>
        <p>
          Dirancang untuk presentasi dan monitoring awal: cepat dibuka, berbasis web,
          dan memuat akses langsung ke peta, dashboard lokasi, serta data CSV.
        </p>
      </div>

      <div class="cards">
        <article class="info-card reveal">
          <p class="eyebrow">Rain Max</p>
          <div class="big-number">{stats["rain_max"]} mm</div>
          <p>Nilai maksimum dari kolom hujan yang terdeteksi pada output forecast gabungan.</p>
        </article>

        <article class="info-card reveal">
          <p class="eyebrow">Rain Mean</p>
          <div class="big-number">{stats["rain_mean"]} mm</div>
          <p>Rata-rata nilai hujan dari output forecast gabungan.</p>
        </article>

        <article class="info-card reveal">
          <p class="eyebrow">Kolom Hujan</p>
          <div class="big-number" style="font-size:22px">{escape(stats["rain_col"])}</div>
          <p>Kolom numerik yang dipakai untuk ringkasan hujan halaman ini.</p>
        </article>

        <article class="info-card reveal">
          <p class="eyebrow">Status</p>
          <div class="big-number" style="font-size:28px">Prototype</div>
          <p>Belum memakai BMKG ADM4 final. Validasi observasi aktual tetap diperlukan.</p>
        </article>
      </div>
    </div>
  </section>

  <section id="lokasi">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Titik forecast.</h2>
        <p>
          Setiap titik memiliki dashboard detail dan halaman prakiraan turunan.
          Gunakan PLTA Redelong sebagai titik utama, dan GPM sebagai representasi catchment.
        </p>
      </div>

      <div class="locations">
        {location_cards(locations)}
      </div>
    </div>
  </section>

  <section>
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Output data.</h2>
        <p>
          File berikut dapat digunakan untuk verifikasi, analisis lanjutan, atau bahan presentasi.
        </p>
      </div>

      <div class="download-grid reveal">
        <a href="forecast_all_locations.csv">Forecast CSV</a>
        <a href="ensemble_all_locations.csv">Ensemble CSV</a>
        <a href="source_status_all_locations.csv">Source Status</a>
        <a href="redelong_all_locations.geojson">GeoJSON Peta</a>
      </div>
    </div>
  </section>

  <section>
    <div class="section-inner">
      <div class="note reveal">
        <p class="eyebrow">Catatan metodologi</p>
        <h2>Untuk dukungan operasional awal, bukan keputusan kritikal tunggal.</h2>
        <p>
          Sistem ini menggabungkan output prakiraan multi-source dan titik catchment
          PLTA Redelong. Hasil forecast perlu dibandingkan dengan observasi aktual,
          terutama sebelum dipakai untuk keputusan operasi yang memiliki konsekuensi besar.
        </p>
      </div>
    </div>
  </section>

  <footer>
    <div class="footer-inner">
      <span>Forecast Redelong Forecast Portal</span>
      <span>Generated {generated}</span>
    </div>
  </footer>

  <script>
    const observer = new IntersectionObserver((entries) => {{
      entries.forEach((entry) => {{
        if (entry.isIntersecting) {{
          entry.target.classList.add('visible');
        }}
      }});
    }}, {{ threshold: 0.14 }});

    document.querySelectorAll('.reveal').forEach((el, i) => {{
      el.style.transitionDelay = `${{Math.min(i * 55, 320)}}ms`;
      observer.observe(el);
    }});

    window.addEventListener('mousemove', (e) => {{
      const x = e.clientX / window.innerWidth;
      const y = e.clientY / window.innerHeight;
      document.documentElement.style.setProperty('--mx', x);
      document.documentElement.style.setProperty('--my', y);
    }});
  </script>
</body>
</html>
"""

    (OUTPUTS / "index.html").write_text(html, encoding="utf-8")
    (OUTPUTS / ".nojekyll").write_text("", encoding="utf-8")

    print("SUCCESS")
    print(f"Cinematic index dibuat: {OUTPUTS / 'index.html'}")


if __name__ == "__main__":
    main()

