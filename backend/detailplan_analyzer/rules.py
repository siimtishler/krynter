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
    SourceType,
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


def parse_land_use(value: str) -> str:
    cleaned = parse_text(value)
    low = cleaned.lower()
    if low in {"ja suurus", "ning suurus", "suurus"}:
        raise ValueError("Heading fragment is not a land-use value")

    parenthesized = re.search(
        r"\(([^)]*(?:maa|eramu|elamu|äri|tootmis|ühiskond)[^)]*)\)",
        cleaned,
        flags=re.IGNORECASE,
    )
    if parenthesized:
        cleaned = parenthesized.group(1)

    cleaned = re.split(r"\s+ei\s+", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    cleaned = parse_text(cleaned)
    if not cleaned:
        raise ValueError("Empty land-use value")
    return normalize_land_use_text(cleaned)


def parse_code(value: str) -> str:
    return parse_text(value).upper().replace(" ", "")


def parse_roof_pitch(value: str) -> str:
    cleaned = parse_text(value)
    cleaned = cleaned.replace("–", "-")
    cleaned = cleaned.replace("˚", "").replace("°", "")
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"\s*/\s*", " või ", cleaned)
    cleaned = re.sub(r"\s*,\s*", " või ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def normalize_land_use_text(value: str) -> str:
    cleaned = parse_text(value)
    cleaned = re.sub(r"\s*%\s*", "%", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.lower()


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
            f"Skipping regex candidate field={spec.key} pattern={regex.name} raw={raw}"
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
                "kinnistu_suurus",
                r"\b(?:kinnistu|krunt)\s+(?:on\s+)?suurusega\D{0,20}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                0.9,
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
        parser=parse_land_use,
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
                r"\bkatuse\s*kalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:[˚°])?(?:\s*(?:või|ja|/|,)\s*\d+\s*(?:[-–]\s*\d+)?\s*(?:[˚°])?)*)",
                0.95,
            ),
            RegexPattern(
                "katusekalle",
                r"\bkatusekalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:[˚°])?(?:\s*(?:või|ja|/|,)\s*\d+\s*(?:[-–]\s*\d+)?\s*(?:[˚°])?)*)",
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
    FieldSpec(
        key="omandivorm",
        label="Omandivorm",
        unit=None,
        parser=parse_text,
        patterns=(
            RegexPattern(
                "omandivorm",
                r"\bomandivorm\s*[:：-]?\s*(?P<value>[^\n.;]{3,80})",
                0.9,
            ),
            RegexPattern(
                "known_omandivorm",
                r"\b(?P<value>eraomand|eramaa|munitsipaalomand|riigiomand)\b",
                0.6,
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


def _field_has_value(field: ExtractedField) -> bool:
    return field.value is not None and field.value != ""


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return parse_float(str(value))
    except ValueError:
        return None


def _float_field(fields: dict[str, ExtractedField], key: str) -> float | None:
    field = fields.get(key)
    if field is None:
        return None
    return _float_or_none(field.value)


def _format_number(value: float) -> str:
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def _values_close(left: float, right: float, absolute: float, ratio: float = 0) -> bool:
    tolerance = max(absolute, abs(left) * ratio, abs(right) * ratio)
    return abs(left - right) <= tolerance


def _candidate_exists(field: ExtractedField, candidate: RegexCandidate) -> bool:
    return any(
        existing.source_type == candidate.source_type
        and existing.pattern_name == candidate.pattern_name
        and existing.raw_value == candidate.raw_value
        for existing in field.candidates
    )


def _add_candidate(field: ExtractedField, candidate: RegexCandidate) -> None:
    if not _candidate_exists(field, candidate):
        field.candidates.append(candidate)


def _clear_missing_review(field: ExtractedField) -> None:
    field.needs_review = [
        review
        for review in field.needs_review
        if not review.message.startswith("PDFi valitud lehtedelt ei leitud")
    ]


def _use_candidate(field: ExtractedField, candidate: RegexCandidate) -> None:
    _add_candidate(field, candidate)
    field.value = candidate.value
    field.unit = candidate.unit
    field.confidence = candidate.confidence
    field.source_type = candidate.source_type
    field.evidence = candidate.evidence
    _clear_missing_review(field)


def _make_candidate(
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
    )


def _review(
    field: ExtractedField,
    message: str,
    evidence: Evidence | None = None,
) -> None:
    if any(review.message == message for review in field.needs_review):
        return
    field.needs_review.append(
        ReviewItem(key=field.key, message=message, evidence=evidence)
    )


def _cadastre_area_candidate(
    field: ExtractedField,
    parcel_context: dict[str, Any],
) -> RegexCandidate | None:
    area = _float_or_none(parcel_context.get("pindala"))
    if area is None:
        return None
    value = int(area) if area.is_integer() else area
    return _make_candidate(
        field=field,
        value=value,
        unit="m2",
        source_type=SourceType.CADASTRE,
        pattern_name="cadastre_pindala",
        evidence_text=f"Katastri pindala: {_format_number(area)} m².",
        confidence=0.85,
        raw_value=_format_number(area),
    )


def _cadastre_land_use(parcel_context: dict[str, Any]) -> str | None:
    parts: list[str] = []
    for index in range(1, 4):
        use = parcel_context.get(f"siht{index}")
        if not use:
            continue
        value = normalize_land_use_text(str(use))
        pct = _float_or_none(parcel_context.get(f"so_prts{index}"))
        if pct and pct > 0:
            value = f"{value} {_format_number(pct)}%"
        parts.append(value)
    return ", ".join(parts) if parts else None


def _land_use_terms(value: Any) -> set[str]:
    return {
        match.group(0)
        for match in re.finditer(
            r"[a-zõäöü]+maa|eramu|elamu|äri|tootmis|ühiskond",
            str(value).lower(),
        )
    }


def _cadastre_land_use_candidate(
    field: ExtractedField,
    parcel_context: dict[str, Any],
) -> RegexCandidate | None:
    land_use = _cadastre_land_use(parcel_context)
    if not land_use:
        return None
    return _make_candidate(
        field=field,
        value=land_use,
        unit=None,
        source_type=SourceType.CADASTRE,
        pattern_name="cadastre_sihtotstarve",
        evidence_text=f"Katastri sihtotstarve: {land_use}.",
        confidence=0.85,
        raw_value=land_use,
    )


def _cadastre_ownership_candidate(
    field: ExtractedField,
    parcel_context: dict[str, Any],
) -> RegexCandidate | None:
    ownership = parcel_context.get("omvorm")
    if not ownership:
        return None
    value = parse_text(str(ownership))
    return _make_candidate(
        field=field,
        value=value,
        unit=None,
        source_type=SourceType.CADASTRE,
        pattern_name="cadastre_omvorm",
        evidence_text=f"Katastri omandivorm: {value}.",
        confidence=0.85,
        raw_value=value,
    )


def _enrich_from_cadastre(
    fields: dict[str, ExtractedField],
    parcel_context: dict[str, Any],
) -> None:
    area_field = fields.get("krundi_pind_m2")
    if area_field is not None:
        candidate = _cadastre_area_candidate(area_field, parcel_context)
        if candidate is not None:
            _add_candidate(area_field, candidate)
            pdf_area = _float_or_none(area_field.value)
            cadastre_area = _float_or_none(candidate.value)
            if not _field_has_value(area_field):
                _use_candidate(area_field, candidate)
            elif pdf_area is not None and cadastre_area is not None:
                if not _values_close(pdf_area, cadastre_area, absolute=25, ratio=0.02):
                    _review(
                        area_field,
                        (
                            "PDFi krundi pindala erineb katastri pindalast: "
                            f"PDF {_format_number(pdf_area)} m², "
                            f"kataster {_format_number(cadastre_area)} m²."
                        ),
                        candidate.evidence,
                    )

    land_use_field = fields.get("kasutusotstarve")
    if land_use_field is not None:
        candidate = _cadastre_land_use_candidate(land_use_field, parcel_context)
        if candidate is not None:
            _add_candidate(land_use_field, candidate)
            if not _field_has_value(land_use_field):
                _use_candidate(land_use_field, candidate)
            else:
                pdf_terms = _land_use_terms(land_use_field.value)
                cadastre_terms = _land_use_terms(candidate.value)
                if cadastre_terms and not pdf_terms.intersection(cadastre_terms):
                    _use_candidate(land_use_field, candidate)
                    _review(
                        land_use_field,
                        "PDFi kasutusotstarve ei kattunud katastri sihtotstarbega.",
                        candidate.evidence,
                    )

    ownership_field = fields.get("omandivorm")
    if ownership_field is not None:
        candidate = _cadastre_ownership_candidate(ownership_field, parcel_context)
        if candidate is not None:
            _add_candidate(ownership_field, candidate)
            if not _field_has_value(ownership_field):
                _use_candidate(ownership_field, candidate)


def _derived_evidence(text: str) -> Evidence:
    return Evidence(pdf=None, page=None, text=text)


def _derived_candidate(
    field: ExtractedField,
    value: float | int,
    unit: str | None,
    pattern_name: str,
    evidence_text: str,
) -> RegexCandidate:
    return _make_candidate(
        field=field,
        value=value,
        unit=unit,
        source_type=SourceType.DERIVED,
        pattern_name=pattern_name,
        evidence_text=evidence_text,
        confidence=0.7,
        raw_value=str(value),
    )


def _enrich_coverage_and_footprint(fields: dict[str, ExtractedField]) -> None:
    area = _float_field(fields, "krundi_pind_m2")
    coverage = _float_field(fields, "taisehitus_pct")
    footprint = _float_field(fields, "ehitusalune_pind_m2")

    footprint_field = fields.get("ehitusalune_pind_m2")
    if area and coverage and footprint_field is not None:
        derived_footprint = round(area * coverage / 100, 2)
        evidence_text = (
            "Arvutatud: krundi pind "
            f"{_format_number(area)} m² * täisehitus {_format_number(coverage)}% "
            f"/ 100 = {_format_number(derived_footprint)} m²."
        )
        candidate = _derived_candidate(
            footprint_field,
            derived_footprint,
            "m2",
            "derived_from_area_and_coverage",
            evidence_text,
        )
        _add_candidate(footprint_field, candidate)
        if not _field_has_value(footprint_field):
            _use_candidate(footprint_field, candidate)
        elif footprint is not None and not _values_close(
            footprint,
            derived_footprint,
            absolute=5,
            ratio=0.02,
        ):
            _review(
                footprint_field,
                (
                    "Ehitusalune pind ei klapi krundi pindala ja täisehituse "
                    f"põhjal arvutatuga: PDF {_format_number(footprint)} m², "
                    f"arvutus {_format_number(derived_footprint)} m²."
                ),
                _derived_evidence(evidence_text),
            )

    coverage_field = fields.get("taisehitus_pct")
    if area and footprint and coverage_field is not None:
        derived_coverage = round(footprint / area * 100, 2)
        evidence_text = (
            "Arvutatud: ehitusalune pind "
            f"{_format_number(footprint)} m² / krundi pind "
            f"{_format_number(area)} m² * 100 = {_format_number(derived_coverage)}%."
        )
        candidate = _derived_candidate(
            coverage_field,
            derived_coverage,
            "%",
            "derived_from_footprint_and_area",
            evidence_text,
        )
        _add_candidate(coverage_field, candidate)
        if not _field_has_value(coverage_field):
            _use_candidate(coverage_field, candidate)
        elif coverage is not None and abs(coverage - derived_coverage) > 0.5:
            _review(
                coverage_field,
                (
                    "Täisehituse protsent ei klapi krundi pindala ja ehitusaluse "
                    f"pinna põhjal arvutatuga: PDF {_format_number(coverage)}%, "
                    f"arvutus {_format_number(derived_coverage)}%."
                ),
                _derived_evidence(evidence_text),
            )


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


def _derived_building_count_source(
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
        count = _safe_building_count_from_text(evidence.text)
        if count is not None:
            return count, evidence
    if floors_field.value is not None:
        count = _safe_building_count_from_text(str(floors_field.value))
        if count is not None:
            return count, Evidence(text=str(floors_field.value))
    return None


def _enrich_building_counts(fields: dict[str, ExtractedField]) -> None:
    source = _derived_building_count_source(fields)
    if source is None:
        return

    count, source_evidence = source
    evidence_text = f"Tuletatud hoonetüüpidest: {source_evidence.text}"
    for key in ("lubatud_majade_ehitamise_arv", "hoonete_arv"):
        field = fields.get(key)
        if field is None:
            continue
        candidate = _make_candidate(
            field=field,
            value=count,
            unit=None,
            source_type=SourceType.DERIVED,
            pattern_name="derived_from_floor_building_types",
            evidence_text=evidence_text,
            confidence=0.65,
            pdf=source_evidence.pdf,
            page=source_evidence.page,
            raw_value=str(count),
        )
        _add_candidate(field, candidate)
        if not _field_has_value(field):
            _use_candidate(field, candidate)
            continue

        existing_count = _float_or_none(field.value)
        if existing_count is not None and int(existing_count) != count:
            _review(
                field,
                (
                    "Hoonete arv erineb korruselisuse tekstist tuletatud arvust: "
                    f"väljal {int(existing_count)}, tuletatud {count}."
                ),
                candidate.evidence,
            )


def _refresh_section_reviews(section: BuildingRightSection) -> None:
    section.needs_review = [
        review for field in section.fields.values() for review in field.needs_review
    ]


def enrich_building_rights(
    section: BuildingRightSection,
    parcel_attributes: dict[str, Any] | None = None,
) -> BuildingRightSection:
    parcel_context = compact_parcel_context(parcel_attributes)
    if parcel_context:
        _enrich_from_cadastre(section.fields, parcel_context)
    _enrich_coverage_and_footprint(section.fields)
    _enrich_building_counts(section.fields)
    _refresh_section_reviews(section)
    return section


@time_function
def extract_building_rights(
    chunks: list[TextChunk],
    field_specs: tuple[FieldSpec, ...] = FIELD_SPECS,
    parcel_attributes: dict[str, Any] | None = None,
) -> BuildingRightSection:
    logger.debug(
        f"Running regex building-right extraction chunks={len(chunks)} "
        f"pages={[(chunk.pdf_path.name, chunk.page) for chunk in chunks]}"
    )
    fields: dict[str, ExtractedField] = {}
    reviews: list[ReviewItem] = []
    for spec in field_specs:
        candidates = extract_field_candidates(chunks, spec)
        field = extracted_field_from_candidates(spec, candidates)
        fields[spec.key] = field
        reviews.extend(field.needs_review)

    extracted_fields = {
        key: {
            "value": field.value,
            "unit": field.unit,
            "candidates": len(field.candidates),
            "page": field.evidence.page if field.evidence else None,
        }
        for key, field in fields.items()
    }
    logger.debug(
        f"Regex building-right extracted={extracted_fields} "
        f"missing={[review.key for review in reviews]}"
    )
    section = BuildingRightSection(fields=fields, needs_review=reviews)
    return enrich_building_rights(section, parcel_attributes)


def run_rule_based_extractors(chunks: list[TextChunk]) -> BuildingRightSection:
    """Backward-compatible wrapper for old imports."""
    return extract_building_rights(chunks)
