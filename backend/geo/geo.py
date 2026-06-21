from pathlib import Path
import geopandas as gpd
import pandas as pd
import shapely
from functools import lru_cache
from backend.core.logging import logger
from backend.core.config import config
from backend.core.utils import time_function

DEFAULT_POI_LIMIT = 3
DEFAULT_NOISE_BUFFER_M = 20
NO_DATA_DB_UPPER_BOUND = 40.0
COVERAGE_TOLERANCE_PCT = 0.01
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

HERITAGE_POI_RESPONSE_COLUMNS = [
    "id",
    "vid",
    "nimetus",
    "klass",
    "kpo_liik_kood_vaartus",
    "alagrupp_vaartus",
    "nahtus_id_vaartus",
]

RESTRICTION_AREA_RESPONSE_COLUMNS = [
    "nimi",
    "klass",
    "nahtus_id_vaartus",
    "voond_liik_id_vaartus",
    "reegel",
    "maksusoodustus",
    "kitsenduse_objekti_vid",
    "kpois_viide",
    "layer",
]

DETAIL_PLAN_RESPONSE_COLUMNS = [
    "sysid",
    "planid",
    "kovid",
    "plannim",
    "korraldaja",
    "planseis_nimi",
    "planeesm",
    "planviide",
    "algatkp_timeposition",
    "vastuvkp_timeposition",
    "kehtestkp_timeposition",
    "url",
    "failid",
]


@lru_cache(maxsize=1)
def load_gpkg_file(filename: Path | str) -> gpd.GeoDataFrame:
    try:
        gdf = gpd.read_file(filename=filename)
    except Exception as e:
        logger.error(e)
    return gdf


cadastregdf = load_gpkg_file(config.cadastre_file)
poigdf = load_gpkg_file(config.poi_file)
noisegdf = load_gpkg_file(config.noise_file)
heritage_poisgdf = load_gpkg_file(config.heritage_poi_file)
restriction_areasgdf = load_gpkg_file(config.restriction_areas_file)
detail_plansgdf = load_gpkg_file(config.detail_plans_file)


