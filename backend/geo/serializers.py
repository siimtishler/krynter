"""API serialization helpers for GeoPandas and Shapely values."""

import pandas as pd

from backend.geo.crs import shape_to_frontend_geojson


def response_value(value):
    """Convert pandas/numpy missing and scalar values into JSON-safe values."""
    if value is None:
        return None

    try:
        is_missing = pd.isna(value)
    except TypeError:
        is_missing = False

    if not hasattr(is_missing, "__len__"):
        try:
            if bool(is_missing):
                return None
        except TypeError:
            pass

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        try:
            return value.item()
        except ValueError:
            return value

    return value


def row_to_dict(row: pd.Series, columns: list[str]) -> dict:
    """Serialize selected non-geometry columns from a row."""
    return {column: response_value(row.get(column)) for column in columns}


def row_to_geojson_dict(row: pd.Series, columns: list[str]) -> dict:
    """Serialize selected row fields plus geometry as frontend GeoJSON."""
    result = row_to_dict(row, columns)
    result["geometry"] = shape_to_frontend_geojson(row.geometry)
    return result


def polygon_overlap_row_to_dict(
    row: pd.Series,
    parcel_geometry,
    columns: list[str],
) -> dict:
    """Serialize a polygon row and include parcel-overlap metrics."""
    result = row_to_geojson_dict(row, columns)
    intersection_area_m2 = float(row.geometry.intersection(parcel_geometry).area)
    parcel_area_m2 = float(parcel_geometry.area)
    result["intersection_area_m2"] = intersection_area_m2
    result["parcel_coverage_pct"] = (
        100 * intersection_area_m2 / parcel_area_m2 if parcel_area_m2 else 0.0
    )
    return result
