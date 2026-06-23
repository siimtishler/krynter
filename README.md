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

For local PDF/OCR/LLM development on Ubuntu/Debian, install the required system
and Python dependencies with:

```bash
scripts/install_local_deps.sh
```

To also install Ollama and pull the default model:

```bash
scripts/install_local_deps.sh --with-ollama
```

To pull a larger model:

```bash
scripts/install_local_deps.sh --with-ollama --model=qwen3:14b
```

## Docker

The Docker stack runs the backend, frontend, OCR dependencies, and Ollama:

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
and downloaded PDF files stay outside the image. The first startup also pulls
the default model into a Docker volume:

```bash
OLLAMA_MODEL=qwen3:8b DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build
```

To try a larger model:

```bash
OLLAMA_MODEL=qwen3:14b DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build
```

Run the standalone PDF analyzer inside Docker:

```bash
docker compose run --rm backend \
  python experiments/run_detailplan_pdf_analysis.py \
  /app/data/detail_downloads/30108673_Kaupmehe/SK100_30108673_KaupmeheTn19.pdf \
  --address "Kaupmehe tn 19"
```

### Detail-plan PDF analysis runtime

The backend endpoint `GET /api/detail-plan-analysis` analyzes the highest-overlap
detail-planning PDF for a parcel. Python dependencies are managed by Poetry, but
the OCR and local LLM runtime also need system services:

* OCR: install OCRmyPDF dependencies, including `tesseract`, `qpdf`, and
  Ghostscript (`gs`).
* Tesseract languages: install both `est` and `eng` language packs.
* LLM: run Ollama locally and pull the first-pass model:
  `ollama pull qwen3:8b`.

Optional environment variables:

* `OLLAMA_BASE_URL`, default `http://127.0.0.1:11434`
* `OLLAMA_MODEL`, default `qwen3:8b`
* `OLLAMA_TIMEOUT_S`, default `600`

Detail plans with less than `DETAIL_PLAN_MIN_COVERAGE_PCT` parcel overlap are
filtered out before they are returned to the frontend. The current cutoff is
`10.0%` in `backend/geo/constants.py`.

Debug local LLM availability:

```bash
curl http://127.0.0.1:11434/api/tags
ollama list
ollama pull qwen3:8b
```

If the analyzer returns `llm_unavailable` with `Ollama generation timed out`,
Ollama is reachable but `/api/chat` did not finish in time. Try:

```bash
OLLAMA_TIMEOUT_S=1200 uvicorn backend.main:app --reload
```

Or for Docker:

```bash
OLLAMA_TIMEOUT_S=1200 DOCKER_BUILDKIT=0 COMPOSE_DOCKER_CLI_BUILD=0 docker compose up --build
```

When using Docker, follow analyzer progress in backend logs:

```bash
docker compose logs -f backend
```

The analyzer logs cache/download, OCR decisions, extracted page counts, selected
chunk pages/scores/snippets, regex facts, Ollama URL/model/prompt size, and each
timed pipeline function.
