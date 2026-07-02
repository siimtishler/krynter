"""LLM-assisted resolver for uncertain detail-plan extraction fields."""

from __future__ import annotations

import json
import re
import time
from enum import StrEnum
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from backend.core.logging import logger
from backend.detailplan_analyzer.field_state import refresh_section_reviews
from backend.detailplan_analyzer.models import (
    BuildingRightSection,
    Evidence,
    ExtractedField,
    RegexCandidate,
    ReviewItem,
    SourceType,
)
from backend.detailplan_analyzer.value_parsing import parse_float


class LLMResolverDecision(StrEnum):
    ACCEPTED_CANDIDATE = "accepted_candidate"
    CORRECTED_CANDIDATE = "corrected_candidate"
    NO_ANSWER = "no_answer"
    CONFLICT = "conflict"


class NeighborField(BaseModel):
    label: str
    value: Any = None
    unit: str | None = None
    source_type: SourceType | None = None
    confidence: float = 0.0


class LLMFieldRequest(BaseModel):
    field_key: str
    label: str
    unit: str | None = None
    candidates: list[RegexCandidate] = Field(default_factory=list)
    needs_review: list[ReviewItem] = Field(default_factory=list)
    parcel_context: dict[str, Any] = Field(default_factory=dict)
    neighboring_fields: dict[str, NeighborField] = Field(default_factory=dict)


class LLMFieldResolution(BaseModel):
    field_key: str
    decision: LLMResolverDecision
    value: Any = None
    unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_type: SourceType = SourceType.LLM
    evidence: Evidence | None = None
    candidate_rank: int | None = None
    reason: str = ""
    flags: list[str] = Field(default_factory=list)


class OllamaFieldGeneration(BaseModel):
    model: str
    base_url: str
    elapsed_s: float
    raw_response: str
    response_payload: dict[str, Any]
    options: dict[str, Any]


class LLMResolverProvider(Protocol):
    def resolve_field(self, request: LLMFieldRequest) -> LLMFieldResolution:
        """Resolve one field from compact field-scoped evidence."""


FLOAT_FIELDS = {
    "krundi_pind_m2",
    "taisehitus_pct",
    "brutopind_m2",
    "ehitusalune_pind_m2",
}
INT_FIELDS = {
    "hoonete_arv",
}
MIN_RESOLUTION_CONFIDENCE = 0.6
MAX_CONTEXT_CHARS = 700
MAX_PROMPT_CANDIDATES = 5


def should_resolve_field(
    field: ExtractedField,
    parcel_context: dict[str, Any],
) -> bool:
    if field.value is not None and field.value != "":
        return False
    if not field.candidates:
        return False
    return True


def build_field_request(
    field: ExtractedField,
    section: BuildingRightSection,
    parcel_context: dict[str, Any],
) -> LLMFieldRequest:
    return LLMFieldRequest(
        field_key=field.key,
        label=field.label,
        unit=field.unit,
        candidates=field.candidates,
        needs_review=field.needs_review,
        parcel_context=parcel_context,
        neighboring_fields=_neighboring_fields(section, field.key),
    )


def build_prompt(request: LLMFieldRequest) -> str:
    payload = {
        "field": {
            "key": request.field_key,
            "label": request.label,
            "unit": request.unit,
        },
        "parcel_context": request.parcel_context,
        "neighboring_fields": {
            key: value.model_dump(mode="json", exclude_none=True)
            for key, value in request.neighboring_fields.items()
        },
        "needs_review": [
            item.model_dump(mode="json", exclude_none=True)
            for item in request.needs_review
        ],
        "candidates": [
            _candidate_prompt_payload(candidate)
            for candidate in request.candidates[:MAX_PROMPT_CANDIDATES]
        ],
    }
    return (
        "You resolve one Estonian detail-plan building-right field from compact "
        "evidence. Use only the supplied candidates, evidence, context, parcel "
        "context, and neighboring field values. Do not invent citations or use "
        "outside knowledge. Prefer accepted_candidate when one candidate clearly "
        "answers the field. Use corrected_candidate only when the value is a "
        "small normalization/correction supported by supplied evidence/context. "
        "Use no_answer or conflict if the evidence is insufficient or conflicting. "
        "Reject candidates about warehouse load, wave height, water depth, fences, "
        "setbacks, existing buildings, neighboring parcels, references to other "
        "detail plans, or general background unless the text clearly states the "
        "building right for the selected parcel.\n\n"
        "Return exactly one JSON object with keys: field_key, decision, value, "
        "unit, confidence, source_type, evidence, candidate_rank, reason, flags. "
        "decision must be one of accepted_candidate, corrected_candidate, "
        "no_answer, conflict. source_type must be llm. evidence must contain "
        "pdf, page, and short text copied from supplied evidence/context when a "
        "value is returned. Keep evidence.text under 160 characters.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}"
    )


