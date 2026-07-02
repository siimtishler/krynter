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
PDF_REGEX_CONFIDENCE_CAP = 0.72
PDF_MANUAL_CONFIDENCE_CAP = 0.78


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


@dataclass(frozen=True)
class ParsedAddress:
    street: str
    road_type: str
    number: str

    @property
    def normalized_number(self) -> str:
        return _normalize_address_number(self.number)


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


ROAD_TYPE_ALIASES = {
    "tn": "tn",
    "tänav": "tn",
    "pst": "pst",
    "puiestee": "pst",
    "mnt": "mnt",
    "maantee": "mnt",
}

ROAD_TYPE_PATTERN = r"tn|tänav|pst|puiestee|mnt|maantee"
ESTONIAN_LETTER_PATTERN = r"A-Za-zÕÄÖÜŠŽõäöüšž"


def _normalize_address_number(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def _normalize_street(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().casefold())


def parse_detail_address(address: str) -> ParsedAddress | None:
    match = re.match(
        rf"^\s*(?P<street>.+?)\s+"
        rf"(?P<road>{ROAD_TYPE_PATTERN})\.?\s*"
        rf"(?P<number>\d+\s*[a-zA-Z]?)\s*$",
        address,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    road_type = ROAD_TYPE_ALIASES.get(match.group("road").casefold())
    if road_type is None:
        return None
    return ParsedAddress(
        street=_normalize_street(match.group("street")),
        road_type=road_type,
        number=_normalize_address_number(match.group("number")),
    )


def normalize_address_key(address: str) -> str | None:
    parsed = parse_detail_address(address)
    if parsed is None:
        return None
    return f"{parsed.street} {parsed.road_type} {parsed.normalized_number}"


def _number_regex(number: str) -> str:
    match = re.match(r"(?P<base>\d+)(?P<suffix>[a-zA-Z]?)$", number)
    if match is None:
        return re.escape(number)
    base = re.escape(match.group("base"))
    suffix = match.group("suffix")
    if suffix:
        return rf"{base}\s*{re.escape(suffix)}(?![{ESTONIAN_LETTER_PATTERN}0-9])"
    return rf"{base}(?!\s*[a-zA-Z](?![{ESTONIAN_LETTER_PATTERN}]))"


def _street_regex(parsed: ParsedAddress) -> str:
    return r"\s*".join(re.escape(part) for part in parsed.street.split())


def _target_address_regex(parsed: ParsedAddress) -> re.Pattern[str]:
    return re.compile(
        rf"\b{_street_regex(parsed)}\s*"
        rf"(?:{ROAD_TYPE_PATTERN})\.?\s*,?\s*"
        rf"{_number_regex(parsed.normalized_number)}",
        flags=re.IGNORECASE,
    )


def _same_street_address_regex(parsed: ParsedAddress) -> re.Pattern[str]:
    return re.compile(
        rf"\b{_street_regex(parsed)}\s*"
        rf"(?:(?:{ROAD_TYPE_PATTERN})\.?\s*,?\s*)?"
        rf"(?P<number>\d+(?:\s*[a-zA-Z](?![{ESTONIAN_LETTER_PATTERN}]))?)",
        flags=re.IGNORECASE,
    )


def address_matches_text(address: str, text: str) -> bool:
    parsed = parse_detail_address(address)
    return parsed is not None and _target_address_regex(parsed).search(text) is not None


def _target_address_match(
    parsed: ParsedAddress,
    text: str,
) -> re.Match[str] | None:
    return _target_address_regex(parsed).search(text)


def _same_street_numbers(parsed: ParsedAddress, text: str) -> list[str]:
    return [
        _normalize_address_number(match.group("number"))
        for match in _same_street_address_regex(parsed).finditer(text)
    ]


def _has_target_address(parsed: ParsedAddress, text: str) -> bool:
    return _target_address_match(parsed, text) is not None


def _has_wrong_same_street_address(parsed: ParsedAddress, text: str) -> bool:
    numbers = _same_street_numbers(parsed, text)
    return any(number != parsed.normalized_number for number in numbers)


def _line_has_multiple_values(field_key: str, line: str) -> bool:
    if field_key == "taisehitus_pct":
        return len(re.findall(r"\d+(?:[,.]\d+)?\s*%", line)) > 1
    if field_key.endswith("_m2"):
        return len(re.findall(r"\d[\d\s.,]*\s*m(?:2|²)\b", line)) > 1
    return False


def _has_other_address_like_text(text: str) -> bool:
    typed_address = re.search(
        rf"\b[{ESTONIAN_LETTER_PATTERN}][{ESTONIAN_LETTER_PATTERN}]+"
        rf"\s+(?:{ROAD_TYPE_PATTERN})\.?\s+\d+\s*[a-zA-Z]?\b",
        text,
        flags=re.IGNORECASE,
    )
    bare_address = re.search(
        rf"\b[{ESTONIAN_LETTER_PATTERN}][{ESTONIAN_LETTER_PATTERN}]+"
        rf"\s+\d+\s*[a-zA-Z]?\s*[–-]",
        text,
        flags=re.IGNORECASE,
    )
    return bool(typed_address or bare_address)


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
    cleaned = parse_text(value)
    cleaned = cleaned.replace("–", "-")
    cleaned = cleaned.replace("˚", "").replace("°", "")
    cleaned = re.sub(r"\s*-\s*", "-", cleaned)
    cleaned = re.sub(r"\s*/\s*", " või ", cleaned)
    cleaned = re.sub(r"\s*,\s*", " või ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def clean_building_height_value(value: Any) -> str:
    cleaned = parse_text(str(value))
    cleaned = re.split(r"\s*\(\s*abs\b", cleaned, maxsplit=1, flags=re.IGNORECASE)[0]
    if re.fullmatch(r"\d+(?:[,.]\d+)?\s*m\b.*", cleaned, flags=re.IGNORECASE):
        cleaned = re.sub(r"\s*m\b.*$", "", cleaned, flags=re.IGNORECASE).strip()
    return cleaned or parse_text(str(value))


def _line_for_match(text: str, match: re.Match) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:700]


def _context_for_match(
    text: str,
    match: re.Match,
    context_lines: int = 3,
    max_chars: int = 1200,
) -> str:
    lines = text.splitlines()
    if not lines:
        return text[:max_chars]

    line_index = 0
    offset = 0
    for index, line in enumerate(lines):
        line_end = offset + len(line)
        if offset <= match.start() <= line_end:
            line_index = index
            break
        offset = line_end + 1

    start = max(0, line_index - context_lines)
    end = min(len(lines), line_index + context_lines + 1)
    return "\n".join(lines[start:end]).strip()[:max_chars]


def _raw_value(match: re.Match) -> str:
    groupdict = match.groupdict()
    if "value" in groupdict and groupdict["value"] is not None:
        return groupdict["value"]
    return match.group(1)


ESTONIAN_NUMBER_WORDS = (
    "üks",
    "uhe",
    "ühe",
    "kaks",
    "kahe",
    "kahte",
    "kolm",
    "kolme",
    "neli",
    "nelja",
    "viis",
    "viie",
    "kuus",
    "kuue",
    "seitse",
    "seitsme",
    "kaheksa",
    "üheksa",
    "uheksa",
    "kümme",
    "kumme",
)


def _has_amount_text(value: Any) -> bool:
    low = str(value).lower()
    return bool(re.search(r"\d", low)) or any(
        word in low for word in ESTONIAN_NUMBER_WORDS
    )


def _candidate_is_parseable_for_field(
    spec: FieldSpec, value: Any, context: str
) -> bool:
    if spec.key == "lubatud_korrused":
        return _has_amount_text(value)
    if spec.key == "hoonete_lubatud_korgused_m":
        low = str(value).lower()
        if not re.search(r"\d", low):
            return False
        if "kõrgus" in low and not re.search(r"\d+(?:[,.]\d+)?\s*m\b", low):
            return False
        return True
    return True


def _candidate_from_match(
    chunk: TextChunk,
    spec: FieldSpec,
    regex: RegexPattern,
    match: re.Match,
    target_address: ParsedAddress | None = None,
) -> RegexCandidate | None:
    raw = _raw_value(match)
    context = _context_for_match(chunk.text, match)
    line = _line_for_match(chunk.text, match)
    try:
        value = spec.parser(raw) if spec.parser else parse_text(raw)
        if spec.key == "hoonete_lubatud_korgused_m":
            value = clean_building_height_value(value)
    except (TypeError, ValueError):
        logger.debug(
            f"Skipping regex candidate field={spec.key} pattern={regex.name} raw={raw}"
        )
        return None
    if not _candidate_is_parseable_for_field(spec, value, context):
        logger.debug(
            f"Skipping unparseable candidate field={spec.key} "
            f"pattern={regex.name} raw={raw}"
        )
        return None

    reasons = list(chunk.reasons)
    if target_address is not None:
        reasons.append("target_address_available")
        candidate_text = " ".join([line, context])
        if _has_target_address(target_address, candidate_text):
            reasons.append("target_address_context")
        if _has_wrong_same_street_address(target_address, line):
            reasons.append("same_street_wrong_address")
        elif _has_wrong_same_street_address(target_address, context) and not (
            _has_target_address(target_address, line)
        ):
            reasons.append("context_wrong_address")
        if _has_wrong_same_street_address(target_address, candidate_text):
            reasons.append("multi_address_context")
        if not _has_target_address(
            target_address, candidate_text
        ) and _has_other_address_like_text(line):
            reasons.append("other_address_context")
        if _line_has_multiple_values(spec.key, line):
            reasons.append("multi_value_table_row")
        if spec.key in {"katusekalle", "hoonete_arv"} and _normalize_address_number(
            parse_text(raw)
        ) in _same_street_numbers(target_address, line):
            reasons.append("address_number_capture")
        target_match = _target_address_match(target_address, line)
        raw_index = line.find(str(raw))
        if (
            spec.key == "hoonete_arv"
            and target_match is not None
            and raw_index != -1
            and raw_index < target_match.start()
        ):
            reasons.append("unscoped_before_target_address")

    return RegexCandidate(
        field_key=spec.key,
        label=spec.label,
        value=value,
        raw_value=parse_text(raw),
        unit=spec.unit,
        confidence=min(regex.confidence, PDF_REGEX_CONFIDENCE_CAP),
        pattern_name=regex.name,
        evidence=Evidence(
            pdf=chunk.pdf_path.name,
            page=chunk.page,
            text=line,
        ),
        reasons=reasons,
        context=context,
    )


STRONG_CONTEXT_TERMS = (
    "ehitusõigus",
    "hoonestustingimused",
    "krundi ehitusõigus",
    "põhinäitajad",
    "lubatud",
    "suurim",
    "maksimaalne",
    "max",
)

WEAK_CONTEXT_TERMS = (
    "olemasolev",
    "olemasoleva",
    "kontaktvöönd",
    "kontaktvöön",
    "naaber",
    "piirdeaed",
    "piirdeai",
    "servituut",
    "sisukord",
    "üldplaneering",
    "visioon",
)

FIELD_WEAK_CONTEXT_TERMS: dict[str, tuple[str, ...]] = {
    "lubatud_korrused": (
        "vaated",
        "kõrghaljastus",
        "kontaktvöönd",
        "naaber",
        "visioon",
    ),
    "hoonete_lubatud_korgused_m": (
        "piirdeaed",
        "piirdeai",
        "piire",
        "hekk",
        "traatvõrk",
        "võrkai",
        "võrgust",
        "võrkaed",
        "tagasi",
        "tagasiaste",
        "maapinnast on 1",
    ),
}


FIELD_STRONG_CONTEXT_TERMS: dict[str, tuple[str, ...]] = {
    "taisehitus_pct": (
        "kavandatud täisehitus",
        "täisehitus %",
        "täisehituse protsent",
    ),
    "hoonete_lubatud_korgused_m": (
        "hoonete lubatud suurim kõrgus",
        "maksimaalne kõrgus",
        "hoone maksimaalne kõrgus",
        "hoone max",
        "lubatud suurim kõrgus",
        "suurim kõrgus",
    ),
    "katusekalle": (
        "lubatud katusekalded",
        "katusekalle",
        "katuse kalle",
    ),
    "tulepusivusklass": (
        "tulepüsivusklassiks",
        "tulepüsivusklass",
        "tulepüsivusaste",
        "tp-" "planeeritud",
    ),
}


def _candidate_value_key(candidate: RegexCandidate) -> str:
    if isinstance(candidate.value, float):
        return _format_number(candidate.value)
    return re.sub(r"\s+", " ", str(candidate.value).lower()).strip()


def _field_values_equivalent(
    field_key: str,
    left: RegexCandidate,
    right: RegexCandidate,
) -> bool:
    if field_key.endswith("_m2") or field_key == "taisehitus_pct":
        left_float = _float_or_none(left.value)
        right_float = _float_or_none(right.value)
        if left_float is not None and right_float is not None:
            return _values_close(left_float, right_float, absolute=0.01)
    return _candidate_value_key(left) == _candidate_value_key(right)


def _score_candidate(candidate: RegexCandidate) -> tuple[float, list[str], list[str]]:
    text = " ".join(
        part for part in (candidate.evidence.text, candidate.context or "") if part
    )
    low = text.lower()
    evidence_low = candidate.evidence.text.lower()
    score = candidate.confidence * 100
    reasons = list(candidate.reasons)
    flags: list[str] = []

    if "target_address_context" in candidate.reasons:
        score += 18
        reasons.append("boost:target_address")
    if "targeted_address" in candidate.reasons:
        score += 18
        reasons.append("boost:targeted_address")
    if "same_street_wrong_address" in candidate.reasons:
        score -= 55
        flags.append("same_street_wrong_address")
    if "context_wrong_address" in candidate.reasons:
        score -= 35
        flags.append("context_wrong_address")
    if "other_address_context" in candidate.reasons:
        score -= 40
        flags.append("other_address_context")
    if "multi_address_context" in candidate.reasons:
        score -= 6
        flags.append("multi_address_context")
    if "multi_value_table_row" in candidate.reasons:
        if "targeted_address" in candidate.reasons:
            flags.append("multi_value_targeted_context")
        else:
            score -= 45
            flags.append("multi_value_unscoped")
    if "address_number_capture" in candidate.reasons:
        score -= 75
        flags.append("address_number_capture")
    if "unscoped_before_target_address" in candidate.reasons:
        score -= 55
        flags.append("unscoped_before_target_address")
    if (
        candidate.field_key == "katusekalle"
        and "target_address_available" in candidate.reasons
        and "target_address_context" not in candidate.reasons
        and "targeted_address" not in candidate.reasons
    ):
        score -= 45
        flags.append("unscoped_address_context")

    for term in STRONG_CONTEXT_TERMS:
        if term in low:
            score += 6
            reasons.append(f"boost:{term}")

    for term in FIELD_STRONG_CONTEXT_TERMS.get(candidate.field_key, ()):
        if term in low:
            score += 15
            reasons.append(f"field_boost:{term}")

    for term in WEAK_CONTEXT_TERMS:
        if term in evidence_low:
            if (
                candidate.field_key == "hoonete_lubatud_korgused_m"
                and term.startswith("olemasolev")
                and re.search(r"olemasoleva\w*\s+maapinn", evidence_low)
            ):
                continue
            score -= 12
            flags.append(f"weak_context:{term}")

    for term in FIELD_WEAK_CONTEXT_TERMS.get(candidate.field_key, ()):
        if term in evidence_low:
            score -= 18
            flags.append(f"field_weak_context:{term}")

    if candidate.field_key == "lubatud_korrused":
        if "maa-alune" in evidence_low or "maa alune" in evidence_low:
            flags.append("underground_floor_context")
            score -= 18
            score = min(score, 70)
        if not _has_amount_text(candidate.value):
            flags.append("missing_floor_amount")
            score -= 35

    if candidate.field_key == "hoonete_lubatud_korgused_m":
        if re.search(
            r"\b(?:piire|piirde|piirdeaia|heki|aia|traatvõrk|võrkai|võrgust)\w*",
            evidence_low,
        ):
            flags.append("not_building_height")
            score -= 35
        raw_low = str(candidate.raw_value).lower()
        if "rääst" in evidence_low and re.search(
            rf"rääst\w*\s+kõrgus\w*\s*[-–]?\s*{re.escape(raw_low)}\s*m",
            evidence_low,
        ):
            flags.append("eave_height")
            score -= 35
        if not _has_amount_text(candidate.value):
            flags.append("missing_height_amount")
            score -= 30

    if candidate.field_key == "krundi_pind_m2" and (
        "vähemalt" in evidence_low
        or "mahtuvate puude" in evidence_low
        or "puurinde" in evidence_low
    ):
        flags.append("general_minimum_area_context")
        score -= 45

    if "toc_downrank" in candidate.reasons:
        score -= 25
        flags.append("toc_context")

    return max(0, min(score, 100)), reasons, flags


def _quality_for_score(score: float, flags: list[str]) -> str:
    blocking_flags = {
        "address_number_capture",
        "context_wrong_address",
        "eave_height",
        "general_minimum_area_context",
        "missing_floor_amount",
        "missing_height_amount",
        "multi_value_unscoped",
        "not_building_height",
        "other_address_context",
        "same_street_wrong_address",
        "underground_floor_context",
        "toc_context",
        "unscoped_before_target_address",
        "unscoped_address_context",
    }
    if score >= 88 and not blocking_flags.intersection(flags):
        return "strong"
    if score >= 62:
        return "candidate"
    return "weak"


def _rank_candidates(candidates: list[RegexCandidate]) -> list[RegexCandidate]:
    ranked: list[RegexCandidate] = []
    for candidate in candidates:
        score, reasons, flags = _score_candidate(candidate)
        candidate.score = round(score, 2)
        candidate.quality = _quality_for_score(score, flags)
        candidate.reasons = sorted(set(reasons))
        candidate.flags = sorted(set(flags))
        ranked.append(candidate)

    ranked.sort(
        key=lambda candidate: (
            -(candidate.score or 0),
            -candidate.confidence,
            candidate.evidence.pdf or "",
            candidate.evidence.page or 0,
            str(candidate.raw_value),
        )
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate.rank = index
    return ranked


def _has_close_conflict(
    spec: FieldSpec,
    best: RegexCandidate,
    candidates: list[RegexCandidate],
) -> bool:
    best_score = best.score or 0
    for candidate in candidates[1:]:
        if (candidate.score or 0) < best_score - 8:
            continue
        if (
            "targeted_address" in best.reasons
            and "targeted_address" not in candidate.reasons
        ):
            continue
        if not _field_values_equivalent(spec.key, best, candidate):
            return True
    return False


def _candidate_can_fill_field(
    spec: FieldSpec,
    candidate: RegexCandidate,
    candidates: list[RegexCandidate],
) -> bool:
    if candidate.quality != "strong":
        return False
    return not _has_close_conflict(spec, candidate, candidates)


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
                r"\b(?:hoone\s*)?(?:maksimaalne\s*)?kõrgus\D{0,90}(?P<value>\d+(?:[,.]\d+)?)\s*m\b",
                0.7,
            ),
        ),
    ),
    FieldSpec(
        key="hoonete_arv",
        label="Lubatud hoonete arv",
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
        key="katusekalle",
        label="Katusekalle",
        unit="degrees",
        parser=parse_roof_pitch,
        patterns=(
            RegexPattern(
                "katuse_kalle",
                r"\bkatuse\s*kalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:[oO˚°])?(?:\s*(?:või|ja|/|,)\s*\d+\s*(?:[-–]\s*\d+)?\s*(?:[oO˚°])?)*)",
                0.95,
            ),
            RegexPattern(
                "katusekalle",
                r"\bkatusekalle\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:[oO˚°])?(?:\s*(?:või|ja|/|,)\s*\d+\s*(?:[-–]\s*\d+)?\s*(?:[oO˚°])?)*)",
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
                0.9,
            ),
        ),
    ),
)


