from fastapi import APIRouter, HTTPException

from backend.core.logging import logger
from backend.detailplan_analyzer.analyzer import (
    analyze_detail_plan,
    highest_overlap_detail_plan,
)
from backend.geo import (
    DEFAULT_POI_LIMIT,
    Parcel,
    find_parcel_by_address,
    find_parcel_by_cadastre_code,
)
from backend.geo.constants import DETAIL_PLAN_RESPONSE_COLUMNS
from backend.geo.datasets import get_detail_plans
from backend.geo.serializers import row_to_geojson_dict

router = APIRouter()


@router.get("/")
def read_root():
    return {"Hello": "World"}


@router.get("/search")
def return_parcel_info_from_searchable(
    type: str, searchable: str, top_n: int = DEFAULT_POI_LIMIT
):
    logger.info([type, searchable])
    if type == "address":
        parcel: Parcel | None = find_parcel_by_address(address=searchable)
    elif type == "cadastre_code":
        parcel: Parcel | None = find_parcel_by_cadastre_code(cadastre_code=searchable)
    else:
        raise HTTPException(status_code=400, detail=f"Search type {type} not defined")

    logger.debug(parcel)
    if parcel is None:
        return {"error": "parcel get failed via cadastre search"}
    return {
        "Aadress": parcel.attributes(),
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
        "noise_levels": parcel.get_surrounding_noise_level(50),
        **parcel.get_spatial_context(),
    }


@router.get("/detail-plan-analysis")
def return_detail_plan_analysis(
    type: str,
    searchable: str,
    force_refresh: bool = False,
):
    logger.info(
        f"detail-plan-analysis request type={type} searchable={searchable} "
        f"force_refresh={force_refresh}"
    )
    if type == "address":
        parcel: Parcel | None = find_parcel_by_address(address=searchable)
    elif type == "cadastre_code":
        parcel: Parcel | None = find_parcel_by_cadastre_code(cadastre_code=searchable)
    else:
        raise HTTPException(status_code=400, detail=f"Search type {type} not defined")

    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcel not found")

    address = parcel.attributes().get("l_aadress") or searchable
    detail_plan = highest_overlap_detail_plan(parcel)
    if detail_plan is None:
        raise HTTPException(status_code=404, detail="Detail plan not found")

    result = analyze_detail_plan(
        detail_plan=detail_plan,
        address=address,
        force_refresh=force_refresh,
    )
    logger.info(
        f"detail-plan-analysis response status={result.status} "
        f"chunks={result.meta.chunks_sent} setup_issues={result.setup_issues}"
    )
    return result.model_dump(mode="json")


@router.get("/detail-plans/geojson")
def return_detail_plans_geojson():
    detail_plans = get_detail_plans()
    features = []
    for _, row in detail_plans.iterrows():
        serialized = row_to_geojson_dict(row, DETAIL_PLAN_RESPONSE_COLUMNS)
        geometry = serialized.pop("geometry")
        features.append(
            {
                "type": "Feature",
                "geometry": geometry,
                "properties": serialized,
            }
        )
    return {
        "type": "FeatureCollection",
        "features": features,
    }


@router.get("/nearby_pois")
def return_nearby_pois_from_cadastre(
    cadastre_code: str,
    top_n: int = DEFAULT_POI_LIMIT,
):
    if top_n < 1:
        raise HTTPException(status_code=400, detail="top_n must be at least 1")

    parcel: Parcel | None = find_parcel_by_cadastre_code(cadastre_code)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Cadastre not found")

    return {
        "cadastre_code": cadastre_code,
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
    }
