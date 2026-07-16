#!/usr/bin/env python3
"""Refresh mature satellite proxy rows for archived Forecast Redelong runs.

This task is deliberately non-blocking: forecast publication must continue when
the external proxy service is late or unavailable. IMERG is the primary
near-real-time reference and CHIRPS is retained as a delayed comparison. The
sources are stored separately and are never blended into one rainfall value.
Attempt state is persisted in ``outputs/validation_archive`` so morning retries
do not repeat the same remote requests.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from build_utils.evaluate_forecast_accuracy import build_archive_daily_forecasts


WIB = timezone(timedelta(hours=7))
PROXY_STRATEGY = "imerg-primary-chirps-fallback-v1"
PROXY_COLUMNS = [
    "date",
    "location_slug",
    "rain_mm_observed",
    "source",
    "observation_type",
]


def read_existing(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=PROXY_COLUMNS)
    try:
        frame = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=PROXY_COLUMNS)
    for column in PROXY_COLUMNS:
        if column not in frame:
            frame[column] = ""
    return frame[PROXY_COLUMNS]


def download_proxy_dataset(
    validation_dir: Path, start: str, end: str, dataset_index: int
) -> pd.DataFrame:
    # Lazy import keeps local validation/unit tests usable before optional
    # network dependencies are installed.  GitHub Actions installs requests.
    from build_utils import download_proxy_observations as proxy

    proxy.OBS_DIR = validation_dir
    return proxy.download_climateserv_dataset(
        locations=proxy.load_locations(),
        dataset=proxy.DATASETS[dataset_index],
        start=start,
        end=end,
        sleep=0.25,
        box_delta=0.025,
        timeout=30,
        poll_seconds=1.0,
        poll_max=35,
    )


def download_imerg(validation_dir: Path, start: str, end: str) -> pd.DataFrame:
    return download_proxy_dataset(validation_dir, start, end, dataset_index=1)


def download_chirps(validation_dir: Path, start: str, end: str) -> pd.DataFrame:
    return download_proxy_dataset(validation_dir, start, end, dataset_index=0)


def merge_proxy_rows(existing: pd.DataFrame, downloaded: pd.DataFrame) -> pd.DataFrame:
    frames = [frame for frame in (existing, downloaded) if not frame.empty]
    combined = (
        pd.concat(frames, ignore_index=True)
        if frames
        else pd.DataFrame(columns=PROXY_COLUMNS)
    )
    if not combined.empty:
        combined["rain_mm_observed"] = pd.to_numeric(
            combined["rain_mm_observed"], errors="coerce"
        )
        combined = (
            combined.dropna(subset=["date", "location_slug", "rain_mm_observed"])
            .drop_duplicates(["date", "location_slug"], keep="last")
            .sort_values(["date", "location_slug"])
        )
    return combined.reindex(columns=PROXY_COLUMNS)


def refresh(outputs: Path, force: bool = False) -> dict:
    validation_dir = outputs / "validation_archive"
    validation_dir.mkdir(parents=True, exist_ok=True)
    imerg_path = validation_dir / "rain_proxy_daily_imerg.csv"
    chirps_path = validation_dir / "rain_proxy_daily_chirps.csv"
    primary_path = validation_dir / "rain_proxy_daily_primary.csv"
    status_path = validation_dir / "proxy_refresh_status.json"
    today = datetime.now(WIB).date()
    attempt_date = today.isoformat()

    archived, archive_stats = build_archive_daily_forecasts(outputs / "archive")
    if archived.empty:
        status = {
            "status": "no_eligible_archive",
            "proxy_strategy": PROXY_STRATEGY,
            "attempt_date_wib": attempt_date,
            "archive": archive_stats,
            "expected_pairs": 0,
            "available_pairs": 0,
            "missing_pairs": 0,
        }
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status

    archived = archived.copy()
    archived["date"] = pd.to_datetime(archived["date"], errors="coerce").dt.strftime("%Y-%m-%d")
    mature = archived[pd.to_datetime(archived["date"]).dt.date < today]
    expected = set(zip(mature["date"], mature["location_slug"]))
    existing_imerg = read_existing(imerg_path)
    existing_chirps = read_existing(chirps_path)

    def available_pairs(frame: pd.DataFrame) -> set[tuple[str, str]]:
        return set(zip(frame["date"].astype(str), frame["location_slug"].astype(str)))

    imerg_available = available_pairs(existing_imerg)
    chirps_available = available_pairs(existing_chirps)
    missing_imerg = sorted(expected - imerg_available)
    missing_chirps = sorted(expected - chirps_available)

    previous = {}
    try:
        previous = json.loads(status_path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    if not expected:
        status = {
            "status": "waiting_for_closed_day",
            "proxy_strategy": PROXY_STRATEGY,
            "attempt_date_wib": attempt_date,
            "archive": archive_stats,
            "expected_pairs": 0,
            "available_pairs": 0,
            "missing_pairs": 0,
            "note": "Hari target harus selesai sebelum data proxy harian dapat dibandingkan.",
        }
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status
    if not missing_imerg:
        existing_imerg.to_csv(primary_path, index=False)
        status = {
            "status": "up_to_date",
            "proxy_strategy": PROXY_STRATEGY,
            "attempt_date_wib": attempt_date,
            "archive": archive_stats,
            "primary_proxy": "GPM IMERG via ClimateSERV",
            "primary_proxy_file": primary_path.name,
            "expected_pairs": len(expected),
            "available_pairs": len(expected & imerg_available),
            "missing_pairs": 0,
            "sources": {
                "imerg": {"available_pairs": len(expected & imerg_available)},
                "chirps": {"available_pairs": len(expected & chirps_available)},
            },
        }
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status
    if (
        not force
        and previous.get("attempt_date_wib") == attempt_date
        and previous.get("proxy_strategy") == PROXY_STRATEGY
        and primary_path.exists()
    ):
        previous["status"] = "already_attempted_today"
        status_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
        return previous

    missing_dates = sorted({date for date, _ in missing_imerg})
    downloaded_imerg = pd.DataFrame(columns=PROXY_COLUMNS)
    downloaded_chirps = pd.DataFrame(columns=PROXY_COLUMNS)
    errors: dict[str, str | None] = {"imerg": None, "chirps": None}
    try:
        downloaded_imerg = download_imerg(
            validation_dir,
            missing_dates[0],
            missing_dates[-1],
        )
    except Exception as exc:  # publication remains available when proxy is down
        errors["imerg"] = str(exc)

    combined_imerg = merge_proxy_rows(existing_imerg, downloaded_imerg)
    combined_imerg.to_csv(imerg_path, index=False)
    imerg_available = available_pairs(combined_imerg)

    # CHIRPS is requested only when IMERG still has no usable pair. This keeps
    # the scheduled build bounded while preserving a documented fallback.
    if not (expected & imerg_available) and missing_chirps:
        chirps_dates = sorted({date for date, _ in missing_chirps})
        try:
            downloaded_chirps = download_chirps(
                validation_dir,
                chirps_dates[0],
                chirps_dates[-1],
            )
        except Exception as exc:
            errors["chirps"] = str(exc)

    combined_chirps = merge_proxy_rows(existing_chirps, downloaded_chirps)
    combined_chirps.to_csv(chirps_path, index=False)
    chirps_available = available_pairs(combined_chirps)

    if expected & imerg_available:
        primary_name = "GPM IMERG via ClimateSERV"
        primary = combined_imerg
        primary_available = imerg_available
    elif expected & chirps_available:
        primary_name = "CHIRPS via ClimateSERV"
        primary = combined_chirps
        primary_available = chirps_available
    else:
        primary_name = "NONE"
        primary = pd.DataFrame(columns=PROXY_COLUMNS)
        primary_available = set()
    primary.to_csv(primary_path, index=False)
    remaining = expected - primary_available
    status = {
        "status": "complete" if not remaining else "proxy_pending",
        "proxy_strategy": PROXY_STRATEGY,
        "attempt_date_wib": attempt_date,
        "archive": archive_stats,
        "primary_proxy": primary_name,
        "primary_proxy_file": primary_path.name,
        "requested_date_start": missing_dates[0],
        "requested_date_end": missing_dates[-1],
        "expected_pairs": len(expected),
        "available_pairs": len(expected & primary_available),
        "missing_pairs": len(remaining),
        "downloaded_rows_this_attempt": {
            "imerg": int(len(downloaded_imerg)),
            "chirps": int(len(downloaded_chirps)),
        },
        "sources": {
            "imerg": {"available_pairs": len(expected & imerg_available)},
            "chirps": {"available_pairs": len(expected & chirps_available)},
        },
        "errors": errors,
        "note": (
            "Validasi memakai referensi proxy satelit gridded karena tidak ada penakar hujan site. "
            "IMERG menjadi referensi utama dan CHIRPS pembanding tertunda; keduanya tidak dicampur."
        ),
        "limitations": [
            "Referensi proxy bukan pengukuran langsung di PLTA.",
            "Definisi hari dari layanan sumber perlu dicatat saat menafsirkan total harian WIB.",
        ],
    }
    status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    return status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--outputs", type=Path, default=Path("outputs"))
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    status = refresh(args.outputs, force=args.force)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
