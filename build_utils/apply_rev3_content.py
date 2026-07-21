#!/usr/bin/env python3
"""Synchronize generated public pages with the final Rev.3 factual context."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
MARKER = "rev3-content-sync-v1"

PLN_OPERATION_URL = (
    "https://web.pln.co.id/cms/media/siaran-pers/2024/01/"
    "awali-2024-pln-operasikan-dua-unit-pltm-kapasitas-35-mw-di-lampung-"
    "langkah-kebut-bauran-energi/"
)
BMKG_REFERENCE_URL = (
    "https://staklim-yogya.bmkg.go.id/2024/02/06/"
    "analisis-curah-hujan-harian-6-februrari-2024/"
)

STYLE = """
<style id="rev3-content-style">
.rev3-panel{margin:18px 0;padding:20px;border:1px solid rgba(103,232,249,.22);border-radius:20px;background:rgba(5,22,39,.88);color:#effaff}
.rev3-panel h2{margin:0 0 12px;font-size:22px}.rev3-panel h3{margin:0 0 7px;font-size:14px}
.rev3-panel p,.rev3-panel li{font-size:10px;line-height:1.62;color:#a9bfd0}.rev3-panel a{color:#67e8f9}
.rev3-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
.rev3-card{padding:14px;border:1px solid rgba(255,255,255,.10);border-radius:15px;background:rgba(255,255,255,.035)}
.rev3-card ul{margin:7px 0 0;padding-left:18px}.rev3-badge{display:inline-flex;padding:5px 8px;border-radius:999px;background:rgba(52,211,153,.13);color:#6ee7b7;font-size:9px;font-weight:800;margin-bottom:8px}
.rev3-warning{border-left:3px solid #fbbf24;padding-left:11px}@media(max-width:720px){.rev3-grid{grid-template-columns:1fr}}
</style>
""".strip()

BMKG_TABLE = """
<ul>
  <li>Tidak hujan/tidak terukur: &lt;0,5 mm/hari</li>
  <li>Hujan ringan: 0,5–20 mm/hari</li>
  <li>Hujan sedang: &gt;20–50 mm/hari</li>
  <li>Hujan lebat: &gt;50–100 mm/hari</li>
  <li>Hujan sangat lebat: &gt;100 mm/hari</li>
</ul>
""".strip()

BESAI_PANEL = f"""
<section id="{MARKER}-besai" class="rev3-panel" data-rev3-content="true">
  <span class="rev3-badge">Status terverifikasi</span>
  <h2>Konteks aset, DAS, dan penggunaan forecast</h2>
  <div class="rev3-grid">
    <article class="rev3-card"><h3>Aset telah beroperasi</h3><p>PLTM Besai Kemu berkapasitas 2 × 3,5 MW telah beroperasi sejak 8 Januari 2024. Status operasional aset berbeda dari status model hidrologi yang masih berupa proxy. <a href="{PLN_OPERATION_URL}" rel="noopener noreferrer">Sumber: PLN</a>.</p></article>
    <article class="rev3-card"><h3>DAS teknis indikatif</h3><p>Geometri pada peta diikat ke koordinat outlet/bendung dan dikontrol terhadap luas 496,74 km² pada Review 2020. Geometri ini bukan batas legal, as-built, atau hasil delineasi DEM final yang telah disetujui Engineering.</p></article>
    <article class="rev3-card"><h3>Data debit yang tersedia</h3><p>Dokumen review memakai data operasi PLTA Besai 1 periode 2004–2014 dengan kekosongan 2010–2011; FS 2017 menyebut cakupan 2004–2016. Data tersebut menjadi baseline historis. Release upstream dan inflow aktual real-time tidak tersedia dalam feed otomatis, sehingga forecast debit tetap berlabel proxy.</p></article>
    <article class="rev3-card"><h3>Kategori hujan harian BMKG</h3>{BMKG_TABLE}<p class="rev3-warning">Kategori ini dipakai sebagai tingkat perhatian meteorologis, bukan SOP bukaan pintu, dispatch, atau penghentian unit. <a href="{BMKG_REFERENCE_URL}" rel="noopener noreferrer">Referensi BMKG</a>.</p></article>
  </div>
</section>
""".strip()

VALIDATION_PANEL = f"""
<section id="{MARKER}-validation" class="rev3-panel" data-rev3-content="true">
  <h2>Validasi lapangan kualitatif</h2>
  <p>Pengecekan manual hujan/tidak hujan telah dilakukan beberapa kali selama pelaksanaan magang dan kejadian hujan yang diprakirakan memang terkonfirmasi terjadi. Pemeriksaan tersebut bersifat kualitatif karena belum disertai log tanggal, jam, lokasi, dan jumlah hujan yang lengkap. Karena itu hasilnya ditampilkan sebagai bukti pengecekan lapangan, tetapi tidak dimasukkan ke persentase akurasi atau metrik jumlah hujan.</p>
  <p>Evaluasi numerik pada halaman ini tetap memakai pasangan forecast dan referensi gridded yang memiliki tanggal serta lokasi yang dapat diaudit.</p>
</section>
""".strip()

REDELONG_THRESHOLD_PANEL = f"""
<section id="{MARKER}-bmkg" class="rev3-panel" data-rev3-content="true">
  <h2>Kategori perhatian meteorologis</h2>
  <div class="rev3-grid">
    <article class="rev3-card"><h3>Ambang akumulasi harian BMKG</h3>{BMKG_TABLE}</article>
    <article class="rev3-card"><h3>Batas penggunaan</h3><p>Kategori digunakan untuk memudahkan pembacaan forecast hujan harian. Kategori bukan level operasi bendung dan tidak otomatis menentukan bukaan pintu, dispatch, atau penghentian unit. Tindakan operasional tetap mengikuti keputusan dan SOP perusahaan. <a href="{BMKG_REFERENCE_URL}" rel="noopener noreferrer">Referensi BMKG</a>.</p></article>
  </div>
</section>
""".strip()

DISCHARGE_PANEL = f"""
<section id="{MARKER}-discharge" class="rev3-panel" data-rev3-content="true">
  <h2>Dasar historis dan batas forecast debit</h2>
  <p>Baseline historis Besai Kemu mengacu pada data operasi PLTA Besai 1 yang dijelaskan dalam dokumen engineering, FDC, debit irigasi, dan debit ekologi. Deret mentah release upstream terbaru, AWLR, rating curve, dan inflow aktual tidak tersedia dalam feed otomatis. Karena itu keluaran H+1 sampai H+3 adalah skenario debit proxy, bukan debit intake operasional.</p>
</section>
""".strip()


def _insert_before(text: str, marker: str, payload: str) -> str:
    if payload in text or f'id="{MARKER}-' in text:
        return text
    if marker in text:
        return text.replace(marker, payload + "\n" + marker, 1)
    return text + "\n" + payload + "\n"


def _add_style(text: str) -> str:
    if 'id="rev3-content-style"' in text:
        return text
    return _insert_before(text, "</head>", STYLE)


def _patch_page(path: Path, panel: str, replacements: list[tuple[str, str]] | None = None) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    original = text
    for old, new in replacements or []:
        text = text.replace(old, new)
    text = _add_style(text)
    target = "</main>" if "</main>" in text else "</body>"
    text = _insert_before(text, target, panel)
    if text != original:
        path.write_text(text, encoding="utf-8")
    return True


def _patch_network(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    original = text
    text = text.replace(
        "Outline Besai Kemu adalah batas indikatif dari gambar FS, bukan vektor survei atau batas legal.",
        "Besai Kemu adalah aset operasional. Geometri DAS yang ditampilkan merupakan delineasi teknis indikatif yang dikontrol terhadap luas Review 2020, bukan batas legal atau as-built.",
    )
    text = text.replace("Referensi engineering", "Aset operasional, referensi engineering")
    if text != original:
        path.write_text(text, encoding="utf-8")
    return True


def _patch_map(path: Path) -> bool:
    if not path.exists():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    original = text
    text = text.replace(
        "Trace Gambar 2-26 FS, diikat ke koordinat bendung dan luas dokumen. Bukan vektor survei, batas legal, atau dasar final design.",
        "Delineasi teknis indikatif diikat ke koordinat outlet/bendung dan luas Review 2020 sebesar 496,74 km². Bukan batas legal, as-built, atau delineasi DEM final yang telah disetujui Engineering.",
    )
    if text != original:
        path.write_text(text, encoding="utf-8")
    return True


def _patch_evaluation_status(path: Path) -> bool:
    if not path.exists():
        return False
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["qualitative_field_checks"] = {
        "performed": True,
        "scope": "manual rain/no-rain confirmation on several occasions",
        "quantitative_metrics_eligible": False,
        "reason": "Tanggal, jam, lokasi, dan jumlah hujan belum diarsipkan secara lengkap; pemeriksaan tidak dimasukkan ke persentase akurasi.",
    }
    limitations = list(payload.get("limitations") or [])
    note = "Validasi lapangan kualitatif hujan/tidak hujan pernah dilakukan, tetapi belum memiliki log lengkap untuk metrik numerik."
    if note not in limitations:
        limitations.append(note)
    payload["limitations"] = limitations
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return True


def apply(outputs: Path) -> dict:
    outputs.mkdir(parents=True, exist_ok=True)
    patched: list[str] = []
    if _patch_page(
        outputs / "besai_kemu.html",
        BESAI_PANEL,
        replacements=[(
            "<b>Referensi engineering tersedia</b><br>Luas DAS 496,74 km² berasal dari review 2020. Batas pada peta adalah trace indikatif dari Gambar 2-26 yang diikat ke koordinat bendung dan luas FS, bukan vektor survei atau batas legal.",
            "<b>Aset operasional, referensi engineering tersedia</b><br>PLTM Besai Kemu beroperasi sejak 8 Januari 2024. Luas DAS 496,74 km² berasal dari Review 2020; geometri peta bersifat teknis indikatif dan belum merupakan batas legal/as-built.",
        )],
    ):
        patched.append("besai_kemu.html")
    if _patch_map(outputs / "besai_kemu_map.html"):
        patched.append("besai_kemu_map.html")
    if _patch_page(outputs / "besai_kemu_discharge.html", DISCHARGE_PANEL):
        patched.append("besai_kemu_discharge.html")
    if _patch_network(outputs / "site_network.html"):
        patched.append("site_network.html")
    for name in ("evaluation_summary.html", "validation_status.html"):
        if _patch_page(outputs / name, VALIDATION_PANEL):
            patched.append(name)
    if _patch_page(outputs / "redelong_operational.html", REDELONG_THRESHOLD_PANEL):
        patched.append("redelong_operational.html")
    if _patch_evaluation_status(outputs / "evaluation_status.json"):
        patched.append("evaluation_status.json")

    status = {
        "schema_version": MARKER,
        "status": "complete",
        "patched_files": sorted(set(patched)),
        "operational_asset": {
            "site": "PLTM Besai Kemu",
            "capacity_mw": 7.0,
            "commercial_operation_date": "2024-01-08",
            "source": PLN_OPERATION_URL,
        },
        "bmkg_daily_thresholds_mm": {
            "not_measurable": [0.0, 0.5],
            "light": [0.5, 20.0],
            "moderate": [20.0, 50.0],
            "heavy": [50.0, 100.0],
            "very_heavy": [100.0, None],
        },
        "qualitative_field_validation": {"performed": True, "included_in_numeric_accuracy": False},
        "catchment_status": "technical_indicative_area_constrained_not_legal_or_as_built",
    }
    (outputs / "rev3_sync.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    args = parser.parse_args()
    result = apply(args.outputs)
    print("SUCCESS:", len(result["patched_files"]), "generated files synchronized with Rev.3 context")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
