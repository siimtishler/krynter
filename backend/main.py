from fastapi import FastAPI
from fastapi import HTTPException
from fastapi.responses import FileResponse

from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.core.config import DATA_DIR, config
from backend.core.logging import logger
from backend.api.api import router


app = FastAPI()

@app.get("/vector_tiles/metadata.json")
def get_vector_tile_metadata():
    metadata_path = DATA_DIR / "kerese" / "metadata.json"
    if not metadata_path.exists():
        raise HTTPException(status_code=404, detail="Vector tile metadata not found")
    return FileResponse(metadata_path, media_type="application/json")


@app.get("/tallinn_parcels/{z}/{x}/{y}.pbf")
def get_vector_tile_close(z: int, x: int, y: int):
    tile_path = config.cadastre_vector_file / str(z) / str(x) / f"{y}.pbf"
    if not tile_path.exists():
        raise HTTPException(status_code=404, detail="Vector tile not found")

    return FileResponse(
        tile_path,
        media_type="application/x-protobuf",
        headers={"Content-Encoding": "gzip"},
    )

app.include_router(router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://127.0.0.1:5500",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
