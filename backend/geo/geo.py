import geopandas as gpd
import pandas as pd
import shapely
from functools import lru_cache
from backend.core.logging import logger
from backend.core.config import config


DEFAULT_POI_LIMIT = 3
POI_FILTER_COLUMNS = ("grupp", "alamgrupp", "poi_type")

# Use filters for one nearest list, or queries when each subtype needs its own limit.
POI_CATEGORIES = {
    "sport_ja_liikumine": {
        "label": "Sport ja liikumine",
        "queries": [
            {
                "label": "Sport",
                "limit": 3,
                "filters": {"grupp": {"sport"}},
            },
            {
                "label": "Terviserajad",
                "limit": 2,
                "filters": {"grupp": {"terviserada"}},
            },
            {
                "label": "Supluskohad",
                "limit": 2,
                "filters": {"grupp": {"supluskoht"}},
            },
        ],
    },
    "poed_ja_ostud": {
        "label": "Poed ja ostud",
        "filters": {
            "alamgrupp": {"kaubanduskeskus"},
        },
    },
    "haridus_ja_lapsed": {
        "label": "Haridus ja lapsed",
        "queries": [
            {
                "label": "Põhikoolid ja gümnaasiumid",
                "limit": 2,
                "filters": {"alamgrupp": {"põhikool või gümnaasium"}},
            },
            {
                "label": "Lastehoid",
                "limit": 1,
                "filters": {"alamgrupp": {"koolieelne lasteasutus", "lasteaed"}},
            },
            {
                "label": "Huvikoolid",
                "limit": 2,
                "filters": {"alamgrupp": {"huvikool"}},
            },
            {
                "label": "Lapsehoid",
                "limit": 1,
                "filters": {"alamgrupp": {"lapsehoiuteenus"}},
            },
        ],
    },
    "tervis": {
        "label": "Tervis",
        "queries": [
            {
                "label": "Perearst",
                "limit": 1,
                "filters": {"grupp": {"perearst"}},
            },
            {
                "label": "Haiglad",
                "limit": 1,
                "filters": {"grupp": {"haigla"}},
            },
            {
                "label": "Apteegid",
                "limit": 1,
                "filters": {"grupp": {"tervisekaubad"}},
            },
        ],
    },
    "transport": {
        "label": "Transport",
        "queries": [
            {
                "label": "Peatused",
                "limit": 3,
                "filters": {"grupp": {"peatus"}},
            },
            {
                "label": "Parklad",
                "limit": 1,
                "filters": {"grupp": {"parkla"}},
            },
        ],
    },
    "igapaevateenused": {
        "label": "Igapäevateenused",
        "queries": [
            {
                "label": "Post",
                "limit": 1,
                "filters": {"grupp": {"post"}},
            },
            {
                "label": "Pank ja ATM",
                "limit": 1,
                "filters": {"grupp": {"pank"}},
            },
            {
                "label": "Tankla",
                "limit": 1,
                "filters": {"grupp": {"tankla"}},
            },
            {
                "label": "Laadimispunkt",
                "limit": 1,
                "filters": {"grupp": {"laadimispunkt"}},
            },
        ],
    },
    "sook_ja_kohvikud": {
        "label": "Söök ja kohvikud",
        "filters": {"grupp": {"toitlustus"}},
    },
    "kultuur_ja_vaba_aeg": {
        "label": "Kultuur ja vaba aeg",
        "queries": [
            {
                "label": "Kinod",
                "limit": 1,
                "filters": {"alamgrupp": {"kino"}},
            },
            {
                "label": "Teatrid",
                "limit": 1,
                "filters": {"alamgrupp": {"teater"}},
            },
            {
                "label": "Muuseumid",
                "limit": 1,
                "filters": {"alamgrupp": {"muuseum"}},
            },
            {
                "label": "Kirikud",
                "limit": 1,
                "filters": {"alamgrupp": {"religioon"}},
            },
        ],
    },
    "majutus": {
        "label": "Majutus",
        "filters": {"grupp": {"majutus"}},
    },
}

POI_RESPONSE_COLUMNS = [
    "nimi",
    "aadress",
    "kaugus_m",
    "grupp",
    "alamgrupp",
    "ylemgrupp",
    "poi_type",
]

@lru_cache(maxsize=1)
def load_tallinn_kataster_file():
    try:
        gd = gpd.read_file(filename=config.cadastre_file)
    except Exception as e:
        logger.error(e)
    return gd

@lru_cache(maxsize=1)
def load_tallinn_poi_file():
    try:
        gd = gpd.read_file(filename=config.poi_file)
    except Exception as e:
        logger.error(e)
    return gd

