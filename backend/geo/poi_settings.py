"""Persisted POI category settings."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

from backend.core.config import config
from backend.core.logging import logger
from backend.geo.constants import DEFAULT_POI_LIMIT, MAX_POI_QUERY_LIMIT, POI_CATEGORIES


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, tuple):
        return [_json_safe(item) for item in value]
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _query_limit(query: dict | None) -> int:
    query = query or {}
    limit = int(query.get("limit", DEFAULT_POI_LIMIT))
    if limit < 0 or limit > MAX_POI_QUERY_LIMIT:
        raise ValueError(f"POI arv peab olema vahemikus 0-{MAX_POI_QUERY_LIMIT}")
    return limit


def _normalize_query(default_query: dict, saved_query: dict | None = None) -> dict:
    normalized = {
        "label": str(default_query.get("label") or "Huvipunktid"),
        "limit": _query_limit(saved_query or default_query),
        "filters": _json_safe(default_query.get("filters", {})),
    }
    if not normalized["filters"]:
        raise ValueError("POI query must include at least one filter")
    return normalized


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "jah"}
    return bool(value)


def _default_query_from_category(category: dict) -> dict:
    return {
        "label": category.get("label", "Huvipunktid"),
        "filters": category.get("filters", {}),
        "limit": category.get("limit", DEFAULT_POI_LIMIT),
    }


def _default_queries(category: dict) -> list[dict]:
    queries = category.get("queries")
    if isinstance(queries, list):
        return queries
    return [_default_query_from_category(category)]


def _saved_query_for(
    default_query: dict, saved_queries: list, index: int
) -> dict | None:
    default_label = default_query.get("label")
    for query in saved_queries:
        if isinstance(query, dict) and query.get("label") == default_label:
            return query
    if index < len(saved_queries) and isinstance(saved_queries[index], dict):
        return saved_queries[index]
    return None


def normalize_poi_categories(categories: dict) -> dict:
    if not isinstance(categories, dict):
        raise ValueError("POI settings must be an object")

    normalized = {}
    for category_id, default_category in POI_CATEGORIES.items():
        category = categories.get(category_id, {})
        if not isinstance(category, dict):
            raise ValueError(f"POI category {category_id} must be an object")

        label = default_category.get("label") or category_id
        saved_queries = category.get("queries")
        if not isinstance(saved_queries, list):
            saved_queries = []
        default_queries = _default_queries(default_category)
        queries = []
        for index, default_query in enumerate(default_queries):
            saved_query = _saved_query_for(default_query, saved_queries, index)
            queries.append(_normalize_query(default_query, saved_query))

        user_disabled = _as_bool(category.get("user-disabled", False)) or all(
            query["limit"] == 0 for query in queries
        )
        normalized[category_id] = {
            "label": str(label),
            "user-disabled": user_disabled,
            "queries": queries,
        }

    return normalized


def constant_poi_categories() -> dict:
    return normalize_poi_categories(copy.deepcopy(POI_CATEGORIES))


def load_default_poi_categories(settings_path: Path | None = None) -> dict:
    path = settings_path or config.poi_settings_default_file
    if not path.exists():
        return constant_poi_categories()

    try:
        return normalize_poi_categories(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Failed to load default POI settings path={path}: {exc}")
        return constant_poi_categories()


def default_poi_categories() -> dict:
    return load_default_poi_categories()


def load_poi_categories(settings_path: Path | None = None) -> dict:
    path = settings_path or config.poi_settings_file
    if not path.exists():
        return default_poi_categories()

    try:
        return normalize_poi_categories(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.warning(f"Failed to load POI settings path={path}: {exc}")
        return default_poi_categories()


def save_poi_categories(categories: dict, settings_path: Path | None = None) -> dict:
    normalized = normalize_poi_categories(categories)
    path = settings_path or config.poi_settings_file
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(_json_safe(normalized), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return normalized


def poi_settings_response() -> dict:
    return {
        "poi_categories": load_poi_categories(),
        "default_poi_categories": load_default_poi_categories(),
        "saved": config.poi_settings_file.exists(),
        "max_query_limit": MAX_POI_QUERY_LIMIT,
    }
