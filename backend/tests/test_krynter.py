import importlib

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from fastapi import HTTPException
from shapely.geometry import Point, box

from backend.api import api
from backend.geo import Parcel
from backend.geo.crs import shape_to_frontend_geojson
from backend.geo.noise import average_noise_from_area
from backend.geo.overlays import (
    get_overlapping_detail_plans,
    get_overlapping_heritage_pois,
    get_overlapping_restriction_areas,
)
from backend.geo.pois import get_nearest_pois_by_group
from backend.geo.serializers import response_value
from backend.geo.spatial import spatial_intersections


def make_poi_gdf() -> gpd.GeoDataFrame:
    rows = [
        {
            "nimi": "Spordihall",
            "aadress": "Sport 1",
            "grupp": "sport",
            "alamgrupp": "võimla, spordihall, spordisaal",
            "ylemgrupp": "Vaba aeg",
            "poi_type": "Spordihoone — ms:poi_spordihoone",
            "geometry": Point(10, 0),
        },
        {
            "nimi": "Terviserada",
            "aadress": "Rada 1",
            "grupp": "terviserada",
            "alamgrupp": "eesti terviserada",
            "ylemgrupp": "Vaba aeg",
            "poi_type": "Terviserada — ms:poi_eestiterviserada_j",
            "geometry": Point(20, 0),
        },
        {
            "nimi": "Supluskoht",
            "aadress": "Rand 1",
            "grupp": "supluskoht",
            "alamgrupp": "ametlik supluskoht",
            "ylemgrupp": "Vaba aeg",
            "poi_type": "Supluskoht — ms:poi_supluskoht",
            "geometry": Point(30, 0),
        },
        {
            "nimi": "Ostukeskus",
            "aadress": "Pood 1",
            "grupp": "kaubandus",
            "alamgrupp": "kaubanduskeskus",
            "ylemgrupp": "Teenused",
            "poi_type": "Ärihoone — ms:poi_arihoone",
            "geometry": Point(40, 0),
        },
        {
            "nimi": "Lasteaed",
            "aadress": "Laps 1",
            "grupp": "haridus",
            "alamgrupp": "koolieelne lasteasutus",
            "ylemgrupp": "Haridus",
            "poi_type": "Haridusasutus — ms:poi_haridusasutus",
            "geometry": Point(50, 0),
        },
        {
            "nimi": "Kool",
            "aadress": "Kool 1",
            "grupp": "haridus",
            "alamgrupp": "põhikool või gümnaasium",
            "ylemgrupp": "Haridus",
            "poi_type": "Haridusasutus — ms:poi_haridusasutus",
            "geometry": Point(60, 0),
        },
    ]
    return gpd.GeoDataFrame(rows, crs="EPSG:3301")


def make_parcel() -> Parcel:
    parcel_gdf = gpd.GeoDataFrame(
        [{"tunnus": "123", "l_aadress": "Test", "geometry": Point(0, 0)}],
        crs="EPSG:3301",
    )
    return Parcel(parcel_gdf)


def test_nearest_pois_groups_include_expected_categories():
    result = get_nearest_pois_by_group(
        Point(0, 0),
        top_n=3,
        pois=make_poi_gdf(),
    )

    assert [item["nimi"] for item in result["sport_ja_liikumine"]["items"]] == [
        "Spordihall",
        "Terviserada",
        "Supluskoht",
    ]
    assert result["poed_ja_ostud"]["items"][0]["nimi"] == "Ostukeskus"
    assert [item["nimi"] for item in result["haridus_ja_lapsed"]["items"]] == [
        "Lasteaed",
        "Kool",
    ]


def test_nearest_pois_are_sorted_limited_and_empty_groups_are_returned():
    result = get_nearest_pois_by_group(
        Point(0, 0),
        top_n=2,
        pois=make_poi_gdf(),
    )

    sport_items = result["sport_ja_liikumine"]["items"]
    assert [item["nimi"] for item in sport_items] == ["Spordihall", "Terviserada"]
    assert [item["kaugus_m"] for item in sport_items] == [10.0, 20.0]
    assert result["tervis"]["items"] == []


