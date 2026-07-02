from pydantic_settings import BaseSettings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"


class Config(BaseSettings):
    app_name: str = "Krynter"
    frontend_crs: str = "EPSG:4326"
    data_crs: str = "EPSG:3301"
    app_debug: bool = True
    detail_plan_llm_resolver_enabled: bool = True
    ollama_base_url: str = "http://localhost:11434"
    ollama_building_right_model: str = "gemma3:4b"
    ollama_timeout_s: float = 600
    cadastre_vector_file: Path = DATA_DIR / "cadastre_vector_tiles"
    poi_file: Path = DATA_DIR / "points_of_interest.gpkg"
    cadastre_file: Path = DATA_DIR / "cadastre.gpkg"
    noise_file: Path = DATA_DIR / "noise_areas.gpkg"
    poi_settings_file: Path = DATA_DIR / "user_poi_settings.json"
    poi_settings_default_file: Path = DATA_DIR / "default_poi_settings.json"
    heritage_poi_file: Path = DATA_DIR / "heritage_points.gpkg"
    restriction_areas_file: Path = DATA_DIR / "land_restrictions.gpkg"
    detail_plans_file: Path = DATA_DIR / "detail_plans.gpkg"
    detail_plan_download_dir: Path = DATA_DIR / "detail_downloads"
    detail_plan_analysis_cache_dir: Path = (
        DATA_DIR / "detail_downloads" / "_analysis_cache"
    )


config = Config()
