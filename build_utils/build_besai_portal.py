#!/usr/bin/env python3
"""Build the first public Besai Kemu forecast and historical explorer."""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import shutil
from collections import defaultdict
from html import escape
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config/sites.json"
HISTORY = ROOT / "data/sites/pltm_besai_kemu/nasa_power_daily_1981_2025.csv.gz"
SITE_DATA = ROOT / "data/sites/pltm_besai_kemu"
ENGINEERING = SITE_DATA / "engineering_parameters.json"
STRUCTURES = SITE_DATA / "structures.geojson"
CATCHMENT = SITE_DATA / "besai_kemu_catchment.geojson"
SUMBERJAYA = SITE_DATA / "sumberjaya_monthly_rainfall_1979_2008.csv"
FDC = SITE_DATA / "fdc_review_2018.csv"
QUANTITATIVE_SOURCES = {"CMA", "ECMWF", "GFS", "ICON", "METEOFRANCE", "UKMO"}
PAGE_MARKER = "forecast-besai-kemu-history-v1"


def as_number(value: object) -> float | None:
    try:
        number = float(value)
        return number if number == number else None
    except (TypeError, ValueError):
        return None


def history_summary() -> dict:
    rows: list[dict] = []
    with gzip.open(HISTORY, "rt", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rain = as_number(row.get("rain_mm"))
            temperature = as_number(row.get("temperature_mean_c"))
            if rain is None:
                continue
            rows.append(
                {
                    "date": row["date"],
                    "year": int(row["date"][:4]),
                    "month": int(row["date"][5:7]),
                    "rain_mm": rain,
                    "temperature_c": temperature,
                }
            )

    annual: dict[int, list[dict]] = defaultdict(list)
    monthly: dict[int, list[dict]] = defaultdict(list)
    year_month: dict[tuple[int, int], list[dict]] = defaultdict(list)
    for row in rows:
        annual[row["year"]].append(row)
        monthly[row["month"]].append(row)
        year_month[(row["year"], row["month"])].append(row)

    annual_rows = []
    for year, group in sorted(annual.items()):
        temperatures = [row["temperature_c"] for row in group if row["temperature_c"] is not None]
        annual_rows.append(
            {
                "year": year,
                "rain_mm": round(sum(row["rain_mm"] for row in group), 1),
                "wet_days": sum(row["rain_mm"] >= 1.0 for row in group),
                "temperature_c": round(mean(temperatures), 1) if temperatures else None,
                "days": len(group),
            }
        )

    climatology = []
    for month in range(1, 13):
        totals = [
            sum(row["rain_mm"] for row in group)
            for (year, item_month), group in year_month.items()
            if item_month == month and len(group) >= 27
        ]
        temperatures = [
            row["temperature_c"]
            for row in monthly[month]
            if row["temperature_c"] is not None
        ]
        climatology.append(
            {
                "month": month,
                "rain_mm": round(mean(totals), 1) if totals else None,
                "temperature_c": round(mean(temperatures), 1) if temperatures else None,
            }
        )

    with SUMBERJAYA.open(encoding="utf-8", newline="") as handle:
        gauge = list(csv.DictReader(handle))
    gauge_annual = [
        {
            "year": int(row["year"]),
            "rain_mm": float(row["annual_mm"]),
            "reported_daily_max_mm": float(row["reported_daily_max_mm"]),
            "quality_flag": row["quality_flag"],
        }
        for row in gauge
    ]
    gauge_monthly = []
    month_columns = [
        "jan_mm", "feb_mm", "mar_mm", "apr_mm", "may_mm", "jun_mm",
        "jul_mm", "aug_mm", "sep_mm", "oct_mm", "nov_mm", "dec_mm",
    ]
    for month, column in enumerate(month_columns, start=1):
        gauge_monthly.append(
            {"month": month, "rain_mm": round(mean(float(row[column]) for row in gauge), 1)}
        )

    return {
        "source": "NASA POWER Daily",
        "observation_type": "gridded_meteorological_proxy",
        "period": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "daily_rows": len(rows),
        "annual": annual_rows,
        "monthly_climatology": climatology,
        "engineering_gauge_reference": {
            "station": "Sumberjaya",
            "observation_type": "historical_gauge_table_transcribed_from_engineering_document",
            "period": {"start": 1979, "end": 2008, "missing_years": [1999]},
            "annual": gauge_annual,
            "monthly_climatology": gauge_monthly,
            "zero_value_years_requiring_review": [2001, 2002, 2007],
            "source_document_page_pdf": 74,
        },
    }


def forecast_summary(outputs: Path) -> list[dict]:
    path = outputs / "forecast_all_locations.csv"
    if not path.exists():
        return []
    source_day: dict[tuple[str, str, str], list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source = str(row.get("source_id", "")).upper()
            location = str(row.get("location_slug", ""))
            if not location.startswith("pltm_besai_kemu") or source not in QUANTITATIVE_SOURCES:
                continue
            source_day[(location, row["target_date"], source)].append(row)

    model_points: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for (location, date, source), rows in source_day.items():
        rain = [as_number(row.get("rain_mm")) for row in rows]
        rain = [value for value in rain if value is not None]
        temperatures = [as_number(row.get("suhu_C")) for row in rows]
        temperatures = [value for value in temperatures if value is not None]
        wind = [as_number(row.get("wind_kmh")) for row in rows]
        wind = [value for value in wind if value is not None]
        if rain:
            model_points[(date, source)].append(
                {
                    "location": location,
                    "rain_mm": sum(rain),
                    "temperature_c": mean(temperatures) if temperatures else None,
                    "wind_kmh": max(wind) if wind else None,
                }
            )

    day_models: dict[str, list[dict]] = defaultdict(list)
    for (date, source), points in model_points.items():
        rain = [point["rain_mm"] for point in points]
        temperature = [point["temperature_c"] for point in points if point["temperature_c"] is not None]
        wind = [point["wind_kmh"] for point in points if point["wind_kmh"] is not None]
        day_models[date].append(
            {
                "source": source,
                "rain_mm": mean(rain),
                "temperature_c": mean(temperature) if temperature else None,
                "wind_kmh": max(wind) if wind else None,
                "point_count": len(points),
            }
        )

    summary = []
    for date, models in sorted(day_models.items()):
        rain = [model["rain_mm"] for model in models]
        temperature = [model["temperature_c"] for model in models if model["temperature_c"] is not None]
        wind = [model["wind_kmh"] for model in models if model["wind_kmh"] is not None]
        point_count = min(model.get("point_count", 1) for model in models)
        rain_mean = round(mean(rain), 1)
        summary.append(
            {
                "date": date,
                "rain_mean_mm": rain_mean,
                "rain_min_mm": round(min(rain), 1),
                "rain_max_mm": round(max(rain), 1),
                "temperature_mean_c": round(mean(temperature), 1) if temperature else None,
                "wind_max_kmh": round(max(wind), 1) if wind else None,
                "model_count": len(models),
                "point_count": point_count,
                "gross_volume_m3": round(rain_mean * 496.74 * 1000),
                "sources": [model["source"] for model in models],
                "status": "indikatif cukup" if len(models) >= 3 and point_count >= 3 else "terbatas",
            }
        )
    return summary


def forecast_cards(forecast: list[dict]) -> str:
    if not forecast:
        return '<p class="empty">Forecast Besai Kemu belum ada pada build ini. Histori tetap dapat dijelajahi.</p>'
    cards = []
    for row in forecast[:4]:
        cards.append(
            f'''<article class="forecast-card"><div class="date">{escape(row['date'])}</div>
            <strong>{row['rain_mean_mm']:.1f}<small> mm</small></strong>
            <p>Rentang model {row['rain_min_mm']:.1f} sampai {row['rain_max_mm']:.1f} mm</p>
            <p>Volume bruto indikatif {row['gross_volume_m3'] / 1_000_000:.2f} juta m³</p>
            <div class="chips"><span>{row['model_count']} model</span><span>{row['point_count']} titik</span><span>{row['status']}</span></div></article>'''
        )
    return "".join(cards)


def page(site: dict, history: dict, forecast: list[dict]) -> str:
    complete = [row for row in history["annual"] if row["days"] >= 365]
    normal = mean(row["rain_mm"] for row in complete)
    wet = mean(row["wet_days"] for row in complete)
    gauge = history["engineering_gauge_reference"]
    engineering = json.loads(ENGINEERING.read_text(encoding="utf-8"))
    chart = json.dumps(
        {"annual": history["annual"], "monthly": history["monthly_climatology"], "gauge": gauge["annual"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cards = forecast_cards(forecast)
    return f'''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="forecast-hydro-page" content="{PAGE_MARKER}"><title>Forecast Besai Kemu</title><style>
:root{{--bg:#020817;--panel:#071426;--line:rgba(125,211,252,.18);--text:#effaff;--muted:#8ea9bd;--cyan:#22d3ee;--green:#34d399;--amber:#fbbf24}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#0b3152 0,transparent 33%),var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}}a{{color:inherit}}.nav{{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 max(20px,calc((100vw - 1180px)/2));border-bottom:1px solid var(--line);background:rgba(2,8,23,.82);backdrop-filter:blur(18px);position:sticky;top:0;z-index:20}}.brand{{display:flex;align-items:center;gap:11px;text-decoration:none}}.mark{{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#22d3ee,#8b5cf6 60%,#34d399);font-weight:950;font-size:11px}}.brand b{{display:block}}.brand small{{color:var(--muted);font-size:9px;letter-spacing:.12em;text-transform:uppercase}}.network{{text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:9px 12px;font-size:10px;font-weight:800}}main{{max-width:1180px;margin:auto;padding:54px 20px 80px}}.hero{{display:grid;grid-template-columns:1.35fr .65fr;gap:22px;align-items:end;margin-bottom:34px}}.eyebrow{{color:#67e8f9;font-size:10px;letter-spacing:.18em;text-transform:uppercase;font-weight:850}}h1{{font-size:clamp(46px,7vw,88px);letter-spacing:-.065em;line-height:.92;margin:14px 0}}.lead{{color:var(--muted);line-height:1.65;max-width:720px}}.status{{border:1px solid rgba(251,191,36,.3);background:rgba(251,191,36,.08);border-radius:20px;padding:18px;color:#f9d783;font-size:11px;line-height:1.6}}.section-head{{display:flex;justify-content:space-between;align-items:end;margin:36px 0 14px}}h2{{font-size:25px;letter-spacing:-.03em;margin:0}}.section-head p{{margin:0;color:var(--muted);font-size:10px}}.forecast-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.forecast-card,.metric,.chart-card{{border:1px solid var(--line);background:rgba(7,20,38,.86);border-radius:20px}}.forecast-card{{padding:17px}}.forecast-card .date{{color:var(--muted);font-size:10px}}.forecast-card strong{{font-size:34px;display:block;margin:12px 0 3px}}.forecast-card strong small{{font-size:12px;color:#67e8f9}}.forecast-card p{{color:var(--muted);font-size:9px;line-height:1.5}}.chips{{display:flex;gap:6px}}.chips span{{background:rgba(34,211,238,.1);color:#67e8f9;border-radius:999px;padding:5px 7px;font-size:8px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.metric{{padding:18px}}.metric span{{font-size:9px;color:var(--muted)}}.metric b{{display:block;font-size:25px;margin-top:8px}}.charts{{display:grid;grid-template-columns:1.35fr .65fr;gap:10px;margin-top:10px}}.chart-card{{padding:18px;min-height:320px}}.chart-card h3{{margin:0 0 5px;font-size:15px}}.chart-card p{{color:var(--muted);font-size:9px;margin:0 0 15px}}canvas{{display:block;width:100%;height:235px}}.months{{height:235px;display:flex;align-items:end;gap:5px;padding-top:15px}}.month{{height:100%;flex:1;display:flex;align-items:end;position:relative}}.bar{{width:100%;min-height:2px;border-radius:5px 5px 2px 2px;background:linear-gradient(#22d3ee,#2563eb)}}.month label{{position:absolute;bottom:-18px;width:100%;text-align:center;font-size:7px;color:var(--muted)}}.source-note{{margin-top:12px;border-left:3px solid var(--amber);padding:11px 14px;color:#d8c28e;background:rgba(251,191,36,.06);font-size:9px;line-height:1.6}}.empty{{grid-column:1/-1;border:1px solid var(--line);border-radius:18px;padding:18px;color:var(--muted)}}@media(max-width:800px){{.hero,.charts{{grid-template-columns:1fr}}.forecast-grid,.metrics{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:480px){{.forecast-grid,.metrics{{grid-template-columns:1fr}}h1{{font-size:48px}}}}
</style></head><body><nav class="nav"><a class="brand" data-fr-brand="true" href="index.html"><span class="mark">FR</span><span><b>Forecast Besai Kemu</b><small>Forecast Hydro Network</small></span></a><div><a class="network" href="besai_kemu_map.html">Peta struktur</a> <a class="network" href="besai_kemu_discharge.html">Forecast debit</a> <a class="network" href="site_network.html">Globe semua site</a></div></nav><main>
<section class="hero"><div><div class="eyebrow">PLTM run-of-river, Way Kanan</div><h1>Besai Kemu</h1><p class="lead">Prakiraan multi-model pada bendung, headpond, powerhouse, dan Stasiun Sumberjaya, dipadukan dengan histori gridded serta data engineering proyek.</p></div><div class="status"><b>Referensi engineering tersedia</b><br>Luas DAS 496,74 km² berasal dari review 2020. Batas pada peta adalah trace indikatif dari Gambar 2-26 yang diikat ke koordinat bendung dan luas FS, bukan vektor survei atau batas legal.</div></section>
<div class="section-head"><div><div class="eyebrow">Forecast</div><h2>Empat hari ke depan</h2></div><p>Rata-rata setara antar-model kuantitatif</p></div><section class="forecast-grid">{cards}</section>
<div class="section-head"><div><div class="eyebrow">Engineering reference</div><h2>Parameter PLTM dan DAS</h2></div><p>Review Januari 2020</p></div><section class="metrics"><div class="metric"><span>Luas DAS dokumen</span><b>{engineering['catchment']['area_km2']:.2f} km²</b></div><div class="metric"><span>Debit desain</span><b>{engineering['hydrology']['adopted_design_discharge_m3s']:.1f} m³/s</b></div><div class="metric"><span>Net head</span><b>{engineering['hydrology']['net_head_m']:.2f} m</b></div><div class="metric"><span>Data hujan Sumberjaya</span><b>{len(gauge['annual'])} tahun</b></div></section>
<div class="section-head"><div><div class="eyebrow">Historical explorer</div><h2>Jejak cuaca 1981 sampai 2025</h2></div><p>NASA POWER Daily, proxy gridded</p></div><section class="metrics"><div class="metric"><span>Hari tersedia</span><b>{history['daily_rows']:,}</b></div><div class="metric"><span>Tahun lengkap</span><b>{len(complete)}</b></div><div class="metric"><span>Hujan tahunan normal</span><b>{normal:,.0f} mm</b></div><div class="metric"><span>Hari hujan normal</span><b>{wet:,.0f}</b></div></section>
<section class="charts"><article class="chart-card"><h3>Hujan tahunan</h3><p>Arahkan kursor untuk membaca tahun dan total hujan.</p><canvas id="annual" width="760" height="235" aria-label="Grafik hujan tahunan"></canvas></article><article class="chart-card"><h3>Pola hujan bulanan</h3><p>Rata-rata total bulanan sepanjang periode.</p><div class="months" id="months"></div></article></section>
<div class="source-note">NASA POWER bukan observasi alat di PLTM. Tabel Stasiun Sumberjaya 1979–2008 adalah transkripsi dokumen engineering; tahun 1999 tidak tersedia dan nilai nol pada 2001, 2002, serta 2007 ditandai untuk peninjauan. Forecast memakai empat titik. Batas DAS yang ditampilkan hanya untuk orientasi dan tidak menggantikan delineasi GIS engineering.</div>
<div class="downloads" style="margin-top:14px"><a class="network" href="besai_kemu_sumberjaya_monthly.csv">Data Sumberjaya CSV</a> <a class="network" href="besai_kemu_fdc_2018.csv">FDC CSV</a> <a class="network" href="besai_kemu_structures.geojson">Struktur GeoJSON</a> <a class="network" href="besai_kemu_history_daily.csv">NASA POWER harian CSV</a></div>
</main><script>const DATA={chart};const names=['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];const monthly=DATA.monthly;const maxM=Math.max(...monthly.map(x=>x.rain_mm||0));document.getElementById('months').innerHTML=monthly.map((x,i)=>`<div class="month" title="${{names[i]}}: ${{x.rain_mm}} mm"><div class="bar" style="height:${{Math.max(2,(x.rain_mm/maxM)*100)}}%"></div><label>${{names[i]}}</label></div>`).join('');const canvas=document.getElementById('annual'),ctx=canvas.getContext('2d'),rows=DATA.annual,maxA=Math.max(...rows.map(x=>x.rain_mm));function draw(){{const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle='rgba(125,211,252,.14)';for(let i=0;i<5;i++){{const y=15+i*(h-35)/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}}ctx.beginPath();rows.forEach((x,i)=>{{const px=i*(w/(rows.length-1)),py=h-20-(x.rain_mm/maxA)*(h-40);i?ctx.lineTo(px,py):ctx.moveTo(px,py)}});ctx.strokeStyle='#22d3ee';ctx.lineWidth=2.5;ctx.stroke();ctx.lineTo(w,h-20);ctx.lineTo(0,h-20);ctx.closePath();const g=ctx.createLinearGradient(0,0,0,h);g.addColorStop(0,'rgba(34,211,238,.32)');g.addColorStop(1,'rgba(34,211,238,0)');ctx.fillStyle=g;ctx.fill()}}draw();canvas.addEventListener('mousemove',e=>{{const r=canvas.getBoundingClientRect(),i=Math.max(0,Math.min(rows.length-1,Math.round((e.clientX-r.left)/r.width*(rows.length-1))));canvas.title=`${{rows[i].year}}: ${{rows[i].rain_mm}} mm, ${{rows[i].wet_days}} hari hujan`;}});</script></body></html>'''


def map_page(structures: dict, catchment: dict) -> str:
    points = [feature for feature in structures["features"] if feature.get("geometry")]
    payload = json.dumps({"type": "FeatureCollection", "features": points}, ensure_ascii=False, separators=(",", ":"))
    catchment_payload = json.dumps(catchment, ensure_ascii=False, separators=(",", ":"))
    return f'''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="forecast-hydro-page" content="forecast-besai-structure-map-v1"><title>Peta Besai Kemu</title><link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css"><script src="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"></script><style>html,body,#map{{height:100%;margin:0}}body{{background:#03111d;font-family:Inter,Segoe UI,sans-serif}}#map{{position:fixed;inset:0}}.brand{{position:fixed;z-index:20;left:14px;top:14px;display:flex;align-items:center;gap:9px;padding:7px 12px 7px 7px;border:1px solid rgba(103,232,249,.3);border-radius:16px;background:rgba(3,17,29,.88);color:#effcff;text-decoration:none;backdrop-filter:blur(14px)}}.mark{{width:38px;height:38px;display:grid;place-items:center;border-radius:13px;background:linear-gradient(135deg,#22d3ee,#8b5cf6,#34d399);font-size:10px;font-weight:950}}.brand b,.brand small{{display:block}}.brand small{{color:#9bb6c8;font-size:8px;margin-top:2px}}.legend{{position:fixed;z-index:19;left:14px;bottom:14px;max-width:360px;padding:12px;border:1px solid rgba(103,232,249,.22);border-radius:14px;background:rgba(3,17,29,.9);color:#dff8ff;font-size:10px;line-height:1.55}}.maplibregl-popup-content{{background:#082234!important;color:#effcff!important;border-radius:12px!important}}</style></head><body><div id="map"></div><a class="brand" data-fr-brand="true" href="besai_kemu.html"><span class="mark">FR</span><span><b>Besai Kemu</b><small>Kembali ke dashboard</small></span></a><div class="legend"><b>Batas DAS indikatif, 496,74 km².</b><br>Trace Gambar 2-26 FS, diikat ke koordinat bendung dan luas dokumen. Bukan vektor survei, batas legal, atau dasar final design.</div><script>const DATA={payload};const CATCHMENT={catchment_payload};const map=new maplibregl.Map({{container:'map',center:[104.4,-4.97],zoom:9,style:{{version:8,sources:{{osm:{{type:'raster',tiles:['https://tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'© OpenStreetMap contributors'}}}},layers:[{{id:'osm',type:'raster',source:'osm'}}]}}}});map.addControl(new maplibregl.NavigationControl(),'top-right');map.on('load',()=>{{map.addSource('catchment',{{type:'geojson',data:CATCHMENT}});map.addLayer({{id:'catchment-fill',type:'fill',source:'catchment',paint:{{'fill-color':'#fbbf24','fill-opacity':0.15}}}});map.addLayer({{id:'catchment-outline',type:'line',source:'catchment',paint:{{'line-color':'#f59e0b','line-width':2.5,'line-dasharray':[3,2]}}}});map.addSource('structures',{{type:'geojson',data:DATA}});map.addLayer({{id:'structures',type:'circle',source:'structures',paint:{{'circle-radius':8,'circle-color':['case',['==',['get','role'],'historical_rain_gauge'],'#fbbf24','#22d3ee'],'circle-stroke-color':'#03111d','circle-stroke-width':3}}}});map.on('click','structures',e=>{{const f=e.features[0],p=f.properties;new maplibregl.Popup({{offset:12}}).setLngLat(f.geometry.coordinates).setHTML(`<b>${{p.name}}</b><br>${{p.role}}<br>${{p.status}}`).addTo(map)}})}});</script></body></html>'''


def build(outputs: Path) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    site = registry["sites"]["pltm_besai_kemu"]
    history = history_summary()
    forecast = forecast_summary(outputs)
    structures = json.loads(STRUCTURES.read_text(encoding="utf-8"))
    catchment = json.loads(CATCHMENT.read_text(encoding="utf-8"))
    (outputs / "besai_kemu_history.json").write_text(
        json.dumps(history, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (outputs / "besai_kemu_forecast.json").write_text(
        json.dumps(forecast, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    with gzip.open(HISTORY, "rb") as source, (
        outputs / "besai_kemu_history_daily.csv"
    ).open("wb") as destination:
        shutil.copyfileobj(source, destination)
    shutil.copy2(SUMBERJAYA, outputs / "besai_kemu_sumberjaya_monthly.csv")
    shutil.copy2(FDC, outputs / "besai_kemu_fdc_2018.csv")
    shutil.copy2(STRUCTURES, outputs / "besai_kemu_structures.geojson")
    shutil.copy2(CATCHMENT, outputs / "besai_kemu_catchment.geojson")
    shutil.copy2(ENGINEERING, outputs / "besai_kemu_engineering_parameters.json")
    (outputs / "besai_kemu.html").write_text(
        page(site, history, forecast), encoding="utf-8"
    )
    (outputs / "besai_kemu_map.html").write_text(map_page(structures, catchment), encoding="utf-8")
    print(
        f"SUCCESS: Besai Kemu history={history['daily_rows']} days, "
        f"forecast={len(forecast)} days"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=ROOT / "outputs")
    args = parser.parse_args()
    build(args.outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
