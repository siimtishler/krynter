import json
import os
from pathlib import Path

import pytest

from backend.detailplan_analyzer.analyzer import (
    analyze_detail_plan,
    highest_overlap_detail_plan,
)
from backend.geo.parcel import find_parcel_by_address

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "detailplan_golden_cases.json"


def _load_cases() -> list[dict]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.getenv("KRUNTER_RUN_INTEGRATION") != "1",
    reason="Set KRUNTER_RUN_INTEGRATION=1 to run real detail-plan golden cases.",
)
@pytest.mark.parametrize("case", _load_cases(), ids=lambda case: case["id"])
def test_detail_plan_golden_case(case):
    assert case["type"] == "address"

    parcel = find_parcel_by_address(case["searchable"])
    assert parcel is not None

    detail_plan = highest_overlap_detail_plan(parcel)
    assert detail_plan is not None
    assert (
        str(
            detail_plan.get("sysid")
            or detail_plan.get("planid")
            or detail_plan.get("kovid")
        )
        == case["plan_id"]
    )

    response = analyze_detail_plan(
        detail_plan=detail_plan,
        address=case["searchable"],
        parcel_attributes=parcel.attributes(),
        enable_llm_resolver=False,
    )

    for field_key, expected in case["expected"].items():
        field = response.building_right.fields[field_key]
        assert field.value == expected["value"]
        assert field.unit == expected["unit"]
