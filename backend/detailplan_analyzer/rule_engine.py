"""Rule-based extraction engine for detail-plan building rights."""

from __future__ import annotations

import re
from typing import Any

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.address_scoped import AddressScopedExtractor
from backend.detailplan_analyzer.addressing import (
    ParsedAddress,
    has_other_address_like_text,
    has_target_address,
    has_wrong_same_street_address,
    normalize_address_number,
    parse_detail_address,
    same_street_numbers,
    target_address_match,
)
from backend.detailplan_analyzer.candidate_scoring import CandidateScorer
from backend.detailplan_analyzer.enrichment import BuildingRightEnricher
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    Evidence,
    ExtractedField,
    RegexCandidate,
    ReviewItem,
    SourceType,
)
from backend.detailplan_analyzer.rule_policies import ExtractionPolicy
from backend.detailplan_analyzer.rule_specs import (
    FIELD_SPECS,
    FieldSpec,
    RegexPattern,
    has_amount_text,
)
from backend.detailplan_analyzer.value_parsing import parse_text


class RuleBasedExtractor:
    """Coordinates regex extraction, address-scoped candidates, and enrichment."""

    def __init__(
        self,
        field_specs: tuple[FieldSpec, ...] = FIELD_SPECS,
        extraction_policy: ExtractionPolicy | None = None,
        scorer: CandidateScorer | None = None,
        enricher: BuildingRightEnricher | None = None,
    ) -> None:
        self.field_specs = field_specs
        self.extraction_policy = extraction_policy or ExtractionPolicy()
        self.scorer = scorer or CandidateScorer()
        self.address_scoped_extractor = AddressScopedExtractor(self.extraction_policy)
        self.enricher = enricher or BuildingRightEnricher()

    @time_function
    def extract(
        self,
        chunks: list[TextChunk],
        parcel_attributes: dict[str, Any] | None = None,
        target_address: str | None = None,
    ) -> BuildingRightSection:
        """Return building-right fields from selected text chunks.

        The extractor first creates and ranks regex candidates per field, then
        fills only strong non-conflicting values. Cadastre and derived enrichers
        run after all PDF candidates are collected, so review notes can compare
        the full set of evidence.
        """
        logger.debug(
            f"Running regex building-right extraction chunks={len(chunks)} "
            f"pages={[(chunk.pdf_path.name, chunk.page) for chunk in chunks]}"
        )
        parsed_target_address = (
            parse_detail_address(target_address) if target_address else None
        )
        fields: dict[str, ExtractedField] = {}
        reviews: list[ReviewItem] = []
        for spec in self.field_specs:
            candidates = self.extract_field_candidates(
                chunks,
                spec,
                target_address=parsed_target_address,
            )
            field = self.field_from_candidates(spec, candidates)
            fields[spec.key] = field
            reviews.extend(field.needs_review)

        section = BuildingRightSection(fields=fields, needs_review=reviews)
        section = self.enricher.enrich(section, parcel_attributes)
        logger.debug(
            f"Regex building-right extracted={self._loggable_fields(section.fields)} "
            f"missing={[review.key for review in section.needs_review]}"
        )
        return section

    def extract_field_candidates(
        self,
        chunks: list[TextChunk],
        spec: FieldSpec,
        target_address: ParsedAddress | None = None,
    ) -> list[RegexCandidate]:
        """Collect, rank, and deduplicate all regex candidates for one field."""
        candidates: list[RegexCandidate] = []
        for chunk in chunks:
            if chunk.field_key is not None and chunk.field_key != spec.key:
                continue
            for regex in spec.patterns:
                for match in re.finditer(
                    regex.pattern,
                    chunk.text,
                    flags=re.IGNORECASE | re.MULTILINE,
                ):
                    candidate = self._candidate_from_match(
                        chunk,
                        spec,
                        regex,
                        match,
                        target_address=target_address,
                    )
                    if candidate is not None:
                        candidates.append(candidate)

        if target_address is not None:
            candidates.extend(
                self.address_scoped_extractor.extract(chunks, spec, target_address)
            )
        return self._dedupe_ranked_candidates(candidates)

    def field_from_candidates(
        self,
        spec: FieldSpec,
        candidates: list[RegexCandidate],
    ) -> ExtractedField:
        ranked = self.scorer.rank_candidates(candidates)
        if not ranked:
            review = ReviewItem(
                key=spec.key,
                message=f"PDFi valitud lehtedelt ei leitud välja: {spec.label}.",
            )
            return ExtractedField(
                key=spec.key,
                label=spec.label,
                unit=spec.unit,
                candidates=[],
                needs_review=[review],
            )

        best = ranked[0]
        if not self.scorer.candidate_can_fill_field(spec, best, ranked):
            review = ReviewItem(
                key=spec.key,
                message=(
                    f"Leiti nõrk või vastuoluline regex-kandidaat väljale "
                    f"{spec.label}; vajab LLM-i või käsitsi kontrolli."
                ),
                evidence=best.evidence,
            )
            return ExtractedField(
                key=spec.key,
                label=spec.label,
                unit=spec.unit,
                candidates=ranked,
                needs_review=[review],
            )

        return ExtractedField(
            key=spec.key,
            label=spec.label,
            value=best.value,
            unit=spec.unit,
            confidence=best.confidence,
            source_type=SourceType.REGEX,
            evidence=best.evidence,
            candidates=ranked,
        )

    def _candidate_from_match(
        self,
        chunk: TextChunk,
        spec: FieldSpec,
        regex: RegexPattern,
        match: re.Match,
        target_address: ParsedAddress | None = None,
    ) -> RegexCandidate | None:
        raw = self._raw_value(match)
        context = self._context_for_match(chunk.text, match)
        line = self._line_for_match(chunk.text, match)
        try:
            value = spec.parse_value(raw)
        except (TypeError, ValueError):
            logger.debug(
                f"Skipping regex candidate field={spec.key} pattern={regex.name} raw={raw}"
            )
            return None
        if not self._candidate_is_parseable_for_field(spec, value):
            logger.debug(
                f"Skipping unparseable candidate field={spec.key} "
                f"pattern={regex.name} raw={raw}"
            )
            return None

        reasons = self._candidate_reasons(
            chunk, spec, raw, line, context, target_address
        )
        return RegexCandidate(
            field_key=spec.key,
            label=spec.label,
            value=value,
            raw_value=parse_text(raw),
            unit=spec.unit,
            confidence=min(
                regex.confidence, self.extraction_policy.pdf_regex_confidence_cap
            ),
            pattern_name=regex.name,
            evidence=Evidence(
                pdf=chunk.pdf_path.name,
                page=chunk.page,
                text=line,
            ),
            reasons=reasons,
            context=context,
        )

    def _candidate_reasons(
        self,
        chunk: TextChunk,
        spec: FieldSpec,
        raw: str,
        line: str,
        context: str,
        target_address: ParsedAddress | None,
    ) -> list[str]:
        reasons = list(chunk.reasons)
        if target_address is None:
            return reasons

        reasons.append("target_address_available")
        candidate_text = " ".join([line, context])
        if has_target_address(target_address, candidate_text):
            reasons.append("target_address_context")
        if has_wrong_same_street_address(target_address, line):
            reasons.append("same_street_wrong_address")
        elif has_wrong_same_street_address(
            target_address, context
        ) and not has_target_address(
            target_address,
            line,
        ):
            reasons.append("context_wrong_address")
        if has_wrong_same_street_address(target_address, candidate_text):
            reasons.append("multi_address_context")
        if not has_target_address(
            target_address, candidate_text
        ) and has_other_address_like_text(line):
            reasons.append("other_address_context")
        if self._line_has_multiple_values(spec.key, line):
            reasons.append("multi_value_table_row")
        if spec.key in {"katusekalle", "hoonete_arv"} and normalize_address_number(
            parse_text(raw)
        ) in same_street_numbers(target_address, line):
            reasons.append("address_number_capture")

        target_match = target_address_match(target_address, line)
        raw_index = line.find(str(raw))
        if (
            spec.key == "hoonete_arv"
            and target_match is not None
            and raw_index != -1
            and raw_index < target_match.start()
        ):
            reasons.append("unscoped_before_target_address")
        return reasons

    def _dedupe_ranked_candidates(
        self,
        candidates: list[RegexCandidate],
    ) -> list[RegexCandidate]:
        ranked = self.scorer.rank_candidates(candidates)
        deduped: dict[tuple[str | None, int | None, str], RegexCandidate] = {}
        for candidate in ranked:
            key = (
                candidate.evidence.pdf,
                candidate.evidence.page,
                candidate.raw_value,
            )
            existing = deduped.get(key)
            if existing is None or (candidate.score or 0) > (existing.score or 0):
                deduped[key] = candidate
        return self.scorer.rank_candidates(list(deduped.values()))

    def _context_for_match(self, text: str, match: re.Match) -> str:
        lines = text.splitlines()
        if not lines:
            return text[: self.extraction_policy.match_context_chars]

        line_index = 0
        offset = 0
        for index, line in enumerate(lines):
            line_end = offset + len(line)
            if offset <= match.start() <= line_end:
                line_index = index
                break
            offset = line_end + 1

        start = max(0, line_index - self.extraction_policy.match_context_lines)
        end = min(
            len(lines), line_index + self.extraction_policy.match_context_lines + 1
        )
        return "\n".join(lines[start:end]).strip()[
            : self.extraction_policy.match_context_chars
        ]

    def _line_for_match(self, text: str, match: re.Match) -> str:
        start = text.rfind("\n", 0, match.start()) + 1
        end = text.find("\n", match.end())
        if end == -1:
            end = len(text)
        return text[start:end].strip()[: self.extraction_policy.evidence_line_chars]

    @staticmethod
    def _raw_value(match: re.Match) -> str:
        groupdict = match.groupdict()
        if "value" in groupdict and groupdict["value"] is not None:
            return groupdict["value"]
        return match.group(1)

    @staticmethod
    def _candidate_is_parseable_for_field(spec: FieldSpec, value: Any) -> bool:
        if spec.key == "lubatud_korrused":
            return has_amount_text(value)
        if spec.key == "hoonete_lubatud_korgused_m":
            low = str(value).lower()
            if not re.search(r"\d", low):
                return False
            if "kõrgus" in low and not re.search(r"\d+(?:[,.]\d+)?\s*m\b", low):
                return False
        return True

    @staticmethod
    def _line_has_multiple_values(field_key: str, line: str) -> bool:
        if field_key == "taisehitus_pct":
            return len(re.findall(r"\d+(?:[,.]\d+)?\s*%", line)) > 1
        if field_key.endswith("_m2"):
            return len(re.findall(r"\d[\d\s.,]*\s*m(?:2|²)\b", line)) > 1
        return False

    @staticmethod
    def _loggable_fields(
        fields: dict[str, ExtractedField],
    ) -> dict[str, dict[str, Any]]:
        return {
            key: {
                "value": field.value,
                "unit": field.unit,
                "candidates": len(field.candidates),
                "page": field.evidence.page if field.evidence else None,
            }
            for key, field in fields.items()
        }