NUMBER_TOKEN_PATTERN = r"\d+(?:[,.]\d+)?"


def _candidate_context_around_line(lines: list[str], index: int) -> str:
    start = max(0, index - 2)
    end = min(len(lines), index + 4)
    return "\n".join(lines[start:end]).strip()[:1200]


def _manual_regex_candidate(
    chunk: TextChunk,
    spec: FieldSpec,
    pattern_name: str,
    raw: str,
    evidence_text: str,
    context: str,
    confidence: float = 0.96,
) -> RegexCandidate | None:
    try:
        value = spec.parser(raw) if spec.parser else parse_text(raw)
        if spec.key == "hoonete_lubatud_korgused_m":
            value = clean_building_height_value(value)
    except (TypeError, ValueError):
        return None
    return RegexCandidate(
        field_key=spec.key,
        label=spec.label,
        value=value,
        raw_value=parse_text(raw),
        unit=spec.unit,
        confidence=min(confidence, PDF_MANUAL_CONFIDENCE_CAP),
        pattern_name=pattern_name,
        evidence=Evidence(
            pdf=chunk.pdf_path.name,
            page=chunk.page,
            text=evidence_text.strip()[:700],
        ),
        reasons=sorted(
            set([*chunk.reasons, "target_address_context", "targeted_address"])
        ),
        context=context,
    )


