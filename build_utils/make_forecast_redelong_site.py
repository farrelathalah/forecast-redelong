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
QUANTITATIVE_SOURCES = {
    "CMA",
    "ECMWF",
    "GFS",
    "ICON",
    "METEOFRANCE",
    "UKMO",
}


def read_csv_auto(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    for sep in [",", ";"]:
        try:
            df = pd.read_csv(path, sep=sep)
            if len(df.columns) > 1:
                return df
        except Exception:
            pass
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def read_locations() -> dict:
    if not LOCATIONS_JSON.exists():
        return {}
    data = json.loads(LOCATIONS_JSON.read_text(encoding="utf-8"))
    return data.get("locations", {})


ROLE_LABELS = {
    "outlet_reference": "Titik referensi PLTA",
    "provisional_catchment": "Area catchment provisional",
    "external_comparison": "Pembanding eksternal",
}


def location_role(loc: dict) -> tuple[str, str, str]:
    role = str(loc.get("operational_role") or loc.get("area_level") or "forecast_point")
    label = ROLE_LABELS.get(role, "Titik forecast")
    note = str(loc.get("spatial_note") or "Titik prakiraan cuaca.")
    return role, label, note


def pick_location_col(df: pd.DataFrame, locations: dict) -> str | None:
    if df.empty:
        return None

    slugs = set(locations.keys())
    names = {str(v.get("location_name", "")).strip() for v in locations.values()}

    exact_candidates = [
        "location_slug", "slug", "location_id", "lokasi_id",
        "location", "location_name", "nama_lokasi", "lokasi", "name"
    ]

    for col in exact_candidates:
        if col in df.columns:
            return col

    best_col = None
    best_score = 0

    for col in df.columns:
        vals = set(df[col].dropna().astype(str).head(2000))
        score = len(vals & slugs) + len(vals & names)
        if score > best_score:
            best_score = score
            best_col = col

    return best_col


def pick_source_col(df: pd.DataFrame) -> str | None:
    for col in ["source_id", "source", "sumber", "model", "provider"]:
        if col in df.columns:
            return col
    for col in df.columns:
        lower = col.lower()
        if "source" in lower or "model" in lower or "sumber" in lower:
            return col
    return None


def pick_rain_col(df: pd.DataFrame) -> str | None:
    if df.empty:
        return None

    preferred = []
    fallback = []

    for col in df.columns:
        lower = col.lower()
        if any(k in lower for k in ["rain", "precip", "hujan"]):
            numeric = pd.to_numeric(df[col], errors="coerce")
            if not numeric.notna().any():
                continue

            if any(k in lower for k in ["prob", "chance", "peluang", "pct", "percent"]):
                fallback.append(col)
            else:
                preferred.append(col)

    return preferred[0] if preferred else (fallback[0] if fallback else None)


def pick_temp_col(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        lower = col.lower()
        if any(k in lower for k in ["temp", "suhu", "temperature"]):
            if pd.to_numeric(df[col], errors="coerce").notna().any():
                return col
    return None


def pick_wind_col(df: pd.DataFrame) -> str | None:
    for col in df.columns:
        lower = col.lower()
        if "wind" in lower or "angin" in lower:
            if pd.to_numeric(df[col], errors="coerce").notna().any():
                return col
    return None


def pick_time_cols(df: pd.DataFrame) -> list[str]:
    out = []
    exact = [
        "datetime", "time", "timestamp", "valid_time",
        "target_datetime", "target_date", "target_time",
        "date", "tanggal", "jam", "hour"
    ]

    for col in exact:
        if col in df.columns and col not in out:
            out.append(col)

    for col in df.columns:
        lower = col.lower()
        if any(k in lower for k in ["date", "time", "tanggal", "jam", "hour"]):
            if col not in out:
                out.append(col)

    return out[:3]


def fmt_num(v, digits=1) -> str:
    try:
        if pd.isna(v):
            return "-"
        return f"{float(v):.{digits}f}"
    except Exception:
        return "-"


def safe_text(v) -> str:
    if pd.isna(v):
        return "-"
    return escape(str(v))


def get_loc_df(df: pd.DataFrame, loc_col: str | None, slug: str, loc: dict) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame()

    if loc_col is None:
        return pd.DataFrame()

    name = str(loc.get("location_name", "")).strip()
    s = df[loc_col].astype(str)

    filtered = df[(s == slug) | (s == name)]

    if filtered.empty:
        filtered = df[s.str.lower() == slug.lower()]

    return filtered.copy()


def metrics_for(df: pd.DataFrame, rain_col: str | None, source_col: str | None) -> dict:
    out = {
        "rows": len(df),
        "sources": "-",
        "rain_max": "-",
        "rain_mean": "-",
        "rain_p90": "-",
    }

    numeric_df = df
    if source_col and source_col in df.columns:
        source_ids = df[source_col].astype(str).str.upper().str.strip()
        numeric_df = df[source_ids.isin(QUANTITATIVE_SOURCES)]
        out["sources"] = str(source_ids[source_ids.isin(QUANTITATIVE_SOURCES)].nunique())

    if rain_col and rain_col in numeric_df.columns and not numeric_df.empty:
        s = pd.to_numeric(numeric_df[rain_col], errors="coerce").dropna()
        if len(s):
            out["rain_max"] = fmt_num(s.max(), 1)
            out["rain_mean"] = fmt_num(s.mean(), 1)
            out["rain_p90"] = fmt_num(s.quantile(0.90), 1)

    return out


def make_bar_chart(df: pd.DataFrame, rain_col: str | None, time_cols: list[str]) -> str:
    if df.empty or rain_col is None or rain_col not in df.columns:
        return '<p class="muted">Data hujan belum tersedia untuk grafik.</p>'

    local = df.copy()
    local["_rain"] = pd.to_numeric(local[rain_col], errors="coerce")
    local = local.dropna(subset=["_rain"])

    if local.empty:
        return '<p class="muted">Data hujan belum tersedia untuk grafik.</p>'

    if time_cols:
        label_col = time_cols[-1]
        grouped = local.groupby(label_col, dropna=False)["_rain"].mean().reset_index()
        grouped = grouped.head(18)
        labels = grouped[label_col].astype(str).tolist()
        values = grouped["_rain"].tolist()
    else:
        values = local["_rain"].head(18).tolist()
        labels = [str(i + 1) for i in range(len(values))]

    max_v = max(values) if values else 1
    if max_v <= 0:
        max_v = 1

    bars = []
    for label, value in zip(labels, values):
        height = max(8, (value / max_v) * 150)
        bars.append(
            f"""
            <div class="bar-wrap">
              <div class="bar-value">{fmt_num(value, 1)}</div>
              <div class="bar" style="height:{height:.1f}px"></div>
              <div class="bar-label">{escape(str(label))}</div>
            </div>
            """
        )

    return f'<div class="bar-chart">{"".join(bars)}</div>'


def make_table(df: pd.DataFrame, selected_cols: list[str], max_rows: int = 30) -> str:
    if df.empty:
        return '<p class="muted">Data tabel belum tersedia.</p>'

    cols = [c for c in selected_cols if c in df.columns]
    if not cols:
        cols = list(df.columns[:8])

    rows = []
    for _, row in df[cols].head(max_rows).iterrows():
        cells = "".join(f"<td>{safe_text(row[c])}</td>" for c in cols)
        rows.append(f"<tr>{cells}</tr>")

    headers = "".join(f"<th>{escape(str(c))}</th>" for c in cols)

    return f"""
    <div class="table-wrap">
      <table>
        <thead><tr>{headers}</tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </div>
    """


def base_css() -> str:
    return """
    :root {
      --bg:#040c16; --panel:rgba(255,255,255,.08); --panel2:rgba(255,255,255,.13);
      --line:rgba(255,255,255,.16); --text:#eff8ff; --muted:#9fb4c9;
      --cyan:#45e0d0; --blue:#74a9ff; --gold:#ffd166; --red:#ff6b6b;
    }
    *{box-sizing:border-box}
    html{scroll-behavior:smooth}
    body{margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;color:var(--text);background:var(--bg);overflow-x:hidden}
    body:before{content:"";position:fixed;inset:0;z-index:-3;background:
      radial-gradient(circle at 12% 18%,rgba(69,224,208,.30),transparent 30%),
      radial-gradient(circle at 82% 18%,rgba(116,169,255,.24),transparent 32%),
      radial-gradient(circle at 50% 95%,rgba(255,209,102,.10),transparent 32%),
      linear-gradient(135deg,#04111e,#08253a 42%,#11183a)}
    .noise{position:fixed;inset:0;z-index:-2;opacity:.07;pointer-events:none;background-image:
      linear-gradient(rgba(255,255,255,.08) 1px,transparent 1px),
      linear-gradient(90deg,rgba(255,255,255,.08) 1px,transparent 1px);background-size:64px 64px}
    a{color:inherit;text-decoration:none}
    .nav{position:fixed;top:0;left:0;right:0;z-index:50;display:flex;align-items:center;justify-content:space-between;
      padding:18px min(5vw,64px);background:linear-gradient(180deg,rgba(3,11,20,.86),rgba(3,11,20,.28),transparent);backdrop-filter:blur(12px)}
    .brand{display:flex;align-items:center;gap:14px}.logo{width:46px;height:46px;border-radius:16px;background:linear-gradient(135deg,var(--cyan),var(--blue));box-shadow:0 0 36px rgba(69,224,208,.28)}
    .brand strong{display:block;font-size:18px;letter-spacing:.2px}.brand span{display:block;color:var(--muted);font-size:12px;margin-top:2px;letter-spacing:.8px;text-transform:uppercase}
    .nav-links{display:flex;gap:10px;flex-wrap:wrap;justify-content:flex-end}
    .nav-links a,.button{border:1px solid var(--line);background:rgba(255,255,255,.075);padding:10px 14px;border-radius:999px;color:var(--text);font-size:14px;font-weight:650;backdrop-filter:blur(14px);transition:.22s}
    .nav-links a:hover,.button:hover{transform:translateY(-2px);background:rgba(255,255,255,.13)}
    .primary{background:linear-gradient(135deg,var(--cyan),var(--blue));color:#03111f;border:none}
    .hero{min-height:100vh;display:grid;align-items:center;padding:120px min(5vw,64px) 80px}
    .hero-inner{max-width:1220px;margin:0 auto;width:100%;display:grid;grid-template-columns:1.32fr .88fr;gap:32px;align-items:center}
    .hero-copy{opacity:0;transform:translateY(24px);animation:intro .9s ease forwards .15s}
    .kicker{display:inline-flex;gap:9px;align-items:center;color:var(--cyan);text-transform:uppercase;font-size:12px;letter-spacing:1.5px;font-weight:800;margin-bottom:20px}
    .kicker:before{content:"";width:10px;height:10px;border-radius:999px;background:var(--cyan);box-shadow:0 0 20px var(--cyan)}
    h1{font-size:clamp(44px,7vw,92px);line-height:.94;letter-spacing:-3px;margin:0;max-width:980px}
    .gradient-text{background:linear-gradient(135deg,#fff,#aeeef0 42%,#9dbdff);-webkit-background-clip:text;background-clip:text;color:transparent}
    .subtitle{margin:26px 0 0;color:var(--muted);font-size:clamp(17px,2vw,21px);line-height:1.75;max-width:760px}
    .actions{display:flex;gap:12px;flex-wrap:wrap;margin-top:34px}
    .panel,.hero-panel,.info-card,.location-card,.note{border:1px solid var(--line);background:linear-gradient(180deg,rgba(255,255,255,.10),rgba(255,255,255,.045));border-radius:30px;backdrop-filter:blur(18px);box-shadow:0 28px 90px rgba(0,0,0,.24)}
    .hero-panel{padding:26px;opacity:0;transform:translateY(24px) scale(.985);animation:intro .9s ease forwards .34s}
    @keyframes intro{to{opacity:1;transform:translateY(0) scale(1)}}
    .metric{border:1px solid var(--line);border-radius:22px;background:rgba(0,0,0,.14);padding:18px;margin-bottom:14px;transition:.24s}
    .metric:hover{transform:translateY(-3px);background:rgba(255,255,255,.09)}
    .metric .label{color:var(--muted);text-transform:uppercase;font-size:12px;letter-spacing:1px;font-weight:800}.metric .value{margin-top:8px;font-size:34px;font-weight:850}
    .scroll-cue{position:absolute;left:50%;bottom:28px;transform:translateX(-50%);color:rgba(255,255,255,.68);text-transform:uppercase;font-size:11px;letter-spacing:2px;animation:pulse 1.7s ease-in-out infinite}
    .scroll-cue:after{content:"";display:block;width:1px;height:46px;margin:12px auto 0;background:linear-gradient(var(--cyan),transparent)}
    @keyframes pulse{0%,100%{opacity:.45;transform:translateX(-50%) translateY(0)}50%{opacity:1;transform:translateX(-50%) translateY(8px)}}
    section{padding:88px min(5vw,64px)}.section-inner{max-width:1220px;margin:0 auto}
    .section-head{display:flex;justify-content:space-between;align-items:end;gap:24px;margin-bottom:28px}.section-head p{color:var(--muted);line-height:1.7;max-width:520px;margin:0}
    h2{font-size:clamp(30px,4vw,54px);line-height:1;letter-spacing:-1.8px;margin:0}
    .cards{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.info-card,.note{padding:22px}.info-card h3{margin:0 0 10px;font-size:18px}
    .info-card p,.muted,.note p{color:var(--muted);line-height:1.65;margin:0}.big-number{font-size:44px;font-weight:900;letter-spacing:-1px;margin:10px 0}
    .locations{display:grid;grid-template-columns:repeat(2,1fr);gap:14px}.location-card{padding:22px;display:flex;align-items:center;justify-content:space-between;gap:18px}
    .location-card.external-comparison{border-color:rgba(255,209,102,.42);background:linear-gradient(180deg,rgba(255,209,102,.11),rgba(255,255,255,.045))}
    .location-card.external-comparison .eyebrow{color:var(--gold)}
    .location-card h3{font-size:22px;margin:0 0 6px}.eyebrow{color:var(--cyan);text-transform:uppercase;font-size:11px;letter-spacing:1.3px;font-weight:800;margin:0 0 8px}
    .card-links{display:flex;gap:8px;flex-wrap:wrap;justify-content:flex-end;min-width:220px}.card-links a{border:1px solid rgba(69,224,208,.25);background:rgba(69,224,208,.10);color:#bafff8;padding:9px 11px;border-radius:999px;font-size:12px;font-weight:800;transition:.2s}
    .card-links a:hover{transform:translateY(-2px);background:rgba(69,224,208,.18)}
    .download-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}.download-grid a{border:1px solid var(--line);background:rgba(255,255,255,.075);padding:18px;border-radius:22px;font-weight:800;transition:.24s}.download-grid a:hover{transform:translateY(-3px);background:rgba(255,255,255,.13)}
    .bar-chart{height:220px;display:flex;align-items:end;gap:10px;overflow-x:auto;padding:18px;border:1px solid var(--line);border-radius:24px;background:rgba(0,0,0,.14)}
    .bar-wrap{min-width:52px;text-align:center;display:flex;flex-direction:column;align-items:center;justify-content:end;height:185px}.bar{width:28px;border-radius:999px 999px 6px 6px;background:linear-gradient(180deg,var(--cyan),var(--blue));box-shadow:0 8px 24px rgba(69,224,208,.18)}
    .bar-value{font-size:11px;color:var(--text);margin-bottom:6px}.bar-label{font-size:10px;color:var(--muted);margin-top:8px;max-width:70px;overflow:hidden;text-overflow:ellipsis}
    .table-wrap{overflow:auto;border:1px solid var(--line);border-radius:22px;background:rgba(0,0,0,.12)}table{border-collapse:collapse;width:100%;font-size:13px}th,td{padding:11px 12px;border-bottom:1px solid rgba(255,255,255,.08);white-space:nowrap}th{text-align:left;color:#bafff8;background:rgba(255,255,255,.06)}
    .reveal{opacity:0;transform:translateY(28px);transition:opacity .72s ease,transform .72s ease}.reveal.visible{opacity:1;transform:translateY(0)}
    footer{padding:42px min(5vw,64px);color:var(--muted);border-top:1px solid var(--line);background:rgba(0,0,0,.16)}.footer-inner{max-width:1220px;margin:0 auto;display:flex;justify-content:space-between;gap:18px;flex-wrap:wrap}
    @media(max-width:980px){.hero-inner{grid-template-columns:1fr}.cards,.download-grid{grid-template-columns:repeat(2,1fr)}.locations{grid-template-columns:1fr}.section-head{flex-direction:column;align-items:flex-start}}
    @media(max-width:620px){.nav{position:absolute;align-items:flex-start;flex-direction:column}.nav-links{justify-content:flex-start}.cards,.download-grid{grid-template-columns:1fr}.location-card{flex-direction:column;align-items:flex-start}.card-links{min-width:0;justify-content:flex-start}h1{letter-spacing:-1.5px}}
    """


def reveal_script() -> str:
    return """
    <script>
      const observer = new IntersectionObserver((entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) entry.target.classList.add('visible');
        });
      }, { threshold: 0.14 });

      document.querySelectorAll('.reveal').forEach((el, i) => {
        el.style.transitionDelay = `${Math.min(i * 55, 320)}ms`;
        observer.observe(el);
      });
    </script>
    """


def brand_nav(active: str = "") -> str:
    return """
    <nav class="nav">
      <a class="brand" href="index.html">
        <div class="logo" aria-hidden="true" style="display:grid;place-items:center;color:#fff;font-weight:900;font-size:12px;letter-spacing:-.04em">FR</div>
        <div>
          <strong>Forecast Redelong</strong>
          <span>Monitoring Hujan PLTA Redelong</span>
        </div>
      </a>
      <div class="nav-links">
        <a href="index.html">Home</a>
        <a href="redelong_rain_map.html">Peta Hujan</a>
        <a href="redelong_overview.html">Overview</a>
        <a href="redelong_operational.html">Operasional DAS</a>
        <a href="plta_redelong/rain_dashboard.html">Dashboard PLTA</a>
      </div>
    </nav>
    """


def make_index(locations, all_df, loc_col, rain_col, source_col):
    stats = metrics_for(all_df, rain_col, source_col)
    generated = datetime.now(WIB).strftime("%Y-%m-%d %H:%M WIB")
    catchment_count = sum(bool(loc.get("include_in_catchment")) for loc in locations.values())

    cards = []
    for slug, loc in locations.items():
        folder = OUTPUTS / slug
        if not folder.exists():
            continue
        name = escape(str(loc.get("location_name", slug)))
        lat = escape(str(loc.get("latitude", "-")))
        lon = escape(str(loc.get("longitude", "-")))
        role, role_label, role_note = location_role(loc)
        card_class = " external-comparison" if role == "external_comparison" else ""
        cards.append(f"""
        <article class="location-card reveal{card_class}">
          <div>
            <p class="eyebrow">{escape(role_label)}</p>
            <h3>{name}</h3>
            <p class="muted">Lat {lat} · Lon {lon}</p>
            <p class="muted" style="margin-top:7px;font-size:12px">{escape(role_note)}</p>
          </div>
          <div class="card-links">
            <a href="{slug}/rain_dashboard.html">Dashboard Hujan</a>
            <a href="{slug}/redelong_app.html">Prakiraan Interaktif</a>
            <a href="{slug}/redelong_3day.html">Halaman 3 Hari</a>
          </div>
        </article>
        """)

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Forecast Redelong</title>
  <style>{base_css()}</style>
</head>
<body>
  <div class="noise"></div>
  {brand_nav()}

  <header class="hero" id="top">
    <div class="hero-inner">
      <div class="hero-copy">
        <div class="kicker">Prakiraan Hujan Multi-Model</div>
        <h1><span class="gradient-text">Forecast hujan</span> untuk PLTA Redelong.</h1>
        <p class="subtitle">
          Portal untuk melihat prakiraan di PLTA, area analisis provisional GPM1–GPM6,
          serta TamaTue sebagai pembanding eksternal.
        </p>
        <div class="actions">
          <a class="button primary" href="redelong_rain_map.html">Masuk ke Peta Hujan</a>
          <a class="button" href="plta_redelong/rain_dashboard.html">Dashboard PLTA Redelong</a>
          <a class="button" href="redelong_operational.html">Ringkasan Operasional DAS</a>
          <a class="button" href="#lokasi">Lihat Titik Catchment</a>
        </div>
      </div>

      <aside class="hero-panel">
        <div class="metric"><div class="label">Titik Forecast</div><div class="value">{len(locations)}</div></div>
        <div class="metric"><div class="label">Masuk Agregasi Catchment</div><div class="value">{catchment_count}</div></div>
        <div class="metric"><div class="label">Model Hujan Numerik</div><div class="value">{stats["sources"]}</div></div>
        <div class="metric"><div class="label">Update Lokal</div><div class="value" style="font-size:20px">{generated}</div></div>
      </aside>
    </div>
    <a class="scroll-cue" href="#ringkasan">Scroll</a>
  </header>

  <section id="ringkasan">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Cara membaca sistem.</h2>
        <p>Ringkasan angka hujan operasional tersedia pada halaman Operasional DAS. Halaman ini menjelaskan struktur dan batas penggunaannya.</p>
      </div>
      <div class="cards">
        <article class="info-card reveal"><p class="eyebrow">Horizon Operasi</p><div class="big-number">72 jam</div><p>Akumulasi 24, 48, dan 72 jam dihitung dari forecast per jam.</p></article>
        <article class="info-card reveal"><p class="eyebrow">Konsensus Numerik</p><div class="big-number">6 model</div><p>CMA, ECMWF, GFS, ICON, Météo-France, dan UKMO dengan bobot sama.</p></article>
        <article class="info-card reveal"><p class="eyebrow">Panduan Resmi</p><div class="big-number" style="font-size:28px">BMKG</div><p>Ditampilkan sebagai kategori cuaca dan tidak diubah menjadi rain_mm.</p></article>
        <article class="info-card reveal"><p class="eyebrow">Status Validasi</p><div class="big-number" style="font-size:28px">Berjalan</div><p>Belum ada klaim akurasi sebelum pasangan forecast dan observasi mencukupi.</p></article>
      </div>
    </div>
  </section>

  <section id="lokasi">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Peran titik forecast.</h2>
        <p>GPM1–GPM6 dipakai untuk agregasi area provisional. PLTA adalah titik referensi outlet, sedangkan TamaTue hanya pembanding eksternal.</p>
      </div>
      <div class="locations">
        {''.join(cards)}
      </div>
    </div>
  </section>

  <section>
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Output data.</h2>
        <p>File forecast, ensemble, status sumber, dan GeoJSON dapat diunduh untuk verifikasi atau presentasi.</p>
      </div>
      <div class="download-grid reveal">
        <a href="forecast_all_locations.csv">Forecast CSV</a>
        <a href="ensemble_all_locations.csv">Ensemble CSV</a>
        <a href="source_status_all_locations.csv">Source Status</a>
        <a href="redelong_all_locations.geojson">GeoJSON</a>
      </div>
    </div>
  </section>

  <footer><div class="footer-inner"><span>Forecast Redelong</span><span>FORECAST PLTA REDELONG · Generated {generated}</span></div></footer>
  {reveal_script()}
</body>
</html>
"""
    (OUTPUTS / "index.html").write_text(html, encoding="utf-8")


def make_location_dashboard(slug, loc, loc_df, rain_col, source_col, time_cols, temp_col, wind_col):
    folder = OUTPUTS / slug
    folder.mkdir(parents=True, exist_ok=True)

    name = str(loc.get("location_name", slug))
    stats = metrics_for(loc_df, rain_col, source_col)

    selected_cols = []
    selected_cols.extend(time_cols)
    if source_col:
        selected_cols.append(source_col)
    for col in [rain_col, temp_col, wind_col]:
        if col and col not in selected_cols:
            selected_cols.append(col)

    chart_df = loc_df
    if source_col and source_col in loc_df.columns:
        source_ids = loc_df[source_col].astype(str).str.upper().str.strip()
        chart_df = loc_df[source_ids.isin(QUANTITATIVE_SOURCES)]
    chart = make_bar_chart(chart_df, rain_col, time_cols)
    table = make_table(loc_df, selected_cols)

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(name)} · Forecast Redelong</title>
  <style>{base_css()}</style>
</head>
<body>
  <div class="noise"></div>
  <nav class="nav">
    <a class="brand" href="../index.html">
      <div class="logo" aria-hidden="true" style="display:grid;place-items:center;color:#fff;font-weight:900;font-size:12px;letter-spacing:-.04em">FR</div>
      <div>
        <strong>Forecast Redelong</strong>
        <span>{escape(name)}</span>
      </div>
    </a>
    <div class="nav-links">
      <a href="../index.html">Home</a>
      <a href="../redelong_rain_map.html">Peta Hujan</a>
      <a href="../redelong_overview.html">Overview</a>
      <a href="../redelong_operational.html">Operasional DAS</a>
    </div>
  </nav>

  <header class="hero">
    <div class="hero-inner">
      <div class="hero-copy">
        <div class="kicker">Dashboard Hujan</div>
        <h1><span class="gradient-text">{escape(name)}</span></h1>
        <p class="subtitle">Dashboard hujan khusus titik {escape(name)}, dibangun langsung dari data forecast CSV.</p>
        <div class="actions">
          <a class="button primary" href="../redelong_rain_map.html">Lihat Peta Hujan</a>
          <a class="button" href="redelong_app.html">Prakiraan Interaktif</a>
          <a class="button" href="redelong_3day.html">Prakiraan 3 Hari</a>
          <a class="button" href="../forecast_all_locations.csv">Download CSV</a>
        </div>
      </div>
      <aside class="hero-panel">
        <div class="metric"><div class="label">Hujan Jam Tertinggi</div><div class="value">{stats["rain_max"]} mm</div></div>
        <div class="metric"><div class="label">P90 Model-Jam</div><div class="value">{stats["rain_p90"]} mm</div></div>
        <div class="metric"><div class="label">Rata-rata Model-Jam</div><div class="value">{stats["rain_mean"]} mm</div></div>
        <div class="metric"><div class="label">Model Numerik</div><div class="value">{stats["sources"]}</div></div>
      </aside>
    </div>
    <a class="scroll-cue" href="#grafik">Scroll</a>
  </header>

  <section id="grafik">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Grafik hujan per jam.</h2>
        <p>Kartu dan grafik di halaman titik merangkum nilai model per jam, bukan akumulasi harian. Gunakan halaman Operasional DAS untuk akumulasi 24/48/72 jam.</p>
      </div>
      <div class="panel reveal" style="padding:22px">{chart}</div>
    </div>
  </section>

  <section>
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Tabel forecast.</h2>
        <p>Cuplikan data forecast mentah untuk audit cepat.</p>
      </div>
      <div class="reveal">{table}</div>
    </div>
  </section>

  <footer><div class="footer-inner"><span>Forecast Redelong</span><span>{escape(name)}</span></div></footer>
  {reveal_script()}
</body>
</html>
"""
    (folder / "rain_dashboard.html").write_text(html, encoding="utf-8")


def make_rain_map(locations, all_df, loc_col, rain_col, source_col):
    points = []
    for slug, loc in locations.items():
        loc_df = get_loc_df(all_df, loc_col, slug, loc)
        stats = metrics_for(loc_df, rain_col, source_col)
        try:
            lat = float(loc.get("latitude"))
            lon = float(loc.get("longitude"))
        except Exception:
            continue
        points.append({
            "slug": slug,
            "name": str(loc.get("location_name", slug)),
            "lat": lat,
            "lon": lon,
            "rain_max": stats["rain_max"],
            "rain_p90": stats["rain_p90"],
            "rain_mean": stats["rain_mean"],
            "rows": stats["rows"],
            "sources": stats["sources"],
            "role": location_role(loc)[0],
            "role_label": location_role(loc)[1],
            "role_note": location_role(loc)[2],
            "include_in_catchment": bool(loc.get("include_in_catchment")),
        })

    points_json = json.dumps(points, ensure_ascii=False)

    html = f"""<!doctype html>
<html lang="id">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Peta Hujan · Forecast Redelong</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
  <style>
    {base_css()}
    #map{{height:72vh;border:1px solid var(--line);border-radius:30px;overflow:hidden;box-shadow:0 28px 90px rgba(0,0,0,.28)}}
    .leaflet-popup-content-wrapper,.leaflet-popup-tip{{background:#071424;color:#eff8ff}}
    .legend{{display:flex;gap:10px;flex-wrap:wrap;margin-top:18px;color:var(--muted)}}
    .legend span{{display:inline-flex;align-items:center;gap:7px}}
    .dot{{width:12px;height:12px;border-radius:999px;display:inline-block}}
    .map-note{{margin-top:14px;padding:14px 16px;border:1px solid rgba(255,209,102,.30);background:rgba(255,209,102,.08);border-radius:16px;color:#ffe6a1;line-height:1.6}}
    .leaflet-control-layers{{background:#071424!important;color:#eff8ff!important;border:1px solid rgba(255,255,255,.18)!important;border-radius:14px!important}}
  </style>
</head>
<body>
  <div class="noise"></div>
  {brand_nav()}

  <section style="padding-top:130px">
    <div class="section-inner">
      <div class="section-head reveal">
        <h2>Peta hujan.</h2>
        <p>Peta awal difokuskan pada PLTA dan GPM1–GPM6. TamaTue dapat dinyalakan sebagai layer pembanding dan tidak masuk agregasi catchment.</p>
      </div>
      <div id="map" class="reveal"></div>
      <div class="legend reveal">
        <span><i class="dot" style="background:#45e0d0"></i>Rendah</span>
        <span><i class="dot" style="background:#ffd166"></i>Menengah</span>
        <span><i class="dot" style="background:#ff6b6b"></i>Tinggi</span>
      </div>
      <div class="map-note reveal"><strong>Catatan spasial:</strong> pilih layer <em>TamaTue · pembanding eksternal</em> pada kontrol peta jika ingin melihat titik tersebut. Nilainya tidak memengaruhi ringkasan hujan DAS.</div>
    </div>
  </section>

  <footer><div class="footer-inner"><span>Forecast Redelong</span><span>FORECAST PLTA REDELONG</span></div></footer>

  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const points = {points_json};

    const map = L.map('map', {{ scrollWheelZoom: true }});
    const center = points.length ? [points[0].lat, points[0].lon] : [4.748139, 96.977344];
    map.setView(center, 10);

    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      maxZoom: 18,
      attribution: '&copy; OpenStreetMap'
    }}).addTo(map);

    function asNumber(v) {{
      const n = Number(v);
      return Number.isFinite(n) ? n : 0;
    }}

    function color(r) {{
      if (r >= 30) return '#ff6b6b';
      if (r >= 10) return '#ffd166';
      return '#45e0d0';
    }}

    const primaryLayer = L.layerGroup().addTo(map);
    const comparisonLayer = L.layerGroup();
    const bounds = [];
    points.forEach(p => {{
      const r = asNumber(p.rain_p90);
      const isExternal = p.role === 'external_comparison';
      const marker = L.circleMarker([p.lat, p.lon], {{
        radius: Math.max(9, Math.min(24, 9 + r / 2)),
        color: isExternal ? '#ffd166' : color(r),
        weight: 2,
        fillColor: color(r),
        fillOpacity: 0.72,
        dashArray: isExternal ? '6 5' : null
      }}).addTo(isExternal ? comparisonLayer : primaryLayer);

      marker.bindPopup(`
        <strong>${{p.name}}</strong><br>
        Peran: ${{p.role_label}}<br>
        Agregasi catchment: ${{p.include_in_catchment ? 'Ya' : 'Tidak'}}<br>
        Hujan jam tertinggi: ${{p.rain_max}} mm<br>
        P90 model-jam: ${{p.rain_p90}} mm<br>
        Rata-rata model-jam: ${{p.rain_mean}} mm<br>
        Model numerik: ${{p.sources}}<br>
        <a href="${{p.slug}}/rain_dashboard.html">Buka dashboard hujan</a>
      `);

      if (!isExternal) bounds.push([p.lat, p.lon]);
    }});

    L.control.layers(null, {{
      'TamaTue · pembanding eksternal': comparisonLayer
    }}, {{collapsed:false, position:'topright'}}).addTo(map);

    if (bounds.length) {{
      map.fitBounds(bounds, {{ padding: [40, 40] }});
    }}
  </script>
  {reveal_script()}
</body>
</html>
"""
    (OUTPUTS / "redelong_rain_map.html").write_text(html, encoding="utf-8")


def make_overview(locations, all_df, loc_col, rain_col, source_col, time_cols):
    # Overview ringkas: salinan konsep index, tetapi lebih operasional.
    make_index(locations, all_df, loc_col, rain_col, source_col)
    text = (OUTPUTS / "index.html").read_text(encoding="utf-8")
    text = text.replace("<title>Forecast Redelong</title>", "<title>Overview · Forecast Redelong</title>")
    text = text.replace("Forecast hujan", "Overview forecast hujan")
    (OUTPUTS / "redelong_overview.html").write_text(text, encoding="utf-8")


def main():
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    locations = read_locations()
    all_df = read_csv_auto(OUTPUTS / "forecast_all_locations.csv")

    loc_col = pick_location_col(all_df, locations)
    rain_col = pick_rain_col(all_df)
    source_col = pick_source_col(all_df)
    temp_col = pick_temp_col(all_df)
    wind_col = pick_wind_col(all_df)
    time_cols = pick_time_cols(all_df)

    for slug, loc in locations.items():
        loc_df = get_loc_df(all_df, loc_col, slug, loc)
        make_location_dashboard(slug, loc, loc_df, rain_col, source_col, time_cols, temp_col, wind_col)

    make_rain_map(locations, all_df, loc_col, rain_col, source_col)
    make_overview(locations, all_df, loc_col, rain_col, source_col, time_cols)
    make_index(locations, all_df, loc_col, rain_col, source_col)

    (OUTPUTS / ".nojekyll").write_text("", encoding="utf-8")

    print("SUCCESS")
    print("Forecast Redelong site dibuat.")
    print(f"location column: {loc_col}")
    print(f"rain column: {rain_col}")
    print(f"source column: {source_col}")
    print(f"time columns: {time_cols}")
    print(f"locations: {len(locations)}")


if __name__ == "__main__":
    main()
