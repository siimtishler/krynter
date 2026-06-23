"""Shared constants and response field definitions for geo services."""

DEFAULT_POI_LIMIT = 3
DEFAULT_NOISE_BUFFER_M = 20
DETAIL_PLAN_MIN_COVERAGE_PCT = 10.0
NO_DATA_DB_UPPER_BOUND = 40.0
COVERAGE_TOLERANCE_PCT = 0.01
POI_FILTER_COLUMNS = ("grupp", "alamgrupp", "poi_type")

# Use filters for one nearest list, or queries when each subtype needs its own limit.
POI_CATEGORIES = {
    "sport_ja_liikumine": {
        "label": "Sport ja liikumine",
        "queries": [
            {"label": "Sport", "limit": 3, "filters": {"grupp": {"sport"}}},
            {
                "label": "Terviserajad",
                "limit": 2,
                "filters": {"grupp": {"terviserada"}},
            },
            {"label": "Supluskohad", "limit": 2, "filters": {"grupp": {"supluskoht"}}},
        ],
    },
    "poed_ja_ostud": {
        "label": "Poed ja ostud",
        "filters": {"alamgrupp": {"kaubanduskeskus"}},
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
            {"label": "Huvikoolid", "limit": 2, "filters": {"alamgrupp": {"huvikool"}}},
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
            {"label": "Perearst", "limit": 1, "filters": {"grupp": {"perearst"}}},
            {"label": "Haiglad", "limit": 1, "filters": {"grupp": {"haigla"}}},
            {"label": "Apteegid", "limit": 1, "filters": {"grupp": {"tervisekaubad"}}},
        ],
    },
    "transport": {
        "label": "Transport",
        "queries": [
            {"label": "Peatused", "limit": 3, "filters": {"grupp": {"peatus"}}},
            {"label": "Parklad", "limit": 1, "filters": {"grupp": {"parkla"}}},
        ],
    },
    "igapaevateenused": {
        "label": "Igapäevateenused",
        "queries": [
            {"label": "Post", "limit": 1, "filters": {"grupp": {"post"}}},
            {"label": "Pank ja ATM", "limit": 1, "filters": {"grupp": {"pank"}}},
            {"label": "Tankla", "limit": 1, "filters": {"grupp": {"tankla"}}},
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
            {"label": "Kinod", "limit": 1, "filters": {"alamgrupp": {"kino"}}},
            {"label": "Teatrid", "limit": 1, "filters": {"alamgrupp": {"teater"}}},
            {"label": "Muuseumid", "limit": 1, "filters": {"alamgrupp": {"muuseum"}}},
            {"label": "Kirikud", "limit": 1, "filters": {"alamgrupp": {"religioon"}}},
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
