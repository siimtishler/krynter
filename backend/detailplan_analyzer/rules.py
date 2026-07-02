"""Compatibility facade for detail-plan rule-based extraction.

The implementation is split across focused modules:
- `rule_specs` contains field metadata and regex patterns.
- `addressing` contains parcel-address parsing and matching.
- `candidate_scoring` scores and ranks PDF-derived candidates.
- `address_scoped` extracts candidates tied to the selected parcel address.
- `rule_engine` coordinates candidate generation and field selection.
- `enrichment` adds cadastre and derived candidates after extraction.
"""

from __future__ import annotations

from typing import Any

from backend.detailplan_analyzer.address_scoped import AddressScopedExtractor
from backend.detailplan_analyzer.addressing import (
    ParsedAddress,
    address_matches_text,
    normalize_address_key,
    parse_detail_address,
)
from backend.detailplan_analyzer.candidate_scoring import CandidateScorer
from backend.detailplan_analyzer.enrichment import (
    BuildingRightEnricher,
    EnrichmentPolicy,
    compact_parcel_context,
)
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    ExtractedField,
    RegexCandidate,
)
from backend.detailplan_analyzer.rule_engine import RuleBasedExtractor
from backend.detailplan_analyzer.rule_policies import (
    CandidateScoringPolicy,
    ExtractionPolicy,
)
from backend.detailplan_analyzer.rule_specs import (
    FIELD_SPECS,
    FieldSpec,
    RegexPattern,
    has_amount_text,
)
from backend.detailplan_analyzer.value_parsing import (
    clean_building_height_value,
    parse_code,
    parse_float,
    parse_int,
    parse_roof_pitch,
    parse_text,
)


def extract_field_candidates(
    chunks: list[TextChunk],
    spec: FieldSpec,
    target_address: ParsedAddress | None = None,
) -> list[RegexCandidate]:
    return RuleBasedExtractor().extract_field_candidates(
        chunks,
        spec,
        target_address=target_address,
    )


def extracted_field_from_candidates(
    spec: FieldSpec,
    candidates: list[RegexCandidate],
) -> ExtractedField:
    return RuleBasedExtractor().field_from_candidates(spec, candidates)


def enrich_building_rights(
    section: BuildingRightSection,
    parcel_attributes: dict[str, Any] | None = None,
) -> BuildingRightSection:
    return BuildingRightEnricher().enrich(section, parcel_attributes)


def extract_building_rights(
    chunks: list[TextChunk],
    field_specs: tuple[FieldSpec, ...] = FIELD_SPECS,
    parcel_attributes: dict[str, Any] | None = None,
    target_address: str | None = None,
) -> BuildingRightSection:
    return RuleBasedExtractor(field_specs=field_specs).extract(
        chunks,
        parcel_attributes=parcel_attributes,
        target_address=target_address,
    )


def run_rule_based_extractors(chunks: list[TextChunk]) -> BuildingRightSection:
    """Backward-compatible wrapper for old imports."""
    return extract_building_rights(chunks)


__all__ = [
    "AddressScopedExtractor",
    "BuildingRightEnricher",
    "CandidateScorer",
    "CandidateScoringPolicy",
    "EnrichmentPolicy",
    "ExtractionPolicy",
    "FIELD_SPECS",
    "FieldSpec",
    "ParsedAddress",
    "RegexPattern",
    "RuleBasedExtractor",
    "address_matches_text",
    "clean_building_height_value",
    "compact_parcel_context",
    "enrich_building_rights",
    "extract_building_rights",
    "extract_field_candidates",
    "extracted_field_from_candidates",
    "has_amount_text",
    "normalize_address_key",
    "parse_code",
    "parse_detail_address",
    "parse_float",
    "parse_int",
    "parse_roof_pitch",
    "parse_text",
    "run_rule_based_extractors",
]
