#!/usr/bin/env python3
"""Build a public multi-site catalog without overstating provisional data."""

from __future__ import annotations

import argparse
import html
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "config" / "sites.json"
OUTPUTS = ROOT / "outputs"
PAGE_MARKER = "forecast-hydro-multisite-network-v1"


def load_sites() -> dict:
    payload = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if not isinstance(payload.get("sites"), dict) or not payload["sites"]:
        raise ValueError("config/sites.json tidak memiliki site")
    return payload


def site_card(slug: str, site: dict) -> str:
    catchment = site["catchment"]
    verified = not site["site_status"].startswith("provisional")
    status_class = "ready" if verified else "provisional"
    status_text = "Data proyek tersedia" if verified else "Sumber publik provisional"
    area = catchment.get("area_km2")
    area_text = f"{float(area):,.2f} km²".replace(",", "X").replace(".", ",").replace("X", ".") if area is not None else "Menunggu delineasi"
    entry = site.get("public_entry")
    action = (
        f'<a class="open" href="{html.escape(entry)}">Buka site</a>'
        if entry
        else '<span class="pending">Forecast sedang diintegrasikan</span>'
    )
    return f"""
    <article class="site-card" data-site="{html.escape(slug)}">
      <div class="site-head"><span class="status {status_class}">{status_text}</span><small>{html.escape(site['plant_type'])}</small></div>
      <h2>{html.escape(site['display_name'])}</h2>
      <p>{html.escape(site['regency'])}, {html.escape(site['province'])}</p>
      <div class="facts"><span><b>{site.get('capacity_mw', 'N/A')}</b> MW</span><span><b>{area_text}</b> area</span></div>
      <p class="note">{html.escape(catchment['note'])}</p>
      {action}
    </article>"""


def page_html(payload: dict) -> str:
    sites = payload["sites"]
    public_sites = []
    for slug, site in sites.items():
        public_sites.append(
            {
                "slug": slug,
                "name": site["display_name"],
                "plant_type": site["plant_type"],
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "province": site["province"],
                "status": site["site_status"],
                "public_entry": site.get("public_entry"),
            }
        )
    cards = "".join(site_card(slug, site) for slug, site in sites.items())
    site_json = json.dumps(public_sites, ensure_ascii=False, separators=(",", ":"))
    return f'''<!doctype html>
<html lang="id"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="forecast-hydro-page" content="{PAGE_MARKER}"><title>Forecast Site, Globe Cuaca</title>
<link rel="stylesheet" href="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.css"><script src="https://unpkg.com/maplibre-gl@5.24.0/dist/maplibre-gl.js"></script>
<style>
:root{{--bg:#020817;--panel:rgba(3,15,30,.91);--line:rgba(125,211,252,.2);--text:#edfaff;--muted:#8ba7bc;--cyan:#22d3ee;--amber:#fbbf24;--green:#34d399}}*{{box-sizing:border-box}}html,body,#map{{width:100%;height:100%;margin:0}}body{{overflow:hidden;background:var(--bg);color:var(--text);font-family:Inter,Segoe UI,system-ui,sans-serif}}#map{{position:fixed;inset:0}}.top{{position:fixed;z-index:20;left:16px;right:16px;top:14px;display:flex;justify-content:space-between;pointer-events:none}}.brand,.home{{pointer-events:auto;background:rgba(2,10,22,.86);border:1px solid var(--line);backdrop-filter:blur(16px);color:inherit;text-decoration:none}}.brand{{display:flex;align-items:center;gap:10px;padding:7px 13px 7px 7px;border-radius:17px}}.mark{{width:38px;height:38px;border-radius:13px;display:grid;place-items:center;background:linear-gradient(135deg,#22d3ee,#8b5cf6 62%,#34d399);font-size:10px;font-weight:950}}.brand b{{display:block;font-size:13px}}.brand small{{display:block;color:var(--muted);font-size:8px;letter-spacing:.13em;text-transform:uppercase;margin-top:2px}}.home{{border-radius:13px;padding:11px 14px;font-size:11px;font-weight:800}}.panel{{position:fixed;z-index:18;top:82px;bottom:16px;left:16px;width:min(410px,calc(100vw - 32px));border:1px solid var(--line);border-radius:24px;background:var(--panel);backdrop-filter:blur(20px);overflow:auto;padding:20px;box-shadow:0 30px 90px rgba(0,0,0,.45)}}.eyebrow{{font-size:9px;font-weight:850;letter-spacing:.17em;text-transform:uppercase;color:#67e8f9}}h1{{font-size:29px;line-height:1.05;letter-spacing:-.04em;margin:9px 0}}.intro{{font-size:11px;line-height:1.6;color:var(--muted);margin:0 0 17px}}.sites{{display:grid;gap:10px}}.site-card{{border:1px solid var(--line);border-radius:18px;background:rgba(255,255,255,.035);padding:14px}}.site-head{{display:flex;align-items:center;justify-content:space-between;gap:8px}}.site-head small{{color:var(--muted);font-size:8px}}.status{{padding:5px 8px;border-radius:999px;font-size:8px;font-weight:850}}.status.ready{{background:rgba(52,211,153,.14);color:#6ee7b7}}.status.provisional{{background:rgba(251,191,36,.13);color:#fcd34d}}.site-card h2{{font-size:18px;margin:11px 0 3px}}.site-card>p{{color:var(--muted);font-size:10px;margin:0}}.facts{{display:flex;gap:7px;margin:12px 0}}.facts span{{flex:1;border:1px solid var(--line);border-radius:12px;padding:8px;color:var(--muted);font-size:8px}}.facts b{{display:block;color:var(--text);font-size:12px;margin-bottom:2px}}.site-card .note{{font-size:8px;line-height:1.5;color:#d7bd79}}.open,.pending{{display:inline-flex;margin-top:11px;font-size:9px;font-weight:850;padding:8px 10px;border-radius:10px}}.open{{background:rgba(34,211,238,.14);border:1px solid rgba(34,211,238,.32);color:#67e8f9;text-decoration:none}}.pending{{background:rgba(255,255,255,.045);color:var(--muted)}}.maplibregl-ctrl-top-right{{top:67px}}.maplibregl-popup-content{{background:#07192b!important;color:#eaf8ff!important;border:1px solid var(--line);border-radius:13px!important;font-size:10px}}@media(max-width:700px){{.panel{{top:auto;height:55vh}}.top{{left:9px;right:9px;top:8px}}.home{{display:none}}}}
</style></head><body><div id="map" aria-label="Globe cuaca Forecast Site"></div><div class="top"><a class="brand" href="index.html"><span class="mark">FR</span><span><b>Forecast Site</b><small>Cuaca dan hidrologi site</small></span></a><a class="home" href="index.html">Kembali ke portal</a></div>
<aside class="panel"><div class="eyebrow">Globe Forecast Site</div><h1>Seluruh site dalam satu globe.</h1><p class="intro">Redelong dan Besai Kemu ditampilkan sejak awal. Status data terverifikasi dan provisional tetap dibedakan.</p><div class="sites">{cards}</div></aside>
<script>const SITES={site_json};if(typeof maplibregl==='undefined')throw new Error('MapLibre unavailable');const map=new maplibregl.Map({{container:'map',center:[104,-1],zoom:2.7,style:{{version:8,projection:{{type:'globe'}},sources:{{satellite:{{type:'raster',tiles:['https://tiles.maps.eox.at/wmts/1.0.0/s2cloudless-2020_3857/default/g/{{z}}/{{y}}/{{x}}.jpg'],tileSize:256,attribution:'Cloudless imagery, EOX'}}}},layers:[{{id:'satellite',type:'raster',source:'satellite'}}],sky:{{'atmosphere-blend':['interpolate',['linear'],['zoom'],0,1,7,0]}}}}}});map.addControl(new maplibregl.NavigationControl({{visualizePitch:true}}),'top-right');map.on('load',()=>{{map.addSource('sites',{{type:'geojson',data:{{type:'FeatureCollection',features:SITES.map(s=>({{type:'Feature',properties:s,geometry:{{type:'Point',coordinates:[s.longitude,s.latitude]}}}}))}}}});map.addLayer({{id:'site-points',type:'circle',source:'sites',paint:{{'circle-radius':['interpolate',['linear'],['zoom'],2,5,8,10],'circle-color':['case',['==',['get','status'],'verified_from_project_package'],'#34d399','#fbbf24'],'circle-stroke-color':'#04111f','circle-stroke-width':3}}}});map.on('click','site-points',e=>{{if(!e.features)return;const f=e.features[0],p=f.properties;new maplibregl.Popup({{offset:12}}).setLngLat(f.geometry.coordinates).setHTML(`<b>${{p.name}}</b><br>${{p.plant_type}}, ${{p.province}}<br>${{p.status.includes('provisional')?'Data provisional':'Data proyek tersedia'}}`).addTo(map);}});map.on('mouseenter','site-points',()=>map.getCanvas().style.cursor='pointer');map.on('mouseleave','site-points',()=>map.getCanvas().style.cursor='');}});document.querySelectorAll('[data-site]').forEach(card=>card.addEventListener('mouseenter',()=>{{const site=SITES.find(s=>s.slug===card.dataset.site);map.flyTo({{center:[site.longitude,site.latitude],zoom:7,pitch:38,duration:1400}});}}));</script></body></html>'''


