"""Field metadata and regex patterns for building-right extraction."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from backend.detailplan_analyzer.value_parsing import (
    clean_building_height_value,
    parse_code,
    parse_float,
    parse_int,
    parse_roof_pitch,
    parse_text,
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

    def parse_value(self, raw: str) -> Any:
        value = self.parser(raw) if self.parser else parse_text(raw)
        if self.key == "hoonete_lubatud_korgused_m":
            return clean_building_height_value(value)
        return value


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


def has_amount_text(value: Any) -> bool:
    low = str(value).lower()
    return bool(any(char.isdigit() for char in low)) or any(
        word in low for word in ESTONIAN_NUMBER_WORDS
    )


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
