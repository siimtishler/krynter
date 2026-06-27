"""Lazy GeoPackage dataset loading."""

from enum import Enum
from functools import lru_cache
from pathlib import Path

import geopandas as gpd

from backend.core.config import config
from backend.core.logging import logger


class Dataset(Enum):
    """Known backend GeoPackage datasets."""

    CADASTRE = "cadastre"
    POIS = "pois"
    NOISE = "noise"
    HERITAGE_POIS = "heritage_pois"
    RESTRICTION_AREAS = "restriction_areas"
    DETAIL_PLANS = "detail_plans"


_DATASET_FILES = {
    Dataset.CADASTRE: config.cadastre_file,
    Dataset.POIS: config.poi_file,
    Dataset.NOISE: config.noise_file,
    Dataset.HERITAGE_POIS: config.heritage_poi_file,
    Dataset.RESTRICTION_AREAS: config.restriction_areas_file,
    Dataset.DETAIL_PLANS: config.detail_plans_file,
}


@lru_cache(maxsize=None)
def load_gpkg_file(filename: Path | str) -> gpd.GeoDataFrame:
    """Load a GeoPackage file once per process."""
    try:
        return gpd.read_file(filename=filename)
    except Exception:
        logger.exception(f"Failed to load GeoPackage file {filename}")
        raise


def dataset_path(dataset: Dataset) -> Path:
    """Return the configured file path for a dataset."""
    return _DATASET_FILES[dataset]


@lru_cache(maxsize=None)
def load_dataset(dataset: Dataset) -> gpd.GeoDataFrame:
    """Load a configured dataset once per process."""
    return load_gpkg_file(dataset_path(dataset))


def get_cadastre() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.CADASTRE)


def get_pois() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.POIS)


def get_noise() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.NOISE)


def get_heritage_pois() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.HERITAGE_POIS)


def get_restriction_areas() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.RESTRICTION_AREAS)


def get_detail_plans() -> gpd.GeoDataFrame:
    return load_dataset(Dataset.DETAIL_PLANS)
