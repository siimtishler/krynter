"""Candidate scoring and ranking for rule-based extraction."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.detailplan_analyzer.models import RegexCandidate
from backend.detailplan_analyzer.rule_policies import CandidateScoringPolicy
from backend.detailplan_analyzer.rule_specs import FieldSpec, has_amount_text
from backend.detailplan_analyzer.value_parsing import (
    float_or_none,
    format_number,
    values_close,
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
        "tp-planeeritud",
    ),
}


@dataclass
class CandidateScoreState:
    score: float
    reasons: list[str]
    flags: list[str]


class CandidateScorer:
    """Scores, ranks, and gates regex candidates before a field is filled."""

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

    def __init__(self, policy: CandidateScoringPolicy | None = None) -> None:
        self.policy = policy or CandidateScoringPolicy()

    def rank_candidates(self, candidates: list[RegexCandidate]) -> list[RegexCandidate]:
        """Apply extraction heuristics and return candidates in deterministic order."""
        ranked: list[RegexCandidate] = []
        for candidate in candidates:
            score, reasons, flags = self._score_candidate(candidate)
            candidate.score = round(score, 2)
            candidate.quality = self._quality_for_score(score, flags)
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

    def candidate_can_fill_field(
        self,
        spec: FieldSpec,
        candidate: RegexCandidate,
        candidates: list[RegexCandidate],
    ) -> bool:
        if candidate.quality != "strong":
            return False
        return not self._has_close_conflict(spec, candidate, candidates)

    def _score_candidate(
        self,
        candidate: RegexCandidate,
    ) -> tuple[float, list[str], list[str]]:
        text = " ".join(
            part for part in (candidate.evidence.text, candidate.context or "") if part
        )
        low = text.lower()
        evidence_low = candidate.evidence.text.lower()
        state = CandidateScoreState(
            score=candidate.confidence * 100,
            reasons=list(candidate.reasons),
            flags=[],
        )

        self._score_address_context(candidate, state)
        self._score_keyword_context(candidate, low, evidence_low, state)
        self._score_field_specifics(candidate, evidence_low, state)

        if "toc_downrank" in candidate.reasons:
            state.score -= self.policy.toc_penalty
            state.flags.append("toc_context")

        return max(0, min(state.score, 100)), state.reasons, state.flags

    def _score_address_context(
        self,
        candidate: RegexCandidate,
        state: CandidateScoreState,
    ) -> None:
        if "target_address_context" in candidate.reasons:
            state.score += self.policy.target_address_boost
            state.reasons.append("boost:target_address")
        if "targeted_address" in candidate.reasons:
            state.score += self.policy.targeted_address_boost
            state.reasons.append("boost:targeted_address")
        if "same_street_wrong_address" in candidate.reasons:
            state.score -= self.policy.same_street_wrong_address_penalty
            state.flags.append("same_street_wrong_address")
        if "context_wrong_address" in candidate.reasons:
            state.score -= self.policy.context_wrong_address_penalty
            state.flags.append("context_wrong_address")
        if "other_address_context" in candidate.reasons:
            state.score -= self.policy.other_address_context_penalty
            state.flags.append("other_address_context")
        if "multi_address_context" in candidate.reasons:
            state.score -= self.policy.multi_address_context_penalty
            state.flags.append("multi_address_context")
        if "multi_value_table_row" in candidate.reasons:
            if "targeted_address" in candidate.reasons:
                state.flags.append("multi_value_targeted_context")
            else:
                state.score -= self.policy.multi_value_unscoped_penalty
                state.flags.append("multi_value_unscoped")
        if "address_number_capture" in candidate.reasons:
            state.score -= self.policy.address_number_capture_penalty
            state.flags.append("address_number_capture")
        if "unscoped_before_target_address" in candidate.reasons:
            state.score -= self.policy.unscoped_before_target_address_penalty
            state.flags.append("unscoped_before_target_address")
        if (
            candidate.field_key == "katusekalle"
            and "target_address_available" in candidate.reasons
            and "target_address_context" not in candidate.reasons
            and "targeted_address" not in candidate.reasons
        ):
            state.score -= self.policy.unscoped_address_context_penalty
            state.flags.append("unscoped_address_context")

    def _score_keyword_context(
        self,
        candidate: RegexCandidate,
        low: str,
        evidence_low: str,
        state: CandidateScoreState,
    ) -> None:
        for term in STRONG_CONTEXT_TERMS:
            if term in low:
                state.score += self.policy.strong_context_boost
                state.reasons.append(f"boost:{term}")

        for term in FIELD_STRONG_CONTEXT_TERMS.get(candidate.field_key, ()):
            if term in low:
                state.score += self.policy.field_strong_context_boost
                state.reasons.append(f"field_boost:{term}")

        for term in WEAK_CONTEXT_TERMS:
            if term not in evidence_low:
                continue
            if (
                candidate.field_key == "hoonete_lubatud_korgused_m"
                and term.startswith("olemasolev")
                and re.search(r"olemasoleva\w*\s+maapinn", evidence_low)
            ):
                continue
            state.score -= self.policy.weak_context_penalty
            state.flags.append(f"weak_context:{term}")

        for term in FIELD_WEAK_CONTEXT_TERMS.get(candidate.field_key, ()):
            if term in evidence_low:
                state.score -= self.policy.field_weak_context_penalty
                state.flags.append(f"field_weak_context:{term}")

    def _score_field_specifics(
        self,
        candidate: RegexCandidate,
        evidence_low: str,
        state: CandidateScoreState,
    ) -> None:
        if candidate.field_key == "lubatud_korrused":
            if "maa-alune" in evidence_low or "maa alune" in evidence_low:
                state.flags.append("underground_floor_context")
                state.score -= self.policy.underground_floor_penalty
                state.score = min(state.score, self.policy.underground_floor_score_cap)
            if not has_amount_text(candidate.value):
                state.flags.append("missing_floor_amount")
                state.score -= self.policy.missing_floor_amount_penalty

        if candidate.field_key == "hoonete_lubatud_korgused_m":
            if re.search(
                r"\b(?:piire|piirde|piirdeaia|heki|aia|traatvõrk|võrkai|võrgust)\w*",
                evidence_low,
            ):
                state.flags.append("not_building_height")
                state.score -= self.policy.not_building_height_penalty
            raw_low = str(candidate.raw_value).lower()
            if "rääst" in evidence_low and re.search(
                rf"rääst\w*\s+kõrgus\w*\s*[-–]?\s*{re.escape(raw_low)}\s*m",
                evidence_low,
            ):
                state.flags.append("eave_height")
                state.score -= self.policy.eave_height_penalty
            if not has_amount_text(candidate.value):
                state.flags.append("missing_height_amount")
                state.score -= self.policy.missing_height_amount_penalty

        if candidate.field_key == "krundi_pind_m2" and (
            "vähemalt" in evidence_low
            or "mahtuvate puude" in evidence_low
            or "puurinde" in evidence_low
        ):
            state.flags.append("general_minimum_area_context")
            state.score -= self.policy.general_minimum_area_penalty

    def _quality_for_score(self, score: float, flags: list[str]) -> str:
        if (
            score >= self.policy.strong_score_threshold
            and not self.blocking_flags.intersection(flags)
        ):
            return "strong"
        if score >= self.policy.candidate_score_threshold:
            return "candidate"
        return "weak"

    def _has_close_conflict(
        self,
        spec: FieldSpec,
        best: RegexCandidate,
        candidates: list[RegexCandidate],
    ) -> bool:
        best_score = best.score or 0
        for candidate in candidates[1:]:
            if (candidate.score or 0) < best_score - self.policy.close_conflict_score_gap:
                continue
            if (
                "targeted_address" in best.reasons
                and "targeted_address" not in candidate.reasons
            ):
                continue
            if not self._field_values_equivalent(spec.key, best, candidate):
                return True
        return False

    @staticmethod
    def _field_values_equivalent(
        field_key: str,
        left: RegexCandidate,
        right: RegexCandidate,
    ) -> bool:
        if field_key.endswith("_m2") or field_key == "taisehitus_pct":
            left_float = float_or_none(left.value)
            right_float = float_or_none(right.value)
            if left_float is not None and right_float is not None:
                return values_close(left_float, right_float, absolute=0.01)
        return (
            CandidateScorer._candidate_value_key(left)
            == CandidateScorer._candidate_value_key(right)
        )

    @staticmethod
    def _candidate_value_key(candidate: RegexCandidate) -> str:
        if isinstance(candidate.value, float):
            return format_number(candidate.value)
        return re.sub(r"\s+", " ", str(candidate.value).lower()).strip()
