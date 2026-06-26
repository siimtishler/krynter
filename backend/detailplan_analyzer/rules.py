"""Configurable regex extraction for detail-plan building rights."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    Evidence,
    ExtractedField,
    RegexCandidate,
    ReviewItem,
)

ValueParser = Callable[[str], Any]


@dataclass(frozen=True)
class RegexPattern:
    name: str
    pattern: str
    confidence: float = 0.8


@dataclass(frozen=True)
class FieldSpec:
    key: str
    label: str
    unit: str | None
    patterns: tuple[RegexPattern, ...]
    parser: ValueParser | None = None


def parse_float(value: str) -> float:
    cleaned = value.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def parse_int(value: str) -> int:
    return int(round(parse_float(value)))


def parse_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip(" :;-.,")).strip()


def parse_code(value: str) -> str:
    return parse_text(value).upper().replace(" ", "")


def parse_roof_pitch(value: str) -> str:
    return parse_text(value).replace("–", "-").replace(" - ", "-")


def _line_for_match(text: str, match: re.Match) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:700]


def _raw_value(match: re.Match) -> str:
    groupdict = match.groupdict()
    if "value" in groupdict and groupdict["value"] is not None:
        return groupdict["value"]
    return match.group(1)


def _candidate_from_match(
    chunk: TextChunk,
    spec: FieldSpec,
    regex: RegexPattern,
    match: re.Match,
) -> RegexCandidate | None:
    raw = _raw_value(match)
    try:
        value = spec.parser(raw) if spec.parser else parse_text(raw)
    except (TypeError, ValueError):
        logger.debug(
            "Skipping regex candidate field=%s pattern=%s raw=%s",
            spec.key,
            regex.name,
            raw,
        )
        return None

    return RegexCandidate(
        field_key=spec.key,
        label=spec.label,
        value=value,
        raw_value=parse_text(raw),
        unit=spec.unit,
        confidence=regex.confidence,
        pattern_name=regex.name,
        evidence=Evidence(
            pdf=chunk.pdf_path.name,
            page=chunk.page,
            text=_line_for_match(chunk.text, match),
        ),
    )


def _best_candidate(candidates: list[RegexCandidate]) -> RegexCandidate | None:
    if not candidates:
        return None
    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate.confidence,
            candidate.evidence.pdf or "",
            candidate.evidence.page or 0,
        ),
    )[0]


FIELD_SPECS: tuple[FieldSpec, ...] = (
    FieldSpec(
        key="krundi_pind_m2",
        label="Krundi pind/suurus",
        unit="m2",
        parser=parse_float,
        patterns=(
            RegexPattern(
                "krundi_pind",
                r"\bkrundi\s+(?:pind|pindala|suurus)\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.95,
            ),
            RegexPattern(
                "maaüksuse_pindala",
                r"\bmaa(?:üksuse|tüki)?\s+pindala\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.85,
            ),
            RegexPattern(
                "pindala_near_krunt",
                r"\bpindala\D{0,30}(?P<value>\d[\d\s.,]*)\s*m(?:2|²).{0,60}\bkrunt",
                0.65,
            ),
        ),
    ),
    FieldSpec(
        key="taisehitus_pct",
        label="Täisehitus",
        unit="%",
        parser=parse_float,
        patterns=(
            RegexPattern(
                "taisehitus_protsent",
                r"\btäisehitus(?:e\s*protsent|protsent)?\D{0,40}(?P<value>\d+(?:[,.]\d+)?)\s*%",
                0.95,
            ),
            RegexPattern(
                "percent_near_taisehitus",
                r"(?P<value>\d+(?:[,.]\d+)?)\s*%\D{0,40}\btäisehitus",
                0.75,
            ),
        ),
    ),
    FieldSpec(
        key="brutopind_m2",
        label="Brutopind",
        unit="m2",
        parser=parse_float,
        patterns=(
            RegexPattern(
                "brutopind",
                r"\b(?:suletud\s+)?bruto\s*pind\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.9,
            ),
            RegexPattern(
                "brutopind_compact",
                r"\bbrutopind\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.9,
            ),
        ),
    ),
    FieldSpec(
        key="ehitusalune_pind_m2",
        label="Ehitusalune pind",
        unit="m2",
        parser=parse_float,
        patterns=(
            RegexPattern(
                "ehitusalune_pind",
                r"\b(?:ehitisealune|ehitusalune)\s+pind(?:\s+max)?\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.95,
            ),
            RegexPattern(
                "hoonete_alune_pind",
                r"\bhoonete\s+alune\s+pind\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.75,
            ),
        ),
    ),
    FieldSpec(
        key="lubatud_korrused",
        label="Lubatud korrused",
        unit=None,
        parser=parse_text,
        patterns=(
            RegexPattern(
                "korruselisus",
                r"\bkorruselisus\s*[:：-]?\s*(?P<value>[^\n.;]{1,140})",
                0.95,
            ),
            RegexPattern(
                "korruste_arv",
                r"\bkorruste\s+arv\s*[:：-]?\s*(?P<value>[^\n.;]{1,100})",
                0.85,
            ),
            RegexPattern(
                "korruseline",
                r"\b(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:maapealset\s*)?korrus(?:t|eline|elise)?)\b",
                0.55,
            ),
        ),
    ),
    FieldSpec(
        key="lubatud_majade_ehitamise_arv",
        label="Lubatud majade ehitamise arv",
        unit=None,
        parser=parse_int,
        patterns=(
            RegexPattern(
                "lubatud_hoonete_arv",
                r"\blubatud(?:\s+eraldiseisvate)?\s+(?:hoonete|majade)\s+arv\D{0,30}(?P<value>\d+)",
                0.95,
            ),
            RegexPattern(
                "lubatud_ehitada_hoonet",
                r"\blubatud.{0,50}\behitada\D{0,40}(?P<value>\d+)\s+(?:hoonet|maja)",
                0.75,
            ),
        ),
    ),
    FieldSpec(
        key="hoonete_lubatud_korgused_m",
        label="Hoonete lubatud kõrgused",
        unit="m",
        parser=parse_text,
        patterns=(
            RegexPattern(
                "hoonestuse_korgus",
                r"\b(?:maksimaalne\s*)?hoonestuse\s+kõrgus\s*[:：-]?\s*(?P<value>[^\n.;]{1,140})",
                0.95,
            ),
            RegexPattern(
                "hoone_korgus",
                r"\b(?:hoone\s*)?(?:maksimaalne\s*)?kõrgus\D{0,40}(?P<value>\d+(?:[,.]\d+)?)\s*m\b",
                0.65,
            ),
        ),
    ),
    FieldSpec(
        key="hoonete_arv",
        label="Hoonete arv",
        unit=None,
        parser=parse_int,
        patterns=(
            RegexPattern(
                "hoonete_arv",
                r"\bhoonete\s+arv\D{0,30}(?P<value>\d+)",
                0.9,
            ),
            RegexPattern(
                "planeeritud_hoonet",
                r"\bplaneeritud\s+(?P<value>\d+)\s+hoonet",
                0.7,
            ),
        ),
    ),
    FieldSpec(
        key="kasutusotstarve",
        label="Kasutusotstarve/sihtotstarve",
        unit=None,
        parser=parse_text,
        patterns=(
            RegexPattern(
                "sihtotstarve",
                r"\b(?:maakasutuse\s+)?sihtotstarve\s*[:：-]?\s*(?P<value>[^\n.;]{3,140})",
                0.95,
            ),
            RegexPattern(
                "kasutusotstarve",
                r"\bkasutusotstarve\s*[:：-]?\s*(?P<value>[^\n.;]{3,140})",
                0.9,
            ),
        ),
    ),
    FieldSpec(
        key="katusekalle",
        label="Katusekalle",
        unit="degrees",
        parser=parse_roof_pitch,
        patterns=(
            RegexPattern(
                "katuse_kalle",
                r"\bkatuse\s*kalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?(?:\s*°)?)",
                0.95,
            ),
            RegexPattern(
                "katusekalle",
                r"\bkatusekalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?(?:\s*°)?)",
                0.95,
            ),
        ),
    ),
    FieldSpec(
        key="tulepusivusklass",
        label="Tulepüsivusklass",
        unit=None,
        parser=parse_code,
        patterns=(
            RegexPattern(
                "tulepusivus_tp",
                r"\btulepüsivus(?:aste|klass)?\s*[:：-]?\s*(?P<value>TP\s*[-–]?\s*\d+)",
                0.95,
            ),
            RegexPattern(
                "tp_code",
                r"\b(?P<value>TP\s*[-–]?\s*\d+)\b",
                0.65,
            ),
        ),
    ),
)


def extract_field_candidates(
    chunks: list[TextChunk],
    spec: FieldSpec,
) -> list[RegexCandidate]:
    candidates: list[RegexCandidate] = []
    for chunk in chunks:
        for regex in spec.patterns:
            for match in re.finditer(
                regex.pattern,
                chunk.text,
                flags=re.IGNORECASE | re.MULTILINE,
            ):
                candidate = _candidate_from_match(chunk, spec, regex, match)
                if candidate is not None:
                    candidates.append(candidate)

    deduped: dict[tuple[int | None, str], RegexCandidate] = {}
    for candidate in candidates:
        key = (
            candidate.evidence.page,
            candidate.raw_value,
        )
        existing = deduped.get(key)
        if existing is None or candidate.confidence > existing.confidence:
            deduped[key] = candidate
    return list(deduped.values())


def extracted_field_from_candidates(
    spec: FieldSpec,
    candidates: list[RegexCandidate],
) -> ExtractedField:
    best = _best_candidate(candidates)
    if best is None:
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
    return ExtractedField(
        key=spec.key,
        label=spec.label,
        value=best.value,
        unit=spec.unit,
        confidence=best.confidence,
        source_type="regex",
        evidence=best.evidence,
        candidates=candidates,
    )


@time_function
def extract_building_rights(
    chunks: list[TextChunk],
    field_specs: tuple[FieldSpec, ...] = FIELD_SPECS,
) -> BuildingRightSection:
    logger.debug(
        "Running regex building-right extraction chunks=%s pages=%s",
        len(chunks),
        [(chunk.pdf_path.name, chunk.page) for chunk in chunks],
    )
    fields: dict[str, ExtractedField] = {}
    reviews: list[ReviewItem] = []
    for spec in field_specs:
        candidates = extract_field_candidates(chunks, spec)
        field = extracted_field_from_candidates(spec, candidates)
        fields[spec.key] = field
        reviews.extend(field.needs_review)

    logger.debug(
        "Regex building-right extracted=%s missing=%s",
        {
            key: {
                "value": field.value,
                "unit": field.unit,
                "candidates": len(field.candidates),
                "page": field.evidence.page if field.evidence else None,
            }
            for key, field in fields.items()
        },
        [review.key for review in reviews],
    )
    return BuildingRightSection(fields=fields, needs_review=reviews)


def run_rule_based_extractors(chunks: list[TextChunk]) -> BuildingRightSection:
    """Backward-compatible wrapper for old imports."""
    return extract_building_rights(chunks)
