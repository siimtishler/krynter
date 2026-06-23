"""Text extraction, normalization, and relevant-page selection."""

from __future__ import annotations

import contextlib
import io
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path

import fitz

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.models import Evidence
from backend.detailplan_analyzer.pdfs import OCRRuntime, run_ocr

TOPIC_KEYWORDS = {
    "krunt": 2,
    "krundi suurus": 6,
    "pindala": 4,
    "sihtotstarve": 5,
    "kasutusotstarve": 5,
    "korrus": 4,
    "täisehitus": 7,
    "ehitisealune": 6,
    "ehitusalune": 6,
    "kõrgus": 4,
    "hoonete arv": 6,
    "arhitektuur": 4,
    "haljastus": 4,
    "keskkond": 2,
    "juurdepääs": 4,
    "parkim": 4,
    "tehnovõrk": 5,
    "veevarustus": 3,
    "kanalisatsioon": 3,
    "elekter": 3,
    "servituut": 5,
    "kitsendus": 5,
    "kaitsevöönd": 4,
}


@dataclass(frozen=True)
class PageText:
    pdf_path: Path
    page: int
    text: str
    normalized_text: str


@dataclass(frozen=True)
class TextChunk:
    pdf_path: Path
    page: int
    text: str
    score: int
    reasons: list[str]


def normalize_planning_text(text: str) -> str:
    text = text.replace("\xa0", " ")
    lines = []
    for line in text.splitlines():
        normalized_line = re.sub(r"[ \t]+", " ", line).strip()
        if normalized_line:
            lines.append(normalized_line)
    return "\n".join(lines)


@time_function
def pdf_has_text(pdf_path: Path, min_chars: int = 100) -> bool:
    try:
        with fitz.open(pdf_path) as document:
            text_len = 0
            for page_index in range(min(5, document.page_count)):
                text_len += len(document.load_page(page_index).get_text("text").strip())
                if text_len >= min_chars:
                    logger.debug(
                        "PDF has text pdf=%s sampled_pages=%s sampled_chars=%s",
                        pdf_path,
                        page_index + 1,
                        text_len,
                    )
                    return True
    except Exception:
        logger.exception("Failed checking PDF text pdf=%s", pdf_path)
        return False
    logger.debug(
        "PDF has insufficient text pdf=%s sampled_chars=%s", pdf_path, text_len
    )
    return False


@time_function
def prepare_pdf_for_text(
    pdf_path: Path,
    runtime: OCRRuntime | None = None,
    force_refresh: bool = False,
) -> tuple[Path, bool]:
    if pdf_has_text(pdf_path):
        logger.debug("Using embedded PDF text pdf=%s", pdf_path)
        return pdf_path, False

    ocr_pdf = pdf_path.with_name(f"{pdf_path.stem}_ocr.pdf")
    if not force_refresh and ocr_pdf.exists() and pdf_has_text(ocr_pdf):
        logger.debug("Using cached OCR PDF raw_pdf=%s ocr_pdf=%s", pdf_path, ocr_pdf)
        return ocr_pdf, True

    logger.info("PDF needs OCR pdf=%s", pdf_path)
    return run_ocr(pdf_path, ocr_pdf, runtime), True


@time_function
def extract_pages(pdf_path: Path) -> list[PageText]:
    pages: list[PageText] = []
    with fitz.open(pdf_path) as document:
        for index, page in enumerate(document, start=1):
            text = page.get_text("text")
            pages.append(
                PageText(
                    pdf_path=pdf_path,
                    page=index,
                    text=text,
                    normalized_text=normalize_planning_text(text),
                )
            )
    non_empty = sum(1 for page in pages if page.normalized_text.strip())
    total_chars = sum(len(page.normalized_text) for page in pages)
    logger.debug(
        "Extracted pages pdf=%s page_count=%s non_empty_pages=%s normalized_chars=%s",
        pdf_path,
        len(pages),
        non_empty,
        total_chars,
    )
    return pages


def address_variants(address: str) -> list[str]:
    variants = {address.strip()}
    replacements = [
        (" tn ", " tn. "),
        (" tänav ", " tn "),
        (" mnt ", " mnt. "),
        (" pst ", " pst. "),
    ]
    for old, new in replacements:
        variants.add(address.replace(old, new).strip())
        variants.add(address.replace(new, old).strip())
    if "," in address:
        variants.add(address.split(",", maxsplit=1)[0].strip())
    return sorted({variant for variant in variants if variant})


