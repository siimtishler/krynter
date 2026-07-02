"""High-level detail-planning PDF analysis orchestration."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from backend.core.config import config
from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import (
    PageText,
    TextChunk,
    extract_pages_cached,
    find_address_lines,
    prepare_pdf_for_text,
    select_field_evidence_chunks,
    select_relevant_chunks,
)
from backend.detailplan_analyzer.llm_resolver import (
    LLMResolverProvider,
    OllamaResolverProvider,
    resolve_building_rights,
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
from backend.detailplan_analyzer.rules import (
    compact_parcel_context,
    extract_building_rights,
)


@dataclass(frozen=True)
class DetailPlanAnalysisOptions:
    cache_dir: Path | None = None
    force_refresh: bool = False
    enable_llm_resolver: bool | None = None
    llm_provider: LLMResolverProvider | None = None


def empty_building_right() -> BuildingRightSection:
    return BuildingRightSection()


def _detail_plan_id(detail_plan: dict[str, Any]) -> Any:
    return (
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
    )


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


class DetailPlanAnalyzerPipeline:
    """Runs the synchronous PDF-to-building-right analysis pipeline.

    The pipeline owns runtime options such as cache refresh and LLM resolver
    configuration. Public module-level functions create a pipeline and delegate
    to it so older imports keep working while the orchestration stays readable.
    """

    def __init__(self, options: DetailPlanAnalysisOptions | None = None) -> None:
        self.options = options or DetailPlanAnalysisOptions()

    def analyze_pdfs(
        self,
        pdf_paths: list[Path],
        address: str,
        detail_plan: dict[str, Any] | None = None,
        parcel_attributes: dict[str, Any] | None = None,
    ) -> DetailPlanAnalysisResponse:
        """Analyze already-local PDFs for one parcel address.

        This stage handles OCR/text extraction, chunk selection, deterministic
        rule extraction, optional LLM resolution, and final response assembly.
        Downloading is deliberately outside this method so tests and CLI runs
        can provide local PDFs directly.
        """
        detail_plan = detail_plan or {}
        logger.info(
            f"Starting regex PDF analysis address={address} "
            f"pdf_count={len(pdf_paths)} pdfs={[str(path) for path in pdf_paths]} "
            f"detail_plan_id={_detail_plan_id(detail_plan)} "
            f"force_refresh={self.options.force_refresh}"
        )
        meta = self._meta(
            address=address,
            detail_plan=detail_plan,
            parcel_attributes=parcel_attributes,
            pdf_paths=pdf_paths,
        )

        if not pdf_paths:
            logger.warning(f"No PDF paths supplied for analysis address={address}")
            return self._response_with_setup_issue(
                status=AnalysisStatus.NOT_FOUND,
                meta=meta,
                message="Detailplaneeringu PDF-faile ei leitud.",
            )

        try:
            pages = self._extract_pages(pdf_paths, meta)
        except OCRSetupError as exc:
            setup_issues = [f"OCR setup missing: {item}" for item in exc.missing]
            logger.warning(f"OCR setup missing for analysis missing={exc.missing}")
            return DetailPlanAnalysisResponse(
                status=AnalysisStatus.NEEDS_SETUP,
                meta=meta,
                building_right=empty_building_right(),
                setup_issues=setup_issues,
            )

        chunks = self._select_chunks(pages, address, meta)
        setup_issues: list[str] = []
        building_right = extract_building_rights(
            chunks,
            parcel_attributes=parcel_attributes,
            target_address=address,
        )
        if not chunks:
            setup_issues.append(
                "PDFidest ei leitud regex-analüüsiks sobivaid tekstilehti."
            )

        self._maybe_resolve_with_llm(
            building_right=building_right,
            parcel_context=meta.parcel_context,
            setup_issues=setup_issues,
            chunks=chunks,
        )

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

    def analyze_detail_plan(
        self,
        detail_plan: dict[str, Any],
        address: str,
        parcel_attributes: dict[str, Any] | None = None,
    ) -> DetailPlanAnalysisResponse:
        """Download/cache a detail plan and analyze its selected PDFs."""
        plan_dir = detail_plan_cache_dir(detail_plan)
        logger.info(
            f"Analyzing detail plan address={address} plan_id={_detail_plan_id(detail_plan)} "
            f"plan_name={detail_plan.get('plannim')} cache_dir={plan_dir} "
            f"force_refresh={self.options.force_refresh}"
        )
        try:
            pdf_paths = download_plan_pdfs(
                detail_plan,
                force_refresh=self.options.force_refresh,
            )
        except (PDFDownloadError, ValueError) as exc:
            logger.warning(f"Failed loading detail-plan PDFs: {exc}")
            return DetailPlanAnalysisResponse(
                status=AnalysisStatus.NOT_FOUND,
                meta=DetailPlanMeta(
                    address=address,
                    detail_plan=detail_plan,
                    parcel_context=compact_parcel_context(parcel_attributes),
                    cache_dir=str(plan_dir),
                ),
                building_right=empty_building_right(),
                setup_issues=[f"Detailplaneeringu PDF-faile ei saanud laadida: {exc}"],
            )

        return DetailPlanAnalyzerPipeline(
            replace(self.options, cache_dir=plan_dir)
        ).analyze_pdfs(
            pdf_paths=pdf_paths,
            address=address,
            detail_plan=detail_plan,
            parcel_attributes=parcel_attributes,
        )

    def _meta(
        self,
        address: str,
        detail_plan: dict[str, Any],
        parcel_attributes: dict[str, Any] | None,
        pdf_paths: list[Path],
    ) -> DetailPlanMeta:
        return DetailPlanMeta(
            address=address,
            detail_plan=detail_plan,
            parcel_context=compact_parcel_context(parcel_attributes),
            source_pdfs=[path.name for path in pdf_paths],
            cache_dir=str(self.options.cache_dir) if self.options.cache_dir else None,
        )

    def _extract_pages(
        self,
        pdf_paths: list[Path],
        meta: DetailPlanMeta,
    ) -> list[PageText]:
        pages: list[PageText] = []
        runtime = check_ocr_runtime()
        for raw_pdf in pdf_paths:
            logger.info(f"Preparing PDF for text extraction pdf={raw_pdf}")
            working_pdf, ocr_used = prepare_pdf_for_text(
                raw_pdf,
                runtime=runtime,
                force_refresh=self.options.force_refresh,
            )
            meta.ocr_used = meta.ocr_used or ocr_used
            extracted = extract_pages_cached(
                working_pdf,
                force_refresh=self.options.force_refresh,
            )
            logger.debug(
                f"PDF extraction complete raw_pdf={raw_pdf} "
                f"working_pdf={working_pdf} ocr_used={ocr_used} "
                f"pages={len(extracted)} "
                f"chars={sum(len(page.normalized_text) for page in extracted)}"
            )
            pages.extend(extracted)
        return pages

    def _select_chunks(
        self,
        pages: list[PageText],
        address: str,
        meta: DetailPlanMeta,
    ) -> list[TextChunk]:
        chunks = select_relevant_chunks(pages, address)
        field_chunks = select_field_evidence_chunks(pages)
        chunks.extend(field_chunks)
        meta.chunks_sent = len(chunks)
        logger.info(
            f"Chunk selection complete address={address} "
            f"page_count={len(pages)} chunk_count={len(chunks)} "
            f"field_chunk_count={len(field_chunks)}"
        )
        find_address_lines(pages, address)
        return chunks

    def _maybe_resolve_with_llm(
        self,
        building_right: BuildingRightSection,
        parcel_context: dict[str, Any],
        setup_issues: list[str],
        chunks: list[TextChunk],
    ) -> None:
        if not self._llm_resolver_enabled():
            return
        if setup_issues or not chunks:
            logger.info(
                "Skipping LLM resolver because setup issues or no chunks are present"
            )
            return

        provider = self.options.llm_provider or OllamaResolverProvider(
            base_url=config.ollama_base_url,
            model=config.ollama_building_right_model,
            timeout_s=config.ollama_timeout_s,
        )
        resolve_building_rights(
            building_right,
            parcel_context=parcel_context,
            provider=provider,
        )

    def _llm_resolver_enabled(self) -> bool:
        if self.options.enable_llm_resolver is not None:
            return self.options.enable_llm_resolver
        return config.detail_plan_llm_resolver_enabled

    @staticmethod
    def _response_with_setup_issue(
        status: AnalysisStatus,
        meta: DetailPlanMeta,
        message: str,
    ) -> DetailPlanAnalysisResponse:
        return DetailPlanAnalysisResponse(
            status=status,
            meta=meta,
            building_right=empty_building_right(),
            setup_issues=[message],
        )


@time_function
def analyze_pdfs(
    pdf_paths: list[Path],
    address: str,
    detail_plan: dict[str, Any] | None = None,
    parcel_attributes: dict[str, Any] | None = None,
    cache_dir: Path | None = None,
    force_refresh: bool = False,
    enable_llm_resolver: bool | None = None,
    llm_provider: LLMResolverProvider | None = None,
) -> DetailPlanAnalysisResponse:
    options = DetailPlanAnalysisOptions(
        cache_dir=cache_dir,
        force_refresh=force_refresh,
        enable_llm_resolver=enable_llm_resolver,
        llm_provider=llm_provider,
    )
    return DetailPlanAnalyzerPipeline(options).analyze_pdfs(
        pdf_paths=pdf_paths,
        address=address,
        detail_plan=detail_plan,
        parcel_attributes=parcel_attributes,
    )


@time_function
def analyze_detail_plan(
    detail_plan: dict[str, Any],
    address: str,
    parcel_attributes: dict[str, Any] | None = None,
    force_refresh: bool = False,
    enable_llm_resolver: bool | None = None,
    llm_provider: LLMResolverProvider | None = None,
) -> DetailPlanAnalysisResponse:
    options = DetailPlanAnalysisOptions(
        force_refresh=force_refresh,
        enable_llm_resolver=enable_llm_resolver,
        llm_provider=llm_provider,
    )
    return DetailPlanAnalyzerPipeline(options).analyze_detail_plan(
        detail_plan,
        address,
        parcel_attributes=parcel_attributes,
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
    enable_llm_resolver: bool | None = None,
    llm_provider: LLMResolverProvider | None = None,
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
        parcel_attributes=parcel.attributes(),
        force_refresh=force_refresh,
        enable_llm_resolver=enable_llm_resolver,
        llm_provider=llm_provider,
    )


@time_function
def process_planning_pdf(pdf_path: str, address: str = "") -> dict:
    logger.info(
        f"Processing single planning PDF with regex pdf_path={pdf_path} "
        f"address={address}"
    )
    response = analyze_pdfs([Path(pdf_path)], address)
    return response.model_dump(mode="json")
