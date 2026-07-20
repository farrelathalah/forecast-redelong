#!/usr/bin/env python3
"""Fetch a GloFAS discharge proxy at the documented Besai Kemu weir."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

try:
    from build_utils.fetch_glofas_discharge import build_for_coordinate
except ModuleNotFoundError:  # direct script execution from repository root
    from fetch_glofas_discharge import build_for_coordinate


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUTS = ROOT / "outputs"
WEIR_LATITUDE = -4.862591667
WEIR_LONGITUDE = 104.500497222
GLOFAS_SAMPLING_LATITUDE = -4.862591667
GLOFAS_SAMPLING_LONGITUDE = 104.450497222


def build(outputs: Path, history_start: str = "2000-01-01", history_end: str | None = None) -> dict:
    metadata = build_for_coordinate(
        outputs,
        GLOFAS_SAMPLING_LATITUDE,
        GLOFAS_SAMPLING_LONGITUDE,
        file_prefix="besai_glofas_discharge",
        schema_version="forecast-besai-glofas-proxy-v1",
        site_name="PLTM Besai Kemu",
        history_start=history_start,
        history_end=history_end,
    )
    history = pd.read_csv(outputs / "hydrology" / "besai_glofas_discharge_history.csv")
    discharge = pd.to_numeric(history["river_discharge"], errors="coerce").dropna()
    q40_proxy = float(discharge.quantile(0.60))
    metadata.update(
        {
            "asset_coordinate": [WEIR_LATITUDE, WEIR_LONGITUDE],
            "sampling_coordinate": [GLOFAS_SAMPLING_LATITUDE, GLOFAS_SAMPLING_LONGITUDE],
            "grid_selection_method": (
                "screened nearby GloFAS cells for spatial proximity and a non-trivial "
                "flow-duration regime; the exact asset request selected a small tributary cell"
            ),
            "documented_design_q40_m3s": 21.59,
            "selected_proxy_q40_m3s": round(q40_proxy, 3),
            "grid_selection_status": (
                "screened_proxy_pending_glofas_map_confirmation"
                if q40_proxy >= 10.0
                else "reject_small_tributary_grid"
            ),
        }
    )
    if q40_proxy < 10.0:
        raise ValueError(
            "Grid GloFAS Besai masih menyerupai anak sungai kecil; hentikan publikasi debit"
        )
    (outputs / "hydrology" / "besai_glofas_discharge_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return metadata


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch GloFAS proxy for PLTM Besai Kemu")
    parser.add_argument("--outputs", type=Path, default=DEFAULT_OUTPUTS)
    parser.add_argument("--history-start", default="2000-01-01")
    parser.add_argument("--history-end")
    args = parser.parse_args()
    print(json.dumps(build(args.outputs.resolve(), args.history_start, args.history_end), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
