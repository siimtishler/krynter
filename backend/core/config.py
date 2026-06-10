from pydantic_settings import BaseSettings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

class Config(BaseSettings):
    app_name: str = "Krynter"
    frontend_crs: str = "EPSG:4326"
    data_crs: str = "EPSG:3301"
    app_debug: bool = True

config = Config()