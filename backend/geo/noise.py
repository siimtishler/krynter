"""Noise-area intersection and area-weighted noise summaries."""

import geopandas as gpd

from backend.geo.constants import (
    COVERAGE_TOLERANCE_PCT,
    DEFAULT_NOISE_BUFFER_M,
    NO_DATA_DB_UPPER_BOUND,
)
from backend.geo.crs import ensure_data_crs
from backend.geo.datasets import get_noise


def _clip_noise_areas(
    noise_areas: gpd.GeoDataFrame,
    geometry,
) -> gpd.GeoDataFrame:
    """Clip noise polygons to a geometry and calculate clipped area columns."""
    clipped = noise_areas.copy()
    clipped["geometry"] = clipped.geometry.intersection(geometry)
    clipped = clipped[~clipped.geometry.is_empty].copy()
    clipped["MYRAKLASS"] = clipped["MYRAKLASS"].astype(float)
    clipped["area"] = clipped.geometry.area
    clipped["area_pct"] = 100 * clipped["area"] / geometry.area
    return clipped


def get_noise_areas(
    parceldf: gpd.GeoDataFrame,
    buffered_area_m: float,
    noise_areas: gpd.GeoDataFrame | None = None,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Return noise areas clipped to a parcel buffer and to the parcel itself."""
    parceldf = ensure_data_crs(parceldf)
    source_noise_areas = get_noise() if noise_areas is None else noise_areas
    source_noise_areas = ensure_data_crs(source_noise_areas)

    unbuffered = parceldf.geometry.iloc[0]
    buffered = unbuffered.buffer(buffered_area_m)
    idx = source_noise_areas.sindex.query(buffered, predicate="intersects")
    candidates = source_noise_areas.iloc[idx].copy()

    noise_areas_buffered = _clip_noise_areas(candidates, buffered)
    noise_areas_unbuffered = _clip_noise_areas(
        candidates.loc[candidates.geometry.intersects(unbuffered)],
        unbuffered,
    )

    return noise_areas_buffered, noise_areas_unbuffered


def average_noise_from_area(
    noise_areas: gpd.GeoDataFrame,
    geometry,
    no_data_db_upper_bound: float = NO_DATA_DB_UPPER_BOUND,
) -> dict:
    """Calculate an area-weighted noise average or upper bound."""
    geometry_area = float(geometry.area)
    mapped_area = (
        float(noise_areas.geometry.area.sum()) if not noise_areas.empty else 0.0
    )
    missing_area = max(geometry_area - mapped_area, 0.0)
    mapped_pct = 100 * mapped_area / geometry_area if geometry_area else 0.0
    missing_pct = max(100 - mapped_pct, 0.0)

    if geometry_area and not noise_areas.empty:
        mapped_weighted_db = float(
            (
                (noise_areas.geometry.area / geometry_area) * noise_areas["MYRAKLASS"]
            ).sum()
        )
    else:
        mapped_weighted_db = 0.0

    if mapped_pct >= 100 - COVERAGE_TOLERANCE_PCT:
        avg_db = mapped_weighted_db
        result_type = "exact"
        label = f"Keskmine = {avg_db:.1f} dB"
        avg_db_upper = None
    else:
        avg_db = None
        result_type = "upper_bound"
        avg_db_upper = (
            mapped_weighted_db + (missing_area / geometry_area) * no_data_db_upper_bound
            if geometry_area
            else 0.0
        )
        label = f"Keskmine < {avg_db_upper:.1f} dB"

    return {
        "label": label,
        "result_type": result_type,
        "avg_db": avg_db,
        "avg_db_upper": avg_db_upper,
        "mapped_pct": mapped_pct,
        "missing_pct": missing_pct,
        "area": geometry_area,
        "mapped_area": mapped_area,
        "missing_area": missing_area,
        "mapped_weighted_db": mapped_weighted_db,
        "no_data_db_upper_bound": no_data_db_upper_bound,
    }


def get_surrounding_noise_level(
    parceldf: gpd.GeoDataFrame,
    buffered_area_m: float = DEFAULT_NOISE_BUFFER_M,
) -> dict:
    """Summarize noise for a parcel and its surrounding buffer."""
    parceldf = ensure_data_crs(parceldf)
    unbuffered = parceldf.geometry.iloc[0]
    buffered = unbuffered.buffer(buffered_area_m)
    noise_areas_buffered, noise_areas_unbuffered = get_noise_areas(
        parceldf,
        buffered_area_m,
    )

    return {
        "buffer_m": buffered_area_m,
        "buffered": average_noise_from_area(noise_areas_buffered, buffered),
        "unbuffered": average_noise_from_area(noise_areas_unbuffered, unbuffered),
    }
