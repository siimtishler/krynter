"""Shared constants and response field definitions for geo services."""

DEFAULT_POI_LIMIT = 3
MAX_POI_QUERY_LIMIT = 5
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
            {"label": "Sport", "filters": {"grupp": {"sport"}}},
            {"label": "Terviserada", "filters": {"grupp": {"terviserada"}}},
            {"label": "Supluskoht", "filters": {"grupp": {"supluskoht"}}},
        ],
    },
    "poed_ja_ostud": {
        "label": "Poed ja ostud",
        "queries": [
            {"label": "Kaubanduskeskus", "filters": {"alamgrupp": {"kaubanduskeskus"}}}
        ],
    },
    "haridus_ja_lapsed": {
        "label": "Haridus ja lapsed",
        "queries": [
            {
                "label": "Põhikool ja gümnaasium",
                "filters": {"alamgrupp": {"põhikool või gümnaasium"}},
            },
            {
                "label": "Lastehoid",
                "filters": {"alamgrupp": {"koolieelne lasteasutus", "lasteaed"}},
            },
            {"label": "Huvikool", "filters": {"alamgrupp": {"huvikool"}}},
            {"label": "Lapsehoid", "filters": {"alamgrupp": {"lapsehoiuteenus"}}},
        ],
    },
    "tervis": {
        "label": "Tervis",
        "queries": [
            {"label": "Perearst", "filters": {"grupp": {"perearst"}}},
            {"label": "Haigla", "filters": {"grupp": {"haigla"}}},
            {"label": "Apteek", "filters": {"grupp": {"tervisekaubad"}}},
        ],
    },
    "transport": {
        "label": "Transport",
        "queries": [
            {"label": "Bussipeatus", "filters": {"alamgrupp": {"bussipeatus"}}},
            {"label": "Rongipeatus", "filters": {"alamgrupp": {"rongipeatus"}}},
            {"label": "Trammipeatus", "filters": {"alamgrupp": {"trammipeatus"}}},
            {"label": "Parkla", "filters": {"alamgrupp": {"parkla", "avalik parkla"}}},
        ],
    },
    "igapaevateenused": {
        "label": "Igapäevateenused",
        "queries": [
            {"label": "Post", "filters": {"grupp": {"post"}}},
            {"label": "Pank ja ATM", "filters": {"grupp": {"pank"}}},
            {"label": "Tankla", "filters": {"grupp": {"tankla"}}},
            {"label": "Laadimispunkt", "filters": {"grupp": {"laadimispunkt"}}},
        ],
    },
    "sook_ja_kohvikud": {
        "label": "Söök ja kohvikud",
        "queries": [
            {"label": "Turg", "filters": {"alamgrupp": {"taluturg ja väiketootja"}}},
            {"label": "Restoran", "filters": {"alamgrupp": {"restoran"}}},
            {"label": "Kohvik", "filters": {"alamgrupp": {"kohvik"}}},
            {"label": "Tänavatoit", "filters": {"alamgrupp": {"tänavatoit"}}},
            {"label": "Baar/pubi", "filters": {"alamgrupp": {"baar ja pubi"}}},
            {
                "label": "Elamustoitlustus",
                "filters": {"alamgrupp": {"elamustoitlustus"}},
            },
        ],
        "filters": {"grupp": {"toitlustus"}},
    },
    "kultuur_ja_vaba_aeg": {
        "label": "Kultuur ja vaba aeg",
        "queries": [
            {"label": "Kino", "filters": {"alamgrupp": {"kino"}}},
            {"label": "Teater", "filters": {"alamgrupp": {"teater"}}},
            {"label": "Muuseum", "filters": {"alamgrupp": {"muuseum"}}},
            {"label": "Kirik", "filters": {"alamgrupp": {"religioon"}}},
            {"label": "Noortekeskus", "filters": {"alamgrupp": {"noortekeskus"}}},
            {"label": "Kontserdimaja", "filters": {"alamgrupp": {"kontserdimaja"}}},
            {
                "label": "Kultuuri- ja rahvamaja",
                "filters": {"alamgrupp": {"kultuuri- ja rahvamaja"}},
            },
            {
                "label": "Kultuuri- ja huvikeskus",
                "filters": {"alamgrupp": {"kultuuri- ja huvikeskus"}},
            },
        ],
    },
    "majutus": {
        "label": "Majutus",
        "queries": [
            {"label": "Majutus", "filters": {"alamgrupp": {"majutus"}}},
            {"label": "Ühiselamu", "filters": {"alamgrupp": {"ühiselamu"}}},
        ],
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
    "www",
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
