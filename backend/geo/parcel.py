"""Parcel domain object and cadastre lookup helpers."""

import geopandas as gpd

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.geo.constants import DEFAULT_NOISE_BUFFER_M, DEFAULT_POI_LIMIT
from backend.geo.datasets import get_cadastre, get_pois
from backend.geo.noise import get_surrounding_noise_level
from backend.geo.overlays import (
    get_overlapping_detail_plans,
    get_overlapping_heritage_pois,
    get_overlapping_restriction_areas,
)
from backend.geo.pois import get_nearest_pois_by_group


class Parcel:
    """Convenience wrapper around the selected parcel GeoDataFrame row."""

    def __init__(self, frame: gpd.GeoDataFrame):
        self.frame = frame
        self.row = frame.iloc[0]
        self.geometry = self.row.geometry

    def attributes(self) -> dict:
        """Return parcel attributes without the Shapely geometry object."""
        parcel_dict = self.row.to_dict()
        parcel_dict.pop("geometry", None)
        return parcel_dict

    @time_function
    def get_nearby_pois(self, top_n: int = DEFAULT_POI_LIMIT) -> dict:
        return get_nearest_pois_by_group(
            self.geometry,
            top_n=top_n,
            pois=get_pois(),
        )

    @time_function
    def get_surrounding_noise_level(
        self,
        buffered_area_m: float = DEFAULT_NOISE_BUFFER_M,
    ) -> dict:
        return get_surrounding_noise_level(
            self.frame,
            buffered_area_m=buffered_area_m,
        )

    @time_function
    def get_heritage_pois(self) -> dict:
        return get_overlapping_heritage_pois(self.geometry)

    @time_function
    def get_restriction_areas(self) -> dict:
        return get_overlapping_restriction_areas(self.geometry)

    @time_function
    def get_detail_plans(self) -> dict:
        return get_overlapping_detail_plans(self.geometry)

    def get_spatial_context(self) -> dict:
        return {
            "heritage_pois": self.get_heritage_pois(),
            "restriction_areas": self.get_restriction_areas(),
            "detail_plans": self.get_detail_plans(),
        }


def find_parcel_by_cadastre_code(cadastre_code: str) -> Parcel | None:
    """Find exactly one parcel by cadastre code."""
    cadastre = get_cadastre()
    matches = cadastre.loc[cadastre["tunnus"].eq(cadastre_code)]
    if matches.empty:
        logger.error("No matches found")
        return None
    if len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    return Parcel(frame=matches)


def find_parcel_by_address(address: str) -> Parcel | None:
    """Find exactly one parcel by full address."""
    cadastre = get_cadastre()
    matches = cadastre.loc[cadastre["l_aadress"].eq(address)]
    if matches.empty:
        logger.error("No matches found")
        return None
    if len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    return Parcel(frame=matches)
