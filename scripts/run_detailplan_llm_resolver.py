"""Run the local Ollama resolver for selected detail-plan analyzer fields.

Examples:
    poetry run python scripts/run_detailplan_llm_resolver.py --address "Kaupmehe tn 19"
    poetry run python scripts/run_detailplan_llm_resolver.py --sample-size 5
    poetry run python scripts/run_detailplan_llm_resolver.py plan.pdf --field taisehitus_pct --model gemma3:4b
    poetry run python scripts/run_detailplan_llm_resolver.py --result-json data/detail_downloads/123/result.json --all-fields
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any

import geopandas as gpd
import pandas as pd
import pyogrio

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from backend.core.config import config  # noqa: E402
from backend.detailplan_analyzer.analyzer import analyze_pdfs  # noqa: E402
from backend.detailplan_analyzer.llm_resolver import (  # noqa: E402
    OllamaResolverProvider,
    apply_resolution,
    build_field_request,
    build_prompt,
    parse_resolution,
    should_resolve_field,
)
from backend.detailplan_analyzer.models import DetailPlanAnalysisResponse  # noqa: E402
from backend.detailplan_analyzer.pdfs import download_plan_pdfs  # noqa: E402
from backend.detailplan_analyzer.extraction import pdf_has_text  # noqa: E402
from backend.geo.constants import DETAIL_PLAN_MIN_COVERAGE_PCT  # noqa: E402
from backend.geo.crs import ensure_data_crs  # noqa: E402

DEFAULT_GPKG = (
    config.detail_plans_file
    if config.detail_plans_file.exists()
    else PROJECT_ROOT / "data" / "detail_plans_tln.gpkg"
)
DEFAULT_CADASTRE_GPKG = (
    config.cadastre_file
    if config.cadastre_file.exists()
    else PROJECT_ROOT / "data" / "Tallinn_KATASTER_GPKG2.gpkg"
)


@dataclass(frozen=True)
class AnalysisCase:
    label: str
    response: DetailPlanAnalysisResponse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run one or more LLM resolver calls against analyzer candidate evidence "
            "and print timing, model, raw model output, parsed output, and apply result."
        )
    )
    parser.add_argument(
        "pdf_path",
        nargs="?",
        type=Path,
        help="Optional local PDF path for low-level debugging.",
    )
    parser.add_argument(
        "--result-json",
        type=Path,
        help="Existing analyzer result.json to use as resolver input.",
    )
    parser.add_argument(
        "--address",
        default="",
        help=(
            "Parcel address. With pdf_path this is only an analyzer hint; without "
            "pdf_path the script finds the parcel and highest-overlap detail plan."
        ),
    )
    parser.add_argument(
        "--cadastre-code",
        help="Optional exact cadastre code lookup instead of address.",
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        help="Random parcel sample size. Each sampled parcel uses its highest-overlap detail plan.",
    )
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
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--max-sample-attempts",
        type=int,
        default=600,
        help="Maximum random cadastre rows checked to fill --sample-size.",
    )
    parser.add_argument(
        "--allow-no-eligible",
        action="store_true",
        help=(
            "In --sample-size mode, keep cases even when no field has candidate "
            "evidence for the resolver."
        ),
    )
    parser.add_argument(
        "--parcel-attributes-json",
        type=Path,
        help="Optional parcel attributes JSON for PDF analysis.",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Refresh PDF text extraction/OCR caches when analyzing a PDF.",
    )
    parser.add_argument(
        "--allow-ocr",
        action="store_true",
        help=(
            "Allow fresh OCR during address/sample modes. Disabled by default so "
            "LLM timing runs skip scanned PDFs instead of spending minutes in OCR."
        ),
    )
    parser.add_argument(
        "--field",
        action="append",
        default=[],
        help="Field key to test. Can be passed multiple times.",
    )
    parser.add_argument(
        "--all-fields",
        action="store_true",
        help="Run every eligible field. Otherwise only --max-fields are run.",
    )
    parser.add_argument(
        "--max-fields",
        type=int,
        default=1,
        help="Maximum eligible fields to run when --all-fields is not set.",
    )
    parser.add_argument(
        "--base-url",
        default=config.ollama_base_url,
        help=f"Ollama base URL (default: {config.ollama_base_url})",
    )
    parser.add_argument(
        "--model",
        default=config.ollama_building_right_model,
        help=f"Ollama model (default: {config.ollama_building_right_model})",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=config.ollama_timeout_s,
        help=f"HTTP timeout seconds (default: {config.ollama_timeout_s})",
    )
    parser.add_argument("--temperature", type=float, default=0)
    parser.add_argument("--num-ctx", type=int, default=4096)
    parser.add_argument("--num-predict", type=int, default=256)
    parser.add_argument("--top-p", type=float)
    parser.add_argument("--top-k", type=int)
    parser.add_argument("--repeat-penalty", type=float)
    parser.add_argument("--llm-seed", type=int)
    parser.add_argument(
        "--show-prompt",
        action="store_true",
        help="Include the full prompt in the JSON output.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to write the JSON report.",
    )
    args = parser.parse_args()
    source_count = sum(
        bool(item)
        for item in (
            args.pdf_path,
            args.result_json,
            args.address and not args.pdf_path,
            args.cadastre_code,
            args.sample_size,
        )
    )
    if source_count != 1:
        parser.error(
            "provide exactly one input source: pdf_path, --result-json, "
            "--address, --cadastre-code, or --sample-size"
        )
    if args.sample_size is not None and args.sample_size < 1:
        parser.error("--sample-size must be at least 1")
    return args


def llm_options(args: argparse.Namespace) -> dict[str, Any]:
    options: dict[str, Any] = {
        "temperature": args.temperature,
        "num_ctx": args.num_ctx,
    }
    optional_args = {
        "num_predict": args.num_predict,
        "top_p": args.top_p,
        "top_k": args.top_k,
        "repeat_penalty": args.repeat_penalty,
        "seed": args.llm_seed,
    }
    options.update(
        {key: value for key, value in optional_args.items() if value is not None}
    )
    return options


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


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


def plan_id(detail_plan: dict[str, Any]) -> str:
    return str(
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
        or detail_plan.get("id")
        or "unknown"
    )


def load_spatial_data(args: argparse.Namespace) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    detail_layer = args.layer or first_layer(args.gpkg)
    detail_plans = ensure_data_crs(gpd.read_file(args.gpkg, layer=detail_layer))
    if "failid" in detail_plans.columns:
        detail_plans = detail_plans[
            detail_plans["failid"].notna()
            & (detail_plans["failid"].astype(str) != "")
        ]
    if detail_plans.empty:
        raise ValueError(f"No analyzable detail-plan rows found in {args.gpkg}")

    cadastre_layer = args.cadastre_layer or first_layer(args.cadastre_gpkg)
    cadastre = ensure_data_crs(gpd.read_file(args.cadastre_gpkg, layer=cadastre_layer))
    if cadastre.empty:
        raise ValueError(f"No cadastre rows found in {args.cadastre_gpkg}")
    return cadastre, detail_plans


def highest_overlap_detail_plan_for_parcel(
    parcel_row: pd.Series,
    detail_plans: gpd.GeoDataFrame,
) -> dict[str, Any] | None:
    geometry = parcel_row.geometry
    if geometry is None or geometry.is_empty:
        return None

    matches_index = detail_plans.sindex.query(geometry, predicate="intersects")
    if len(matches_index) == 0:
        return None

    candidates = detail_plans.iloc[matches_index].copy()
    candidates = candidates[candidates.geometry.intersects(geometry)]
    if candidates.empty:
        return None

    intersection_areas = candidates.geometry.intersection(geometry).area
    parcel_area_m2 = float(geometry.area or 0)
    candidates = candidates.assign(
        intersection_area_m2=intersection_areas,
        parcel_coverage_pct=(
            100 * intersection_areas / parcel_area_m2 if parcel_area_m2 else 0.0
        ),
    )
    candidates = candidates[
        candidates["parcel_coverage_pct"] >= DETAIL_PLAN_MIN_COVERAGE_PCT
    ]
    if candidates.empty:
        return None

    best = candidates.sort_values("intersection_area_m2", ascending=False).iloc[0]
    return clean_record(best)


def parcel_row_by_address(
    cadastre: gpd.GeoDataFrame,
    address: str,
) -> pd.Series:
    matches = cadastre.loc[cadastre["l_aadress"].eq(address)]
    if matches.empty:
        matches = cadastre.loc[
            cadastre["l_aadress"].astype(str).str.casefold().eq(address.casefold())
        ]
    if matches.empty:
        raise ValueError(f"Parcel address not found in cadastre: {address}")
    if len(matches) > 1:
        raise ValueError(f"Multiple parcels matched address: {address}")
    return matches.iloc[0]


def parcel_row_by_cadastre_code(
    cadastre: gpd.GeoDataFrame,
    cadastre_code: str,
) -> pd.Series:
    matches = cadastre.loc[cadastre["tunnus"].astype(str).eq(cadastre_code)]
    if matches.empty:
        raise ValueError(f"Cadastre code not found: {cadastre_code}")
    if len(matches) > 1:
        raise ValueError(f"Multiple parcels matched cadastre code: {cadastre_code}")
    return matches.iloc[0]


def analyze_parcel_row(
    parcel_row: pd.Series,
    detail_plans: gpd.GeoDataFrame,
    args: argparse.Namespace,
) -> AnalysisCase | None:
    parcel_attributes = clean_record(parcel_row)
    address = str(parcel_attributes.get("l_aadress") or "")
    detail_plan = highest_overlap_detail_plan_for_parcel(parcel_row, detail_plans)
    if detail_plan is None:
        return None
    pdf_paths = download_plan_pdfs(detail_plan, force_refresh=args.force_refresh)
    if not args.allow_ocr and not pdfs_are_text_ready(pdf_paths):
        print(
            f"[skip] {address or parcel_attributes.get('tunnus')}: "
            f"plan={plan_id(detail_plan)} needs OCR",
            file=sys.stderr,
        )
        return None
    response = analyze_pdfs(
        pdf_paths=pdf_paths,
        address=address,
        detail_plan=detail_plan,
        parcel_attributes=parcel_attributes,
        force_refresh=args.force_refresh,
    )
    label = (
        f"{address or parcel_attributes.get('tunnus') or 'parcel'} "
        f"plan={plan_id(detail_plan)}"
    )
    return AnalysisCase(label=label, response=response)


def pdfs_are_text_ready(pdf_paths: list[Path]) -> bool:
    for pdf_path in pdf_paths:
        if pdf_has_text(pdf_path):
            continue
        ocr_pdf = pdf_path.with_name(f"{pdf_path.stem}_ocr.pdf")
        if ocr_pdf.exists() and pdf_has_text(ocr_pdf):
            continue
        return False
    return True


def sample_parcel_cases(
    cadastre: gpd.GeoDataFrame,
    detail_plans: gpd.GeoDataFrame,
    args: argparse.Namespace,
) -> list[AnalysisCase]:
    candidates = cadastre
    if "l_aadress" in candidates.columns:
        candidates = candidates[
            candidates["l_aadress"].notna()
            & (candidates["l_aadress"].astype(str) != "")
        ]
    shuffled = candidates.sample(
        n=min(len(candidates), args.max_sample_attempts),
        random_state=args.seed,
    )
    cases: list[AnalysisCase] = []
    for _, row in shuffled.iterrows():
        try:
            case = analyze_parcel_row(row, detail_plans, args=args)
        except Exception as exc:
            print(
                f"[skip] failed parcel={row.get('tunnus', '?')} "
                f"error={type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            continue
        if case is None:
            continue
        if not args.allow_no_eligible and not selected_field_keys(case.response, args):
            continue
        cases.append(case)
        print(f"[case] {len(cases)}/{args.sample_size}: {case.label}", file=sys.stderr)
        if len(cases) >= args.sample_size:
            break
    if len(cases) < args.sample_size:
        raise ValueError(
            f"Only found {len(cases)} parcel/detail-plan cases after "
            f"{len(shuffled)} sampled cadastre rows."
        )
    return cases


def load_cases(args: argparse.Namespace) -> list[AnalysisCase]:
    if args.result_json:
        response = DetailPlanAnalysisResponse.model_validate(load_json(args.result_json))
        return [AnalysisCase(label=str(args.result_json), response=response)]

    if args.pdf_path:
        parcel_attributes = (
            load_json(args.parcel_attributes_json)
            if args.parcel_attributes_json
            else None
        )
        response = analyze_pdfs(
            pdf_paths=[args.pdf_path],
            address=args.address,
            parcel_attributes=parcel_attributes,
            force_refresh=args.force_refresh,
        )
        return [AnalysisCase(label=str(args.pdf_path), response=response)]

    cadastre, detail_plans = load_spatial_data(args)
    if args.address:
        row = parcel_row_by_address(cadastre, args.address)
        case = analyze_parcel_row(row, detail_plans, args=args)
        if case is None:
            raise ValueError(f"No overlapping detail plan found for: {args.address}")
        return [case]
    if args.cadastre_code:
        row = parcel_row_by_cadastre_code(cadastre, args.cadastre_code)
        case = analyze_parcel_row(row, detail_plans, args=args)
        if case is None:
            raise ValueError(
                f"No overlapping detail plan found for: {args.cadastre_code}"
            )
        return [case]
    return sample_parcel_cases(
        cadastre=cadastre,
        detail_plans=detail_plans,
        args=args,
    )


def selected_field_keys(
    response: DetailPlanAnalysisResponse,
    args: argparse.Namespace,
) -> list[str]:
    parcel_context = response.meta.parcel_context
    eligible = [
        key
        for key, field in response.building_right.fields.items()
        if should_resolve_field(field, parcel_context)
    ]
    if args.field:
        requested = set(args.field)
        eligible = [key for key in eligible if key in requested]
    if args.all_fields:
        return eligible
    return eligible[: max(args.max_fields, 0)]


def run_field(
    response: DetailPlanAnalysisResponse,
    field_key: str,
    provider: OllamaResolverProvider,
    include_prompt: bool,
) -> dict[str, Any]:
    field = response.building_right.fields[field_key]
    request = build_field_request(
        field,
        response.building_right,
        response.meta.parcel_context,
    )
    prompt = build_prompt(request)
    report: dict[str, Any] = {
        "field_key": field_key,
        "label": field.label,
        "candidate_count": len(field.candidates),
        "review_count": len(field.needs_review),
        "candidates": [
            candidate.model_dump(mode="json", exclude_none=True)
            for candidate in field.candidates[:5]
        ],
    }
    if include_prompt:
        report["prompt"] = prompt

    started = time.perf_counter()
    try:
        generation = provider.generate_field_raw(request)
        report["generation"] = generation.model_dump(mode="json")
        try:
            resolution = parse_resolution(generation.raw_response)
            report["parsed_resolution"] = resolution.model_dump(
                mode="json",
                exclude_none=True,
            )
            report["applied"] = apply_resolution(field, resolution)
            report["field_after_apply"] = field.model_dump(
                mode="json",
                exclude_none=True,
            )
        except Exception as exc:
            report["parse_or_apply_error"] = {
                "type": type(exc).__name__,
                "message": str(exc),
            }
    except Exception as exc:
        report["generation_error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    elapsed_s = time.perf_counter() - started
    report["elapsed_s"] = round(elapsed_s, 3)
    report["elapsed_min"] = round(elapsed_s / 60, 3)
    return report


def main() -> None:
    args = parse_args()
    started = time.perf_counter()
    cases = load_cases(args)
    options = llm_options(args)
    provider = OllamaResolverProvider(
        base_url=args.base_url,
        model=args.model,
        timeout_s=args.timeout,
        options=options,
    )
    case_reports = []
    eligible_count = 0
    for case in cases:
        field_keys = selected_field_keys(case.response, args)
        eligible_count += len(field_keys)
        field_reports = [
            run_field(
                case.response,
                field_key,
                provider,
                include_prompt=args.show_prompt,
            )
            for field_key in field_keys
        ]
        case_reports.append(
            {
                "label": case.label,
                "status": case.response.status,
                "address": case.response.meta.address,
                "detail_plan": case.response.meta.detail_plan,
                "parcel_context": case.response.meta.parcel_context,
                "eligible_field_count": len(field_keys),
                "fields": field_reports,
            }
        )
    total_elapsed_s = time.perf_counter() - started
    report = {
        "model": args.model,
        "base_url": args.base_url,
        "timeout_s": args.timeout,
        "options": options,
        "input": {
            "pdf_path": str(args.pdf_path) if args.pdf_path else None,
            "result_json": str(args.result_json) if args.result_json else None,
            "address": args.address,
            "cadastre_code": args.cadastre_code,
            "sample_size": args.sample_size,
            "detail_plans_gpkg": str(args.gpkg),
            "cadastre_gpkg": str(args.cadastre_gpkg),
        },
        "case_count": len(cases),
        "eligible_field_count": eligible_count,
        "cases": case_reports,
        "total_elapsed_s": round(total_elapsed_s, 3),
        "total_elapsed_min": round(total_elapsed_s / 60, 3),
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload, encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
