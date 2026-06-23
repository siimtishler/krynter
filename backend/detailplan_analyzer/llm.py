"""Ollama structured-analysis client."""

from __future__ import annotations

import json
import os
import re

import httpx
from pydantic import ValidationError

from backend.core.logging import logger
from backend.core.utils import time_function
from backend.detailplan_analyzer.extraction import TextChunk
from backend.detailplan_analyzer.models import StructuredLLMResponse

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "qwen3:8b"
DEFAULT_OLLAMA_TIMEOUT_S = 600
DEFAULT_OLLAMA_PREFLIGHT_TIMEOUT_S = 10


class LLMUnavailable(RuntimeError):
    """Raised when Ollama cannot be reached or returns an unusable response."""


class LLMValidationFailed(RuntimeError):
    """Raised when a model response cannot be parsed as the required schema."""


def ollama_base_url() -> str:
    return os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def ollama_model() -> str:
    return os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def ollama_timeout_s() -> int:
    return int(os.getenv("OLLAMA_TIMEOUT_S", str(DEFAULT_OLLAMA_TIMEOUT_S)))


def _strip_thinking(content: str) -> str:
    return re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()


def _extract_json(content: str) -> dict:
    content = _strip_thinking(content)
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start == -1 or end == -1 or end <= start:
            raise
        return json.loads(content[start : end + 1])


def _chunk_payload(chunks: list[TextChunk]) -> str:
    parts = []
    for chunk in chunks:
        parts.append(
            "\n".join(
                [
                    f"PDF: {chunk.pdf_path.name}",
                    f"Lehekülg: {chunk.page}",
                    "Tekst:",
                    chunk.text,
                ]
            )
        )
    return "\n\n---\n\n".join(parts)


def _prompt_size(messages: list[dict[str, str]]) -> int:
    return sum(len(message.get("content", "")) for message in messages)


def _analysis_prompt(address: str, chunks: list[TextChunk]) -> list[dict[str, str]]:
    schema = json.dumps(
        StructuredLLMResponse.model_json_schema(),
        ensure_ascii=False,
    )
    user_prompt = f"""
Aadress: {address}

Analüüsi ainult allpool antud PDFi chunk'e. Ära kasuta väliseid teadmisi.
Kui väärtust ei ole chunk'ides, jäta see nulliks või lisa puuduste loetellu.
Iga väide peab põhinema chunk'is oleval tekstil ja võimalusel sisaldama lehekülje numbrit.

Vasta ainult JSON objektina, mis vastab sellele JSON schemale:
{schema}

Chunk'id:
{_chunk_payload(chunks)}
""".strip()
    return [
        {
            "role": "system",
            "content": (
                "Sa oled Eesti detailplaneeringute analüütik. "
                "Tagasta ainult valideeritav JSON."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]


def _repair_prompt(invalid_content: str) -> list[dict[str, str]]:
    schema = json.dumps(
        StructuredLLMResponse.model_json_schema(),
        ensure_ascii=False,
    )
    return [
        {
            "role": "system",
            "content": "Paranda vastus valideeritavaks JSONiks. Tagasta ainult JSON.",
        },
        {
            "role": "user",
            "content": (
                "See vastus ei olnud nõutud schema järgi valideeritav. "
                f"Schema: {schema}\n\nVastus:\n{invalid_content}"
            ),
        },
    ]


@time_function
def _ollama_chat(
    messages: list[dict[str, str]],
    model: str,
    base_url: str,
    timeout_s: int,
) -> str:
    logger.info(
        "Calling Ollama base_url=%s model=%s timeout_s=%s prompt_chars=%s",
        base_url,
        model,
        timeout_s,
        _prompt_size(messages),
    )
    try:
        response = httpx.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": messages,
                "stream": False,
                "format": StructuredLLMResponse.model_json_schema(),
                "options": {"temperature": 0},
            },
            timeout=httpx.Timeout(timeout_s, connect=10),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:2000]
        logger.error(
            "Ollama HTTP status error base_url=%s model=%s status=%s body=%s",
            base_url,
            model,
            exc.response.status_code,
            body,
        )
        raise LLMUnavailable(
            f"Ollama HTTP {exc.response.status_code} at {base_url}/api/chat: {body}"
        ) from exc
    except httpx.ReadTimeout as exc:
        logger.exception(
            "Ollama generation timed out base_url=%s model=%s timeout_s=%s prompt_chars=%s",
            base_url,
            model,
            timeout_s,
            _prompt_size(messages),
        )
        raise LLMUnavailable(
            f"Ollama generation timed out after {timeout_s}s at {base_url}/api/chat "
            f"with model {model}. The model may still be loading or generating slowly. "
            "Try a smaller model, fewer chunks, or set OLLAMA_TIMEOUT_S higher."
        ) from exc
    except httpx.RequestError as exc:
        logger.exception(
            "Ollama request failed base_url=%s model=%s error=%s",
            base_url,
            model,
            exc,
        )
        raise LLMUnavailable(
            f"Could not reach Ollama at {base_url} with model {model}: {exc}"
        ) from exc

    payload = response.json()
    content = payload.get("message", {}).get("content")
    if not isinstance(content, str) or not content.strip():
        logger.error(
            "Ollama returned empty content payload_keys=%s", list(payload.keys())
        )
        raise LLMUnavailable("Ollama returned an empty message")
    logger.debug("Ollama response chars=%s snippet=%s", len(content), content[:1000])
    return content