def patch_homepage(outputs: Path) -> None:
    path = outputs / "index.html"
    if not path.exists():
        return
    content = path.read_text(encoding="utf-8", errors="replace")
    if 'id="fr-globe-entry"' in content:
        content = re.sub(
            r'<style id="fr-sites-entry-style">.*?</style>\s*',
            "",
            content,
            flags=re.DOTALL,
        )
        content = re.sub(
            r'<a id="fr-sites-entry"[^>]*>.*?</a>\s*',
            "",
            content,
            flags=re.DOTALL,
        )
        path.write_text(content, encoding="utf-8")
        return
    if 'id="fr-sites-entry"' in content:
        return
    style = '<style id="fr-sites-entry-style">#fr-sites-entry{position:fixed;right:22px;bottom:86px;z-index:9200;padding:9px 13px;border:1px solid rgba(52,211,153,.36);border-radius:999px;background:rgba(2,15,30,.88);backdrop-filter:blur(16px);color:#a7f3d0;text-decoration:none;font:800 11px/1.2 Inter,system-ui,sans-serif}@media(max-width:620px){#fr-sites-entry{right:12px;bottom:76px}}</style>'
    link = '<a id="fr-sites-entry" href="site_network.html">Globe Forecast Site</a>'
    content = content.replace("</head>", style + "\n</head>", 1)
    content = content.replace("</body>", link + "\n</body>", 1)
    path.write_text(content, encoding="utf-8")


def build(outputs: Path) -> None:
    outputs.mkdir(parents=True, exist_ok=True)
    payload = load_sites()
    (outputs / "site_catalog.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (outputs / "site_network.html").write_text(page_html(payload), encoding="utf-8")
    patch_homepage(outputs)
    print(f"SUCCESS: {len(payload['sites'])} sites, {outputs / 'site_network.html'}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=OUTPUTS)
    args = parser.parse_args()
    build(args.outputs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