class GeometryConverter:
    def __init__(self):
        self._front_end_crs = config.frontend_crs
        self._data_crs = config.data_crs

    def convert_shape_to_front_end_crs_geojson(self, shape: shapely.Polygon) -> dict:
        converted_geometry = gpd.GeoSeries([shape], crs=self._data_crs).to_crs(
            self._front_end_crs
        )
        return shapely.geometry.mapping(converted_geometry.iloc[0])

    def _ensure_gpd_crs(self, gpd: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if gpd.crs is None:
            return gpd.set_crs(self._data_crs)
        if gpd.crs != self._data_crs:
            return gpd.to_crs(self._data_crs)
        return gpd

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
            value = self._response_value(poi.get(column))
            if column == "kaugus_m" and value is not None:
                value = float(value)
            result[column] = value

        result["geometry"] = self.convert_shape_to_front_end_crs_geojson(poi.geometry)
        return result

    def _response_value(self, value):
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

    def _spatial_intersections(
        self,
        geometry: shapely.geometry.base.BaseGeometry,
        source_gdf: gpd.GeoDataFrame,
    ) -> gpd.GeoDataFrame:
        source_gdf = self._ensure_gpd_crs(source_gdf)
        if source_gdf.empty:
            return source_gdf.copy()

        idx = source_gdf.sindex.query(geometry, predicate="intersects")
        candidates = source_gdf.iloc[idx].copy()
        if candidates.empty:
            return candidates

        return candidates.loc[candidates.geometry.intersects(geometry)].copy()

    def _row_to_spatial_dict(
        self,
        row: pd.Series,
        columns: list[str],
    ) -> dict:
        result = {
            column: self._response_value(row.get(column))
            for column in columns
        }
        result["geometry"] = self.convert_shape_to_front_end_crs_geojson(row.geometry)
        return result

    def _polygon_overlap_row_to_dict(
        self,
        row: pd.Series,
        parcel_geometry: shapely.geometry.base.BaseGeometry,
        columns: list[str],
    ) -> dict:
        result = self._row_to_spatial_dict(row, columns)
        intersection_area_m2 = float(row.geometry.intersection(parcel_geometry).area)
        parcel_area_m2 = float(parcel_geometry.area)
        result["intersection_area_m2"] = intersection_area_m2
        result["parcel_coverage_pct"] = (
            100 * intersection_area_m2 / parcel_area_m2
            if parcel_area_m2
            else 0.0
        )
        return result

    def get_overlapping_heritage_pois(
        self,
        parcel_geometry: shapely.geometry.base.BaseGeometry,
        heritage_pois: gpd.GeoDataFrame,
    ) -> dict:
        matches = self._spatial_intersections(parcel_geometry, heritage_pois)
        items = [
            self._row_to_spatial_dict(row, HERITAGE_POI_RESPONSE_COLUMNS)
            for _, row in matches.iterrows()
        ]
        return items

    def get_overlapping_restriction_areas(
        self,
        parcel_geometry: shapely.geometry.base.BaseGeometry,
        restriction_areas: gpd.GeoDataFrame,
    ) -> dict:
        matches = self._spatial_intersections(parcel_geometry, restriction_areas)
        items = [
            self._polygon_overlap_row_to_dict(
                row,
                parcel_geometry,
                RESTRICTION_AREA_RESPONSE_COLUMNS,
            )
            for _, row in matches.iterrows()
        ]
        items.sort(key=lambda item: item["intersection_area_m2"], reverse=True)
        return items

    def get_overlapping_detail_plans(
        self,
        parcel_geometry: shapely.geometry.base.BaseGeometry,
        detail_plans: gpd.GeoDataFrame,
    ) -> dict:
        matches = self._spatial_intersections(parcel_geometry, detail_plans)
        items = [
            self._polygon_overlap_row_to_dict(
                row,
                parcel_geometry,
                DETAIL_PLAN_RESPONSE_COLUMNS,
            )
            for _, row in matches.iterrows()
        ]
        items.sort(key=lambda item: item["intersection_area_m2"], reverse=True)
        return items

    def get_nearest_pois_by_group(
        self,
        point_or_geometry: shapely.geometry.base.BaseGeometry,
        pois: gpd.GeoDataFrame,
        top_n: int = DEFAULT_POI_LIMIT,
    ) -> dict:
        pois = self._ensure_gpd_crs(pois)
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

    def _clip_noise_areas(
        self,
        noise_areas: gpd.GeoDataFrame,
        geometry: shapely.geometry.base.BaseGeometry,
    ) -> gpd.GeoDataFrame:
        clipped = noise_areas.copy()
        clipped["geometry"] = clipped.geometry.intersection(geometry)
        clipped = clipped[~clipped.geometry.is_empty].copy()
        clipped["MYRAKLASS"] = clipped["MYRAKLASS"].astype(float)
        clipped["area"] = clipped.geometry.area
        clipped["area_pct"] = 100 * clipped["area"] / geometry.area
        return clipped

    def get_noise_areas(
        self,
        parceldf: gpd.GeoDataFrame,
        buffered_area_m: float,
    ) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
        """
        Gets intersection of noise areas with the parcel and buffered parcel area.
        """
        parceldf = self._ensure_gpd_crs(parceldf)
        noise_areas = self._ensure_gpd_crs(noisegdf)

        unbuffered = parceldf.geometry.iloc[0]
        buffered = unbuffered.buffer(buffered_area_m)
        idx = noise_areas.sindex.query(buffered, predicate="intersects")
        candidates = noise_areas.iloc[idx].copy()

        noise_areas_buffered = self._clip_noise_areas(candidates, buffered)
        noise_areas_unbuffered = self._clip_noise_areas(
            candidates.loc[candidates.geometry.intersects(unbuffered)],
            unbuffered,
        )

        return noise_areas_buffered, noise_areas_unbuffered

    def _average_noise_from_area(
        self,
        noise_areas: gpd.GeoDataFrame,
        geometry: shapely.geometry.base.BaseGeometry,
        no_data_db_upper_bound: float = NO_DATA_DB_UPPER_BOUND,
    ) -> dict:
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
                    (noise_areas.geometry.area / geometry_area)
                    * noise_areas["MYRAKLASS"]
                ).sum()
            )
        else:
            mapped_weighted_db = 0.0

        if mapped_pct >= 100 - COVERAGE_TOLERANCE_PCT:
            avg_db = mapped_weighted_db
            result_type = "exact"
            label = f"average = {avg_db:.1f} dB"
            avg_db_upper = None
        else:
            avg_db = None
            result_type = "upper_bound"
            avg_db_upper = (
                (
                    mapped_weighted_db
                    + (missing_area / geometry_area) * no_data_db_upper_bound
                )
                if geometry_area
                else 0.0
            )
            label = f"average < {avg_db_upper:.1f} dB"

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
        self,
        parceldf: gpd.GeoDataFrame,
        buffered_area_m: float = DEFAULT_NOISE_BUFFER_M,
    ) -> dict:
        parceldf = self._ensure_gpd_crs(parceldf)
        unbuffered = parceldf.geometry.iloc[0]
        buffered = unbuffered.buffer(buffered_area_m)
        noise_areas_buffered, noise_areas_unbuffered = self.get_noise_areas(
            parceldf,
            buffered_area_m,
        )

        return {
            "buffer_m": buffered_area_m,
            "buffered": self._average_noise_from_area(noise_areas_buffered, buffered),
            "unbuffered": self._average_noise_from_area(
                noise_areas_unbuffered, unbuffered
            ),
        }


