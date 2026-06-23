"""PDF download, ZIP extraction, OCR setup checks, and OCR execution."""

from __future__ import annotations

import re
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from backend.core.config import config
from backend.core.logging import logger
from backend.core.utils import time_function


class PDFDownloadError(RuntimeError):
    """Raised when plan files cannot be downloaded or unpacked."""


class OCRSetupError(RuntimeError):
    """Raised when OCR is required but local OCR tooling is unavailable."""

    def __init__(self, missing: list[str]):
        self.missing = missing
        super().__init__(", ".join(missing))


@dataclass(frozen=True)
class OCRRuntime:
    missing: list[str]
    languages: set[str]

    @property
    def ready(self) -> bool:
        return not self.missing


def safe_name(value: str | int | None, default: str = "detail_plan") -> str:
    text = str(value or default).strip().lower()
    text = re.sub(r"[^a-z0-9_-]+", "_", text)
    return text.strip("_") or default


def cached_plan_pdfs(plan_dir: Path) -> list[Path]:
    if not plan_dir.exists():
        return []
    return sorted(
        path
        for path in plan_dir.rglob("*.pdf")
        if path.is_file() and not path.stem.endswith("_ocr")
    )


def _content_extension(content_type: str, url: str, body: bytes) -> str:
    content_type = content_type.lower()
    path_suffix = Path(urlparse(url).path).suffix.lower()
    if "application/zip" in content_type or body.startswith(b"PK"):
        return ".zip"
    if "application/pdf" in content_type or body.startswith(b"%PDF"):
        return ".pdf"
    if path_suffix in {".zip", ".pdf"}:
        return path_suffix
    raise PDFDownloadError(f"Unsupported detail-plan file type: {content_type}")


@time_function
def download_file(url: str, target_base: Path, timeout_s: int = 60) -> Path:
    logger.debug("Downloading detail-plan file url=%s target_base=%s", url, target_base)
    response = httpx.get(url, timeout=timeout_s)
    if response.status_code != 200:
        raise PDFDownloadError(f"Failed to download {url}: HTTP {response.status_code}")

    suffix = _content_extension(
        response.headers.get("content-type", ""),
        url,
        response.content,
    )
    target_path = target_base.with_suffix(suffix)
    target_path.write_bytes(response.content)
    logger.debug(
        "Downloaded detail-plan file path=%s content_type=%s bytes=%s",
        target_path,
        response.headers.get("content-type", ""),
        len(response.content),
    )
    return target_path


@time_function
def extract_relevant_pdfs(zip_path: Path, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    output_root = output_dir.resolve()
    extracted: list[Path] = []

    with zipfile.ZipFile(zip_path) as archive:
        members = archive.namelist()
        pdf_members = [
            member
            for member in members
            if Path(member).suffix.lower() == ".pdf" and not member.endswith("/")
        ]
        sk_pdf_members = [
            member for member in pdf_members if Path(member).name.startswith("SK")
        ]
        members_to_extract = sk_pdf_members or pdf_members
        logger.debug(
            "ZIP members=%s pdf_members=%s sk_pdf_members=%s extracting=%s zip=%s",
            len(members),
            len(pdf_members),
            len(sk_pdf_members),
            len(members_to_extract),
            zip_path,
        )

        for member in members_to_extract:
            member_path = Path(member)
            relative_target = (
                Path(member_path.name) if sk_pdf_members else Path(*member_path.parts)
            )
            target_path = (output_dir / relative_target).resolve()
            if not target_path.is_relative_to(output_root):
                raise ValueError(f"Unsafe zip member path: {member}")

            target_path.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target_path.open("wb") as target:
                target.write(source.read())
            extracted.append(target_path)

    logger.debug("Extracted PDF paths: %s", [str(path) for path in extracted])
    return sorted(extracted)


def detail_plan_cache_dir(
    detail_plan: dict,
    cache_root: Path | None = None,
) -> Path:
    root = cache_root or config.detail_plan_download_dir
    plan_id = (
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid")
    )
    return root / safe_name(plan_id)


@time_function
def download_plan_pdfs(
    detail_plan: dict,
    cache_root: Path | None = None,
    force_refresh: bool = False,
) -> list[Path]:
    plan_dir = detail_plan_cache_dir(detail_plan, cache_root)
    logger.debug(
        "Preparing plan PDFs plan_id=%s failid=%s cache_dir=%s force_refresh=%s",
        detail_plan.get("sysid")
        or detail_plan.get("planid")
        or detail_plan.get("kovid"),
        detail_plan.get("failid"),
        plan_dir,
        force_refresh,
    )
    if not force_refresh:
        cached = cached_plan_pdfs(plan_dir)
        if cached:
            logger.debug("Using cached plan PDFs: %s", [str(path) for path in cached])
            return cached

    file_url = detail_plan.get("failid")
    if not file_url:
        logger.debug("Detail plan has no failid URL: %s", detail_plan)
        return []

    plan_dir.mkdir(parents=True, exist_ok=True)
    downloaded_path = download_file(file_url, plan_dir / "download")

    if downloaded_path.suffix.lower() == ".pdf":
        target_path = plan_dir / "download.pdf"
        if downloaded_path != target_path:
            downloaded_path.replace(target_path)
        logger.debug("Downloaded direct PDF: %s", target_path)
        return [target_path]

    if downloaded_path.suffix.lower() == ".zip":
        extracted = extract_relevant_pdfs(downloaded_path, plan_dir)
        downloaded_path.unlink(missing_ok=True)
        return extracted

    raise PDFDownloadError(f"Unsupported downloaded file: {downloaded_path}")


def tesseract_languages() -> set[str]:
    if shutil.which("tesseract") is None:
        return set()

    result = subprocess.run(
        ["tesseract", "--list-langs"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return set()

    lines = [line.strip() for line in result.stdout.splitlines()]
    return {line for line in lines if line and not line.startswith("List of")}


@time_function
def check_ocr_runtime() -> OCRRuntime:
    missing = [
        tool
        for tool in ("ocrmypdf", "tesseract", "qpdf", "gs")
        if shutil.which(tool) is None
    ]
    languages = tesseract_languages()
    for language in ("est", "eng"):
        if "tesseract" not in missing and language not in languages:
            missing.append(f"tesseract language '{language}'")
    runtime = OCRRuntime(missing=missing, languages=languages)
    logger.debug(
        "OCR runtime ready=%s missing=%s languages=%s",
        runtime.ready,
        runtime.missing,
        sorted(runtime.languages),
    )
    return runtime


@time_function
def run_ocr(raw_pdf: Path, ocr_pdf: Path, runtime: OCRRuntime | None = None) -> Path:
    runtime = runtime or check_ocr_runtime()
    if not runtime.ready:
        raise OCRSetupError(runtime.missing)

    ocr_pdf.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Running OCRmyPDF raw_pdf=%s ocr_pdf=%s", raw_pdf, ocr_pdf)
    result = subprocess.run(
        [
            "ocrmypdf",
            "--language",
            "est+eng",
            "--deskew",
            "--skip-text",
            str(raw_pdf),
            str(ocr_pdf),
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.error("OCRmyPDF failed stderr=%s", result.stderr.strip()[:2000])
        raise PDFDownloadError(result.stderr.strip() or "OCRmyPDF failed")
    logger.debug("OCRmyPDF completed stdout=%s", result.stdout.strip()[:1000])
    return ocr_pdf
