"""Address-scoped candidate extraction for selected parcel rows/windows."""

from __future__ import annotations

import re

from backend.detailplan_analyzer.addressing import (
    ParsedAddress,
    has_wrong_same_street_address,
    normalize_address_number,
    same_street_address_regex,
    target_address_match,
    target_address_regex,
)
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import Evidence, RegexCandidate
from backend.detailplan_analyzer.rule_policies import ExtractionPolicy
from backend.detailplan_analyzer.rule_specs import FieldSpec
from backend.detailplan_analyzer.value_parsing import (
    float_or_none,
    parse_text,
)

NUMBER_TOKEN_PATTERN = r"\d+(?:[,.]\d+)?"

TARGETED_FIELD_KEYS = {
    "krundi_pind_m2",
    "taisehitus_pct",
    "ehitusalune_pind_m2",
    "hoonete_lubatud_korgused_m",
    "hoonete_arv",
    "katusekalle",
}


class AddressScopedExtractor:
    """Extracts candidates from text windows anchored to the selected parcel address."""

    def __init__(self, policy: ExtractionPolicy | None = None) -> None:
        self.policy = policy or ExtractionPolicy()

    def extract(
        self,
        chunks: list[TextChunk],
        spec: FieldSpec,
        target_address: ParsedAddress,
    ) -> list[RegexCandidate]:
        if spec.key not in TARGETED_FIELD_KEYS:
            return []

        candidates: list[RegexCandidate] = []
        for chunk in chunks:
            if chunk.field_key is not None and chunk.field_key != spec.key:
                continue
            candidates.extend(
                self._table_row_target_candidates(chunk, spec, target_address)
            )
            candidates.extend(
                self._targeted_window_candidates(chunk, spec, target_address)
            )
        return candidates

    def _manual_regex_candidate(
        self,
        chunk: TextChunk,
        spec: FieldSpec,
        pattern_name: str,
        raw: str,
        evidence_text: str,
        context: str,
        confidence: float = 0.96,
    ) -> RegexCandidate | None:
        try:
            value = spec.parse_value(raw)
        except (TypeError, ValueError):
            return None
        return RegexCandidate(
            field_key=spec.key,
            label=spec.label,
            value=value,
            raw_value=parse_text(raw),
            unit=spec.unit,
            confidence=min(confidence, self.policy.pdf_manual_confidence_cap),
            pattern_name=pattern_name,
            evidence=Evidence(
                pdf=chunk.pdf_path.name,
                page=chunk.page,
                text=evidence_text.strip()[: self.policy.evidence_line_chars],
            ),
            reasons=sorted(
                set([*chunk.reasons, "target_address_context", "targeted_address"])
            ),
            context=context,
        )

    def _address_row_numbers(
        self,
        line: str,
        target_address: ParsedAddress,
    ) -> list[tuple[str, bool]]:
        match = target_address_match(target_address, line)
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
        self,
        chunk: TextChunk,
        spec: FieldSpec,
        target_address: ParsedAddress,
    ) -> list[RegexCandidate]:
        candidates: list[RegexCandidate] = []
        lines = chunk.text.splitlines()
        for index, line in enumerate(lines):
            numbers = self._address_row_numbers(line, target_address)
            if not numbers:
                continue
            low_line = line.lower()
            if "katastri" in low_line or re.search(r"\d+:\d+:\d+", line):
                continue

            numeric_values = [float_or_none(value) for value, _ in numbers]
            table_like = (
                len(numeric_values) >= 3
                and numeric_values[0] is not None
                and numeric_values[1] is not None
                and numeric_values[0] > 100
                and numeric_values[1] > 20
            )
            context = self._candidate_context_around_line(lines, index)
            raw = self._table_row_value_for_spec(spec, numbers, table_like, low_line)
            if raw is None:
                continue
            candidate = self._manual_regex_candidate(
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

    def _table_row_value_for_spec(
        self,
        spec: FieldSpec,
        numbers: list[tuple[str, bool]],
        table_like: bool,
        low_line: str,
    ) -> str | None:
        if spec.key == "krundi_pind_m2" and table_like:
            return numbers[0][0]
        if spec.key == "ehitusalune_pind_m2" and table_like:
            return numbers[1][0]
        if spec.key == "taisehitus_pct":
            percent_values = [value for value, is_percent in numbers if is_percent]
            if percent_values and "täisehitus" in low_line:
                return percent_values[0]
            if table_like:
                return numbers[2][0]
        if spec.key == "hoonete_arv" and table_like and len(numbers) >= 5:
            return numbers[4][0]
        return None

    def _selected_address_windows(
        self,
        chunk: TextChunk,
        target_address: ParsedAddress,
    ) -> list[tuple[str, str]]:
        windows: list[tuple[str, str]] = []
        target_regex = target_address_regex(target_address)
        wrong_regex = same_street_address_regex(target_address)
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
            if has_wrong_same_street_address(target_address, line_prefix):
                continue

            end = min(len(chunk.text), match.start() + self.policy.target_window_chars)
            for other in wrong_regex.finditer(chunk.text, match.end(), end):
                if (
                    normalize_address_number(other.group("number"))
                    != target_address.normalized_number
                ):
                    end = other.start()
                    break
            window = chunk.text[match.start() : end].strip()
            line = self._line_for_offset(chunk.text, match.start())
            if window:
                windows.append((window, line))
        return windows

    def _targeted_window_candidates(
        self,
        chunk: TextChunk,
        spec: FieldSpec,
        target_address: ParsedAddress,
    ) -> list[RegexCandidate]:
        candidates: list[RegexCandidate] = []
        for window, line in self._selected_address_windows(chunk, target_address):
            raw, pattern_name = self._window_value_for_spec(
                spec, window, line, target_address
            )
            if raw is None:
                continue
            evidence = line if line else window.splitlines()[0]
            candidate = self._manual_regex_candidate(
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

    def _window_value_for_spec(
        self,
        spec: FieldSpec,
        window: str,
        line: str,
        target_address: ParsedAddress,
    ) -> tuple[str | None, str]:
        if spec.key == "taisehitus_pct":
            return self._coverage_from_window(window), "address_scoped_context"
        if spec.key == "ehitusalune_pind_m2":
            return self._footprint_from_window(window), "address_scoped_context"
        if spec.key == "hoonete_lubatud_korgused_m":
            return self._building_height_from_window(window), "address_scoped_context"
        if spec.key == "katusekalle":
            return (
                self._roof_pitch_from_window(window, line, target_address),
                "address_scoped_context",
            )
        if spec.key == "hoonete_arv":
            return self._building_count_from_window(window, line)
        return None, "address_scoped_context"

    def _coverage_from_window(self, window: str) -> str | None:
        return self._first_match(
            rf"\btäisehitus(?:e\s*protsent|protsent)?\D{{0,90}}"
            rf"(?P<value>{NUMBER_TOKEN_PATTERN})\s*%",
            window,
        )

    def _footprint_from_window(self, window: str) -> str | None:
        return self._first_match(
            r"\b(?:ehitisealune|ehitusalune|hoonete\s+suurim\s+lubatud\s+ehitusalune)"
            r"\s+pind(?:ala)?\D{0,90}(?P<value>\d[\d\s.,]*)\s*m(?:2|²)\b",
            window,
        )

    def _building_height_from_window(self, window: str) -> str | None:
        return self._first_match(
            rf"\b(?:maksimaalne\s+hoonestuse\s+kõrgus|"
            rf"lubatud\s+suurim\s+(?:katuseharja\s+)?kõrgus|"
            rf"maksimaalseks\s+kõrguseks)"
            rf"\D{{0,120}}(?P<value>{NUMBER_TOKEN_PATTERN})\s*m\b",
            window,
        )

    def _building_count_from_window(
        self,
        window: str,
        line: str,
    ) -> tuple[str | None, str]:
        if "hoonete arv" in line.lower() or "hoonete arv" in window.lower():
            scoped = re.search(
                r"\bkrundil\b\D{0,12}(?P<value>\d+)\b",
                window,
                flags=re.IGNORECASE,
            )
            if scoped is not None:
                return scoped.group("value"), "address_scoped_context"
        count = self._building_count_from_noun_quantities(window)
        if count is not None:
            return str(count), "address_scoped_building_nouns"
        return None, "address_scoped_context"

    def _roof_pitch_from_window(
        self,
        window: str,
        line: str,
        target_address: ParsedAddress,
    ) -> str | None:
        if "katuse" not in window.lower() and "katuse" not in line.lower():
            return None

        pitch = re.search(
            r"\bkatuse\s*kalle|\bkatusekalle", window, flags=re.IGNORECASE
        )
        if pitch is not None:
            pitch_value = re.search(
                rf"(?P<value>{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?\s*[-–]\s*"
                rf"{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?)",
                window[pitch.end() : pitch.end() + 180],
                flags=re.IGNORECASE,
            )
            if pitch_value is not None:
                return pitch_value.group("value")

        if "katuse" not in line.lower():
            return None
        address_match = target_address_match(target_address, line)
        if address_match is None:
            return None
        pitch_value = re.search(
            rf"(?P<value>{NUMBER_TOKEN_PATTERN}\s*[˚°]?\s*[-–]\s*"
            rf"{NUMBER_TOKEN_PATTERN}\s*[˚°Oo]?)",
            line[address_match.end() : address_match.end() + 120],
            flags=re.IGNORECASE,
        )
        return pitch_value.group("value") if pitch_value else None

    def _candidate_context_around_line(self, lines: list[str], index: int) -> str:
        start = max(0, index - self.policy.targeted_context_before_lines)
        end = min(len(lines), index + self.policy.targeted_context_after_lines)
        return "\n".join(lines[start:end]).strip()[: self.policy.match_context_chars]

    @staticmethod
    def _first_match(pattern: str, text: str) -> str | None:
        match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        return match.group("value") if match else None

    @staticmethod
    def _line_for_offset(text: str, offset: int) -> str:
        start = text.rfind("\n", 0, offset) + 1
        end = text.find("\n", offset)
        if end == -1:
            end = len(text)
        return text[start:end].strip()[:700]

    @staticmethod
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
