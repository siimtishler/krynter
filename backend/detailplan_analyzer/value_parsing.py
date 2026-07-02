"""Shared parsing and numeric comparison helpers for detail-plan extraction."""

from __future__ import annotations

import re
from typing import Any


def parse_float(value: str) -> float:
    """Parse Estonian-formatted numbers used in PDFs and LLM responses."""
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


def float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return parse_float(str(value))
    except ValueError:
        return None


def format_number(value: float) -> str:
    rounded = round(value, 2)
    if rounded.is_integer():
        return str(int(rounded))
    return f"{rounded:.2f}".rstrip("0").rstrip(".")


def values_close(left: float, right: float, absolute: float, ratio: float = 0) -> bool:
    tolerance = max(absolute, abs(left) * ratio, abs(right) * ratio)
    return abs(left - right) <= tolerance
