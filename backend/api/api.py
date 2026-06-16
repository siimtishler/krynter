import geopandas as gpd
from fastapi import APIRouter, HTTPException, Response

from backend.core.config import PROJECT_ROOT, config
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


@router.get("/debug/kerese-gpkg.geojson")
def get_kerese_gpkg_geojson():
    kerese_path = PROJECT_ROOT / "experiments" / "kerese_tnv.gpkg"
    if not kerese_path.exists():
        raise HTTPException(status_code=404, detail="Kerese GPKG not found")

    gdf = gpd.read_file(kerese_path)
    if gdf.crs is None:
        gdf = gdf.set_crs(config.data_crs)

    gdf = gdf.to_crs(config.frontend_crs)
    return Response(content=gdf.to_json(), media_type="application/geo+json")


@router.get("/search_address")
def return_parcel_from_address(address: str, top_n: int = DEFAULT_POI_LIMIT):
    parcel: Parcel = get_parcel_cadastre_series_from_address(address)
    logger.debug(parcel)
    if parcel is None:
        return {"error": "parcel get failed via address search"}
    coords = parcel.get_parcel_geometry_geojson()
    centre_point = parcel.get_center_point_coords_geojson()
    return {
        "Aadress": Parcel.to_dict(parcel.parcel),
        "coordinates": coords,
        "centre_point": centre_point,
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
    }


@router.get("/search_cadastre")
def return_address_from_cadastre(cadastre_code: str, top_n: int = DEFAULT_POI_LIMIT):
    parcel: Parcel = get_parcel_cadastre_series_from_cadastre(cadastre_code)
    logger.debug(parcel)
    if parcel is None:
        return {"error": "parcel get failed via cadastre search"}
    coords = parcel.get_parcel_geometry_geojson()
    centre_point = parcel.get_center_point_coords_geojson()
    return {
        "Aadress": Parcel.to_dict(parcel.parcel),
        "coordinates": coords,
        "centre_point": centre_point,
        "nearby_pois": parcel.get_nearby_pois(top_n=top_n),
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
