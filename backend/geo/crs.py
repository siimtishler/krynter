"""Coordinate reference system helpers for backend geometry data."""

import geopandas as gpd
import shapely

from backend.core.config import config


def ensure_data_crs(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return a GeoDataFrame in the configured backend data CRS."""
    if gdf.crs is None:
        return gdf.set_crs(config.data_crs)
    if gdf.crs != config.data_crs:
        return gdf.to_crs(config.data_crs)
    return gdf


def shape_to_frontend_geojson(shape: shapely.geometry.base.BaseGeometry) -> dict:
    """Convert a Shapely geometry from data CRS to frontend GeoJSON CRS."""
    converted_geometry = gpd.GeoSeries([shape], crs=config.data_crs).to_crs(
        config.frontend_crs
    )
    return shapely.geometry.mapping(converted_geometry.iloc[0])
