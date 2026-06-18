from fastapi import APIRouter, HTTPException

from backend.core.logging import logger
from backend.geo.geo import (
    DEFAULT_POI_LIMIT,
    Parcel,
    get_parcel_cadastre_series_from_address,
    get_parcel_cadastre_series_from_cadastre,
)

router = APIRouter()


@router.get("/")
def read_root():
    return {"Hello": "World"}


@router.get("/search_address")
def return_parcel_from_address(address: str, top_n: int = DEFAULT_POI_LIMIT):
    parcel: Parcel = get_parcel_cadastre_series_from_address(address)
    logger.debug(parcel)
    if parcel is None:
        return {"error": "parcel get failed via address search"}
    return {
        "Aadress": Parcel.to_dict(parcel.parcel),
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
        "noise_levels": parcel.get_surrounding_noise_level(20),
    }


@router.get("/search_cadastre")
def return_address_from_cadastre(cadastre_code: str, top_n: int = DEFAULT_POI_LIMIT):
    parcel: Parcel = get_parcel_cadastre_series_from_cadastre(cadastre_code)
    logger.debug(parcel)
    if parcel is None:
        return {"error": "parcel get failed via cadastre search"}
    return {
        "Aadress": Parcel.to_dict(parcel.parcel),
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
        "noise_levels": parcel.get_surrounding_noise_level(20),
    }


@router.get("/nearby_pois")
def return_nearby_pois_from_cadastre(
    cadastre_code: str,
    top_n: int = DEFAULT_POI_LIMIT,
):
    if top_n < 1:
        raise HTTPException(status_code=400, detail="top_n must be at least 1")

    parcel: Parcel = get_parcel_cadastre_series_from_cadastre(cadastre_code)
    if parcel is None:
        raise HTTPException(status_code=404, detail="Cadastre not found")

    return {
        "cadastre_code": cadastre_code,
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
    }
