"""High-level regex-only detail-planning PDF analysis orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import (
    PageText,
    TextChunk,
    extract_pages_cached,
    find_address_lines,
    prepare_pdf_for_text,
    select_relevant_chunks,
)
from backend.detailplan_analyzer.models import (
    AnalysisStatus,
    BuildingRightSection,
    DetailPlanAnalysisResponse,
    DetailPlanMeta,
    SourceReference,
)
from backend.detailplan_analyzer.pdfs import (
    OCRSetupError,
    PDFDownloadError,
    check_ocr_runtime,
    detail_plan_cache_dir,
    download_plan_pdfs,
)
from backend.detailplan_analyzer.rules import extract_building_rights


def empty_building_right() -> BuildingRightSection:
    return BuildingRightSection()


def _sources_from_chunks(chunks: list[TextChunk]) -> list[SourceReference]:
    sources: list[SourceReference] = []
    seen: set[tuple[str, int]] = set()
    for chunk in chunks:
        key = (chunk.pdf_path.name, chunk.page)
        if key in seen:
            continue
        seen.add(key)
        sources.append(
            SourceReference(
                pdf=chunk.pdf_path.name,
                page=chunk.page,
                reason=", ".join(chunk.reasons[:5]),
            )
        )
    return sources


def _status_for(
    building_right: BuildingRightSection,
    setup_issues: list[str],
) -> AnalysisStatus:
    if setup_issues and any("OCR" in issue or "ocr" in issue for issue in setup_issues):
        return AnalysisStatus.NEEDS_SETUP
    if building_right.needs_review:
        return AnalysisStatus.PARTIAL
    return AnalysisStatus.OK


@time_function
def analyze_pdfs(
    pdf_paths: list[Path],
    address: str,
    detail_plan: dict[str, Any] | None = None,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
) -> DetailPlanAnalysisResponse:
    detail_plan = detail_plan or {}
    logger.info(
        "Starting regex PDF analysis address=%s pdf_count=%s pdfs=%s detail_plan_id=%s force_refresh=%s",
        address,
        len(pdf_paths),
        [str(path) for path in pdf_paths],
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid"),
        force_refresh,
    )
    meta = DetailPlanMeta(
        address=address,
        detail_plan=detail_plan,
        source_pdfs=[path.name for path in pdf_paths],
        cache_dir=str(cache_dir) if cache_dir else None,
    )

    if not pdf_paths:
        logger.warning("No PDF paths supplied for analysis address=%s", address)
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NOT_FOUND,
            meta=meta,
            building_right=empty_building_right(),
            setup_issues=["Detailplaneeringu PDF-faile ei leitud."],
        )

    runtime = check_ocr_runtime()
    pages: list[PageText] = []
    setup_issues: list[str] = []
    try:
        for raw_pdf in pdf_paths:
            logger.info("Preparing PDF for text extraction pdf=%s", raw_pdf)
            working_pdf, ocr_used = prepare_pdf_for_text(
                raw_pdf,
                runtime=runtime,
                force_refresh=force_refresh,
            )
            meta.ocr_used = meta.ocr_used or ocr_used
            extracted = extract_pages_cached(working_pdf, force_refresh=force_refresh)
            logger.debug(
                "PDF extraction complete raw_pdf=%s working_pdf=%s ocr_used=%s pages=%s chars=%s",
                raw_pdf,
                working_pdf,
                ocr_used,
                len(extracted),
                sum(len(page.normalized_text) for page in extracted),
            )
            pages.extend(extracted)
    except OCRSetupError as exc:
        setup_issues.extend([f"OCR setup missing: {item}" for item in exc.missing])
        logger.warning("OCR setup missing for analysis missing=%s", exc.missing)
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NEEDS_SETUP,
            meta=meta,
            building_right=empty_building_right(),
            setup_issues=setup_issues,
        )

    chunks = select_relevant_chunks(pages, address)
    meta.chunks_sent = len(chunks)
    logger.info(
        "Chunk selection complete address=%s page_count=%s chunk_count=%s",
        address,
        len(pages),
        len(chunks),
    )
    find_address_lines(pages, address)

    building_right = (
        extract_building_rights(chunks) if chunks else empty_building_right()
    )
    if not chunks:
        setup_issues.append("PDFidest ei leitud regex-analüüsiks sobivaid tekstilehti.")

    response = DetailPlanAnalysisResponse(
        status=_status_for(building_right, setup_issues),
        meta=meta,
        building_right=building_right,
        sources=_sources_from_chunks(chunks),
        setup_issues=setup_issues,
    )
    logger.info(
        "Regex PDF analysis complete status=%s ocr_used=%s chunks_sent=%s missing=%s setup_issues=%s",
        response.status,
        response.meta.ocr_used,
        response.meta.chunks_sent,
        [review.key for review in response.building_right.needs_review],
        response.setup_issues,
    )
    return response


@time_function
def analyze_detail_plan(
    detail_plan: dict[str, Any],
    address: str,
    force_refresh: bool = False,
) -> DetailPlanAnalysisResponse:
    plan_dir = detail_plan_cache_dir(detail_plan)
    logger.info(
        "Analyzing detail plan address=%s plan_id=%s plan_name=%s cache_dir=%s force_refresh=%s",
        address,
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid"),
        detail_plan.get("plannim"),
        plan_dir,
        force_refresh,
    )
    try:
        pdf_paths = download_plan_pdfs(detail_plan, force_refresh=force_refresh)
    except (PDFDownloadError, ValueError) as exc:
        logger.warning("Failed loading detail-plan PDFs: %s", exc)
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NOT_FOUND,
            meta=DetailPlanMeta(
                address=address,
                detail_plan=detail_plan,
                cache_dir=str(plan_dir),
            ),
            building_right=empty_building_right(),
            setup_issues=[f"Detailplaneeringu PDF-faile ei saanud laadida: {exc}"],
        )
    return analyze_pdfs(
        pdf_paths=pdf_paths,
        address=address,
        detail_plan=detail_plan,
        cache_dir=plan_dir,
        force_refresh=force_refresh,
    )


@time_function
def highest_overlap_detail_plan(parcel) -> dict[str, Any] | None:
    detail_plans = parcel.get_detail_plans()
    items = detail_plans.get("items", [])
    logger.debug("Selecting highest-overlap detail plan count=%s", len(items))
    if not items:
        return None
    selected = sorted(
        items,
        key=lambda item: item.get("intersection_area_m2") or 0,
        reverse=True,
    )[0]
    logger.info(
        "Selected detail plan sysid=%s name=%s coverage_pct=%s intersection_area_m2=%s",
        selected.get("sysid"),
        selected.get("plannim"),
        selected.get("parcel_coverage_pct"),
        selected.get("intersection_area_m2"),
    )
    return selected


@time_function
def analyze_parcel_detail_plan(
    parcel,
    address: str,
    force_refresh: bool = False,
) -> DetailPlanAnalysisResponse:
    detail_plan = highest_overlap_detail_plan(parcel)
    if detail_plan is None:
        logger.warning("No overlapping detail plan found for address=%s", address)
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NOT_FOUND,
            meta=DetailPlanMeta(address=address),
            building_right=empty_building_right(),
            setup_issues=["Kinnistuga kattuvat detailplaneeringut ei leitud."],
        )
    return analyze_detail_plan(
        detail_plan,
        address,
        force_refresh=force_refresh,
    )


@time_function
def process_planning_pdf(pdf_path: str, address: str = "") -> dict:
    logger.info(
        "Processing single planning PDF with regex pdf_path=%s address=%s",
        pdf_path,
        address,
    )
    response = analyze_pdfs([Path(pdf_path)], address)
    return response.model_dump(mode="json")
