from pathlib import Path
import re

path = Path("outputs/index.html")
html = path.read_text(encoding="utf-8")

html = re.sub(
    r"\s*<!-- REDELONG_QUICK_ENTRY -->.*?</div>\s*(?=</body>)",
    "\n",
    html,
    flags=re.S,
)

path.write_text(html, encoding="utf-8")
print("SUCCESS")
print("Quick-entry panel dihapus dari index.html")
