from pathlib import Path

OUTPUTS = Path("outputs")

targets = [
    OUTPUTS / "index.html",
    OUTPUTS / "redelong_overview.html",
]

LINK = '<a href="evaluation_summary.html">Evaluasi Akurasi</a>'

for path in targets:
    if not path.exists():
        continue

    html = path.read_text(encoding="utf-8")

    if "evaluation_summary.html" in html:
        print("already linked:", path)
        continue

    if '<a href="redelong_overview.html">Overview</a>' in html:
        html = html.replace(
            '<a href="redelong_overview.html">Overview</a>',
            '<a href="redelong_overview.html">Overview</a>\n        ' + LINK
        )
    elif '<a href="plta_redelong/rain_dashboard.html">Dashboard PLTA</a>' in html:
        html = html.replace(
            '<a href="plta_redelong/rain_dashboard.html">Dashboard PLTA</a>',
            '<a href="plta_redelong/rain_dashboard.html">Dashboard PLTA</a>\n      ' + LINK
        )
    elif "</nav>" in html:
        html = html.replace("</nav>", LINK + "\n</nav>", 1)
    else:
        html += "\n" + LINK

    path.write_text(html, encoding="utf-8")
    print("linked:", path)

print("SUCCESS")
