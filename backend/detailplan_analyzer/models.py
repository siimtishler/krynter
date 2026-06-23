"""Pydantic models for detail-planning PDF analysis."""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field


class AnalysisStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NEEDS_SETUP = "needs_setup"
    LLM_UNAVAILABLE = "llm_unavailable"
    NOT_FOUND = "not_found"


SourceType = Literal["regex", "llm", "derived", "pdf", "system"]


class Evidence(BaseModel):
    pdf: str | None = None
    page: int | None = None
    text: str


class Fact(BaseModel):
    key: str
    label: str
    value: Any = None
    unit: str | None = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    source_type: SourceType
    evidence: Evidence | None = None


class ReviewItem(BaseModel):
    key: str
    message: str
    evidence: Evidence | None = None


class AnalysisSection(BaseModel):
    title: str
    found_in_pdf: list[Fact] = Field(default_factory=list)
    needs_review: list[ReviewItem] = Field(default_factory=list)


class SourceReference(BaseModel):
    pdf: str
    page: int
    reason: str


class DetailPlanMeta(BaseModel):
    address: str
    detail_plan: dict[str, Any] = Field(default_factory=dict)
    source_pdfs: list[str] = Field(default_factory=list)
    ocr_used: bool = False
    ollama_model: str | None = None
    chunks_sent: int = 0
    cache_dir: str | None = None


class DetailPlanAnalysisResponse(BaseModel):
    status: AnalysisStatus
    meta: DetailPlanMeta
    sections: dict[str, AnalysisSection]
    sources: list[SourceReference] = Field(default_factory=list)
    setup_issues: list[str] = Field(default_factory=list)


class LLMClaim(BaseModel):
    text: str
    page: int | None = None
    evidence_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class LLMValue(BaseModel):
    value: Any = None
    page: int | None = None
    evidence_text: str | None = None
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class LLMBuildingRight(BaseModel):
    parcel_area_m2: LLMValue = Field(default_factory=LLMValue)
    use_purpose: LLMValue = Field(default_factory=LLMValue)
    floors: LLMValue = Field(default_factory=LLMValue)
    site_coverage_pct: LLMValue = Field(default_factory=LLMValue)
    height_m: LLMValue = Field(default_factory=LLMValue)
    building_count: LLMValue = Field(default_factory=LLMValue)


class StructuredLLMResponse(BaseModel):
    summary: str | None = None
    building_right: LLMBuildingRight = Field(default_factory=LLMBuildingRight)
    architecture: list[LLMClaim] = Field(default_factory=list)
    landscaping_environment: list[LLMClaim] = Field(default_factory=list)
    access_parking: list[LLMClaim] = Field(default_factory=list)
    utilities: list[LLMClaim] = Field(default_factory=list)
    servitudes_restrictions: list[LLMClaim] = Field(default_factory=list)
    missing_or_needs_review: list[str] = Field(default_factory=list)
    buyer_risks: list[LLMClaim] = Field(default_factory=list)