def page_topic_score(text: str) -> tuple[int, list[str]]:
    low = text.lower()
    score = 0
    reasons: list[str] = []
    for keyword, weight in TOPIC_KEYWORDS.items():
        if keyword in low:
            score += weight
            reasons.append(keyword)

    dotted_leaders = text.count("....")
    if "sisukord" in low or dotted_leaders > 5:
        score -= 15
        reasons.append("toc_downrank")
    return score, reasons


def _page_score(page: PageText, variants: list[str]) -> tuple[int, list[str]]:
    score, reasons = page_topic_score(page.normalized_text)
    low = page.normalized_text.lower()
    if any(variant.lower() in low for variant in variants):
        score += 100
        reasons.append("address")
    return score, reasons


@time_function
def select_relevant_chunks(
    pages: list[PageText],
    address: str,
    max_chunks: int = 12,
) -> list[TextChunk]:
    variants = address_variants(address)
    logger.debug(
        "Selecting chunks address=%s variants=%s page_count=%s max_chunks=%s",
        address,
        variants,
        len(pages),
        max_chunks,
    )
    scored = [
        (page, *_page_score(page, variants))
        for page in pages
        if page.normalized_text.strip()
    ]
    if not scored:
        logger.debug("No non-empty pages available for chunk selection")
        return []

    has_address_hit = any("address" in reasons for _, _, reasons in scored)
    candidates = []
    for page, score, reasons in scored:
        if has_address_hit:
            if "address" in reasons or score >= 8:
                candidates.append((page, score, reasons))
        elif score > 0:
            candidates.append((page, score, reasons))

    if not candidates:
        candidates = scored[:max_chunks]

    candidates.sort(key=lambda item: (-item[1], item[0].pdf_path.name, item[0].page))
    chunks = [
        TextChunk(
            pdf_path=page.pdf_path,
            page=page.page,
            text=page.normalized_text[:8000],
            score=score,
            reasons=reasons,
        )
        for page, score, reasons in candidates[:max_chunks]
    ]
    logger.debug(
        "Selected chunks: %s",
        [
            {
                "pdf": chunk.pdf_path.name,
                "page": chunk.page,
                "score": chunk.score,
                "reasons": chunk.reasons,
                "chars": len(chunk.text),
                "snippet": chunk.text[:220],
            }
            for chunk in chunks
        ],
    )
    return chunks


def markdown_for_page(pdf_path: Path, page: int) -> str:
    try:
        import pymupdf4llm

        with _suppress_parser_output():
            markdown = pymupdf4llm.to_markdown(str(pdf_path), pages=[page - 1])
        if isinstance(markdown, str) and markdown.strip():
            return normalize_planning_text(markdown)
    except Exception:
        pass
    return ""


@contextlib.contextmanager
def _suppress_parser_output():
    stdout_buffer = io.StringIO()
    stderr_buffer = io.StringIO()
    devnull = os.open(os.devnull, os.O_WRONLY)
    stdout_fd = os.dup(1)
    stderr_fd = os.dup(2)
    try:
        os.dup2(devnull, 1)
        os.dup2(devnull, 2)
        with (
            contextlib.redirect_stdout(stdout_buffer),
            contextlib.redirect_stderr(stderr_buffer),
        ):
            yield
    finally:
        os.dup2(stdout_fd, 1)
        os.dup2(stderr_fd, 2)
        os.close(stdout_fd)
        os.close(stderr_fd)
        os.close(devnull)


@time_function
def chunks_with_llm_text(chunks: list[TextChunk]) -> list[TextChunk]:
    llm_chunks: list[TextChunk] = []
    for chunk in chunks:
        markdown = markdown_for_page(chunk.pdf_path, chunk.page)
        llm_chunks.append(replace(chunk, text=(markdown or chunk.text)[:10000]))
    logger.debug(
        "Prepared LLM chunks count=%s total_chars=%s pages=%s",
        len(llm_chunks),
        sum(len(chunk.text) for chunk in llm_chunks),
        [(chunk.pdf_path.name, chunk.page) for chunk in llm_chunks],
    )
    return llm_chunks


def find_address_lines(pages: list[PageText], address: str) -> list[Evidence]:
    variants = [variant.lower() for variant in address_variants(address)]
    matches: list[Evidence] = []
    for page in pages:
        for line in page.normalized_text.splitlines():
            low = line.lower()
            if any(variant in low for variant in variants):
                matches.append(
                    Evidence(
                        pdf=page.pdf_path.name,
                        page=page.page,
                        text=line[:500],
                    )
                )
    logger.debug(
        "Found address lines address=%s count=%s first_matches=%s",
        address,
        len(matches),
        [match.model_dump() for match in matches[:5]],
    )
    return matches
