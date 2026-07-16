#!/usr/bin/env python3
"""Refresh mature CHIRPS proxy rows for archived Forecast Redelong runs.

This task is deliberately non-blocking: forecast publication must continue when
the external proxy service is late or unavailable.  Attempt state is persisted
in ``outputs/validation_archive`` so morning retries do not repeat the same
remote requests.
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


def download_chirps(validation_dir: Path, start: str, end: str) -> pd.DataFrame:
    # Lazy import keeps local validation/unit tests usable before optional
    # network dependencies are installed.  GitHub Actions installs requests.
    from build_utils import download_proxy_observations as proxy

    proxy.OBS_DIR = validation_dir
    return proxy.download_climateserv_dataset(
        locations=proxy.load_locations(),
        dataset=proxy.DATASETS[0],
        start=start,
        end=end,
        sleep=0.25,
        box_delta=0.025,
        timeout=30,
        poll_seconds=1.0,
        poll_max=35,
    )


def refresh(outputs: Path, force: bool = False) -> dict:
    validation_dir = outputs / "validation_archive"
    validation_dir.mkdir(parents=True, exist_ok=True)
    proxy_path = validation_dir / "rain_proxy_daily_chirps.csv"
    status_path = validation_dir / "proxy_refresh_status.json"
    today = datetime.now(WIB).date()
    attempt_date = today.isoformat()

    archived, archive_stats = build_archive_daily_forecasts(outputs / "archive")
    if archived.empty:
        status = {
            "status": "no_eligible_archive",
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
    existing = read_existing(proxy_path)
    available = set(zip(existing["date"].astype(str), existing["location_slug"].astype(str)))
    missing = sorted(expected - available)

    previous = {}
    try:
        previous = json.loads(status_path.read_text(encoding="utf-8-sig"))
    except Exception:
        pass
    if not missing:
        status = {
            "status": "up_to_date",
            "attempt_date_wib": attempt_date,
            "archive": archive_stats,
            "expected_pairs": len(expected),
            "available_pairs": len(expected & available),
            "missing_pairs": 0,
        }
        status_path.write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
        return status
    if not force and previous.get("attempt_date_wib") == attempt_date:
        previous["status"] = "already_attempted_today"
        status_path.write_text(json.dumps(previous, ensure_ascii=False, indent=2), encoding="utf-8")
        return previous

    missing_dates = sorted({date for date, _ in missing})
    downloaded = pd.DataFrame(columns=PROXY_COLUMNS)
    error = None
    try:
        downloaded = download_chirps(
            validation_dir,
            missing_dates[0],
            missing_dates[-1],
        )
    except Exception as exc:  # publication remains available when proxy is down
        error = str(exc)

    available_frames = [frame for frame in (existing, downloaded) if not frame.empty]
    combined = (
        pd.concat(available_frames, ignore_index=True)
        if available_frames
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
    combined.reindex(columns=PROXY_COLUMNS).to_csv(proxy_path, index=False)
    available = set(zip(combined["date"].astype(str), combined["location_slug"].astype(str)))
    remaining = expected - available
    status = {
        "status": "complete" if not remaining else "proxy_pending",
        "attempt_date_wib": attempt_date,
        "archive": archive_stats,
        "requested_date_start": missing_dates[0],
        "requested_date_end": missing_dates[-1],
        "expected_pairs": len(expected),
        "available_pairs": len(expected & available),
        "missing_pairs": len(remaining),
        "downloaded_rows_this_attempt": int(len(downloaded)),
        "error": error,
        "note": "CHIRPS adalah proxy gridded; tidak menggantikan observasi penakar hujan site.",
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
