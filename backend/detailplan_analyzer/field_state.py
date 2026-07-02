"""Small helpers for mutating extracted fields consistently."""

from __future__ import annotations

from typing import Any

from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    Evidence,
    ExtractedField,
    RegexCandidate,
    ReviewItem,
    SourceType,
)


def field_has_value(field: ExtractedField) -> bool:
    return field.value is not None and field.value != ""


def candidate_exists(field: ExtractedField, candidate: RegexCandidate) -> bool:
    return any(
        existing.source_type == candidate.source_type
        and existing.pattern_name == candidate.pattern_name
        and existing.raw_value == candidate.raw_value
        and existing.evidence.pdf == candidate.evidence.pdf
        and existing.evidence.page == candidate.evidence.page
        for existing in field.candidates
    )


def add_candidate(field: ExtractedField, candidate: RegexCandidate) -> None:
    if not candidate_exists(field, candidate):
        field.candidates.append(candidate)


def clear_missing_review(field: ExtractedField) -> None:
    field.needs_review = [
        review
        for review in field.needs_review
        if not review.message.startswith("PDFi valitud lehtedelt ei leitud")
    ]


def use_candidate(field: ExtractedField, candidate: RegexCandidate) -> None:
    add_candidate(field, candidate)
    field.value = candidate.value
    field.unit = candidate.unit
    field.confidence = candidate.confidence
    field.source_type = candidate.source_type
    field.evidence = candidate.evidence
    clear_missing_review(field)


def make_candidate(
    field: ExtractedField,
    value: Any,
    unit: str | None,
    source_type: SourceType,
    pattern_name: str,
    evidence_text: str,
    confidence: float,
    pdf: str | None = None,
    page: int | None = None,
    raw_value: str | None = None,
) -> RegexCandidate:
    raw = raw_value if raw_value is not None else str(value)
    return RegexCandidate(
        field_key=field.key,
        label=field.label,
        value=value,
        raw_value=raw,
        unit=unit,
        confidence=confidence,
        source_type=source_type,
        pattern_name=pattern_name,
        evidence=Evidence(pdf=pdf, page=page, text=evidence_text),
        score=round(confidence * 100, 2),
        quality="strong" if confidence >= 0.85 else "candidate",
        reasons=[f"source:{source_type.value}"],
        context=evidence_text,
    )


def add_review(
    field: ExtractedField,
    message: str,
    evidence: Evidence | None = None,
) -> None:
    if any(review.message == message for review in field.needs_review):
        return
    field.needs_review.append(
        ReviewItem(key=field.key, message=message, evidence=evidence)
    )


def refresh_section_reviews(section: BuildingRightSection) -> None:
    section.needs_review = [
        review for field in section.fields.values() for review in field.needs_review
    ]