def test_daily_services_returns_configured_service_types_not_only_closest_group():
    rows = [
        {
            "nimi": "ATM 1",
            "aadress": "Pank 1",
            "grupp": "pank",
            "alamgrupp": "sularahaautomaat",
            "ylemgrupp": "Teenused",
            "poi_type": "Pank — ms:poi_pank",
            "geometry": Point(10, 0),
        },
        {
            "nimi": "ATM 2",
            "aadress": "Pank 2",
            "grupp": "pank",
            "alamgrupp": "sularahaautomaat",
            "ylemgrupp": "Teenused",
            "poi_type": "Pank — ms:poi_pank",
            "geometry": Point(11, 0),
        },
        {
            "nimi": "ATM 3",
            "aadress": "Pank 3",
            "grupp": "pank",
            "alamgrupp": "sularahaautomaat",
            "ylemgrupp": "Teenused",
            "poi_type": "Pank — ms:poi_pank",
            "geometry": Point(12, 0),
        },
        {
            "nimi": "Postkontor",
            "aadress": "Post 1",
            "grupp": "post",
            "alamgrupp": "postkontor",
            "ylemgrupp": "Teenused",
            "poi_type": "Post — ms:poi_post",
            "geometry": Point(40, 0),
        },
        {
            "nimi": "Tankla",
            "aadress": "Tankla 1",
            "grupp": "tankla",
            "alamgrupp": "tankla",
            "ylemgrupp": "Teenused",
            "poi_type": "Tankla — ms:poi_tankla",
            "geometry": Point(50, 0),
        },
    ]
    pois = gpd.GeoDataFrame(rows, crs="EPSG:3301")

    result = get_nearest_pois_by_group(
        Point(0, 0),
        top_n=3,
        pois=pois,
    )

    items = result["igapaevateenused"]["items"]
    assert [item["nimi"] for item in items] == ["ATM 1", "Postkontor", "Tankla"]


def test_noise_average_returns_upper_bound_for_missing_area():
    parcel = box(0, 0, 10, 10)
    noise_areas = gpd.GeoDataFrame(
        [{"MYRAKLASS": 60, "geometry": box(0, 0, 5, 10)}],
        crs="EPSG:3301",
    )

    result = average_noise_from_area(noise_areas, parcel)

    assert result["result_type"] == "upper_bound"
    assert result["avg_db"] is None
    assert result["avg_db_upper"] == 50.0
    assert result["mapped_pct"] == 50.0
    assert result["missing_pct"] == 50.0


def test_noise_average_returns_less_than_40_for_no_noise_areas():
    parcel = box(0, 0, 10, 10)
    noise_areas = gpd.GeoDataFrame(
        {"MYRAKLASS": [], "geometry": []},
        crs="EPSG:3301",
    )

    result = average_noise_from_area(noise_areas, parcel)

    assert result["label"] == "average < 40.0 dB"
    assert result["mapped_pct"] == 0.0
    assert result["missing_pct"] == 100.0


def test_heritage_point_inside_parcel_is_returned():
    parcel = box(0, 0, 10, 10)
    heritage_pois = gpd.GeoDataFrame(
        [
            {
                "id": "inside",
                "vid": "1",
                "nimetus": "Inside object",
                "klass": "KULTM",
                "kpo_liik_kood_vaartus": "EHITISMALESTIS",
                "alagrupp_vaartus": "Muinsuskaitse",
                "nahtus_id_vaartus": "Kinnismälestis",
                "geometry": Point(5, 5),
            },
            {
                "id": "outside",
                "vid": "2",
                "nimetus": "Outside object",
                "klass": "KULTM",
                "kpo_liik_kood_vaartus": "EHITISMALESTIS",
                "alagrupp_vaartus": "Muinsuskaitse",
                "nahtus_id_vaartus": "Kinnismälestis",
                "geometry": Point(20, 20),
            },
        ],
        crs="EPSG:3301",
    )

    result = get_overlapping_heritage_pois(parcel, heritage_pois)

    assert result["count"] == 1
    assert result["items"][0]["id"] == "inside"
    assert result["items"][0]["geometry"]["type"] == "Point"


