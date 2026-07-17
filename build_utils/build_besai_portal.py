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

    return {
        "source": "NASA POWER Daily",
        "observation_type": "gridded_meteorological_proxy",
        "period": {"start": rows[0]["date"], "end": rows[-1]["date"]},
        "daily_rows": len(rows),
        "annual": annual_rows,
        "monthly_climatology": climatology,
    }


def forecast_summary(outputs: Path) -> list[dict]:
    path = outputs / "forecast_all_locations.csv"
    if not path.exists():
        return []
    source_day: dict[tuple[str, str], list[dict]] = defaultdict(list)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            source = str(row.get("source_id", "")).upper()
            if row.get("location_slug") != "pltm_besai_kemu" or source not in QUANTITATIVE_SOURCES:
                continue
            source_day[(row["target_date"], source)].append(row)

    day_models: dict[str, list[dict]] = defaultdict(list)
    for (date, source), rows in source_day.items():
        rain = [as_number(row.get("rain_mm")) for row in rows]
        rain = [value for value in rain if value is not None]
        temperatures = [as_number(row.get("suhu_C")) for row in rows]
        temperatures = [value for value in temperatures if value is not None]
        wind = [as_number(row.get("wind_kmh")) for row in rows]
        wind = [value for value in wind if value is not None]
        if rain:
            day_models[date].append(
                {
                    "source": source,
                    "rain_mm": sum(rain),
                    "temperature_c": mean(temperatures) if temperatures else None,
                    "wind_kmh": max(wind) if wind else None,
                }
            )

    summary = []
    for date, models in sorted(day_models.items()):
        rain = [model["rain_mm"] for model in models]
        temperature = [model["temperature_c"] for model in models if model["temperature_c"] is not None]
        wind = [model["wind_kmh"] for model in models if model["wind_kmh"] is not None]
        summary.append(
            {
                "date": date,
                "rain_mean_mm": round(mean(rain), 1),
                "rain_min_mm": round(min(rain), 1),
                "rain_max_mm": round(max(rain), 1),
                "temperature_mean_c": round(mean(temperature), 1) if temperature else None,
                "wind_max_kmh": round(max(wind), 1) if wind else None,
                "model_count": len(models),
                "sources": [model["source"] for model in models],
                "status": "cukup" if len(models) >= 3 else "terbatas",
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
            <div class="chips"><span>{row['model_count']} model</span><span>{row['status']}</span></div></article>'''
        )
    return "".join(cards)


def page(site: dict, history: dict, forecast: list[dict]) -> str:
    complete = [row for row in history["annual"] if row["days"] >= 365]
    normal = mean(row["rain_mm"] for row in complete)
    wet = mean(row["wet_days"] for row in complete)
    chart = json.dumps(
        {"annual": history["annual"], "monthly": history["monthly_climatology"]},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    cards = forecast_cards(forecast)
    return f'''<!doctype html><html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="forecast-hydro-page" content="{PAGE_MARKER}"><title>Forecast Besai Kemu</title><style>
:root{{--bg:#020817;--panel:#071426;--line:rgba(125,211,252,.18);--text:#effaff;--muted:#8ea9bd;--cyan:#22d3ee;--green:#34d399;--amber:#fbbf24}}*{{box-sizing:border-box}}body{{margin:0;background:radial-gradient(circle at 80% 0,#0b3152 0,transparent 33%),var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}}a{{color:inherit}}.nav{{height:72px;display:flex;align-items:center;justify-content:space-between;padding:0 max(20px,calc((100vw - 1180px)/2));border-bottom:1px solid var(--line);background:rgba(2,8,23,.82);backdrop-filter:blur(18px);position:sticky;top:0;z-index:20}}.brand{{display:flex;align-items:center;gap:11px;text-decoration:none}}.mark{{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:linear-gradient(135deg,#22d3ee,#8b5cf6 60%,#34d399);font-weight:950;font-size:11px}}.brand b{{display:block}}.brand small{{color:var(--muted);font-size:9px;letter-spacing:.12em;text-transform:uppercase}}.network{{text-decoration:none;border:1px solid var(--line);border-radius:999px;padding:9px 12px;font-size:10px;font-weight:800}}main{{max-width:1180px;margin:auto;padding:54px 20px 80px}}.hero{{display:grid;grid-template-columns:1.35fr .65fr;gap:22px;align-items:end;margin-bottom:34px}}.eyebrow{{color:#67e8f9;font-size:10px;letter-spacing:.18em;text-transform:uppercase;font-weight:850}}h1{{font-size:clamp(46px,7vw,88px);letter-spacing:-.065em;line-height:.92;margin:14px 0}}.lead{{color:var(--muted);line-height:1.65;max-width:720px}}.status{{border:1px solid rgba(251,191,36,.3);background:rgba(251,191,36,.08);border-radius:20px;padding:18px;color:#f9d783;font-size:11px;line-height:1.6}}.section-head{{display:flex;justify-content:space-between;align-items:end;margin:36px 0 14px}}h2{{font-size:25px;letter-spacing:-.03em;margin:0}}.section-head p{{margin:0;color:var(--muted);font-size:10px}}.forecast-grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.forecast-card,.metric,.chart-card{{border:1px solid var(--line);background:rgba(7,20,38,.86);border-radius:20px}}.forecast-card{{padding:17px}}.forecast-card .date{{color:var(--muted);font-size:10px}}.forecast-card strong{{font-size:34px;display:block;margin:12px 0 3px}}.forecast-card strong small{{font-size:12px;color:#67e8f9}}.forecast-card p{{color:var(--muted);font-size:9px;line-height:1.5}}.chips{{display:flex;gap:6px}}.chips span{{background:rgba(34,211,238,.1);color:#67e8f9;border-radius:999px;padding:5px 7px;font-size:8px}}.metrics{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}.metric{{padding:18px}}.metric span{{font-size:9px;color:var(--muted)}}.metric b{{display:block;font-size:25px;margin-top:8px}}.charts{{display:grid;grid-template-columns:1.35fr .65fr;gap:10px;margin-top:10px}}.chart-card{{padding:18px;min-height:320px}}.chart-card h3{{margin:0 0 5px;font-size:15px}}.chart-card p{{color:var(--muted);font-size:9px;margin:0 0 15px}}canvas{{display:block;width:100%;height:235px}}.months{{height:235px;display:flex;align-items:end;gap:5px;padding-top:15px}}.month{{height:100%;flex:1;display:flex;align-items:end;position:relative}}.bar{{width:100%;min-height:2px;border-radius:5px 5px 2px 2px;background:linear-gradient(#22d3ee,#2563eb)}}.month label{{position:absolute;bottom:-18px;width:100%;text-align:center;font-size:7px;color:var(--muted)}}.source-note{{margin-top:12px;border-left:3px solid var(--amber);padding:11px 14px;color:#d8c28e;background:rgba(251,191,36,.06);font-size:9px;line-height:1.6}}.empty{{grid-column:1/-1;border:1px solid var(--line);border-radius:18px;padding:18px;color:var(--muted)}}@media(max-width:800px){{.hero,.charts{{grid-template-columns:1fr}}.forecast-grid,.metrics{{grid-template-columns:repeat(2,1fr)}}}}@media(max-width:480px){{.forecast-grid,.metrics{{grid-template-columns:1fr}}h1{{font-size:48px}}}}
</style></head><body><nav class="nav"><a class="brand" data-fr-brand="true" href="index.html"><span class="mark">FR</span><span><b>Forecast Besai Kemu</b><small>Forecast Hydro Network</small></span></a><a class="network" href="site_network.html">Globe semua site</a></nav><main>
<section class="hero"><div><div class="eyebrow">PLTM run-of-river, Way Kanan</div><h1>Besai Kemu</h1><p class="lead">Prakiraan multi-model dan histori cuaca gridded pada titik referensi publik. Sistem ini siap diperluas ke batas DAS setelah intake atau weir dikonfirmasi oleh tim engineering.</p></div><div class="status"><b>Status provisional</b><br>Koordinat dan ADM4 berasal dari sumber publik. Jangan gunakan halaman ini untuk menghitung volume hujan atau debit sebelum batas DAS diverifikasi.</div></section>
<div class="section-head"><div><div class="eyebrow">Forecast</div><h2>Empat hari ke depan</h2></div><p>Rata-rata setara antar-model kuantitatif</p></div><section class="forecast-grid">{cards}</section>
<div class="section-head"><div><div class="eyebrow">Historical explorer</div><h2>Jejak cuaca 1981 sampai 2025</h2></div><p>NASA POWER Daily, proxy gridded</p></div><section class="metrics"><div class="metric"><span>Hari tersedia</span><b>{history['daily_rows']:,}</b></div><div class="metric"><span>Tahun lengkap</span><b>{len(complete)}</b></div><div class="metric"><span>Hujan tahunan normal</span><b>{normal:,.0f} mm</b></div><div class="metric"><span>Hari hujan normal</span><b>{wet:,.0f}</b></div></section>
<section class="charts"><article class="chart-card"><h3>Hujan tahunan</h3><p>Arahkan kursor untuk membaca tahun dan total hujan.</p><canvas id="annual" width="760" height="235" aria-label="Grafik hujan tahunan"></canvas></article><article class="chart-card"><h3>Pola hujan bulanan</h3><p>Rata-rata total bulanan sepanjang periode.</p><div class="months" id="months"></div></article></section>
<div class="source-note">Histori ini bukan observasi alat di PLTM. NASA POWER adalah referensi meteorologi gridded pada koordinat provisional {site['latitude']}, {site['longitude']}. Forecast dan histori akan tetap dipisahkan dari klaim debit sampai delineasi DAS disetujui.</div>
</main><script>const DATA={chart};const names=['Jan','Feb','Mar','Apr','Mei','Jun','Jul','Agu','Sep','Okt','Nov','Des'];const monthly=DATA.monthly;const maxM=Math.max(...monthly.map(x=>x.rain_mm||0));document.getElementById('months').innerHTML=monthly.map((x,i)=>`<div class="month" title="${{names[i]}}: ${{x.rain_mm}} mm"><div class="bar" style="height:${{Math.max(2,(x.rain_mm/maxM)*100)}}%"></div><label>${{names[i]}}</label></div>`).join('');const canvas=document.getElementById('annual'),ctx=canvas.getContext('2d'),rows=DATA.annual,maxA=Math.max(...rows.map(x=>x.rain_mm));function draw(){{const w=canvas.width,h=canvas.height;ctx.clearRect(0,0,w,h);ctx.strokeStyle='rgba(125,211,252,.14)';for(let i=0;i<5;i++){{const y=15+i*(h-35)/4;ctx.beginPath();ctx.moveTo(0,y);ctx.lineTo(w,y);ctx.stroke()}}ctx.beginPath();rows.forEach((x,i)=>{{const px=i*(w/(rows.length-1)),py=h-20-(x.rain_mm/maxA)*(h-40);i?ctx.lineTo(px,py):ctx.moveTo(px,py)}});ctx.strokeStyle='#22d3ee';ctx.lineWidth=2.5;ctx.stroke();ctx.lineTo(w,h-20);ctx.lineTo(0,h-20);ctx.closePath();const g=ctx.createLinearGradient(0,0,0,h);g.addColorStop(0,'rgba(34,211,238,.32)');g.addColorStop(1,'rgba(34,211,238,0)');ctx.fillStyle=g;ctx.fill()}}draw();canvas.addEventListener('mousemove',e=>{{const r=canvas.getBoundingClientRect(),i=Math.max(0,Math.min(rows.length-1,Math.round((e.clientX-r.left)/r.width*(rows.length-1))));canvas.title=`${{rows[i].year}}: ${{rows[i].rain_mm}} mm, ${{rows[i].wet_days}} hari hujan`;}});</script></body></html>'''


def build(outputs: Path) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    site = registry["sites"]["pltm_besai_kemu"]
    history = history_summary()
    forecast = forecast_summary(outputs)
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
    (outputs / "besai_kemu.html").write_text(
        page(site, history, forecast), encoding="utf-8"
    )
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
