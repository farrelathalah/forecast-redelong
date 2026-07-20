#!/usr/bin/env python3
"""Apply the shared Forecast Site interaction layer to public HTML.

The forecast engine and the public-site builders intentionally remain separate.
This final build pass gives every retained page the same FR hover interaction
and a lightweight rain atmosphere without changing any forecast values.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path


EXPERIENCE_MARKER = "fr-global-experience-v1"
PUBLIC_BRAND = "Forecast Site"
LEGACY_PUBLIC_BRAND = "Forecast Redelong"
ANCHOR_RE = re.compile(r"<a\b(?P<attrs>[^>]*)>(?P<body>.*?)</a\s*>", re.I | re.S)
MONOGRAM_RE = re.compile(
    r"<(?P<tag>span|div|strong|b)\b(?P<attrs>[^>]*)>\s*FR\s*</(?P=tag)\s*>",
    re.I | re.S,
)

GLOBAL_HEAD = f"""
<meta name="fr-global-experience" content="{EXPERIENCE_MARKER}">
<style id="{EXPERIENCE_MARKER}">
  [data-fr-spin-target="true"] {{
    transform-origin:50% 50%;
    transition:transform .65s cubic-bezier(.2,.75,.2,1),box-shadow .2s ease!important;
    will-change:transform;
  }}
  [data-fr-global-brand="true"]:hover [data-fr-spin-target="true"],
  [data-fr-global-brand="true"]:focus-visible [data-fr-spin-target="true"],
  [data-fr-global-brand="true"][data-fr-spin-target="true"]:hover,
  [data-fr-global-brand="true"][data-fr-spin-target="true"]:focus-visible {{
    transform:rotate(360deg) scale(1.06)!important;
  }}
  #fr-global-rain {{
    position:fixed;inset:0;width:100%;height:100%;pointer-events:none;
    z-index:2147480000;opacity:.22;mix-blend-mode:screen;
  }}
  @media (prefers-reduced-motion:reduce), print {{
    [data-fr-spin-target="true"] {{transition:none!important}}
    [data-fr-global-brand="true"]:hover [data-fr-spin-target="true"],
    [data-fr-global-brand="true"]:focus-visible [data-fr-spin-target="true"],
    [data-fr-global-brand="true"][data-fr-spin-target="true"]:hover,
    [data-fr-global-brand="true"][data-fr-spin-target="true"]:focus-visible {{transform:none!important}}
    #fr-global-rain {{display:none!important}}
  }}