@time_function
def check_ollama_runtime(
    model: str,
    base_url: str,
    timeout_s: int = DEFAULT_OLLAMA_PREFLIGHT_TIMEOUT_S,
) -> None:
    logger.debug("Checking Ollama runtime base_url=%s model=%s", base_url, model)
    try:
        response = httpx.get(
            f"{base_url}/api/tags",
            timeout=httpx.Timeout(timeout_s, connect=5),
        )
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = exc.response.text[:1000]
        logger.error(
            "Ollama tags endpoint returned HTTP %s body=%s",
            exc.response.status_code,
            body,
        )
        raise LLMUnavailable(
            f"Ollama tags endpoint returned HTTP {exc.response.status_code}: {body}"
        ) from exc
    except httpx.RequestError as exc:
        logger.exception("Ollama tags endpoint unreachable base_url=%s", base_url)
        raise LLMUnavailable(f"Could not reach Ollama at {base_url}: {exc}") from exc

    payload = response.json()
    models = payload.get("models", [])
    model_names = {
        item.get("name")
        for item in models
        if isinstance(item, dict) and item.get("name")
    }
    logger.debug("Ollama available models=%s", sorted(model_names))
    if model not in model_names:
        raise LLMUnavailable(
            f"Ollama model {model!r} is not available at {base_url}. "
            f"Available models: {sorted(model_names)}. Run: ollama pull {model}"
        )


def _validate_content(content: str) -> StructuredLLMResponse:
    try:
        return StructuredLLMResponse.model_validate(_extract_json(content))
    except (json.JSONDecodeError, ValidationError) as exc:
        logger.exception(
            "LLM response validation failed content_snippet=%s", content[:2000]
        )
        raise LLMValidationFailed(str(exc)) from exc


@time_function
def analyze_with_local_llm(
    address: str,
    chunks: list[TextChunk],
    model: str | None = None,
    base_url: str | None = None,
    timeout_s: int | None = None,
) -> StructuredLLMResponse:
    selected_model = model or ollama_model()
    selected_base_url = base_url or ollama_base_url()
    selected_timeout_s = timeout_s or ollama_timeout_s()
    logger.info(
        "Starting local LLM analysis address=%s chunks=%s model=%s base_url=%s timeout_s=%s",
        address,
        len(chunks),
        selected_model,
        selected_base_url,
        selected_timeout_s,
    )
    logger.debug(
        "LLM chunk summary=%s",
        [
            {
                "pdf": chunk.pdf_path.name,
                "page": chunk.page,
                "chars": len(chunk.text),
                "score": chunk.score,
                "reasons": chunk.reasons,
            }
            for chunk in chunks
        ],
    )
    check_ollama_runtime(selected_model, selected_base_url)

    messages = _analysis_prompt(address, chunks)
    content = _ollama_chat(
        messages,
        model=selected_model,
        base_url=selected_base_url,
        timeout_s=selected_timeout_s,
    )
    try:
        result = _validate_content(content)
        logger.info("LLM response validated on first attempt")
        return result
    except LLMValidationFailed:
        logger.info("Attempting one LLM JSON repair pass")
        repaired = _ollama_chat(
            _repair_prompt(content),
            model=selected_model,
            base_url=selected_base_url,
            timeout_s=selected_timeout_s,
        )
        result = _validate_content(repaired)
        logger.info("LLM response validated after repair")
        return result
