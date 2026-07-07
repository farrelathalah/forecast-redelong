from pathlib import Path

path = Path("outputs/index.html")

if not path.exists():
    raise FileNotFoundError("outputs/index.html tidak ditemukan.")

html = path.read_text(encoding="utf-8")

marker = "<!-- REDELONG_QUICK_ENTRY -->"

if marker not in html:
    injection = f"""
{marker}
<style>
  .redelong-entry-panel {{
    position: fixed;
    right: 28px;
    bottom: 28px;
    z-index: 99999;
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    max-width: min(560px, calc(100vw - 56px));
    padding: 14px;
    border-radius: 22px;
    background: rgba(5, 18, 32, 0.72);
    border: 1px solid rgba(255,255,255,0.16);
    backdrop-filter: blur(16px);
    box-shadow: 0 18px 60px rgba(0,0,0,0.28);
  }}
  .redelong-entry-panel a {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    padding: 11px 14px;
    border-radius: 999px;
    color: #eef7ff;
    text-decoration: none;
    font-family: Inter, Segoe UI, Arial, sans-serif;
    font-size: 13px;
    font-weight: 700;
    letter-spacing: .2px;
    border: 1px solid rgba(255,255,255,0.16);
    background: rgba(255,255,255,0.08);
  }}
  .redelong-entry-panel a.primary {{
    color: #04111e;
    border: none;
    background: linear-gradient(135deg, #38d5c8, #72a7ff);
  }}
  .redelong-entry-panel a:hover {{
    transform: translateY(-1px);
    filter: brightness(1.08);
  }}
  @media (max-width: 720px) {{
    .redelong-entry-panel {{
      left: 16px;
      right: 16px;
      bottom: 16px;
    }}
    .redelong-entry-panel a {{
      flex: 1 1 100%;
    }}
  }}
</style>
<div class="redelong-entry-panel">
  <a class="primary" href="redelong_overview.html">Overview Operasional</a>
  <a href="redelong_portal_map.html">Peta Portal</a>
  <a href="plta_redelong/redelong_app.html">Dashboard PLTA Redelong</a>
  <a href="forecast_all_locations.csv">Download CSV</a>
</div>
"""

    if "</body>" in html:
        html = html.replace("</body>", injection + "\n</body>")
    else:
        html += injection

path.write_text(html, encoding="utf-8")

print("SUCCESS")
print("Panel quick entry ditambahkan ke outputs/index.html")
