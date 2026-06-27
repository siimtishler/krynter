"""Pydantic models for regex-only detail-planning PDF analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class AnalysisStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NEEDS_SETUP = "needs_setup"
    NOT_FOUND = "not_found"


class SourceType(StrEnum):
    REGEX = "regex"
    PDF = "pdf"
    CADASTRE = "cadastre"
    DERIVED = "derived"


class Evidence(BaseModel):
    pdf: str | None = None
    page: int | None = None
    text: str


class RegexCandidate(BaseModel):
    field_key: str
    label: str
    value: Any = None
    raw_value: str
    unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_type: SourceType = SourceType.REGEX
    pattern_name: str
    evidence: Evidence
    rank: int | None = None
    score: float | None = None
    quality: str | None = None
    reasons: list[str] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    context: str | None = None


class ReviewItem(BaseModel):
    key: str
    message: str
    evidence: Evidence | None = None


class ExtractedField(BaseModel):
    key: str
    label: str
    value: Any = None
    unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_type: SourceType | None = None
    evidence: Evidence | None = None
    candidates: list[RegexCandidate] = Field(default_factory=list)
    needs_review: list[ReviewItem] = Field(default_factory=list)


class BuildingRightSection(BaseModel):
    title: str = "Ehitamise põhiõigus"
    fields: dict[str, ExtractedField] = Field(default_factory=dict)
    needs_review: list[ReviewItem] = Field(default_factory=list)


class SourceReference(BaseModel):
    pdf: str
    page: int
    reason: str


class DetailPlanMeta(BaseModel):
    address: str
    detail_plan: dict[str, Any] = Field(default_factory=dict)
    parcel_context: dict[str, Any] = Field(default_factory=dict)
    source_pdfs: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    chunks_sent: int = 0
    cache_dir: str | None = None


class DetailPlanAnalysisResponse(BaseModel):
    status: AnalysisStatus
    meta: DetailPlanMeta
    building_right: BuildingRightSection
    sources: list[SourceReference] = Field(default_factory=list)
    setup_issues: list[str] = Field(default_factory=list)
