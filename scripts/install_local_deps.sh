#!/usr/bin/env bash
set -euo pipefail

INSTALL_OLLAMA=false
OLLAMA_BUILDING_RIGHT_MODEL="${OLLAMA_BUILDING_RIGHT_MODEL:-gemma3:4b}"

for arg in "$@"; do
  case "$arg" in
    --with-ollama)
      INSTALL_OLLAMA=true
      ;;
    --model=*)
      OLLAMA_BUILDING_RIGHT_MODEL="${arg#--model=}"
      ;;
    -h|--help)
      cat <<'USAGE'
Install local development dependencies for Krünter.

Usage:
  scripts/install_local_deps.sh
  scripts/install_local_deps.sh --with-ollama
  scripts/install_local_deps.sh --with-ollama --model=qwen3:8b

Environment:
  OLLAMA_BUILDING_RIGHT_MODEL=gemma3:4b
    Default resolver model pulled when --with-ollama is used.
USAGE
      exit 0
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

if ! command -v apt-get >/dev/null 2>&1; then
  echo "This installer currently supports Debian/Ubuntu systems with apt-get." >&2
  exit 1
fi

if command -v sudo >/dev/null 2>&1; then
  SUDO=sudo
else
  SUDO=
fi

echo "Installing OCR system dependencies..."
$SUDO apt-get update
$SUDO apt-get install -y \
  curl \
  gdal-bin \
  ghostscript \
  qpdf \
  tesseract-ocr \
  tesseract-ocr-eng \
  tesseract-ocr-est

echo "Installing Python dependencies from poetry.lock..."
poetry install

if [ "$INSTALL_OLLAMA" = true ]; then
  if ! command -v ollama >/dev/null 2>&1; then
    echo "Installing Ollama..."
    curl -fsSL https://ollama.com/install.sh | sh
  fi

  echo "Starting Ollama if needed..."
  if ! pgrep -x ollama >/dev/null 2>&1; then
    nohup ollama serve >/tmp/krynter-ollama.log 2>&1 &
    sleep 3
  fi

  echo "Pulling Ollama model: $OLLAMA_BUILDING_RIGHT_MODEL"
  ollama pull "$OLLAMA_BUILDING_RIGHT_MODEL"
else
  cat <<'NOTE'

Ollama was not installed by default.
To install Ollama and pull the default model, run:

  scripts/install_local_deps.sh --with-ollama

NOTE
fi

echo "Checking OCR runtime..."
poetry run python - <<'PY'
from backend.detailplan_analyzer.pdfs import check_ocr_runtime

runtime = check_ocr_runtime()
print(f"OCR ready: {runtime.ready}")
print("Missing:", ", ".join(runtime.missing) or "-")
print("Languages:", ", ".join(sorted(runtime.languages)) or "-")
PY

echo "Done."
