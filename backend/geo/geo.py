import geopandas as gpd
import pandas as pd
import numpy as np
import shapely
from backend.core.config import DATA_DIR
from functools import lru_cache
from backend.core.logging import logger
from backend.core.config import config


GPKG_FILE = DATA_DIR / "Tallinn_KATASTER_GPKG.gpkg"

@lru_cache(maxsize=1)
def load_tallinn_kataster_file():
    try:
        gd = gpd.read_file(filename=GPKG_FILE)
    except Exception as e:
        logger.error(e)
    return gd

gd = load_tallinn_kataster_file()


class GeometryConverter():
    def __init__(self):
        self._front_end_crs = config.frontend_crs
        self._data_crs = config.data_crs

    def self_front_end_crs(self, crs: str):
        self._front_end_crs = crs
    
    def convert_shape_to_front_end_crs_geojson(self, shape: shapely.Polygon) -> dict:
        converted_geometry = gpd.GeoSeries([shape], crs=self._data_crs).to_crs(self._front_end_crs)
        return shapely.geometry.mapping(
            converted_geometry.iloc[0]
        )

class ParcelCadastre():
    def __init__(self, parcel: pd.Series):
        self.parcel = parcel
        self.converter = GeometryConverter()

    def get_center_point_coords_geojson(self) -> dict:
        centre_point = shapely.centroid(self.parcel.geometry)
        return self.converter.convert_shape_to_front_end_crs_geojson(centre_point)

    def get_parcel_geometry_geojson(self) -> dict:
        return self.converter.convert_shape_to_front_end_crs_geojson(self.parcel.geometry)


def get_parcel_cadastre_series_from_address(address: str) -> ParcelCadastre:
    """
    Given the exact address string returns the parcel address
    """
    matches = gd.loc[gd["l_aadress"].eq(address)]
    if matches.empty:
        logger.error("No matches found")
        return None
    elif len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    parcel = matches.iloc[0]
    return ParcelCadastre(parcel=parcel)

if __name__ == "__main__":
    cadastre = get_parcel_cadastre_series_from_address("P. Kerese tn 5a")
    if cadastre == None:
        logger.error("No cadastre")
    coords = cadastre.get_center_point_coords_geojson()
    centre_point = cadastre.get_parcel_geometry_geojson()
    logger.info(coords)
    logger.info(centre_point)