class OllamaResolverProvider:
    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        model: str = "gemma3:4b",
        timeout_s: float = 600,
        options: dict[str, Any] | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_s = timeout_s
        self.options = options or {}

    def generate_field_raw(self, request: LLMFieldRequest) -> OllamaFieldGeneration:
        options = {
            "temperature": 0,
            "num_ctx": 8192,
            **self.options,
        }
        started = time.perf_counter()
        response = httpx.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": build_prompt(request),
                "stream": False,
                "format": "json",
                "options": options,
            },
            timeout=self.timeout_s,
        )
        elapsed_s = time.perf_counter() - started
        response.raise_for_status()
        payload = response.json()
        raw_response = payload.get("response")
        if not isinstance(raw_response, str):
            raise ValueError("Ollama response did not contain a string response")
        return OllamaFieldGeneration(
            model=self.model,
            base_url=self.base_url,
            elapsed_s=round(elapsed_s, 3),
            raw_response=raw_response,
            response_payload=payload,
            options=options,
        )

    def resolve_field(self, request: LLMFieldRequest) -> LLMFieldResolution:
        generation = self.generate_field_raw(request)
        return parse_resolution(generation.raw_response)


def parse_resolution(raw_response: str) -> LLMFieldResolution:
    return LLMFieldResolution.model_validate(
        _normalize_resolution_payload(_extract_json_object(raw_response))
    )


def apply_resolution(
    field: ExtractedField,
    resolution: LLMFieldResolution,
    min_confidence: float = MIN_RESOLUTION_CONFIDENCE,
) -> bool:
    """Apply a validated LLM decision without inventing unsupported evidence."""
    if resolution.field_key != field.key:
        return False
    if resolution.source_type != SourceType.LLM:
        return False
    if resolution.decision in {
        LLMResolverDecision.NO_ANSWER,
        LLMResolverDecision.CONFLICT,
    }:
        return False
    if resolution.confidence < min_confidence:
        return False

    selected_candidate: RegexCandidate | None = None
    if resolution.decision == LLMResolverDecision.ACCEPTED_CANDIDATE:
        selected_candidate = _candidate_by_rank(field, resolution.candidate_rank)
        if selected_candidate is None:
            return False
        if not _candidate_allowed_for_llm_resolution(field.key, selected_candidate):
            return False
        value = selected_candidate.value
        unit = selected_candidate.unit
        evidence = selected_candidate.evidence
        context = selected_candidate.context
    else:
        value = _coerce_value(field.key, resolution.value)
        unit = resolution.unit if resolution.unit is not None else field.unit
        evidence = _supported_evidence(field, resolution.evidence)
        if evidence is None:
            return False
        selected_candidate = _candidate_by_rank(field, resolution.candidate_rank)
        context = selected_candidate.context if selected_candidate else evidence.text

    llm_candidate = _llm_candidate(
        field=field,
        value=value,
        unit=unit,
        confidence=resolution.confidence,
        evidence=evidence,
        decision=resolution.decision,
        reason=resolution.reason,
        flags=resolution.flags,
        context=context,
    )
    _append_llm_candidate(field, llm_candidate)
    field.value = value
    field.unit = unit
    field.confidence = resolution.confidence
    field.source_type = SourceType.LLM
    field.evidence = evidence
    field.needs_review = []
    return True


def resolve_building_rights(
    section: BuildingRightSection,
    parcel_context: dict[str, Any],
    provider: LLMResolverProvider,
) -> BuildingRightSection:
    resolved = 0
    for field in section.fields.values():
        if not should_resolve_field(field, parcel_context):
            continue
        request = build_field_request(field, section, parcel_context)
        try:
            resolution = provider.resolve_field(request)
        except Exception as exc:
            logger.warning(
                "LLM resolver skipped field=%s candidates=%s error=%s: %s",
                field.key,
                len(field.candidates),
                type(exc).__name__,
                exc,
            )
            continue
        try:
            applied = apply_resolution(field, resolution)
        except Exception as exc:
            logger.warning(
                "LLM resolver rejected field=%s decision=%s error=%s: %s",
                field.key,
                getattr(resolution, "decision", None),
                type(exc).__name__,
                exc,
            )
            continue
        if applied:
            resolved += 1
    refresh_section_reviews(section)
    logger.info(f"LLM resolver complete resolved_fields={resolved}")
    return section


def _neighboring_fields(
    section: BuildingRightSection,
    current_key: str,
) -> dict[str, NeighborField]:
    neighbors: dict[str, NeighborField] = {}
    for key, field in section.fields.items():
        if key == current_key or field.value is None or field.value == "":
            continue
        neighbors[key] = NeighborField(
            label=field.label,
            value=field.value,
            unit=field.unit,
            source_type=field.source_type,
            confidence=field.confidence,
        )
    return neighbors


def _candidate_prompt_payload(candidate: RegexCandidate) -> dict[str, Any]:
    return {
        "rank": candidate.rank,
        "value": candidate.value,
        "raw_value": candidate.raw_value,
        "unit": candidate.unit,
        "confidence": candidate.confidence,
        "source_type": candidate.source_type.value,
        "pattern_name": candidate.pattern_name,
        "score": candidate.score,
        "quality": candidate.quality,
        "reasons": candidate.reasons,
        "flags": candidate.flags,
        "evidence": candidate.evidence.model_dump(mode="json", exclude_none=True),
        "context": _clip(candidate.context),
    }


