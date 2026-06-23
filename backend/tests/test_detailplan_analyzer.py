import zipfile
from pathlib import Path

import fitz
import geopandas as gpd
import httpx
import pytest
from fastapi import HTTPException
from shapely.geometry import Point

from backend.api import api
from backend.detailplan_analyzer import analyzer, llm
from backend.detailplan_analyzer.extraction import (
    PageText,
    TextChunk,
    extract_pages,
    pdf_has_text,
    select_relevant_chunks,
)
from backend.detailplan_analyzer.models import (
    AnalysisStatus,
    DetailPlanAnalysisResponse,
    DetailPlanMeta,
    LLMBuildingRight,
    LLMValue,
    StructuredLLMResponse,
)
from backend.detailplan_analyzer.pdfs import (
    OCRRuntime,
    cached_plan_pdfs,
    extract_relevant_pdfs,
)
from backend.detailplan_analyzer.rules import run_rule_based_extractors
from backend.geo import Parcel


def make_pdf(path: Path, text: str) -> Path:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()
    return path


def test_zip_extraction_prefers_sk_pdfs(tmp_path):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("docs/SK100_plan.pdf", b"sk")
        archive.writestr("docs/MH100_report.pdf", b"mh")

    extracted = extract_relevant_pdfs(zip_path, tmp_path / "out")

    assert [path.name for path in extracted] == ["SK100_plan.pdf"]
    assert extracted[0].read_bytes() == b"sk"


def test_zip_extraction_extracts_all_pdfs_when_no_sk(tmp_path):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("a/MH100_report.pdf", b"mh")
        archive.writestr("b/DOC100_appendix.PDF", b"doc")
        archive.writestr("notes.txt", b"skip")

    extracted = extract_relevant_pdfs(zip_path, tmp_path / "out")

    assert sorted(path.name for path in extracted) == [
        "DOC100_appendix.PDF",
        "MH100_report.pdf",
    ]
    assert not (tmp_path / "out" / "notes.txt").exists()


def test_zip_extraction_rejects_unsafe_paths(tmp_path):
    zip_path = tmp_path / "files.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("../evil.pdf", b"bad")

    with pytest.raises(ValueError):
        extract_relevant_pdfs(zip_path, tmp_path / "out")


def test_cached_plan_pdfs_excludes_generated_ocr_outputs(tmp_path):
    (tmp_path / "source.pdf").write_bytes(b"pdf")
    (tmp_path / "source_ocr.pdf").write_bytes(b"ocr")

    assert [path.name for path in cached_plan_pdfs(tmp_path)] == ["source.pdf"]


def test_pdf_has_text_and_extract_pages(tmp_path):
    pdf_path = make_pdf(
        tmp_path / "text.pdf",
        "Kaupmehe tn 19 detailplaneeringu seletuskiri. " * 5,
    )

    assert pdf_has_text(pdf_path)
    pages = extract_pages(pdf_path)
    assert len(pages) == 1
    assert "Kaupmehe tn 19" in pages[0].normalized_text


def test_select_relevant_chunks_uses_address_and_downranks_toc(tmp_path):
    pdf_path = tmp_path / "plan.pdf"
    pages = [
        PageText(
            pdf_path=pdf_path,
            page=1,
            text="SISUKORD\nkrunt .... korrus .... täisehitus ....",
            normalized_text="SISUKORD\nkrunt .... korrus .... täisehitus ....",
        ),
        PageText(
            pdf_path=pdf_path,
            page=2,
            text="Kaupmehe tn 19 krundi suurus on 1000 m2.",
            normalized_text="Kaupmehe tn 19 krundi suurus on 1000 m2.",
        ),
        PageText(
            pdf_path=pdf_path,
            page=3,
            text="Täisehitus on 25% ja hoone kõrgus on 12 m.",
            normalized_text="Täisehitus on 25% ja hoone kõrgus on 12 m.",
        ),
    ]

    chunks = select_relevant_chunks(pages, "Kaupmehe tn 19", max_chunks=2)

    assert [chunk.page for chunk in chunks] == [2, 3]


def test_rule_based_extractors_find_estonian_planning_fields(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=4,
        text=(
            "Krundi suurus 1 200 m²\n"
            "Sihtotstarve elamumaa 100%\n"
            "Korruselisus 2\n"
            "Täisehitus 25,5%\n"
            "Hoone maksimaalne kõrgus 9,5 m\n"
            "Hoonete arv 2\n"
            "Parkimine lahendada krundil.\n"
            "Tehnovõrkude lahendus täpsustatakse projektis.\n"
            "Servituut seatakse tehnovõrgu kaitseks."
        ),
        score=10,
        reasons=["test"],
    )

    result = run_rule_based_extractors([chunk])

    assert result.building_right["krundi_suurus"].value == 1200
    assert result.building_right["taisehitus"].value == 25.5
    assert result.building_right["korgus"].value == 9.5
    assert result.building_right["hoonete_arv"].value == 2
    assert result.section_facts["tehnovorgud"]
    assert result.section_facts["servituudid_ja_kitsendused"]


