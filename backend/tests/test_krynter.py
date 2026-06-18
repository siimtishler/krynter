import geopandas as gpd
from fastapi.testclient import TestClient
from shapely.geometry import Point, box

from backend.api import api
from backend.geo.geo import GeometryConverter, Parcel
from backend.main import app


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
    result = GeometryConverter().get_nearest_pois_by_group(
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
    result = GeometryConverter().get_nearest_pois_by_group(
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

    result = GeometryConverter().get_nearest_pois_by_group(
        Point(0, 0),
        top_n=3,
        pois=pois,
    )

    items = result["igapaevateenused"]["items"]
    assert [item["nimi"] for item in items] == ["ATM 1", "Postkontor", "Tankla"]


def test_noise_average_returns_upper_bound_for_missing_area():
    converter = GeometryConverter()
    parcel = box(0, 0, 10, 10)
    noise_areas = gpd.GeoDataFrame(
        [{"MYRAKLASS": 60, "geometry": box(0, 0, 5, 10)}],
        crs="EPSG:3301",
    )

    result = converter._average_noise_from_area(noise_areas, parcel)

    assert result["result_type"] == "upper_bound"
    assert result["avg_db"] is None
    assert result["avg_db_upper"] == 50.0
    assert result["mapped_pct"] == 50.0
    assert result["missing_pct"] == 50.0


def test_noise_average_returns_less_than_40_for_no_noise_areas():
    converter = GeometryConverter()
    parcel = box(0, 0, 10, 10)
    noise_areas = gpd.GeoDataFrame(
        {"MYRAKLASS": [], "geometry": []},
        crs="EPSG:3301",
    )

    result = converter._average_noise_from_area(noise_areas, parcel)

    assert result["label"] == "average < 40.0 dB"
    assert result["mapped_pct"] == 0.0
    assert result["missing_pct"] == 100.0


def test_search_cadastre_includes_nearby_pois(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_parcel_cadastre_series_from_cadastre",
        lambda cadastre_code: make_parcel(),
    )
    monkeypatch.setattr(
        Parcel,
        "get_nearby_pois",
        lambda self, top_n=3: {"sport_ja_liikumine": {"label": "Sport", "items": []}},
    )

    client = TestClient(app)
    response = client.get("/api/search_cadastre", params={"cadastre_code": "123"})

    assert response.status_code == 200
    assert "nearby_pois" in response.json()


def test_nearby_pois_endpoint_returns_grouped_pois(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_parcel_cadastre_series_from_cadastre",
        lambda cadastre_code: make_parcel(),
    )
    monkeypatch.setattr(
        Parcel,
        "get_nearby_pois",
        lambda self, top_n=3: {"sport_ja_liikumine": {"label": "Sport", "items": []}},
    )

    client = TestClient(app)
    response = client.get("/api/nearby_pois", params={"cadastre_code": "123"})

    assert response.status_code == 200
    assert response.json()["nearby_pois"] == {
        "sport_ja_liikumine": {"label": "Sport", "items": []}
    }


def test_nearby_pois_endpoint_returns_404_for_missing_cadastre(monkeypatch):
    monkeypatch.setattr(
        api,
        "get_parcel_cadastre_series_from_cadastre",
        lambda cadastre_code: None,
    )

    client = TestClient(app)
    response = client.get("/api/nearby_pois", params={"cadastre_code": "missing"})

    assert response.status_code == 404