gd = load_tallinn_kataster_file()
poigd = load_tallinn_poi_file()


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

    def _ensure_poi_crs(self, pois: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if pois.crs is None:
            return pois.set_crs(self._data_crs)
        if pois.crs != self._data_crs:
            return pois.to_crs(self._data_crs)
        return pois

    def _category_filters(self, category_or_query: dict) -> dict:
        if "filters" in category_or_query:
            return category_or_query["filters"]

        return {
            column: category_or_query[column]
            for column in POI_FILTER_COLUMNS
            if column in category_or_query
        }

    def _category_queries(self, category: dict) -> list[dict]:
        return category.get("queries") or [category]

    def _query_limit(self, category_or_query: dict, default_limit: int) -> int:
        return max(0, int(category_or_query.get("limit", default_limit)))

    def _category_mask(self, pois: gpd.GeoDataFrame, filters: dict) -> pd.Series:
        mask = pd.Series(False, index=pois.index)
        for column in POI_FILTER_COLUMNS:
            values = filters.get(column)
            if values and column in pois.columns:
                mask = mask | pois[column].isin(values)
        return mask

    def _nearest_pois_for_query(
        self,
        pois: gpd.GeoDataFrame,
        origin: shapely.geometry.base.BaseGeometry,
        query: dict,
        default_limit: int,
    ) -> gpd.GeoDataFrame:
        limit = self._query_limit(query, default_limit)
        if limit < 1:
            return pois.iloc[0:0].copy()

        filters = self._category_filters(query)
        query_pois = pois.loc[self._category_mask(pois, filters)].copy()
        if query_pois.empty:
            return query_pois

        query_pois["kaugus_m"] = query_pois.distance(origin)
        query_pois.sort_values("kaugus_m", inplace=True)
        return query_pois.head(limit)

    def _nearest_pois_for_category(
        self,
        pois: gpd.GeoDataFrame,
        origin: shapely.geometry.base.BaseGeometry,
        category: dict,
        default_limit: int,
    ) -> list[dict]:
        rows = []
        seen_indexes = set()

        for query in self._category_queries(category):
            query_pois = self._nearest_pois_for_query(
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

        return [self._poi_row_to_dict(row) for row in rows]

    def _poi_row_to_dict(self, poi: pd.Series) -> dict:
        result = {}
        for column in POI_RESPONSE_COLUMNS:
            value = poi.get(column)
            if pd.isna(value):
                value = None
            elif column == "kaugus_m":
                value = float(value)
            result[column] = value

        result["geometry"] = self.convert_shape_to_front_end_crs_geojson(poi.geometry)
        return result

    def get_nearest_pois_by_group(
        self,
        point_or_geometry: shapely.geometry.base.BaseGeometry,
        pois: gpd.GeoDataFrame,
        top_n: int = DEFAULT_POI_LIMIT,
    ) -> dict:
        pois = self._ensure_poi_crs(pois)
        origin = shapely.centroid(point_or_geometry)
        nearby_pois = {}

        for category_id, category in POI_CATEGORIES.items():
            nearby_pois[category_id] = {
                "label": category["label"],
                "items": self._nearest_pois_for_category(
                    pois=pois,
                    origin=origin,
                    category=category,
                    default_limit=top_n,
                ),
            }

        return nearby_pois

class Parcel():
    def __init__(self, parcel: gpd.GeoSeries):
        self.parcel = parcel
        self.converter = GeometryConverter()

    @staticmethod
    def to_dict(parcel: pd.Series) -> dict:
        """Removes the geometry to make it iterable"""
        parcel_dict = parcel.to_dict()
        parcel_dict.pop("geometry")

        logger.info(parcel_dict)
        return parcel_dict

    def get_center_point_coords_geojson(self) -> dict:
        centre_point = shapely.centroid(self.parcel.geometry)
        return self.converter.convert_shape_to_front_end_crs_geojson(centre_point)

    def get_parcel_geometry_geojson(self) -> dict:
        return self.converter.convert_shape_to_front_end_crs_geojson(self.parcel.geometry)

    def get_nearby_pois(self, top_n: int = DEFAULT_POI_LIMIT) -> dict:
        return self.converter.get_nearest_pois_by_group(self.parcel.geometry, top_n=top_n, pois=poigd)


def get_parcel_cadastre_series_from_cadastre(cadastre_code: str) -> Parcel:
    """
    Given the exact address string returns the parcel address
    """
    matches = gd.loc[gd["tunnus"].eq(cadastre_code)]
    if matches.empty:
        logger.error("No matches found")
        return None
    elif len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    parcel = matches.iloc[0]
    return Parcel(parcel=parcel)

def get_parcel_cadastre_series_from_address(address: str) -> Parcel:
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
    return Parcel(parcel=parcel)

if __name__ == "__main__":
    cadastre = get_parcel_cadastre_series_from_address("P. Kerese tn 5a")
    if cadastre is None:
        logger.error("No cadastre")
    coords = cadastre.get_center_point_coords_geojson()
    centre_point = cadastre.get_parcel_geometry_geojson()
    logger.info(coords)
    logger.info(centre_point)