</style>
""".strip()

RAIN_CANVAS = '<canvas id="fr-global-rain" data-fr-rain-effect="true" aria-hidden="true"></canvas>'
RAIN_SCRIPT = r"""
<script id="fr-global-rain-script">
(() => {
  const canvas = document.getElementById('fr-global-rain');
  if (!canvas || window.matchMedia('(prefers-reduced-motion: reduce)').matches) return;
  const ctx = canvas.getContext('2d', { alpha: true });
  if (!ctx) return;
  let width = 0, height = 0, drops = [], raf = 0, last = 0;
  const count = () => Math.max(18, Math.min(58, Math.round(innerWidth / 24)));
  const makeDrop = (randomY = true) => ({
    x: Math.random() * width,
    y: randomY ? Math.random() * height : -30,
    length: 10 + Math.random() * 20,
    speed: 360 + Math.random() * 360,
    drift: -34 - Math.random() * 34,
    alpha: .20 + Math.random() * .34,
    line: .55 + Math.random() * .8
  });
  function resize() {
    const dpr = Math.min(devicePixelRatio || 1, 1.5);
    width = innerWidth; height = innerHeight;
    canvas.width = Math.round(width * dpr); canvas.height = Math.round(height * dpr);
    canvas.style.width = width + 'px'; canvas.style.height = height + 'px';
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    drops = Array.from({length: count()}, () => makeDrop(true));
  }
  function frame(now) {
    const dt = Math.min((now - (last || now)) / 1000, .04); last = now;
    ctx.clearRect(0, 0, width, height);
    ctx.lineCap = 'round';
    for (const drop of drops) {
      drop.x += drop.drift * dt; drop.y += drop.speed * dt;
      if (drop.y > height + 40 || drop.x < -40) Object.assign(drop, makeDrop(false), {x: Math.random() * (width + 80)});
      const gradient = ctx.createLinearGradient(drop.x, drop.y, drop.x + drop.drift * .08, drop.y + drop.length);
      gradient.addColorStop(0, 'rgba(186,230,253,0)');
      gradient.addColorStop(1, `rgba(125,211,252,${drop.alpha})`);
      ctx.strokeStyle = gradient; ctx.lineWidth = drop.line;
      ctx.beginPath(); ctx.moveTo(drop.x, drop.y); ctx.lineTo(drop.x + drop.drift * .08, drop.y + drop.length); ctx.stroke();
    }
    raf = requestAnimationFrame(frame);
  }
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { cancelAnimationFrame(raf); raf = 0; }
    else if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
  });
  addEventListener('resize', resize, {passive:true});
  resize(); raf = requestAnimationFrame(frame);
})();
</script>
""".strip()


def normalize_public_separators(content: str) -> tuple[str, int]:
    """Replace decorative middle dots with ordinary Indonesian punctuation.

    Several older builders used a middle dot as a visual separator.  With the
    display font used by the three-day page it looks like a large circle in the
    middle of a sentence.  The final public-build pass normalises both literal
    characters and their HTML entities so generated pages and JavaScript labels
    read naturally in every browser.
    """

    count = len(re.findall(r"[•·]|&(?:bull|middot);", content, flags=re.I))
    if not count:
        return content, 0
    content = re.sub(r"\s*(?:[•·]|&(?:bull|middot);)\s*", ", ", content, flags=re.I)
    return content, count


def normalize_public_brand(content: str) -> tuple[str, int]:
    """Use the portfolio brand while retaining internal file/API contracts."""

    count = content.count(LEGACY_PUBLIC_BRAND)
    if not count:
        return content, 0
    return content.replace(LEGACY_PUBLIC_BRAND, PUBLIC_BRAND), count


def _add_attr(attrs: str, name: str, value: str = "true") -> str:
    if re.search(rf"\b{re.escape(name)}\s*=", attrs, flags=re.I):
        return attrs
    return f'{attrs} {name}="{value}"'


def _visible_text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def _mark_monogram(fragment: str) -> tuple[str, bool]:
    marked = False

    def replace(match: re.Match[str]) -> str:
        nonlocal marked
        marked = True
        attrs = _add_attr(match.group("attrs"), "data-fr-spin-target")
        return f'<{match.group("tag")}{attrs}>FR</{match.group("tag")}>'

    return MONOGRAM_RE.sub(replace, fragment), marked


def mark_fr_anchors(content: str) -> tuple[str, int]:
    branded = 0

    def replace(match: re.Match[str]) -> str:
        nonlocal branded
        body = match.group("body")
        if not re.search(r"\bFR\b", _visible_text(body), flags=re.I):
            return match.group(0)
        branded += 1
        attrs = _add_attr(match.group("attrs"), "data-fr-global-brand")
        if not re.search(r"\baria-label\s*=", attrs, flags=re.I):
            attrs = _add_attr(attrs, "aria-label", f"Kembali ke {PUBLIC_BRAND}")
        body, nested_target = _mark_monogram(body)
        if not nested_target and _visible_text(body).upper() == "FR":
            attrs = _add_attr(attrs, "data-fr-spin-target")
        return f"<a{attrs}>{body}</a>"

    return ANCHOR_RE.sub(replace, content), branded


def apply_to_html(content: str) -> tuple[str, int, str]:
    content, _ = normalize_public_brand(content)
    content, _ = normalize_public_separators(content)
    if EXPERIENCE_MARKER in content:
        brands = len(re.findall(r'data-fr-global-brand=["\']true', content, re.I))
        native_rain = bool(
            re.search(r'id=["\'](?:atmo-canvas|particle-canvas)["\']', content, re.I)
        )
        rain_mode = "native+global" if native_rain else "global"
        if 'id="fr-global-rain"' not in content:
            content = re.sub(
                rf"{EXPERIENCE_MARKER}(?:;rain=[^\"']+)?",
                f"{EXPERIENCE_MARKER};rain={rain_mode}",
                content,
                count=1,
            )
            if re.search(r"</body\s*>", content, re.I):
                content = re.sub(
                    r"</body\s*>",
                    RAIN_CANVAS + "\n" + RAIN_SCRIPT + "\n</body>",
                    content,
                    count=1,
                    flags=re.I,
                )
            else:
                raise ValueError("tag </body> tidak ditemukan")
        return content, brands, rain_mode

    content, branded = mark_fr_anchors(content)
    if branded == 0:
        raise ValueError("halaman tidak memiliki tautan FR interaktif")

    content = re.sub(
        r"<html\b(?P<attrs>[^>]*)>",
        lambda match: (
            match.group(0)
            if re.search(r"\blang\s*=", match.group("attrs"), flags=re.I)
            else f'<html{match.group("attrs")} lang="id">'
        ),
        content,
        count=1,
        flags=re.I,
    )
    native_rain = bool(re.search(r'id=["\'](?:atmo-canvas|particle-canvas)["\']', content, re.I))
    rain_mode = "native+global" if native_rain else "global"
    head = GLOBAL_HEAD.replace(
        f'content="{EXPERIENCE_MARKER}"',
        f'content="{EXPERIENCE_MARKER};rain={rain_mode}"',
        1,
    )
    if not re.search(r"<meta\b[^>]*\bname=[\"']viewport[\"']", content, flags=re.I):
        head = '<meta name="viewport" content="width=device-width,initial-scale=1">\n' + head
    if re.search(r"</head\s*>", content, re.I):
        content = re.sub(r"</head\s*>", head + "\n</head>", content, count=1, flags=re.I)
    else:
        raise ValueError("tag </head> tidak ditemukan")

    if re.search(r"</body\s*>", content, re.I):
        content = re.sub(
            r"</body\s*>",
            RAIN_CANVAS + "\n" + RAIN_SCRIPT + "\n</body>",
            content,
            count=1,
            flags=re.I,
        )
    else:
        raise ValueError("tag </body> tidak ditemukan")
    return content, branded, rain_mode


def apply_all(outputs: Path) -> dict[str, int]:
    pages = sorted(path for path in outputs.rglob("*.html") if path.is_file())
    stats = {
        "pages": 0,
        "brands": 0,
        "native_rain": 0,
        "global_rain": 0,
        "separators_replaced": 0,
        "brands_renamed": 0,
    }
    for path in pages:
        original = path.read_text(encoding="utf-8", errors="replace")
        _, separator_count = normalize_public_separators(original)
        _, brand_count = normalize_public_brand(original)
        try:
            updated, brands, rain_mode = apply_to_html(original)
        except ValueError as exc:
            raise ValueError(f"{path}: {exc}") from exc
        path.write_text(updated, encoding="utf-8")
        stats["pages"] += 1
        stats["brands"] += brands
        stats["separators_replaced"] += separator_count
        stats["brands_renamed"] += brand_count
        if rain_mode in {"native+global", "global"}:
            stats["global_rain"] += 1
        if rain_mode == "native+global":
            stats["native_rain"] += 1
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    args = parser.parse_args()
    stats = apply_all(args.outputs)
    print("SUCCESS")
    print(
        "Global experience applied: "
        f"pages={stats['pages']} brands={stats['brands']} "
        f"native_rain={stats['native_rain']} global_rain={stats['global_rain']} "
        f"separators_replaced={stats['separators_replaced']}"
    )


if __name__ == "__main__":
    main()
