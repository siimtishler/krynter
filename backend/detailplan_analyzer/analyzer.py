"""High-level detail-planning PDF analysis orchestration."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import (
    TextChunk,
    chunks_with_llm_text,
    extract_pages,
    find_address_lines,
    prepare_pdf_for_text,
    select_relevant_chunks,
)
from backend.detailplan_analyzer.llm import (
    LLMUnavailable,
    LLMValidationFailed,
    analyze_with_local_llm,
    ollama_model,
)
from backend.detailplan_analyzer.models import (
    AnalysisSection,
    AnalysisStatus,
    DetailPlanAnalysisResponse,
    DetailPlanMeta,
    Evidence,
    Fact,
    ReviewItem,
    SourceReference,
    StructuredLLMResponse,
)
from backend.detailplan_analyzer.pdfs import (
    OCRSetupError,
    PDFDownloadError,
    check_ocr_runtime,
    detail_plan_cache_dir,
    download_plan_pdfs,
)
from backend.detailplan_analyzer.rules import RuleExtraction, run_rule_based_extractors

SECTION_TITLES = {
    "luhikokkuvote": "Lühikokkuvõte",
    "ehitamise_pohioigus": "Ehitamise põhiõigus",
    "arhitektuursed_tingimused": "Arhitektuursed tingimused",
    "haljastus_ja_keskkond": "Haljastus ja keskkond",
    "juurdepaas_ja_parkimine": "Juurdepääs ja parkimine",
    "tehnovorgud": "Tehnovõrgud",
    "servituudid_ja_kitsendused": "Servituudid ja kitsendused",
    "mis_puudub_voi_vajab_ule_kontrollimist": "Mis puudub või vajab üle kontrollimist",
    "ostja_riskid": "Ostja riskid",
    "allikad_lehekuljeviited": "Allikad / leheküljeviited",
}

REQUIRED_BUILDING_RIGHT = {
    "krundi_suurus": "krundi suurus",
    "kasutusotstarve": "kasutusotstarve",
    "korruselisus": "korruselisus",
    "taisehitus": "täisehitus",
    "korgus": "kõrgus",
    "hoonete_arv": "hoonete arv",
}

RULE_TO_LLM_FIELD = {
    "krundi_suurus": ("parcel_area_m2", "m2"),
    "kasutusotstarve": ("use_purpose", None),
    "korruselisus": ("floors", None),
    "taisehitus": ("site_coverage_pct", "%"),
    "korgus": ("height_m", "m"),
    "hoonete_arv": ("building_count", None),
}


def default_sections() -> dict[str, AnalysisSection]:
    return {key: AnalysisSection(title=title) for key, title in SECTION_TITLES.items()}


def _review(
    key: str,
    message: str,
    evidence: Evidence | None = None,
) -> ReviewItem:
    return ReviewItem(key=key, message=message, evidence=evidence)


def _number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.replace("\xa0", " ").replace(" ", "").replace(",", ".")
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _material_conflict(rule_value: Any, llm_value: Any) -> bool:
    rule_number = _number(rule_value)
    llm_number = _number(llm_value)
    if rule_number is not None and llm_number is not None:
        return abs(rule_number - llm_number) > max(0.5, abs(rule_number) * 0.05)
    return str(rule_value).strip().lower() != str(llm_value).strip().lower()


def _evidence_from_llm(
    page: int | None,
    evidence_text: str | None,
    chunks: list[TextChunk],
) -> Evidence | None:
    if page is None and not evidence_text:
        return None
    pdf = None
    if page is not None:
        matching_chunk = next((chunk for chunk in chunks if chunk.page == page), None)
        if matching_chunk:
            pdf = matching_chunk.pdf_path.name
    return Evidence(
        pdf=pdf, page=page, text=(evidence_text or "LLM page citation")[:700]
    )


def _add_llm_claims(
    sections: dict[str, AnalysisSection],
    section_key: str,
    label: str,
    claims,
    chunks: list[TextChunk],
) -> None:
    for index, claim in enumerate(claims, start=1):
        evidence = _evidence_from_llm(claim.page, claim.evidence_text, chunks)
        if evidence is None:
            sections[section_key].needs_review.append(
                _review(
                    f"{section_key}_llm_claim_{index}",
                    "LLM väitel puudus leheküljeviide või tõenditekst.",
                )
            )
            continue
        sections[section_key].found_in_pdf.append(
            Fact(
                key=f"{section_key}_llm_claim_{index}",
                label=label,
                value=claim.text,
                confidence=claim.confidence,
                source_type="llm",
                evidence=evidence,
            )
        )


def _llm_building_fact(
    field_key: str,
    label: str,
    unit: str | None,
    llm_value,
    chunks: list[TextChunk],
) -> Fact | None:
    if llm_value.value is None:
        return None
    evidence = _evidence_from_llm(llm_value.page, llm_value.evidence_text, chunks)
    if evidence is None:
        return None
    return Fact(
        key=field_key,
        label=label,
        value=llm_value.value,
        unit=unit,
        confidence=llm_value.confidence,
        source_type="llm",
        evidence=evidence,
    )


def _merge_building_right(
    sections: dict[str, AnalysisSection],
    rule_based: RuleExtraction,
    llm_result: StructuredLLMResponse | None,
    chunks: list[TextChunk],
) -> None:
    building_section = sections["ehitamise_pohioigus"]
    found_keys: set[str] = set()

    for key, label_text in REQUIRED_BUILDING_RIGHT.items():
        rule_fact = rule_based.building_right.get(key)
        llm_fact = None
        if llm_result:
            llm_field, unit = RULE_TO_LLM_FIELD[key]
            llm_value = getattr(llm_result.building_right, llm_field)
            llm_fact = _llm_building_fact(
                key,
                rule_fact.label if rule_fact else label_text,
                unit,
                llm_value,
                chunks,
            )

        if rule_fact:
            building_section.found_in_pdf.append(rule_fact)
            found_keys.add(key)
            if llm_fact and _material_conflict(rule_fact.value, llm_fact.value):
                building_section.needs_review.append(
                    _review(
                        key,
                        (
                            "Regex ja LLM leidsid erinevad väärtused: "
                            f"{rule_fact.value!r} vs {llm_fact.value!r}."
                        ),
                        evidence=llm_fact.evidence,
                    )
                )
        elif llm_fact:
            building_section.found_in_pdf.append(llm_fact)
            found_keys.add(key)

    area_fact = next(
        (fact for fact in building_section.found_in_pdf if fact.key == "krundi_suurus"),
        None,
    )
    coverage_fact = next(
        (fact for fact in building_section.found_in_pdf if fact.key == "taisehitus"),
        None,
    )
    area = _number(area_fact.value if area_fact else None)
    coverage = _number(coverage_fact.value if coverage_fact else None)
    if area is not None and coverage is not None:
        building_section.found_in_pdf.append(
            Fact(
                key="ehitisealune_pind_tuletatud",
                label="Tuletatud ehitisealune pind",
                value=round(area * coverage / 100, 2),
                unit="m2",
                confidence=min(area_fact.confidence, coverage_fact.confidence),
                source_type="derived",
                evidence=Evidence(
                    text=(
                        f"Arvutatud: krundi suurus {area:g} m2 × "
                        f"täisehitus {coverage:g}%."
                    )
                ),
            )
        )

    missing_section = sections["mis_puudub_voi_vajab_ule_kontrollimist"]
    for key, label_text in REQUIRED_BUILDING_RIGHT.items():
        if key not in found_keys:
            review = _review(
                key, f"PDFi valitud chunk'idest ei leitud välja: {label_text}."
            )
            building_section.needs_review.append(review)
            missing_section.needs_review.append(review)


def _merge_sections(
    sections: dict[str, AnalysisSection],
    rule_based: RuleExtraction,
    llm_result: StructuredLLMResponse | None,
    chunks: list[TextChunk],
) -> None:
    for section_key, facts in rule_based.section_facts.items():
        sections[section_key].found_in_pdf.extend(facts)

    if not llm_result:
        return

    if llm_result.summary:
        sections["luhikokkuvote"].found_in_pdf.append(
            Fact(
                key="kokkuvote",
                label="Lühikokkuvõte",
                value=llm_result.summary,
                confidence=0.55,
                source_type="llm",
                evidence=Evidence(text="LLM kokkuvõte valitud PDFi chunk'ide põhjal."),
            )
        )

    _add_llm_claims(
        sections,
        "arhitektuursed_tingimused",
        "Arhitektuurne tingimus",
        llm_result.architecture,
        chunks,
    )
    _add_llm_claims(
        sections,
        "haljastus_ja_keskkond",
        "Haljastus ja keskkond",
        llm_result.landscaping_environment,
        chunks,
    )
    _add_llm_claims(
        sections,
        "juurdepaas_ja_parkimine",
        "Juurdepääs ja parkimine",
        llm_result.access_parking,
        chunks,
    )
    _add_llm_claims(
        sections, "tehnovorgud", "Tehnovõrgud", llm_result.utilities, chunks
    )
    _add_llm_claims(
        sections,
        "servituudid_ja_kitsendused",
        "Servituut või kitsendus",
        llm_result.servitudes_restrictions,
        chunks,
    )
    _add_llm_claims(
        sections, "ostja_riskid", "Ostja risk", llm_result.buyer_risks, chunks
    )

    for index, item in enumerate(llm_result.missing_or_needs_review, start=1):
        sections["mis_puudub_voi_vajab_ule_kontrollimist"].needs_review.append(
            _review(f"llm_review_{index}", item)
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
    sections: dict[str, AnalysisSection],
    setup_issues: list[str],
    llm_failed: bool,
) -> AnalysisStatus:
    if setup_issues and any("OCR" in issue or "ocr" in issue for issue in setup_issues):
        return AnalysisStatus.NEEDS_SETUP
    if llm_failed:
        return AnalysisStatus.LLM_UNAVAILABLE
    if any(section.needs_review for section in sections.values()):
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
        "Starting PDF analysis address=%s pdf_count=%s pdfs=%s detail_plan_id=%s force_refresh=%s",
        address,
        len(pdf_paths),
        [str(path) for path in pdf_paths],
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid"),
        force_refresh,
    )
    sections = default_sections()
    meta = DetailPlanMeta(
        address=address,
        detail_plan=detail_plan,
        source_pdfs=[path.name for path in pdf_paths],
        ollama_model=ollama_model(),
        cache_dir=str(cache_dir) if cache_dir else None,
    )

    if not pdf_paths:
        logger.warning("No PDF paths supplied for analysis address=%s", address)
        return DetailPlanAnalysisResponse(
            status=AnalysisStatus.NOT_FOUND,
            meta=meta,
            sections=sections,
            setup_issues=["Detailplaneeringu PDF-faile ei leitud."],
        )

    runtime = check_ocr_runtime()
    pages = []
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
            extracted = extract_pages(working_pdf)
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
            sections=sections,
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

    address_lines = find_address_lines(pages, address)
    for index, evidence in enumerate(address_lines[:5], start=1):
        sections["luhikokkuvote"].found_in_pdf.append(
            Fact(
                key=f"aadressi_rida_{index}",
                label="Aadressiga seotud rida",
                value=evidence.text,
                confidence=0.8,
                source_type="pdf",
                evidence=evidence,
            )
        )

    rule_based = run_rule_based_extractors(chunks)
    logger.info(
        "Rule extraction complete building_right_keys=%s section_fact_counts=%s",
        sorted(rule_based.building_right.keys()),
        {
            section_key: len(facts)
            for section_key, facts in rule_based.section_facts.items()
        },
    )
    llm_result: StructuredLLMResponse | None = None
    llm_failed = False
    llm_chunks = chunks_with_llm_text(chunks) if chunks else []
    if llm_chunks:
        try:
            logger.info(
                "Sending chunks to LLM chunk_count=%s total_chars=%s",
                len(llm_chunks),
                sum(len(chunk.text) for chunk in llm_chunks),
            )
            llm_result = analyze_with_local_llm(address, llm_chunks)
        except (LLMUnavailable, LLMValidationFailed) as exc:
            llm_failed = True
            logger.warning("LLM analysis unavailable: %s", exc)
            setup_issues.append(f"Ollama analysis unavailable: {exc}")
    else:
        logger.warning("No chunks available for LLM analysis")
        setup_issues.append("PDFidest ei leitud analüüsiks sobivaid tekstichunk'e.")

    _merge_building_right(sections, rule_based, llm_result, llm_chunks or chunks)
    _merge_sections(sections, rule_based, llm_result, llm_chunks or chunks)
    sources = _sources_from_chunks(llm_chunks or chunks)
    for source in sources:
        sections["allikad_lehekuljeviited"].found_in_pdf.append(
            Fact(
                key="source_page",
                label="Allikas",
                value=f"{source.pdf}, lk {source.page}",
                confidence=1.0,
                source_type="pdf",
                evidence=Evidence(
                    pdf=source.pdf,
                    page=source.page,
                    text=source.reason,
                ),
            )
        )

    response = DetailPlanAnalysisResponse(
        status=_status_for(sections, setup_issues, llm_failed),
        meta=meta,
        sections=sections,
        sources=sources,
        setup_issues=setup_issues,
    )
    logger.info(
        "PDF analysis complete status=%s ocr_used=%s chunks_sent=%s setup_issues=%s",
        response.status,
        response.meta.ocr_used,
        response.meta.chunks_sent,
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
            sections=default_sections(),
            setup_issues=[f"Detailplaneeringu PDF-faile ei saanud laadida: {exc}"],
        )
    return analyze_pdfs(
        pdf_paths=pdf_paths,
        address=address,
        detail_plan=detail_plan,
        cache_dir=plan_dir,
        force_refresh=force_refresh,
    )


# TODO Move to geo
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
            sections=default_sections(),
            setup_issues=["Kinnistuga kattuvat detailplaneeringut ei leitud."],
        )
    return analyze_detail_plan(detail_plan, address, force_refresh=force_refresh)


@time_function
def process_planning_pdf(pdf_path: str, address: str) -> dict:
    logger.info(
        "Processing single planning PDF pdf_path=%s address=%s", pdf_path, address
    )
    response = analyze_pdfs([Path(pdf_path)], address)
    return response.model_dump(mode="json")
