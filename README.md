## Background

Krünter is a infographics tool used for geographical analysis for the purpose
of evaluating plots of land in Harjumaa Estonia from various perspectives. E.g
* Home buyer
* Real estate developer
* Architect

Each group has a specific criteria in based on which they evaluate the land
Home buyers usually want to know what the surrounding environment has to offer
* Stores 
* Schools 
* Public transport possibilities
* Parks

Real estate developers would need to know the cost effectiveness of certain plots.
Krünter creates a detailplaneeringu analysis taking into account:
* The geological sediment in the area/ground - Can affect building cost
* Landscaping area
* Heritage conservation areas (muinsuskaitsealad)

Architects need to have a quick overview of requirements and surrounding personality of the plot:
* Noise level
* Winds
* Traffic analysis  


## Developing
```
poetry install
poetry shell
```
Start backend dev
`uvicorn backend.main:app --reload`

Start frontend dev
`cd frontend && npm run dev`

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
