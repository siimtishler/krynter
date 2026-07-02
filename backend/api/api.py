from fastapi import APIRouter, Body, HTTPException
from fastapi.responses import FileResponse

from backend.core.logging import logger
from backend.detailplan_analyzer.analyzer import (
    analyze_detail_plan,
    highest_overlap_detail_plan,
)
from backend.detailplan_analyzer.pdfs import (
    PDFDownloadError,
    download_plan_pdfs,
    safe_name,
)
from backend.geo import (
    DEFAULT_POI_LIMIT,
    Parcel,
    find_parcel_by_address,
    find_parcel_by_cadastre_code,
)
from backend.geo.constants import DETAIL_PLAN_RESPONSE_COLUMNS
from backend.geo.datasets import get_detail_plans, get_noise
from backend.geo.poi_settings import (
    poi_settings_response,
    save_poi_categories,
)
from backend.geo.serializers import row_to_geojson_dict

router = APIRouter()


def _parcel_from_searchable(type: str, searchable: str) -> Parcel | None:
    if type == "address":
        return find_parcel_by_address(address=searchable)
    if type == "cadastre_code":
        return find_parcel_by_cadastre_code(cadastre_code=searchable)
    raise HTTPException(status_code=400, detail=f"Search type {type} not defined")


def _feature_collection(frame, columns: list[str]) -> dict:
    features = []
    for _, row in frame.iterrows():
        serialized = row_to_geojson_dict(row, columns)
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


def _detail_plan_file_path(pdf_paths, file_type: str):
    if file_type == "seletuskiri":
        prefixed = [path for path in pdf_paths if path.name.startswith("SK")]
        candidates = prefixed or [
            path for path in pdf_paths if not path.name.startswith("JN100")
        ]
    elif file_type == "detailplaneering":
        candidates = [path for path in pdf_paths if path.name.startswith("JN100")]
    else:
        raise HTTPException(status_code=400, detail="Unknown detail-plan file type")

    if not candidates:
        raise HTTPException(status_code=404, detail="Detail-plan file not found")
    return sorted(candidates)[0]


def _detail_plan_download_filename(address: str, file_type: str) -> str:
    suffix = "detail_planeering" if file_type == "detailplaneering" else "seletuskiri"
    return f"{safe_name(address, 'detail_plan')}_{suffix}.pdf"


@router.get("/")
def read_root():
    return {"Hello": "World"}


@router.get("/search")
def return_parcel_info_from_searchable(
    type: str, searchable: str, top_n: int = DEFAULT_POI_LIMIT
):
    logger.info([type, searchable])
    parcel = _parcel_from_searchable(type, searchable)

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
    enable_llm_resolver: bool | None = True,
):
    logger.info(
        f"detail-plan-analysis request type={type} searchable={searchable} "
        f"force_refresh={force_refresh} enable_llm_resolver={enable_llm_resolver}"
    )
    parcel = _parcel_from_searchable(type, searchable)

    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcel not found")

    parcel_attributes = parcel.attributes()
    address = parcel_attributes.get("l_aadress") or searchable
    detail_plan = highest_overlap_detail_plan(parcel)
    if detail_plan is None:
        raise HTTPException(status_code=404, detail="Detail plan not found")

    analyze_kwargs = {
        "detail_plan": detail_plan,
        "address": address,
        "parcel_attributes": parcel_attributes,
        "force_refresh": force_refresh,
    }
    if enable_llm_resolver is not None:
        analyze_kwargs["enable_llm_resolver"] = enable_llm_resolver
    result = analyze_detail_plan(**analyze_kwargs)
    logger.info(
        f"detail-plan-analysis response status={result.status} "
        f"chunks={result.meta.chunks_sent} setup_issues={result.setup_issues}"
    )
    return result.model_dump(mode="json")


@router.get("/detail-plan-file")
def return_detail_plan_file(type: str, searchable: str, file_type: str):
    parcel = _parcel_from_searchable(type, searchable)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Parcel not found")
    address = parcel.attributes().get("l_aadress") or searchable

    detail_plan = highest_overlap_detail_plan(parcel)
    if detail_plan is None:
        raise HTTPException(status_code=404, detail="Detail plan not found")

    try:
        pdf_paths = download_plan_pdfs(detail_plan)
    except PDFDownloadError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    path = _detail_plan_file_path(pdf_paths, file_type)
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=_detail_plan_download_filename(address, file_type),
    )


@router.get("/poi-settings")
def return_poi_settings():
    return poi_settings_response()


@router.put("/poi-settings")
def update_poi_settings(payload: dict = Body(...)):
    try:
        poi_categories = payload.get("poi_categories", payload)
        return {
            "poi_categories": save_poi_categories(poi_categories),
            "saved": True,
        }
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/detail-plans/geojson")
def return_detail_plans_geojson():
    return _feature_collection(get_detail_plans(), DETAIL_PLAN_RESPONSE_COLUMNS)


@router.get("/noise-area/geojson")
def return_noise_area_geojson():
    return _feature_collection(get_noise(), ["MYRAKLASS"])


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
