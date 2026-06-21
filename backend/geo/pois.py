"""Nearest point-of-interest grouping for parcel summaries."""

import geopandas as gpd
import pandas as pd
import shapely

from backend.geo.constants import (
    DEFAULT_POI_LIMIT,
    POI_CATEGORIES,
    POI_FILTER_COLUMNS,
    POI_RESPONSE_COLUMNS,
)
from backend.geo.crs import ensure_data_crs, shape_to_frontend_geojson
from backend.geo.serializers import response_value


def _category_filters(category_or_query: dict) -> dict:
    """Return filter config for a POI category or query."""
    if "filters" in category_or_query:
        return category_or_query["filters"]

    return {
        column: category_or_query[column]
        for column in POI_FILTER_COLUMNS
        if column in category_or_query
    }


def _category_queries(category: dict) -> list[dict]:
    """Return subqueries for categories that need per-type limits."""
    return category.get("queries") or [category]


def _query_limit(category_or_query: dict, default_limit: int) -> int:
    """Resolve a query-specific limit with a configured default."""
    return max(0, int(category_or_query.get("limit", default_limit)))


def _category_mask(pois: gpd.GeoDataFrame, filters: dict) -> pd.Series:
    """Build a boolean mask for POIs matching any configured filter."""
    mask = pd.Series(False, index=pois.index)
    for column in POI_FILTER_COLUMNS:
        values = filters.get(column)
        if values and column in pois.columns:
            mask = mask | pois[column].isin(values)
    return mask


def _poi_row_to_dict(poi: pd.Series) -> dict:
    """Serialize a POI row for the API response."""
    result = {}
    for column in POI_RESPONSE_COLUMNS:
        value = response_value(poi.get(column))
        if column == "kaugus_m" and value is not None:
            value = float(value)
        result[column] = value

    result["geometry"] = shape_to_frontend_geojson(poi.geometry)
    return result


def _nearest_pois_for_query(
    pois: gpd.GeoDataFrame,
    origin: shapely.geometry.base.BaseGeometry,
    query: dict,
    default_limit: int,
) -> gpd.GeoDataFrame:
    """Return the nearest matching POIs for a single category query."""
    limit = _query_limit(query, default_limit)
    if limit < 1:
        return pois.iloc[0:0].copy()

    filters = _category_filters(query)
    query_pois = pois.loc[_category_mask(pois, filters)].copy()
    if query_pois.empty:
        return query_pois

    query_pois["kaugus_m"] = query_pois.distance(origin)
    query_pois.sort_values("kaugus_m", inplace=True)
    return query_pois.head(limit)


def _nearest_pois_for_category(
    pois: gpd.GeoDataFrame,
    origin: shapely.geometry.base.BaseGeometry,
    category: dict,
    default_limit: int,
) -> list[dict]:
    """Return nearest POIs for a configured category."""
    rows = []
    seen_indexes = set()

    for query in _category_queries(category):
        query_pois = _nearest_pois_for_query(
            pois=pois,
            origin=origin,
            query=query,
            default_limit=default_limit,
        )
        for index, row in query_pois.iterrows():
            if index in seen_indexes:
                continue

            seen_indexes.add(index)
            rows.append(row)

    rows.sort(key=lambda row: row["kaugus_m"])
    total_limit = category.get("total_limit", default_limit)
    rows = rows[: max(0, int(total_limit))]

    return [_poi_row_to_dict(row) for row in rows]


def get_nearest_pois_by_group(
    point_or_geometry: shapely.geometry.base.BaseGeometry,
    pois: gpd.GeoDataFrame,
    top_n: int = DEFAULT_POI_LIMIT,
) -> dict:
    """Return grouped nearby POIs for the provided parcel geometry."""
    pois = ensure_data_crs(pois)
    origin = shapely.centroid(point_or_geometry)
    nearby_pois = {}

    for category_id, category in POI_CATEGORIES.items():
        nearby_pois[category_id] = {
            "label": category["label"],
            "items": _nearest_pois_for_category(
                pois=pois,
                origin=origin,
                category=category,
                default_limit=top_n,
            ),
        }

    return nearby_pois
