"""Cadastre-backed and derived-field enrichment for building-right results."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.detailplan_analyzer.field_state import (
    add_candidate,
    add_review,
    field_has_value,
    make_candidate,
    refresh_section_reviews,
    use_candidate,
)
from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    Evidence,
    ExtractedField,
    RegexCandidate,
    SourceType,
)
from backend.detailplan_analyzer.value_parsing import (
    float_or_none,
    format_number,
    values_close,
)

PARCEL_CONTEXT_KEYS = (
    "tunnus",
    "pindala",
    "siht1",
    "siht2",
    "siht3",
    "so_prts1",
    "so_prts2",
    "so_prts3",
    "omvorm",
)


@dataclass(frozen=True)
class EnrichmentPolicy:
    cadastre_area_mismatch_m2: float = 25
    cadastre_area_mismatch_ratio: float = 0.02
    cadastre_area_confidence: float = 0.85
    derived_value_confidence: float = 0.7
    derived_building_count_confidence: float = 0.65
    footprint_mismatch_m2: float = 5
    footprint_mismatch_ratio: float = 0.02
    coverage_mismatch_pct: float = 0.5


def compact_parcel_context(parcel_attributes: dict[str, Any] | None) -> dict[str, Any]:
    if not parcel_attributes:
        return {}

    context: dict[str, Any] = {}
    for key in PARCEL_CONTEXT_KEYS:
        value = parcel_attributes.get(key)
        if value is None or value == "":
            continue
        if hasattr(value, "item"):
            value = value.item()
        context[key] = value
    return context


class BuildingRightEnricher:
    """Adds non-PDF candidates and review notes after regex extraction.

    Regex candidates are intentionally kept as-is. Enrichment only appends
    cadastre and derived candidates, selects them when the PDF result is missing
    or clearly disagrees with authoritative parcel context, and refreshes the
    section-level review list.
    """

    def __init__(self, policy: EnrichmentPolicy | None = None) -> None:
        self.policy = policy or EnrichmentPolicy()

    def enrich(
        self,
        section: BuildingRightSection,
        parcel_attributes: dict[str, Any] | None = None,
    ) -> BuildingRightSection:
        parcel_context = compact_parcel_context(parcel_attributes)
        if parcel_context:
            self._enrich_from_cadastre(section.fields, parcel_context)
        self._enrich_coverage_and_footprint(section.fields)
        self._enrich_building_counts(section.fields)
        refresh_section_reviews(section)
        return section

    def _enrich_from_cadastre(
        self,
        fields: dict[str, ExtractedField],
        parcel_context: dict[str, Any],
    ) -> None:
        """Prefer cadastre area only when PDF area is missing or clearly mismatched."""
        area_field = fields.get("krundi_pind_m2")
        if area_field is None:
            return

        candidate = self._cadastre_area_candidate(area_field, parcel_context)
        if candidate is None:
            return

        add_candidate(area_field, candidate)
        pdf_candidate = next(
            (
                item
                for item in area_field.candidates
                if item.source_type != SourceType.CADASTRE
                and float_or_none(item.value) is not None
            ),
            None,
        )
        pdf_area = float_or_none(area_field.value)
        if pdf_area is None and pdf_candidate is not None:
            pdf_area = float_or_none(pdf_candidate.value)

        cadastre_area = float_or_none(candidate.value)
        if pdf_area is None or cadastre_area is None:
            if not field_has_value(area_field):
                use_candidate(area_field, candidate)
            return

        if values_close(
            pdf_area,
            cadastre_area,
            absolute=self.policy.cadastre_area_mismatch_m2,
            ratio=self.policy.cadastre_area_mismatch_ratio,
        ):
            if not field_has_value(area_field) and pdf_candidate is not None:
                use_candidate(area_field, pdf_candidate)
            return

        use_candidate(area_field, candidate)
        add_review(
            area_field,
            (
                "PDFi krundi pindala erineb katastri pindalast: "
                f"PDF {format_number(pdf_area)} m², "
                f"kataster {format_number(cadastre_area)} m²."
            ),
            candidate.evidence,
        )

    def _cadastre_area_candidate(
        self,
        field: ExtractedField,
        parcel_context: dict[str, Any],
    ) -> RegexCandidate | None:
        area = float_or_none(parcel_context.get("pindala"))
        if area is None:
            return None
        value = int(area) if area.is_integer() else area
        return make_candidate(
            field=field,
            value=value,
            unit="m2",
            source_type=SourceType.CADASTRE,
            pattern_name="cadastre_pindala",
            evidence_text=f"Katastri pindala: {format_number(area)} m².",
            confidence=self.policy.cadastre_area_confidence,
            raw_value=format_number(area),
        )

    def _enrich_coverage_and_footprint(
        self,
        fields: dict[str, ExtractedField],
    ) -> None:
        area = self._float_field(fields, "krundi_pind_m2")
        coverage = self._float_field(fields, "taisehitus_pct")
        footprint = self._float_field(fields, "ehitusalune_pind_m2")

        self._enrich_footprint_from_area_and_coverage(fields, area, coverage, footprint)
        self._enrich_coverage_from_area_and_footprint(fields, area, footprint, coverage)

    def _enrich_footprint_from_area_and_coverage(
        self,
        fields: dict[str, ExtractedField],
        area: float | None,
        coverage: float | None,
        footprint: float | None,
    ) -> None:
        footprint_field = fields.get("ehitusalune_pind_m2")
        if not (area and coverage and footprint_field is not None):
            return

        derived_footprint = round(area * coverage / 100, 2)
        evidence_text = (
            "Arvutatud: krundi pind "
            f"{format_number(area)} m² * täisehitus {format_number(coverage)}% "
            f"/ 100 = {format_number(derived_footprint)} m²."
        )
        candidate = self._derived_candidate(
            footprint_field,
            derived_footprint,
            "m2",
            "derived_from_area_and_coverage",
            evidence_text,
        )
        add_candidate(footprint_field, candidate)
        if not field_has_value(footprint_field):
            use_candidate(footprint_field, candidate)
            return

        if footprint is not None and not values_close(
            footprint,
            derived_footprint,
            absolute=self.policy.footprint_mismatch_m2,
            ratio=self.policy.footprint_mismatch_ratio,
        ):
            add_review(
                footprint_field,
                (
                    "Ehitusalune pind ei klapi krundi pindala ja täisehituse "
                    f"põhjal arvutatuga: PDF {format_number(footprint)} m², "
                    f"arvutus {format_number(derived_footprint)} m²."
                ),
                self._derived_evidence(evidence_text),
            )

    def _enrich_coverage_from_area_and_footprint(
        self,
        fields: dict[str, ExtractedField],
        area: float | None,
        footprint: float | None,
        coverage: float | None,
    ) -> None:
        coverage_field = fields.get("taisehitus_pct")
        if not (area and footprint and coverage_field is not None):
            return

        derived_coverage = round(footprint / area * 100, 2)
        evidence_text = (
            "Arvutatud: ehitusalune pind "
            f"{format_number(footprint)} m² / krundi pind "
            f"{format_number(area)} m² * 100 = {format_number(derived_coverage)}%."
        )
        candidate = self._derived_candidate(
            coverage_field,
            derived_coverage,
            "%",
            "derived_from_footprint_and_area",
            evidence_text,
        )
        add_candidate(coverage_field, candidate)
        if not field_has_value(coverage_field):
            use_candidate(coverage_field, candidate)
            return

        if (
            coverage is not None
            and abs(coverage - derived_coverage) > self.policy.coverage_mismatch_pct
        ):
            add_review(
                coverage_field,
                (
                    "Täisehituse protsent ei klapi krundi pindala ja ehitusaluse "
                    f"pinna põhjal arvutatuga: PDF {format_number(coverage)}%, "
                    f"arvutus {format_number(derived_coverage)}%."
                ),
                self._derived_evidence(evidence_text),
            )

    def _derived_candidate(
        self,
        field: ExtractedField,
        value: float | int,
        unit: str | None,
        pattern_name: str,
        evidence_text: str,
    ) -> RegexCandidate:
        return make_candidate(
            field=field,
            value=value,
            unit=unit,
            source_type=SourceType.DERIVED,
            pattern_name=pattern_name,
            evidence_text=evidence_text,
            confidence=self.policy.derived_value_confidence,
            raw_value=str(value),
        )

    def _enrich_building_counts(self, fields: dict[str, ExtractedField]) -> None:
        source = self._derived_building_count_source(fields)
        if source is None:
            return

        count, source_evidence = source
        evidence_text = f"Tuletatud hoonetüüpidest: {source_evidence.text}"
        field = fields.get("hoonete_arv")
        if field is None:
            return

        candidate = make_candidate(
            field=field,
            value=count,
            unit=None,
            source_type=SourceType.DERIVED,
            pattern_name="derived_from_floor_building_types",
            evidence_text=evidence_text,
            confidence=self.policy.derived_building_count_confidence,
            pdf=source_evidence.pdf,
            page=source_evidence.page,
            raw_value=str(count),
        )
        add_candidate(field, candidate)
        if not field_has_value(field):
            use_candidate(field, candidate)
            return

        existing_count = float_or_none(field.value)
        if existing_count is not None and int(existing_count) != count:
            add_review(
                field,
                (
                    "Hoonete arv erineb korruselisuse tekstist tuletatud arvust: "
                    f"väljal {int(existing_count)}, tuletatud {count}."
                ),
                candidate.evidence,
            )

    def _derived_building_count_source(
        self,
        fields: dict[str, ExtractedField],
    ) -> tuple[int, Evidence] | None:
        floors_field = fields.get("lubatud_korrused")
        if floors_field is None:
            return None

        evidence_items: list[Evidence] = []
        if floors_field.evidence is not None:
            evidence_items.append(floors_field.evidence)
        evidence_items.extend(candidate.evidence for candidate in floors_field.candidates)

        for evidence in evidence_items:
            count = self._safe_building_count_from_text(evidence.text)
            if count is not None:
                return count, evidence
        if floors_field.value is not None:
            count = self._safe_building_count_from_text(str(floors_field.value))
            if count is not None:
                return count, Evidence(text=str(floors_field.value))
        return None

    @staticmethod
    def _safe_building_count_from_text(text: str) -> int | None:
        low = text.lower()
        if "abihoone" not in low or "elamu" not in low:
            return None
        if "kortermaja" in low and "abihoone" not in low:
            return None

        building_types = set()
        if re.search(r"\belam\w*", low):
            building_types.add("elamu")
        if re.search(r"\babihoon\w*", low):
            building_types.add("abihoone")
        return len(building_types) if len(building_types) >= 2 else None

    @staticmethod
    def _derived_evidence(text: str) -> Evidence:
        return Evidence(pdf=None, page=None, text=text)

    @staticmethod
    def _float_field(fields: dict[str, ExtractedField], key: str) -> float | None:
        field = fields.get(key)
        if field is None:
            return None
        return float_or_none(field.value)