def _clip(value: str | None, max_chars: int = MAX_CONTEXT_CHARS) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value[:max_chars]


def _extract_json_object(raw_response: str) -> dict[str, Any]:
    cleaned = re.sub(
        r"<think>.*?</think>",
        "",
        raw_response,
        flags=re.IGNORECASE | re.DOTALL,
    ).strip()
    cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s*```$", "", cleaned)
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("LLM response did not contain a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("LLM JSON response was not an object")
    return payload


def _normalize_resolution_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(payload)
    if not normalized.get("source_type"):
        normalized["source_type"] = SourceType.LLM.value

    confidence = normalized.get("confidence")
    if isinstance(confidence, str):
        confidence = confidence.strip().replace("%", "")
        if confidence:
            try:
                confidence = float(confidence)
            except ValueError:
                confidence = None
    if isinstance(confidence, int | float) and confidence > 1 and confidence <= 100:
        confidence = confidence / 100
    if confidence is not None:
        normalized["confidence"] = confidence

    flags = normalized.get("flags")
    if flags is None or flags == "":
        normalized["flags"] = []
    elif isinstance(flags, str):
        normalized["flags"] = [flags]

    candidate_rank = normalized.get("candidate_rank")
    if candidate_rank == "":
        normalized["candidate_rank"] = None

    evidence = normalized.get("evidence")
    if evidence in ({}, "", None):
        normalized["evidence"] = None
    return normalized


def _candidate_by_rank(
    field: ExtractedField,
    rank: int | None,
) -> RegexCandidate | None:
    if rank is None:
        return None
    return next(
        (candidate for candidate in field.candidates if candidate.rank == rank),
        None,
    )


def _candidate_allowed_for_llm_resolution(
    field_key: str,
    candidate: RegexCandidate,
) -> bool:
    text = " ".join(
        part for part in (candidate.evidence.text, candidate.context or "") if part
    ).casefold()
    if field_key == "hoonete_lubatud_korgused_m":
        non_building_height_terms = (
            "lubatud koormus",
            "laine kõrgus",
            "veetase",
            "sügavus",
            "kõrguseni",
            "kai nr",
            "kaide",
        )
        if any(term in text for term in non_building_height_terms):
            return False
    return True


def _coerce_value(field_key: str, value: Any) -> Any:
    if value is None or value == "":
        raise ValueError("Resolved value is empty")
    if field_key in FLOAT_FIELDS:
        parsed = parse_float(str(value))
        return int(parsed) if parsed.is_integer() else parsed
    if field_key in INT_FIELDS:
        return int(round(parse_float(str(value))))
    return re.sub(r"\s+", " ", str(value).strip())


def _supported_evidence(
    field: ExtractedField,
    evidence: Evidence | None,
) -> Evidence | None:
    if evidence is None or not evidence.text.strip():
        return None
    for candidate in field.candidates:
        if (
            evidence.pdf != candidate.evidence.pdf
            or evidence.page != candidate.evidence.page
        ):
            continue
        if _text_supported(evidence.text, candidate.evidence.text):
            return evidence
        if candidate.context and _text_supported(evidence.text, candidate.context):
            return evidence
    return None


def _text_supported(quote: str, source: str) -> bool:
    normalized_quote = _normalize_for_match(quote)
    normalized_source = _normalize_for_match(source)
    return bool(normalized_quote) and (
        normalized_quote in normalized_source or normalized_source in normalized_quote
    )


def _normalize_for_match(value: str) -> str:
    return re.sub(r"\s+", " ", value.casefold()).strip()


def _llm_candidate(
    field: ExtractedField,
    value: Any,
    unit: str | None,
    confidence: float,
    evidence: Evidence,
    decision: LLMResolverDecision,
    reason: str,
    flags: list[str],
    context: str | None,
) -> RegexCandidate:
    return RegexCandidate(
        field_key=field.key,
        label=field.label,
        value=value,
        raw_value=str(value),
        unit=unit,
        confidence=confidence,
        source_type=SourceType.LLM,
        pattern_name=f"llm_{decision.value}",
        evidence=evidence,
        rank=None,
        score=round(confidence * 100, 2),
        quality="strong" if confidence >= 0.85 else "candidate",
        reasons=[
            "source:llm",
            f"decision:{decision.value}",
            *(["reason:" + reason] if reason else []),
        ],
        flags=flags,
        context=context,
    )


def _append_llm_candidate(field: ExtractedField, candidate: RegexCandidate) -> None:
    exists = any(
        existing.source_type == SourceType.LLM
        and existing.pattern_name == candidate.pattern_name
        and existing.raw_value == candidate.raw_value
        and existing.evidence.pdf == candidate.evidence.pdf
        and existing.evidence.page == candidate.evidence.page
        for existing in field.candidates
    )
    if not exists:
        field.candidates.append(candidate)
