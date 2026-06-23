FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_NO_INTERACTION=1 \
    POETRY_VIRTUALENVS_CREATE=false \
    POETRY_VERSION=2.4.1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        ghostscript \
        libgomp1 \
        qpdf \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-est \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml poetry.lock README.md ./
RUN pip install --no-cache-dir "poetry==$POETRY_VERSION" \
    && poetry install --only main --no-root

COPY backend ./backend
COPY experiments/run_detailplan_pdf_analysis.py ./experiments/run_detailplan_pdf_analysis.py

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