def test_analyze_pdfs_computes_derived_field_and_flags_conflict(monkeypatch, tmp_path):
    pdf_path = tmp_path / "plan.pdf"
    page = PageText(
        pdf_path=pdf_path,
        page=3,
        text=(
            "Kaupmehe tn 19 krundi suurus 1000 m2\n"
            "Täisehitus 25%\n"
            "Hoonete arv 1\n"
        ),
        normalized_text=(
            "Kaupmehe tn 19 krundi suurus 1000 m2\n"
            "Täisehitus 25%\n"
            "Hoonete arv 1\n"
        ),
    )
    llm_response = StructuredLLMResponse(
        building_right=LLMBuildingRight(
            site_coverage_pct=LLMValue(
                value=40,
                page=3,
                evidence_text="Täisehitus 40%",
            )
        )
    )

    monkeypatch.setattr(analyzer, "check_ocr_runtime", lambda: OCRRuntime([], set()))
    monkeypatch.setattr(
        analyzer,
        "prepare_pdf_for_text",
        lambda raw_pdf, runtime=None, force_refresh=False: (raw_pdf, False),
    )
    monkeypatch.setattr(analyzer, "extract_pages", lambda working_pdf: [page])
    monkeypatch.setattr(analyzer, "chunks_with_llm_text", lambda chunks: chunks)
    monkeypatch.setattr(
        analyzer,
        "analyze_with_local_llm",
        lambda address, chunks: llm_response,
    )

    response = analyzer.analyze_pdfs([pdf_path], "Kaupmehe tn 19")
    building_facts = response.sections["ehitamise_pohioigus"].found_in_pdf

    assert response.status == AnalysisStatus.PARTIAL
    assert any(
        fact.key == "ehitisealune_pind_tuletatud" and fact.value == 250
        for fact in building_facts
    )
    assert any(
        item.key == "taisehitus"
        for item in response.sections["ehitamise_pohioigus"].needs_review
    )


def test_ollama_invalid_json_gets_one_repair_attempt(monkeypatch):
    calls = []
    valid_payload = {
        "summary": "Kokkuvõte",
        "building_right": {},
        "architecture": [],
        "landscaping_environment": [],
        "access_parking": [],
        "utilities": [],
        "servitudes_restrictions": [],
        "missing_or_needs_review": [],
        "buyer_risks": [],
    }

    class FakeResponse:
        def __init__(self, content):
            self.content = content

        def raise_for_status(self):
            return None

        def json(self):
            return {"message": {"content": self.content}}

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            return FakeResponse("not json")
        return FakeResponse(__import__("json").dumps(valid_payload))

    class FakeTagsResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr(llm.httpx, "post", fake_post)
    monkeypatch.setattr(llm.httpx, "get", lambda *args, **kwargs: FakeTagsResponse())

    result = llm.analyze_with_local_llm(
        "Kaupmehe tn 19",
        [TextChunk(Path("plan.pdf"), 1, "tekst", 1, ["test"])],
        model="qwen3:8b",
        base_url="http://ollama.test",
    )

    assert result.summary == "Kokkuvõte"
    assert len(calls) == 2


def test_ollama_http_error_is_unavailable(monkeypatch):
    def fake_post(*args, **kwargs):
        raise httpx.ConnectError("no server")

    monkeypatch.setattr(llm.httpx, "post", fake_post)

    with pytest.raises(llm.LLMUnavailable):
        llm.analyze_with_local_llm(
            "Kaupmehe tn 19",
            [TextChunk(Path("plan.pdf"), 1, "tekst", 1, ["test"])],
        )


def test_detail_plan_analysis_api_uses_highest_overlap_and_returns_json(monkeypatch):
    parcel = Parcel(
        gpd.GeoDataFrame(
            [{"l_aadress": "Kaupmehe tn 19", "geometry": Point(0, 0)}],
            crs="EPSG:3301",
        )
    )
    expected = DetailPlanAnalysisResponse(
        status=AnalysisStatus.LLM_UNAVAILABLE,
        meta=DetailPlanMeta(address="Kaupmehe tn 19"),
        sections=analyzer.default_sections(),
        setup_issues=["Ollama analysis unavailable"],
    )

    monkeypatch.setattr(
        api, "find_parcel_by_cadastre_code", lambda cadastre_code: parcel
    )
    monkeypatch.setattr(
        api,
        "highest_overlap_detail_plan",
        lambda parcel: {"sysid": "1", "failid": "https://example.test/files"},
    )
    monkeypatch.setattr(
        api,
        "analyze_detail_plan",
        lambda detail_plan, address, force_refresh=False: expected,
    )

    response = api.return_detail_plan_analysis(
        type="cadastre_code",
        searchable="123",
    )

    assert response["status"] == "llm_unavailable"
    assert response["meta"]["address"] == "Kaupmehe tn 19"


def test_detail_plan_analysis_api_returns_404_when_no_detail_plan(monkeypatch):
    parcel = Parcel(
        gpd.GeoDataFrame(
            [{"l_aadress": "Kaupmehe tn 19", "geometry": Point(0, 0)}],
            crs="EPSG:3301",
        )
    )
    monkeypatch.setattr(api, "find_parcel_by_address", lambda address: parcel)
    monkeypatch.setattr(api, "highest_overlap_detail_plan", lambda parcel: None)

    with pytest.raises(HTTPException) as exc_info:
        api.return_detail_plan_analysis(type="address", searchable="Kaupmehe tn 19")

    assert exc_info.value.status_code == 404