def test_restriction_area_intersection_includes_metrics():
    parcel = box(0, 0, 10, 10)
    restriction_areas = gpd.GeoDataFrame(
        [
            {
                "nimi": "Half overlap",
                "klass": "KOBP",
                "nahtus_id_vaartus": "Nature",
                "voond_liik_id_vaartus": "Restriction",
                "reegel": "Rule",
                "maksusoodustus": "50",
                "kitsenduse_objekti_vid": "KLO1",
                "kpois_viide": "https://example.test/restriction",
                "layer": "restriction",
                "geometry": box(0, 0, 5, 10),
            },
            {
                "nimi": "Outside",
                "klass": "KOBP",
                "nahtus_id_vaartus": "Nature",
                "voond_liik_id_vaartus": "Restriction",
                "reegel": "Rule",
                "maksusoodustus": "50",
                "kitsenduse_objekti_vid": "KLO2",
                "kpois_viide": "https://example.test/outside",
                "layer": "restriction",
                "geometry": box(20, 20, 30, 30),
            },
        ],
        crs="EPSG:3301",
    )

    result = get_overlapping_restriction_areas(parcel, restriction_areas)

    assert result["count"] == 1
    assert result["items"][0]["nimi"] == "Half overlap"
    assert result["items"][0]["intersection_area_m2"] == 50.0
    assert result["items"][0]["parcel_coverage_pct"] == 50.0
    assert result["items"][0]["geometry"]["type"] == "Polygon"


def test_detail_plan_intersection_returns_expected_fields():
    parcel = box(0, 0, 10, 10)
    detail_plans = gpd.GeoDataFrame(
        [
            {
                "sysid": 1,
                "planid": 2,
                "kovid": "DP001",
                "plannim": "Test detail plan",
                "korraldaja": "Tallinn",
                "planseis_nimi": "kehtiv",
                "planeesm": "Purpose",
                "planviide": "https://example.test/plan",
                "algatkp_timeposition": "2020-01-01",
                "vastuvkp_timeposition": "2020-02-01",
                "kehtestkp_timeposition": "2020-03-01",
                "url": "https://example.test/detail",
                "failid": "https://example.test/files",
                "geometry": box(5, 0, 15, 10),
            }
        ],
        crs="EPSG:3301",
    )

    result = get_overlapping_detail_plans(parcel, detail_plans)

    assert result["count"] == 1
    assert result["items"][0]["plannim"] == "Test detail plan"
    assert result["items"][0]["intersection_area_m2"] == 50.0
    assert result["items"][0]["parcel_coverage_pct"] == 50.0


def test_empty_spatial_matches_return_empty_items():
    parcel = box(0, 0, 10, 10)
    empty_heritage = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:3301")
    empty_restrictions = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:3301")
    empty_detail_plans = gpd.GeoDataFrame({"geometry": []}, crs="EPSG:3301")

    assert get_overlapping_heritage_pois(parcel, empty_heritage) == {
        "count": 0,
        "items": [],
    }
    assert get_overlapping_restriction_areas(parcel, empty_restrictions) == {
        "count": 0,
        "items": [],
    }
    assert get_overlapping_detail_plans(parcel, empty_detail_plans) == {
        "count": 0,
        "items": [],
    }


def test_response_value_normalizes_missing_and_scalar_values():
    assert response_value(None) is None
    assert response_value(np.nan) is None
    assert response_value(pd.Timestamp("2024-01-02")) == "2024-01-02T00:00:00"
    assert response_value(np.int64(7)) == 7
    assert response_value(np.float64(1.5)) == 1.5


