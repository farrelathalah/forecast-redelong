from pathlib import Path
import re

path = Path("build_utils/evaluate_forecast_accuracy.py")
text = path.read_text(encoding="utf-8")

original = text

if "PROXY_OBS_PATH" not in text:
    text = text.replace(
        'OBS_PATH = ROOT / "data" / "redelong" / "observations" / "rain_observed_daily.csv"',
        'OBS_PATH = ROOT / "data" / "redelong" / "observations" / "rain_observed_daily.csv"\nPROXY_OBS_PATH = ROOT / "data" / "redelong" / "observations" / "rain_proxy_daily.csv"'
    )

if 'obs_mode = "field_observation"' not in text:
    pattern = r'^(\s*)obs\s*=\s*read_csv\(OBS_PATH\)\s*$'

    def repl(match):
        indent = match.group(1)
        return (
            f'{indent}obs = read_csv(OBS_PATH)\n'
            f'{indent}obs_mode = "field_observation"\n\n'
            f'{indent}if obs.empty or "rain_mm_observed" not in obs.columns or not pd.to_numeric(obs.get("rain_mm_observed"), errors="coerce").notna().any():\n'
            f'{indent}    obs = read_csv(PROXY_OBS_PATH)\n'
            f'{indent}    obs_mode = "proxy_observation"'
        )

    text, n = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if n == 0:
        raise SystemExit("ERROR: Tidak menemukan baris obs = read_csv(OBS_PATH). Kirim output Select-String OBS_PATH ke ChatGPT.")

text = text.replace(
    'write_page(joined, metrics, generated)',
    'write_page(joined, metrics, generated, obs_mode)'
)

text = text.replace(
    'def write_page(joined: pd.DataFrame, metrics: pd.DataFrame, generated: str) -> None:',
    'def write_page(joined: pd.DataFrame, metrics: pd.DataFrame, generated: str, obs_mode: str) -> None:'
)

if "Mode evaluasi:" not in text:
    text = text.replace(
        '<h1>Evaluasi akurasi forecast.</h1>',
        '<h1>Evaluasi akurasi forecast.</h1>\\n      <p><strong>Mode evaluasi:</strong> {escape(obs_mode)}</p>'
    )

text = text.replace(
    'Halaman ini membandingkan forecast hujan harian dengan data observasi aktual.',
    'Halaman ini membandingkan forecast hujan harian dengan data pembanding. Jika data lapangan belum tersedia, sistem dapat memakai proxy observation seperti data satelit atau gridded.'
)

if text == original:
    print("WARNING: Tidak ada perubahan. File mungkin sudah dipatch atau pola tidak cocok.")
else:
    path.write_text(text, encoding="utf-8")
    print("SUCCESS: evaluate_forecast_accuracy.py sudah support proxy fallback.")
