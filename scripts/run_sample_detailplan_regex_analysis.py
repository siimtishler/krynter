"""Run regex detail-plan analysis for N sampled GeoPackage rows.

Examples:
    poetry run python scripts/run_sample_detailplan_regex_analysis.py 5
    poetry run python scripts/run_sample_detailplan_regex_analysis.py 10 --seed 7
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.utils import time_function  # noqa: E402
from backend.core.config import config  # noqa: E402
from backend.detailplan_analyzer.analyzer import analyze_detail_plan  # noqa: E402
from backend.detailplan_analyzer.pdfs import detail_plan_cache_dir  # noqa: E402
from backend.geo.crs import ensure_data_crs  # noqa: E402

DEFAULT_GPKG = (
    config.detail_plans_file
    if config.detail_plans_file.exists()
    else PROJECT_ROOT / "data" / "detail_plans.gpkg"
)
DEFAULT_CADASTRE_GPKG = (
    config.cadastre_file
    if config.cadastre_file.exists()
    else PROJECT_ROOT / "data" / "cadastre.gpkg"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sample detail plans from a GeoPackage, run the regex PDF pipeline, "
            "and write result.json beside each cached PDF."
        )
    )
    parser.add_argument("count", type=int, help="Number of detail-plan rows to sample")
    parser.add_argument(
        "--gpkg",
        type=Path,
        default=DEFAULT_GPKG,
        help=f"Detail-plan GeoPackage path (default: {DEFAULT_GPKG})",
    )
    parser.add_argument(
        "--layer",
        default=None,
        help="Detail-plan GeoPackage layer name. Defaults to the first layer.",
    )
    parser.add_argument(
        "--cadastre-gpkg",
        type=Path,
        default=DEFAULT_CADASTRE_GPKG,
        help=f"Cadastre GeoPackage path (default: {DEFAULT_CADASTRE_GPKG})",
    )
    parser.add_argument(
        "--cadastre-layer",
        default=None,
        help="Cadastre GeoPackage layer name. Defaults to the first layer.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for reproducible sampling (default: 42)",
    )
    parser.add_argument(
        "--address-column",
        default=None,
        help=(
            "Optional column used as the analyzer address hint. "
            "If omitted, the analyzer selects pages by regex topic keywords."
        ),
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Redownload PDFs and refresh text extraction/OCR caches.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing result.json files. Existing files are skipped by default.",
    )
    return parser.parse_args()


def first_layer(gpkg_path: Path) -> str:
    layers = pyogrio.list_layers(gpkg_path)
    if len(layers) == 0:
        raise ValueError(f"No layers found in {gpkg_path}")
    return str(layers[0][0])


def clean_value(value: Any) -> Any:
    if isinstance(value, pd.Timestamp):
        return value.isoformat() if not pd.isna(value) else None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def clean_record(row: pd.Series) -> dict[str, Any]:
    record = row.drop(labels=["geometry"], errors="ignore").to_dict()
    return {key: clean_value(value) for key, value in record.items()}


def highest_overlap_parcel_attributes(
    plan_row: pd.Series,
    cadastre: gpd.GeoDataFrame,
) -> dict[str, Any] | None:
    geometry = plan_row.geometry
    if geometry is None or geometry.is_empty or cadastre.empty:
        return None

    matches_index = cadastre.sindex.query(geometry, predicate="intersects")
    if len(matches_index) == 0:
        return None

    candidates = cadastre.iloc[matches_index].copy()
    candidates = candidates[candidates.geometry.intersects(geometry)]
    if candidates.empty:
        return None

    intersection_areas = candidates.geometry.intersection(geometry).area
    best_index = intersection_areas.idxmax()
    attributes = clean_record(candidates.loc[best_index])
    attributes["detail_plan_intersection_area_m2"] = float(
        intersection_areas.loc[best_index]
    )
    return attributes


def plan_id(detail_plan: dict[str, Any]) -> str:
    return str(
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
        or detail_plan.get("id")
        or "unknown"
    )


def write_result(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

@time_function
def main() -> None:
    args = parse_args()
    if args.count < 1:
        raise ValueError("count must be at least 1")

    layer = args.layer or first_layer(args.gpkg)
    frame = ensure_data_crs(gpd.read_file(args.gpkg, layer=layer))
    if "failid" in frame.columns:
        frame = frame[frame["failid"].notna() & (frame["failid"].astype(str) != "")]
    if frame.empty:
        raise ValueError(f"No analyzable detail-plan rows found in {args.gpkg}")

    cadastre_layer = args.cadastre_layer or first_layer(args.cadastre_gpkg)
    cadastre = ensure_data_crs(gpd.read_file(args.cadastre_gpkg, layer=cadastre_layer))

    sample_count = min(args.count, len(frame))
    sampled = frame.sample(n=sample_count, random_state=args.seed)

    print(
        f"Running regex analysis for {sample_count} sampled plans "
        f"from {args.gpkg} layer={layer!r}"
    )
    for index, row in sampled.iterrows():
        detail_plan = clean_record(row)
        cache_dir = detail_plan_cache_dir(detail_plan)
        result_path = cache_dir / "result.json"
        current_plan_id = plan_id(detail_plan)

        if result_path.exists() and not args.overwrite:
            print(f"[skip] {current_plan_id}: {result_path} already exists")
            continue

        address = ""
        if args.address_column:
            if args.address_column not in row.index:
                raise ValueError(f"Unknown address column: {args.address_column}")
            address = str(clean_value(row[args.address_column]) or "")
        parcel_attributes = highest_overlap_parcel_attributes(row, cadastre)
        if not address and parcel_attributes:
            address = str(parcel_attributes.get("l_aadress") or "")

        parcel_label = (
            parcel_attributes.get("tunnus") if parcel_attributes else "no parcel"
        )
        print(
            f"[run] {current_plan_id}: {detail_plan.get('plannim') or index} "
            f"(parcel={parcel_label})"
        )
        response = analyze_detail_plan(
            detail_plan=detail_plan,
            address=address,
            parcel_attributes=parcel_attributes,
            force_refresh=args.force_refresh,
        )
        payload = response.model_dump(mode="json")
        write_result(result_path, payload)
        print(f"[done] {current_plan_id}: {payload['status']} -> {result_path}")


if __name__ == "__main__":
    main()
