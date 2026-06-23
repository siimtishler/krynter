"""Parcel intersections with configured spatial overlay datasets."""

from collections.abc import Callable

import geopandas as gpd
import pandas as pd

from backend.geo.constants import (
    DETAIL_PLAN_MIN_COVERAGE_PCT,
    DETAIL_PLAN_RESPONSE_COLUMNS,
    HERITAGE_POI_RESPONSE_COLUMNS,
    RESTRICTION_AREA_RESPONSE_COLUMNS,
)
from backend.geo.datasets import (
    get_detail_plans,
    get_heritage_pois,
    get_restriction_areas,
)
from backend.geo.serializers import (
    polygon_overlap_row_to_dict,
    row_to_geojson_dict,
)
from backend.geo.spatial import spatial_intersections, spatial_match_response


def _serialize_overlay_matches(
    parcel_geometry,
    source_gdf: gpd.GeoDataFrame,
    serializer: Callable[[pd.Series], dict],
    sort_by_overlap: bool = False,
) -> dict:
    matches = spatial_intersections(parcel_geometry, source_gdf)
    items = [serializer(row) for _, row in matches.iterrows()]

    if sort_by_overlap:
        items.sort(key=lambda item: item["intersection_area_m2"], reverse=True)

    return spatial_match_response(items)


def _polygon_overlay_response(
    parcel_geometry,
    source_gdf: gpd.GeoDataFrame,
    columns: list[str],
) -> dict:
    return _serialize_overlay_matches(
        parcel_geometry=parcel_geometry,
        source_gdf=source_gdf,
        serializer=lambda row: polygon_overlap_row_to_dict(
            row,
            parcel_geometry,
            columns,
        ),
        sort_by_overlap=True,
    )


def get_overlapping_heritage_pois(
    parcel_geometry,
    heritage_pois: gpd.GeoDataFrame | None = None,
) -> dict:
    """Return heritage points that intersect the parcel geometry."""
    source = get_heritage_pois() if heritage_pois is None else heritage_pois
    return _serialize_overlay_matches(
        parcel_geometry=parcel_geometry,
        source_gdf=source,
        serializer=lambda row: row_to_geojson_dict(
            row,
            HERITAGE_POI_RESPONSE_COLUMNS,
        ),
    )


def get_overlapping_restriction_areas(
    parcel_geometry,
    restriction_areas: gpd.GeoDataFrame | None = None,
) -> dict:
    """Return restriction areas intersecting a parcel, sorted by overlap area."""
    source = get_restriction_areas() if restriction_areas is None else restriction_areas
    return _polygon_overlay_response(
        parcel_geometry,
        source,
        RESTRICTION_AREA_RESPONSE_COLUMNS,
    )


def get_overlapping_detail_plans(
    parcel_geometry,
    detail_plans: gpd.GeoDataFrame | None = None,
) -> dict:
    """Return detailed plans intersecting a parcel, sorted by overlap area."""
    source = get_detail_plans() if detail_plans is None else detail_plans
    response = _polygon_overlay_response(
        parcel_geometry,
        source,
        DETAIL_PLAN_RESPONSE_COLUMNS,
    )
    items = [
        item
        for item in response["items"]
        if item["parcel_coverage_pct"] >= DETAIL_PLAN_MIN_COVERAGE_PCT
    ]
    return spatial_match_response(items)
