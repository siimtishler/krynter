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
    cadastre_vector_file: Path = DATA_DIR / "tallinn_parcels"
    poi_file: Path = DATA_DIR / "Tallinn_POIS3.gpkg"
    cadastre_file: Path = DATA_DIR / "Tallinn_KATASTER_GPKG2.gpkg"
    noise_file: Path = DATA_DIR / "myra_tln.gpkg"
    heritage_poi_file: Path = DATA_DIR / "muinsuskaitse_poi.gpkg"
    restriction_areas_file: Path = DATA_DIR / "restriction_areas.gpkg"
    detail_plans_file: Path = DATA_DIR / "detail_plans_tln.gpkg"
    detail_plan_download_dir: Path = DATA_DIR / "detail_downloads"
    detail_plan_analysis_cache_dir: Path = (
        DATA_DIR / "detail_downloads" / "_analysis_cache"
    )


config = Config()
