"""Rule-based extraction for Estonian detail-planning text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import Evidence, Fact

NumberParser = Callable[[str], Any]


@dataclass
class RuleExtraction:
    building_right: dict[str, Fact] = field(default_factory=dict)
    section_facts: dict[str, list[Fact]] = field(default_factory=dict)


def parse_float(value: str) -> float:
    cleaned = value.replace("\xa0", " ")
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def parse_int(value: str) -> int:
    return int(round(parse_float(value)))


def _line_for_match(text: str, match: re.Match) -> str:
    start = text.rfind("\n", 0, match.start()) + 1
    end = text.find("\n", match.end())
    if end == -1:
        end = len(text)
    return text[start:end].strip()[:700]


def _fact_from_match(
    chunk: TextChunk,
    match: re.Match,
    key: str,
    label: str,
    unit: str | None,
    parser: NumberParser | None,
    confidence: float,
) -> Fact:
    raw_value = match.groupdict().get("value") or match.group(1)
    value = parser(raw_value) if parser else raw_value.strip(" :;-")
    return Fact(
        key=key,
        label=label,
        value=value,
        unit=unit,
        confidence=confidence,
        source_type="regex",
        evidence=Evidence(
            pdf=chunk.pdf_path.name,
            page=chunk.page,
            text=_line_for_match(chunk.text, match),
        ),
    )


def _first_match_fact(
    chunks: list[TextChunk],
    key: str,
    label: str,
    patterns: list[str],
    unit: str | None = None,
    parser: NumberParser | None = parse_float,
    confidence: float = 0.8,
) -> Fact | None:
    for chunk in chunks:
        for pattern in patterns:
            match = re.search(pattern, chunk.text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                return _fact_from_match(
                    chunk=chunk,
                    match=match,
                    key=key,
                    label=label,
                    unit=unit,
                    parser=parser,
                    confidence=confidence,
                )
    return None


def _line_facts(
    chunks: list[TextChunk],
    section_key: str,
    label: str,
    keywords: list[str],
    limit: int = 4,
) -> list[Fact]:
    facts: list[Fact] = []
    seen: set[str] = set()
    lowered_keywords = [keyword.lower() for keyword in keywords]
    for chunk in chunks:
        for line in chunk.text.splitlines():
            normalized = line.strip()
            low = normalized.lower()
            if not normalized or normalized in seen:
                continue
            if any(keyword in low for keyword in lowered_keywords):
                seen.add(normalized)
                facts.append(
                    Fact(
                        key=f"{section_key}_line",
                        label=label,
                        value=normalized,
                        confidence=0.55,
                        source_type="regex",
                        evidence=Evidence(
                            pdf=chunk.pdf_path.name,
                            page=chunk.page,
                            text=normalized[:700],
                        ),
                    )
                )
                if len(facts) >= limit:
                    return facts
    return facts


BUILDING_RIGHT_PATTERNS = {
    "krundi_suurus": {
        "label": "Krundi suurus",
        "unit": "m2",
        "parser": parse_float,
        "patterns": [
            r"krundi(?:\s+pos\s*\d+)?\s+(?:suurus|pindala)\D{0,40}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)",
            r"(?:suurus|pindala)\D{0,30}(?P<value>\d[\d\s.,]*)\s*m(?:2|²).{0,60}krunt",
            r"(?P<value>\d[\d\s.,]*)\s*m(?:2|²).{0,60}krundi\s+(?:suurus|pindala)",
        ],
    },
    "kasutusotstarve": {
        "label": "Kasutusotstarve",
        "unit": None,
        "parser": None,
        "patterns": [
            r"(?:sihtotstarve|kasutusotstarve)\D{0,40}(?P<value>[^\n.;]{3,120})",
            r"(?P<value>(?:elamu|äri|tootmis|ühiskondlike ehitiste|transpordi)[^\n.;]{0,80}maa)",
        ],
    },
    "korruselisus": {
        "label": "Korruselisus",
        "unit": None,
        "parser": None,
        "patterns": [
            r"(?P<value>\d+\s*(?:[-–]\s*\d+)?\s*(?:maapealset\s*)?korrus(?:t|eline|eline hooneosa)?)",
            r"korruselisus\D{0,30}(?P<value>\d+\s*(?:[-–]\s*\d+)?)",
        ],
    },
    "taisehitus": {
        "label": "Täisehitus",
        "unit": "%",
        "parser": parse_float,
        "patterns": [
            r"täisehitus(?:e\s*protsent|protsent)?\D{0,40}(?P<value>\d+(?:[,.]\d+)?)\s*%",
            r"(?P<value>\d+(?:[,.]\d+)?)\s*%\D{0,40}täisehitus",
        ],
    },
    "korgus": {
        "label": "Kõrgus",
        "unit": "m",
        "parser": parse_float,
        "patterns": [
            r"(?:hoone\s*)?(?:maksimaalne\s*)?kõrgus\D{0,40}(?P<value>\d+(?:[,.]\d+)?)\s*m",
            r"(?P<value>\d+(?:[,.]\d+)?)\s*m\D{0,50}(?:kõrgune|kõrgus)",
        ],
    },
    "hoonete_arv": {
        "label": "Hoonete arv",
        "unit": None,
        "parser": parse_int,
        "patterns": [
            r"hoonete\s+arv\D{0,30}(?P<value>\d+)",
            r"planeeritud\s+(?P<value>\d+)\s+hoonet",
        ],
    },
}


SECTION_KEYWORDS = {
    "arhitektuursed_tingimused": (
        "Arhitektuursed tingimused",
        ["arhitektuur", "fassaad", "katuse", "viimistlus", "materjal"],
    ),
    "haljastus_ja_keskkond": (
        "Haljastus ja keskkond",
        ["haljastus", "keskkond", "puu", "rohe", "müratase", "radoon"],
    ),
    "juurdepaas_ja_parkimine": (
        "Juurdepääs ja parkimine",
        ["juurdepääs", "ligipääs", "parkim", "liiklus"],
    ),
    "tehnovorgud": (
        "Tehnovõrgud",
        [
            "tehnovõrk",
            "veevarustus",
            "kanalisatsioon",
            "elektr",
            "side",
            "gaas",
            "küte",
        ],
    ),
    "servituudid_ja_kitsendused": (
        "Servituudid ja kitsendused",
        ["servituut", "kitsendus", "kaitsevöönd"],
    ),
}


@time_function
def run_rule_based_extractors(chunks: list[TextChunk]) -> RuleExtraction:
    logger.debug(
        "Running rule-based extractors chunks=%s pages=%s",
        len(chunks),
        [(chunk.pdf_path.name, chunk.page) for chunk in chunks],
    )
    extraction = RuleExtraction()
    for key, spec in BUILDING_RIGHT_PATTERNS.items():
        fact = _first_match_fact(
            chunks=chunks,
            key=key,
            label=spec["label"],
            patterns=spec["patterns"],
            unit=spec["unit"],
            parser=spec["parser"],
        )
        if fact:
            extraction.building_right[key] = fact

    for section_key, (label, keywords) in SECTION_KEYWORDS.items():
        extraction.section_facts[section_key] = _line_facts(
            chunks=chunks,
            section_key=section_key,
            label=label,
            keywords=keywords,
        )

    logger.debug(
        "Rule-based building_right=%s section_fact_counts=%s",
        {
            key: {
                "value": fact.value,
                "unit": fact.unit,
                "page": fact.evidence.page if fact.evidence else None,
                "evidence": fact.evidence.text[:220] if fact.evidence else None,
            }
            for key, fact in extraction.building_right.items()
        },
        {
            section_key: len(facts)
            for section_key, facts in extraction.section_facts.items()
        },
    )
    return extraction
