## Background

Krünter is a geospatial parcel-analysis web app for Harjumaa, Estonia. It lets a user search/select a land parcel by address or cadastre code, then shows useful context around it: nearby POIs, noise areas, heritage/restriction overlays, detail-plan overlaps, and parcel attributes on a MapLibre frontend.
Technically it has:
- Frontend: Vite/vanilla JS app with MapLibre map layers and API calls.
- Backend: FastAPI service with GeoPandas/Shapely-based spatial lookup over local GeoPackage datasets.
Detail-plan analyzer: downloads/caches detail-plan PDFs or ZIPs, OCRs with OCRmyPDF/Tesseract when needed, extracts text with PyMuPDF, selects relevant chunks, then uses regex/rule scoring to extract building-right fields like plot area, building coverage, allowed floors, height, roof slope, fire class, etc.
- Optional LLM layer: current code includes an Ollama-backed resolver hook that can verify/resolve uncertain regex candidates after deterministic extraction.
- Data/runtime: Docker/Poetry setup, local data/ mount for large GIS files and cached downloaded PDFs.


## Developing
```
poetry install
poetry shell
```
Start backend dev
`uvicorn backend.main:app --reload`

Start frontend dev
`cd frontend && npm run dev`

Addtionally:
Add .env to frontend/ and `VITE_SHOW_DEBUG_HTML=true` to see extra debug info directly on the site

Open up the frontend URL and youre good to go


### Local dependency installer

For local PDF/OCR development on Ubuntu/Debian, install the required system and
Python dependencies with:

```bash
scripts/install_local_deps.sh
```

Ollama install options are still present in the helper script from the previous
LLM workflow, but the current regex-only analyzer does not use Ollama.

```bash
scripts/install_local_deps.sh --with-ollama
```

To pull a larger model:

```bash
scripts/install_local_deps.sh --with-ollama --model=qwen3:14b
```

## Docker

The Docker stack runs the backend, frontend, OCR dependencies, and currently
still includes the older Ollama service pending dependency cleanup:

```bash
DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build
```

The `DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0` prefix is intentional:
Docker buildx can fail from a non-ASCII workspace path such as `Krünter` with
`x-docker-expose-session-sharedkey contains value with non-printable ASCII
characters`.

Services:

* Frontend: http://127.0.0.1:5173
* Backend API: http://127.0.0.1:8000
* Ollama: http://127.0.0.1:11434

The backend container mounts local `./data` to `/app/data`, so large GeoPackage
and downloaded PDF files stay outside the image.

Run the standalone PDF analyzer inside Docker:

```bash
docker compose run --rm backend \
  python scripts/run_detailplan_regex_analysis.py \
  /app/data/detail_downloads/30108673_Kaupmehe/SK100_30108673_KaupmeheTn19.pdf \
  --address "Kaupmehe tn 19"
```

### Detail-plan PDF analysis runtime

The backend endpoint `GET /api/detail-plan-analysis` analyzes the highest-overlap
detail-planning PDF for a parcel. It downloads/caches the PDF, OCRs only when
needed, extracts page text with PyMuPDF, selects building-right pages, and returns
a synchronous regex-only `ehitamise_pohioigus` result.

Manual local PDF run:

```bash
poetry run python scripts/run_detailplan_regex_analysis.py \
  data/detail_downloads/30109024/SK100_30109024_MaiTn2RaudteeTn_ocr.pdf \
  --address "Mai tn 2"
```

Python dependencies are managed by Poetry, but OCR also needs system services:

* OCR: install OCRmyPDF dependencies, including `tesseract`, `qpdf`, and
  Ghostscript (`gs`).
* Tesseract languages: install both `est` and `eng` language packs.

Detail plans with less than `DETAIL_PLAN_MIN_COVERAGE_PCT` parcel overlap are
filtered out before they are returned to the frontend. The current cutoff is
`10.0%` in `backend/geo/constants.py`.

When using Docker, follow analyzer progress in backend logs:

```bash
docker compose logs -f backend
```

The analyzer logs cache/download, OCR decisions, extracted page counts, selected
chunk pages/scores/snippets, regex candidates, missing fields, and each timed
pipeline function.