def test_shape_to_frontend_geojson_returns_mapping():
    result = shape_to_frontend_geojson(Point(0, 0))

    assert result["type"] == "Point"
    assert len(result["coordinates"]) == 2


def test_spatial_intersections_filters_non_overlapping_candidates():
    source = gpd.GeoDataFrame(
        [
            {"name": "inside", "geometry": box(0, 0, 5, 5)},
            {"name": "outside", "geometry": box(20, 20, 30, 30)},
        ],
        crs="EPSG:3301",
    )

    result = spatial_intersections(box(1, 1, 2, 2), source)

    assert result["name"].to_list() == ["inside"]


def test_search_cadastre_includes_nearby_pois(monkeypatch):
    monkeypatch.setattr(
        api,
        "find_parcel_by_cadastre_code",
        lambda cadastre_code: make_parcel(),
    )
    monkeypatch.setattr(
        Parcel,
        "get_nearby_pois",
        lambda self, top_n=3: {"sport_ja_liikumine": {"label": "Sport", "items": []}},
    )
    monkeypatch.setattr(
        Parcel,
        "get_surrounding_noise_level",
        lambda self, buffered_area_m=20: {"buffer_m": buffered_area_m},
    )
    monkeypatch.setattr(
        Parcel,
        "get_spatial_context",
        lambda self: {
            "heritage_pois": {"count": 0, "items": []},
            "restriction_areas": {"count": 0, "items": []},
            "detail_plans": {"count": 0, "items": []},
        },
    )

    body = api.return_parcel_info_from_searchable(
        type="cadastre_code",
        searchable="123",
    )

    assert "nearby_pois" in body
    assert body["heritage_pois"] == {"count": 0, "items": []}
    assert body["restriction_areas"] == {"count": 0, "items": []}
    assert body["detail_plans"] == {"count": 0, "items": []}


def test_nearby_pois_endpoint_returns_grouped_pois(monkeypatch):
    monkeypatch.setattr(
        api,
        "find_parcel_by_cadastre_code",
        lambda cadastre_code: make_parcel(),
    )
    monkeypatch.setattr(
        Parcel,
        "get_nearby_pois",
        lambda self, top_n=3: {"sport_ja_liikumine": {"label": "Sport", "items": []}},
    )

    response = api.return_nearby_pois_from_cadastre(cadastre_code="123")

    assert response["nearby_pois"] == {
        "sport_ja_liikumine": {"label": "Sport", "items": []}
    }


def test_nearby_pois_endpoint_returns_404_for_missing_cadastre(monkeypatch):
    monkeypatch.setattr(
        api,
        "find_parcel_by_cadastre_code",
        lambda cadastre_code: None,
    )

    with pytest.raises(HTTPException) as exc_info:
        api.return_nearby_pois_from_cadastre(cadastre_code="missing")

    assert exc_info.value.status_code == 404


def test_geo_module_imports_do_not_load_geopackages(monkeypatch):
    read_calls = []

    def track_read_file(*args, **kwargs):
        read_calls.append((args, kwargs))
        raise AssertionError("GeoPackage loading should be lazy")

    monkeypatch.setattr(gpd, "read_file", track_read_file)

    import backend.geo as geo_module
    import backend.geo.datasets as datasets_module
    import backend.geo.noise as noise_module
    import backend.geo.overlays as overlays_module
    import backend.geo.parcel as parcel_module
    import backend.geo.pois as pois_module
    import backend.geo.serializers as serializers_module
    import backend.geo.spatial as spatial_module

    for module in (
        datasets_module,
        serializers_module,
        spatial_module,
        pois_module,
        noise_module,
        overlays_module,
        parcel_module,
        geo_module,
    ):
        importlib.reload(module)

    assert read_calls == []
