from fastapi import APIRouter

from backend.geo.geo import (
    get_parcel_cadastre_series_from_address,
    ParcelCadastre
)

router = APIRouter()

@router.get("/")
def read_root():
    return {"Hello": "World"}


@router.get("/search")
def return_address(address: str):
    cadastre = get_parcel_cadastre_series_from_address(address)
    if cadastre == None:
        return {
            "error": "cadastre get failed"
        }
    coords = cadastre.get_parcel_geometry_geojson()
    centre_point = cadastre.get_center_point_coords_geojson()
    return {
        "Aadress": f"nox {address}",
        "coordinates": coords,
        "centre_point": centre_point
    }