class Parcel:
    def __init__(self, parcel_df: gpd.GeoDataFrame):
        self.parcel_df = parcel_df
        self.parcel = parcel_df.iloc[0]
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
        return self.converter.convert_shape_to_front_end_crs_geojson(
            self.parcel.geometry
        )

    @time_function
    def get_nearby_pois(self, top_n: int = DEFAULT_POI_LIMIT) -> dict:
        return self.converter.get_nearest_pois_by_group(
            self.parcel.geometry, top_n=top_n, pois=poigdf
        )

    @time_function
    def get_surrounding_noise_level(
        self,
        buffered_area_m: float = DEFAULT_NOISE_BUFFER_M,
    ) -> dict:
        return self.converter.get_surrounding_noise_level(
            self.parcel_df,
            buffered_area_m=buffered_area_m,
        )

    @time_function
    def get_heritage_pois(self) -> dict:
        return self.converter.get_overlapping_heritage_pois(
            self.parcel.geometry,
            heritage_poisgdf,
        )

    @time_function
    def get_restriction_areas(self) -> dict:
        return self.converter.get_overlapping_restriction_areas(
            self.parcel.geometry,
            restriction_areasgdf,
        )

    @time_function
    def get_detail_plans(self) -> dict:
        return self.converter.get_overlapping_detail_plans(
            self.parcel.geometry,
            detail_plansgdf,
        )


def get_parcel_cadastre_series_from_cadastre(cadastre_code: str) -> Parcel:
    """
    Given the exact address string returns the parcel address
    """
    matches = cadastregdf.loc[cadastregdf["tunnus"].eq(cadastre_code)]
    if matches.empty:
        logger.error("No matches found")
        return None
    elif len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    return Parcel(parcel_df=matches)


def get_parcel_cadastre_series_from_address(address: str) -> Parcel:
    """
    Given the exact address string returns the parcel address
    """
    matches = cadastregdf.loc[cadastregdf["l_aadress"].eq(address)]
    if matches.empty:
        logger.error("No matches found")
        return None
    elif len(matches) > 1:
        logger.warning("Found more than 1 match")
        return None
    return Parcel(parcel_df=matches)


if __name__ == "__main__":
    cadastre = get_parcel_cadastre_series_from_address("P. Kerese tn 5a")
    if cadastre is None:
        logger.error("No cadastre")
    coords = cadastre.get_center_point_coords_geojson()
    centre_point = cadastre.get_parcel_geometry_geojson()
    logger.info(coords)
    logger.info(centre_point)
