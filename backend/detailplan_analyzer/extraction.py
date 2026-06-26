"""Text extraction, normalization, and relevant-page selection."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

import fitz

from backend.core.config import config
from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.models import Evidence
from backend.detailplan_analyzer.pdfs import OCRRuntime, run_ocr

TOPIC_KEYWORDS = {
    "krunt": 2,
    "krundi suurus": 6,
    "krundi pind": 6,
    "pindala": 4,
    "sihtotstarve": 5,
    "kasutusotstarve": 5,
    "korrus": 4,
    "täisehitus": 7,
    "ehitisealune": 6,
    "ehitusalune": 6,
    "brutopind": 5,
    "bruto pind": 5,
    "kõrgus": 4,
    "hoonete arv": 6,
    "katuse": 4,
    "katusekalle": 5,
    "tulepüsivus": 5,
    "tp-": 4,
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


def _pdf_fingerprint(pdf_path: Path) -> str:
    stat = pdf_path.stat()
    payload = "|".join(
        [
            str(pdf_path.resolve()),
            str(stat.st_mtime_ns),
            str(stat.st_size),
        ]
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _page_cache_path(pdf_path: Path) -> Path:
    return (
        config.detail_plan_analysis_cache_dir
        / "pages"
        / f"{_pdf_fingerprint(pdf_path)}.json"
    )


def _serialize_page(page: PageText) -> dict:
    return {
        "pdf_path": str(page.pdf_path),
        "page": page.page,
        "text": page.text,
        "normalized_text": page.normalized_text,
    }


def _deserialize_page(payload: dict) -> PageText:
    return PageText(
        pdf_path=Path(payload["pdf_path"]),
        page=payload["page"],
        text=payload["text"],
        normalized_text=payload["normalized_text"],
    )


@time_function
def pdf_has_text(pdf_path: Path, min_chars: int = 100) -> bool:
    try:
        with fitz.open(pdf_path) as document:
            text_len = 0
            for page_index in range(min(5, document.page_count)):
                text_len += len(document.load_page(page_index).get_text("text").strip())
                if text_len >= min_chars:
                    logger.debug(
                        f"PDF has text pdf={pdf_path} "
                        f"sampled_pages={page_index + 1} sampled_chars={text_len}"
                    )
                    return True
    except Exception:
        logger.exception(f"Failed checking PDF text pdf={pdf_path}")
        return False
    logger.debug(f"PDF has insufficient text pdf={pdf_path} sampled_chars={text_len}")
    return False


@time_function
def prepare_pdf_for_text(
    pdf_path: Path,
    runtime: OCRRuntime | None = None,
    force_refresh: bool = False,
) -> tuple[Path, bool]:
    if pdf_has_text(pdf_path):
        logger.debug(f"Using embedded PDF text pdf={pdf_path}")
        return pdf_path, False

    ocr_pdf = pdf_path.with_name(f"{pdf_path.stem}_ocr.pdf")
    if not force_refresh and ocr_pdf.exists() and pdf_has_text(ocr_pdf):
        logger.debug(f"Using cached OCR PDF raw_pdf={pdf_path} ocr_pdf={ocr_pdf}")
        return ocr_pdf, True

    logger.info(f"PDF needs OCR pdf={pdf_path}")
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
        f"Extracted pages pdf={pdf_path} page_count={len(pages)} "
        f"non_empty_pages={non_empty} normalized_chars={total_chars}"
    )
    return pages


@time_function
def extract_pages_cached(pdf_path: Path, force_refresh: bool = False) -> list[PageText]:
    cache_path = _page_cache_path(pdf_path)
    if not force_refresh and cache_path.exists():
        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            pages = [_deserialize_page(item) for item in payload["pages"]]
            logger.debug(
                f"Using cached page text pdf={pdf_path} cache={cache_path} "
                f"page_count={len(pages)}"
            )
            return pages
        except (KeyError, TypeError, json.JSONDecodeError):
            logger.exception(f"Failed reading page text cache cache={cache_path}")

    pages = extract_pages(pdf_path)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "pdf_path": str(pdf_path),
                "fingerprint": _pdf_fingerprint(pdf_path),
                "pages": [_serialize_page(page) for page in pages],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    logger.debug(f"Cached page text pdf={pdf_path} cache={cache_path}")
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
        f"Selecting chunks address={address} variants={variants} "
        f"page_count={len(pages)} max_chunks={max_chunks}"
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
    selected_chunks = [
        {
            "pdf": chunk.pdf_path.name,
            "page": chunk.page,
            "score": chunk.score,
            "reasons": chunk.reasons,
            "chars": len(chunk.text),
            "snippet": chunk.text[:220],
        }
        for chunk in chunks
    ]
    logger.debug(
        f"Selected chunks: {selected_chunks}",
    )
    return chunks


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
        f"Found address lines address={address} count={len(matches)} "
        f"first_matches={[match.model_dump() for match in matches[:5]]}"
    )
    return matches
