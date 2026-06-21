"""Generic spatial lookup helpers."""

import geopandas as gpd

from backend.geo.crs import ensure_data_crs


def spatial_intersections(geometry, source_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return source rows whose geometry intersects the provided geometry."""
    source_gdf = ensure_data_crs(source_gdf)
    if source_gdf.empty:
        return source_gdf.copy()

    idx = source_gdf.sindex.query(geometry, predicate="intersects")
    candidates = source_gdf.iloc[idx].copy()
    if candidates.empty:
        return candidates

    return candidates.loc[candidates.geometry.intersects(geometry)].copy()


def spatial_match_response(items: list[dict]) -> dict:
    """Wrap serialized spatial matches in the frontend response shape."""
    return {
        "count": len(items),
        "items": items,
    }
