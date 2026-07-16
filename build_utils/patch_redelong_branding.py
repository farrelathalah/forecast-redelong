from pathlib import Path

ROOT = Path("outputs")

TEXT_REPLACEMENTS = {
    # Protect the JavaScript configuration identifier before replacing visible
    # brand text.  ``window.Forecast Redelong_CONFIG`` is invalid JavaScript.
    "window.Forecast Redelong_CONFIG": "window.REDELONG_CONFIG",
    "window.LANGIT_CONFIG": "window.REDELONG_CONFIG",
    "LANGIT v65.1": "Forecast Redelong v1.0",
    "LANGIT v65": "Forecast Redelong v1.0",
    "LANGIT Sentinel X": "Forecast Redelong Forecast Portal",
    "LANGIT Sentinel": "Forecast Redelong",
    "LANGIT Command Center": "Forecast Redelong Command Center",
    "LANGIT Portal": "Forecast Redelong Portal",
    "LANGIT": "Forecast Redelong",
    "Langit": "Forecast Redelong",
    "ANEMOS": "Forecast Redelong",
    "Anemos": "Forecast Redelong",
    "Sentinel X": "Forecast Decision Layer",
    "Sentinel": "Forecast",
    "Aether": "Ensemble Forecast Layer",
    "cinematic": "portal",
    "Cinematic": "Portal",
    "Dago, Bandung": "PLTA Redelong",
    "Dago": "PLTA Redelong",
    "Jatinangor, Sumedang": "GPM Catchment",
    "Jatinangor": "GPM Catchment",
    "Arjawinangun, Cirebon": "Redelong Catchment",
    "Arjawinangun": "Redelong Catchment",
    "Bandung": "Bener Meriah",
    "ITB": "PLTA Redelong",
    "Marcooo20-D": "farrelathalah",
    "weather-forecast": "forecast-redelong",
    "langit_portal_map.html": "redelong_portal_map.html",
    "langit": "redelong",
}

INVALID_JAVASCRIPT_TOKENS = {
    "window.Forecast Redelong_CONFIG",
    "window.LANGIT_CONFIG",
}

FILE_REPLACEMENTS = {
    "langit": "redelong",
    "aether": "ensemble",
    "sentinel": "Forecast",
    "cinematic": "portal",
}

TEXT_SUFFIXES = {".html", ".css", ".js", ".json", ".md", ".txt", ".csv"}

# These two HTML families are compatibility products from the forecast engine.
# The active public portal does not link to them and their content duplicates
# redelong_app.html / redelong_3day.html while retaining obsolete branding.
# Removing them here keeps the numerical engine untouched and prevents them
# from being copied to GitHub Pages.
LEGACY_PUBLIC_HTML_NAMES = {
    "Forecast_x_report.html",
    "command_center_Forecast_x.html",
    # Also clean stale files when this script is run against a reused output
    # directory instead of the workflow's normal clean build.
    "sentinel_x_report.html",
    "command_center_sentinel_x.html",
    # Superseded engine UI aliases.  The current portal links to
    # redelong_app.html, redelong_3day.html, redelong_activity.html, and
    # redelong_map_room.html instead.
    "anemos_app.html",
    "anemos_today.html",
    "anemos_3day.html",
    "anemos_activity.html",
    "anemos_commute_advice.html",
    "anemos_laundry_advice.html",
    "langit_model_court.html",
    "redelong_model_court.html",
    "langit_map.html",
    "redelong_map.html",
}

# The portal rebuild writes this compatibility filename with the current FR
# header.  It must win over an older already-renamed copy when outputs are
# reused locally or restored from another artifact.
CANONICAL_COMPATIBILITY_SOURCES = {"sentinel_x_accuracy_public.html"}

changed_text = 0
renamed_files = 0
removed_legacy_html = 0

for path in list(ROOT.rglob("*")):
    if not path.is_file():
        continue
    if path.suffix.lower() not in TEXT_SUFFIXES:
        continue

    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        continue

    new_text = text
    for old, new in TEXT_REPLACEMENTS.items():
        new_text = new_text.replace(old, new)

    if new_text != text:
        path.write_text(new_text, encoding="utf-8")
        changed_text += 1
        print(f"patched text: {path}")

    for token in INVALID_JAVASCRIPT_TOKENS:
        if token in new_text:
            raise RuntimeError(f"Invalid JavaScript token remains in {path}: {token}")

for path in sorted(list(ROOT.rglob("*")), key=lambda p: len(str(p)), reverse=True):
    if not path.is_file():
        continue

    new_name = path.name
    for old, new in FILE_REPLACEMENTS.items():
        new_name = new_name.replace(old, new)

    if new_name != path.name:
        target = path.with_name(new_name)
        # The portal rebuild writes fresh ``langit_*`` pages, while the forecast
        # engine may leave older ``redelong_*`` files behind.  The fresh portal
        # page is canonical and must replace the stale alias; otherwise links
        # such as redelong_3day.html keep opening the old/blank page.
        if "langit" in path.name or path.name in CANONICAL_COMPATIBILITY_SOURCES:
            path.replace(target)
            renamed_files += 1
            print(f"synced portal page: {path} -> {target}")
        elif not target.exists():
            path.rename(target)
            renamed_files += 1
            print(f"renamed file: {path} -> {target}")

for path in sorted(ROOT.rglob("*.html")):
    if path.name in LEGACY_PUBLIC_HTML_NAMES:
        path.unlink()
        removed_legacy_html += 1
        print(f"removed obsolete public HTML: {path}")

(ROOT / ".nojekyll").write_text("", encoding="utf-8")

print("SUCCESS")
print(f"Jumlah file teks diubah: {changed_text}")
print(f"Jumlah file diganti nama: {renamed_files}")
print(f"Jumlah halaman lama dihentikan: {removed_legacy_html}")
