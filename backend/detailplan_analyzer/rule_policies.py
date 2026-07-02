"""Named policy values for detail-plan rule extraction."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExtractionPolicy:
    pdf_regex_confidence_cap: float = 0.72
    pdf_manual_confidence_cap: float = 0.78
    match_context_lines: int = 3
    match_context_chars: int = 1200
    evidence_line_chars: int = 700
    target_window_chars: int = 900
    targeted_context_before_lines: int = 2
    targeted_context_after_lines: int = 4


@dataclass(frozen=True)
class CandidateScoringPolicy:
    target_address_boost: float = 18
    targeted_address_boost: float = 18
    same_street_wrong_address_penalty: float = 55
    context_wrong_address_penalty: float = 35
    other_address_context_penalty: float = 40
    multi_address_context_penalty: float = 6
    multi_value_unscoped_penalty: float = 45
    address_number_capture_penalty: float = 75
    unscoped_before_target_address_penalty: float = 55
    unscoped_address_context_penalty: float = 45
    strong_context_boost: float = 6
    field_strong_context_boost: float = 15
    weak_context_penalty: float = 12
    field_weak_context_penalty: float = 18
    underground_floor_penalty: float = 18
    underground_floor_score_cap: float = 70
    missing_floor_amount_penalty: float = 35
    not_building_height_penalty: float = 35
    eave_height_penalty: float = 35
    missing_height_amount_penalty: float = 30
    general_minimum_area_penalty: float = 45
    toc_penalty: float = 25
    strong_score_threshold: float = 88
    candidate_score_threshold: float = 62
    close_conflict_score_gap: float = 8
