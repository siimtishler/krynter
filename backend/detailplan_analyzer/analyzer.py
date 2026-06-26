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
    detail_plan_id = (
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
    )
    logger.info(
        f"Starting regex PDF analysis address={address} "
        f"pdf_count={len(pdf_paths)} pdfs={[str(path) for path in pdf_paths]} "
        f"detail_plan_id={detail_plan_id} force_refresh={force_refresh}"
    )
    meta = DetailPlanMeta(
        address=address,
        detail_plan=detail_plan,
        source_pdfs=[path.name for path in pdf_paths],
        cache_dir=str(cache_dir) if cache_dir else None,
    )

    if not pdf_paths:
        logger.warning(f"No PDF paths supplied for analysis address={address}")
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
            logger.info(f"Preparing PDF for text extraction pdf={raw_pdf}")
            working_pdf, ocr_used = prepare_pdf_for_text(
                raw_pdf,
                runtime=runtime,
                force_refresh=force_refresh,
            )
            meta.ocr_used = meta.ocr_used or ocr_used
            extracted = extract_pages_cached(working_pdf, force_refresh=force_refresh)
            logger.debug(
                f"PDF extraction complete raw_pdf={raw_pdf} "
                f"working_pdf={working_pdf} ocr_used={ocr_used} "
                f"pages={len(extracted)} "
                f"chars={sum(len(page.normalized_text) for page in extracted)}"
            )
            pages.extend(extracted)
    except OCRSetupError as exc:
        setup_issues.extend([f"OCR setup missing: {item}" for item in exc.missing])
        logger.warning(f"OCR setup missing for analysis missing={exc.missing}")
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NEEDS_SETUP,
            meta=meta,
            building_right=empty_building_right(),
            setup_issues=setup_issues,
        )

    chunks = select_relevant_chunks(pages, address)
    meta.chunks_sent = len(chunks)
    logger.info(
        f"Chunk selection complete address={address} "
        f"page_count={len(pages)} chunk_count={len(chunks)}"
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
        f"Regex PDF analysis complete status={response.status} "
        f"ocr_used={response.meta.ocr_used} chunks_sent={response.meta.chunks_sent} "
        f"missing={[review.key for review in response.building_right.needs_review]} "
        f"setup_issues={response.setup_issues}"
    )
    return response


@time_function
def analyze_detail_plan(
    detail_plan: dict[str, Any],
    address: str,
    force_refresh: bool = False,
) -> DetailPlanAnalysisResponse:
    plan_dir = detail_plan_cache_dir(detail_plan)
    detail_plan_id = (
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
    )
    logger.info(
        f"Analyzing detail plan address={address} plan_id={detail_plan_id} "
        f"plan_name={detail_plan.get('plannim')} cache_dir={plan_dir} "
        f"force_refresh={force_refresh}"
    )
    try:
        pdf_paths = download_plan_pdfs(detail_plan, force_refresh=force_refresh)
    except (PDFDownloadError, ValueError) as exc:
        logger.warning(f"Failed loading detail-plan PDFs: {exc}")
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
    logger.debug(f"Selecting highest-overlap detail plan count={len(items)}")
    if not items:
        return None
    selected = sorted(
        items,
        key=lambda item: item.get("intersection_area_m2") or 0,
        reverse=True,
    )[0]
    logger.info(
        f"Selected detail plan sysid={selected.get('sysid')} "
        f"name={selected.get('plannim')} "
        f"coverage_pct={selected.get('parcel_coverage_pct')} "
        f"intersection_area_m2={selected.get('intersection_area_m2')}"
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
        logger.warning(f"No overlapping detail plan found for address={address}")
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
        f"Processing single planning PDF with regex pdf_path={pdf_path} "
        f"address={address}"
    )
    response = analyze_pdfs([Path(pdf_path)], address)
    return response.model_dump(mode="json")
