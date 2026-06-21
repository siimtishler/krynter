from fastapi import APIRouter, HTTPException

from backend.core.logging import logger
from backend.geo import (
    DEFAULT_POI_LIMIT,
    Parcel,
    find_parcel_by_address,
    find_parcel_by_cadastre_code,
)

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
