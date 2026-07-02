"""Address parsing and matching helpers for address-scoped PDF rules."""

from __future__ import annotations

import re
from dataclasses import dataclass

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


@dataclass(frozen=True)
class ParsedAddress:
    street: str
    road_type: str
    number: str

    @property
    def normalized_number(self) -> str:
        return normalize_address_number(self.number)


def normalize_address_number(value: str) -> str:
    return re.sub(r"\s+", "", value).lower()


def normalize_street(value: str) -> str:
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
        street=normalize_street(match.group("street")),
        road_type=road_type,
        number=normalize_address_number(match.group("number")),
    )


def normalize_address_key(address: str) -> str | None:
    parsed = parse_detail_address(address)
    if parsed is None:
        return None
    return f"{parsed.street} {parsed.road_type} {parsed.normalized_number}"


def number_regex(number: str) -> str:
    match = re.match(r"(?P<base>\d+)(?P<suffix>[a-zA-Z]?)$", number)
    if match is None:
        return re.escape(number)
    base = re.escape(match.group("base"))
    suffix = match.group("suffix")
    if suffix:
        return rf"{base}\s*{re.escape(suffix)}(?![{ESTONIAN_LETTER_PATTERN}0-9])"
    return rf"{base}(?!\s*[a-zA-Z](?![{ESTONIAN_LETTER_PATTERN}]))"


def street_regex(parsed: ParsedAddress) -> str:
    return r"\s*".join(re.escape(part) for part in parsed.street.split())


def target_address_regex(parsed: ParsedAddress) -> re.Pattern[str]:
    return re.compile(
        rf"\b{street_regex(parsed)}\s*"
        rf"(?:{ROAD_TYPE_PATTERN})\.?\s*,?\s*"
        rf"{number_regex(parsed.normalized_number)}",
        flags=re.IGNORECASE,
    )


def same_street_address_regex(parsed: ParsedAddress) -> re.Pattern[str]:
    return re.compile(
        rf"\b{street_regex(parsed)}\s*"
        rf"(?:(?:{ROAD_TYPE_PATTERN})\.?\s*,?\s*)?"
        rf"(?P<number>\d+(?:\s*[a-zA-Z](?![{ESTONIAN_LETTER_PATTERN}]))?)",
        flags=re.IGNORECASE,
    )


def address_matches_text(address: str, text: str) -> bool:
    parsed = parse_detail_address(address)
    return parsed is not None and target_address_regex(parsed).search(text) is not None


def target_address_match(
    parsed: ParsedAddress,
    text: str,
) -> re.Match[str] | None:
    return target_address_regex(parsed).search(text)


def same_street_numbers(parsed: ParsedAddress, text: str) -> list[str]:
    return [
        normalize_address_number(match.group("number"))
        for match in same_street_address_regex(parsed).finditer(text)
    ]


def has_target_address(parsed: ParsedAddress, text: str) -> bool:
    return target_address_match(parsed, text) is not None


def has_wrong_same_street_address(parsed: ParsedAddress, text: str) -> bool:
    numbers = same_street_numbers(parsed, text)
    return any(number != parsed.normalized_number for number in numbers)


def has_other_address_like_text(text: str) -> bool:
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