def _address_row_numbers(
    line: str,
    target_address: ParsedAddress,
) -> list[tuple[str, bool]]:
    match = _target_address_match(target_address, line)
    if match is None:
        return []
    tail = line[match.end() :]
    return [
        (
            number_match.group(0),
            "%" in tail[number_match.end() : number_match.end() + 2],
        )
        for number_match in re.finditer(NUMBER_TOKEN_PATTERN, tail)
    ]


def _table_row_target_candidates(
    chunk: TextChunk,
    spec: FieldSpec,
    target_address: ParsedAddress,
) -> list[RegexCandidate]:
    candidates: list[RegexCandidate] = []
    lines = chunk.text.splitlines()
    for index, line in enumerate(lines):
        numbers = _address_row_numbers(line, target_address)
        if not numbers:
            continue
        low_line = line.lower()
        if "katastri" in low_line or re.search(r"\d+:\d+:\d+", line):
            continue
        numeric_values = [_float_or_none(value) for value, _ in numbers]
        table_like = (
            len(numeric_values) >= 3
            and numeric_values[0] is not None
            and numeric_values[1] is not None
            and numeric_values[0] > 100
            and numeric_values[1] > 20
        )
        context = _candidate_context_around_line(lines, index)
        raw: str | None = None
        if spec.key == "krundi_pind_m2" and table_like:
            raw = numbers[0][0]
        elif spec.key == "ehitusalune_pind_m2" and table_like:
            raw = numbers[1][0]
        elif spec.key == "taisehitus_pct":
            percent_values = [value for value, is_percent in numbers if is_percent]
            if percent_values and "täisehitus" in low_line:
                raw = percent_values[0]
            elif table_like:
                raw = numbers[2][0]
        elif spec.key == "hoonete_arv":
            if table_like and len(numbers) >= 5:
                raw = numbers[4][0]
        if raw is None:
            continue
        candidate = _manual_regex_candidate(
            chunk,
            spec,
            "address_table_row",
            raw,
            line,
            context,
            confidence=0.97,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _selected_address_windows(
    chunk: TextChunk,
    target_address: ParsedAddress,
    max_chars: int = 900,
) -> list[tuple[str, str]]:
    windows: list[tuple[str, str]] = []
    target_regex = _target_address_regex(target_address)
    wrong_regex = _same_street_address_regex(target_address)
    for match in target_regex.finditer(chunk.text):
        line_start = chunk.text.rfind("\n", 0, match.start()) + 1
        line_end = chunk.text.find("\n", match.end())
        if line_end == -1:
            line_end = len(chunk.text)
        line = chunk.text[line_start:line_end]
        line_low = line.lower()
        if not any(
            term in line_low
            for term in (
                "kinnistu",
                "kinnistule",
                "krunt",
                "krundil",
                "moodustatav",
                "pos",
                "hoonete",
                "katuse",
                "ehitusõigus",
            )
        ):
            continue
        line_prefix = chunk.text[line_start : match.start()]
        if _has_wrong_same_street_address(target_address, line_prefix):
            continue
        end = min(len(chunk.text), match.start() + max_chars)
        for other in wrong_regex.finditer(chunk.text, match.end(), end):
            if (
                _normalize_address_number(other.group("number"))
                != target_address.normalized_number
            ):
                end = other.start()
                break
        window = chunk.text[match.start() : end].strip()
        line = _line_for_offset(chunk.text, match.start())
        if window:
            windows.append((window, line))
    return windows


def _line_for_offset(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:700]


def _first_match(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group("value") if match else None


def _building_count_from_noun_quantities(text: str) -> int | None:
    total = 0
    found = False
    for match in re.finditer(
        r"(?P<count>\d+)\s+(?P<type>elam\w*|abihoon\w*)",
        text,
        flags=re.IGNORECASE,
    ):
        count = int(match.group("count"))
        if count > 20:
            continue
        total += count
        found = True
    if found:
        return total
    if re.search(r"\bühe\s+[^.]{0,80}\belam\w*", text, flags=re.IGNORECASE):
        return 1
    return None


def _targeted_window_candidates(
    chunk: TextChunk,
    spec: FieldSpec,
    target_address: ParsedAddress,
) -> list[RegexCandidate]:
    candidates: list[RegexCandidate] = []
    for window, line in _selected_address_windows(chunk, target_address):
        raw: str | None = None
        pattern_name = "address_scoped_context"
        if spec.key == "taisehitus_pct":
            raw = _first_match(
                rf"\btäisehitus(?:e\s*protsent|protsent)?\D{{0,90}}"
                rf"(?P<value>{NUMBER_TOKEN_PATTERN})\s*%",
                window,
            )
        elif spec.key == "ehitusalune_pind_m2":
            raw = _first_match(
                r"\b(?:ehitisealune|ehitusalune|hoonete\s+suurim\s+lubatud\s+ehitusalune)"
                r"\s+pind(?:ala)?\D{0,90}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
                window,
            )
        elif spec.key == "hoonete_lubatud_korgused_m":
            raw = _first_match(
                rf"\b(?:maksimaalne\s+hoonestuse\s+kõrgus|"
                rf"lubatud\s+suurim\s+(?:katuseharja\s+)?kõrgus|"
                rf"maksimaalseks\s+kõrguseks)"
                rf"\D{{0,120}}(?P<value>{NUMBER_TOKEN_PATTERN})\s*m\b",
                window,
            )
        elif spec.key == "katusekalle":
            if "katuse" in window.lower() or "katuse" in line.lower():
                pitch = re.search(
                    r"\bkatuse\s*kalle|\bkatusekalle",
                    window,
                    flags=re.IGNORECASE,
                )
                if pitch is not None:
                    pitch_value = re.search(
                        rf"(?P<value>{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?\s*[-–]\s*"
                        rf"{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?)",
                        window[pitch.end() : pitch.end() + 180],
                        flags=re.IGNORECASE,
                    )
                    raw = pitch_value.group("value") if pitch_value else None
                if raw is None and "katuse" in line.lower():
                    address_match = _target_address_match(target_address, line)
                    if address_match is not None:
                        pitch_value = re.search(
                            rf"(?P<value>{NUMBER_TOKEN_PATTERN}\s*[˚°]?\s*[-–]\s*"
                            rf"{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?)",
                            line[address_match.end() : address_match.end() + 120],
                            flags=re.IGNORECASE,
                        )
                        raw = pitch_value.group("value") if pitch_value else None
        elif spec.key == "hoonete_arv":
            if "hoonete arv" in line.lower() or "hoonete arv" in window.lower():
                scoped = re.search(
                    r"\bkrundil\b\D{0,12}(?P<value>\d+)\b",
                    window,
                    flags=re.IGNORECASE,
                )
                if scoped is not None:
                    raw = scoped.group("value")
            if raw is None:
                count = _building_count_from_noun_quantities(window)
                if count is not None:
                    raw = str(count)
                    pattern_name = "address_scoped_building_nouns"

        if raw is None:
            continue
        evidence = line if line else window.splitlines()[0]
        candidate = _manual_regex_candidate(
            chunk,
            spec,
            pattern_name,
            raw,
            evidence,
            window,
            confidence=0.97,
        )
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def _targeted_field_candidates(
    chunks: list[TextChunk],
    spec: FieldSpec,
    target_address: ParsedAddress,
) -> list[RegexCandidate]:
    if spec.key not in {
        "krundi_pind_m2",
        "taisehitus_pct",
        "ehitusalune_pind_m2",
        "hoonete_lubatud_korgused_m",
        "hoonete_arv",
        "katusekalle",
    }:
        return []

    candidates: list[RegexCandidate] = []
    for chunk in chunks:
        if chunk.field_key is not None and chunk.field_key != spec.key:
            continue
        candidates.extend(_table_row_target_candidates(chunk, spec, target_address))
        candidates.extend(_targeted_window_candidates(chunk, spec, target_address))
    return candidates


def extract_field_candidates(
    chunks: list[TextChunk],
    spec: FieldSpec,
    target_address: ParsedAddress | None = None,
) -> list[RegexCandidate]:
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
                candidate = _candidate_from_match(
                    chunk,
                    spec,
                    regex,
                    match,
                    target_address=target_address,
                )
                if candidate is not None:
                    candidates.append(candidate)
    if target_address is not None:
        candidates.extend(_targeted_field_candidates(chunks, spec, target_address))

    ranked = _rank_candidates(candidates)
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
    return _rank_candidates(list(deduped.values()))


def extracted_field_from_candidates(
    spec: FieldSpec,
    candidates: list[RegexCandidate],
) -> ExtractedField:
    ranked = _rank_candidates(candidates)
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
    if not _candidate_can_fill_field(spec, best, ranked):
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
        source_type="regex",
        evidence=best.evidence,
        candidates=ranked,
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
        and existing.evidence.pdf == candidate.evidence.pdf
        and existing.evidence.page == candidate.evidence.page
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
        score=round(confidence * 100, 2),
        quality="strong" if confidence >= 0.85 else "candidate",
        reasons=[f"source:{source_type.value}"],
        context=evidence_text,
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


def _enrich_from_cadastre(
    fields: dict[str, ExtractedField],
    parcel_context: dict[str, Any],
) -> None:
    area_field = fields.get("krundi_pind_m2")
    if area_field is not None:
        candidate = _cadastre_area_candidate(area_field, parcel_context)
        if candidate is not None:
            _add_candidate(area_field, candidate)
            pdf_candidate = next(
                (
                    item
                    for item in area_field.candidates
                    if item.source_type != SourceType.CADASTRE
                    and _float_or_none(item.value) is not None
                ),
                None,
            )
            pdf_area = _float_or_none(area_field.value)
            if pdf_area is None and pdf_candidate is not None:
                pdf_area = _float_or_none(pdf_candidate.value)
            cadastre_area = _float_or_none(candidate.value)
            if pdf_area is not None and cadastre_area is not None:
                if _values_close(pdf_area, cadastre_area, absolute=25, ratio=0.02):
                    if not _field_has_value(area_field) and pdf_candidate is not None:
                        _use_candidate(area_field, pdf_candidate)
                else:
                    _use_candidate(area_field, candidate)
                    _review(
                        area_field,
                        (
                            "PDFi krundi pindala erineb katastri pindalast: "
                            f"PDF {_format_number(pdf_area)} m², "
                            f"kataster {_format_number(cadastre_area)} m²."
                        ),
                        candidate.evidence,
                    )
            elif not _field_has_value(area_field):
                _use_candidate(area_field, candidate)


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
    field = fields.get("hoonete_arv")
    if field is None:
        return
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
        return

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
    target_address: str | None = None,
) -> BuildingRightSection:
    logger.debug(
        f"Running regex building-right extraction chunks={len(chunks)} "
        f"pages={[(chunk.pdf_path.name, chunk.page) for chunk in chunks]}"
    )
    fields: dict[str, ExtractedField] = {}
    reviews: list[ReviewItem] = []
    parcel_context = compact_parcel_context(parcel_attributes)
    parsed_target_address = (
        parse_detail_address(target_address) if target_address else None
    )
    for spec in field_specs:
        candidates = extract_field_candidates(
            chunks,
            spec,
            target_address=parsed_target_address,
        )
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
    return enrich_building_rights(section, parcel_context)


def run_rule_based_extractors(chunks: list[TextChunk]) -> BuildingRightSection:
    """Backward-compatible wrapper for old imports."""
    return extract_building_rights(chunks)
