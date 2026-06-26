import zipfile
from pathlib import Path

import fitz
import geopandas as gpd
import pytest
from fastapi import HTTPException
from shapely.geometry import Point

from backend.api import api
from backend.detailplan_analyzer import analyzer
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
)
from backend.detailplan_analyzer.pdfs import (
    OCRRuntime,
    cached_plan_pdfs,
    extract_relevant_pdfs,
)
from backend.detailplan_analyzer.rules import extract_building_rights
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


def test_regex_extracts_building_right_fields(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=4,
        text=(
            "Krundi pind 1 200 m²\n"
            "Maakasutuse sihtotstarve: elamumaa, ärimaa\n"
            "Täisehitus 25,5%\n"
            "Brutopind 1 500,5 m2\n"
            "Ehitusalune pind max: 440 m2\n"
            "Korruselisus: väikeelamul 2, kortermajal kuni 3\n"
            "Lubatud eraldiseisvate hoonete arv 3, Mai tn. 2a krundil 2, neist 1 elamu\n"
            "Maksimaalne hoonestuse kõrgus: väikeelamul 9 m\n"
            "Hoone katuse kalle 0-45\n"
            "Hoonete tulepüsivusaste TP-3\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    fields = result.fields

    assert fields["krundi_pind_m2"].value == 1200
    assert fields["taisehitus_pct"].value == 25.5
    assert fields["brutopind_m2"].value == 1500.5
    assert fields["ehitusalune_pind_m2"].value == 440
    assert fields["lubatud_korrused"].value == "väikeelamul 2, kortermajal kuni 3"
    assert fields["lubatud_majade_ehitamise_arv"].value == 3
    assert fields["hoonete_lubatud_korgused_m"].value == "väikeelamul 9 m"
    assert fields["hoonete_arv"].value == 3
    assert fields["kasutusotstarve"].value == "elamumaa, ärimaa"
    assert fields["katusekalle"].value == "0-45"
    assert fields["tulepusivusklass"].value == "TP-3"


def test_regex_korruselisus_does_not_use_height_line_number(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=2,
        text=(
            "Maksimaalne hoonestuse kõrgus: väikeelamul 9 m\n"
            "maapinnast 7\n"
            "Korruselisus: vaikeelamul 2, kortermajal kuni 3\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])

    assert result.fields["lubatud_korrused"].value == (
        "vaikeelamul 2, kortermajal kuni 3"
    )
    assert result.fields["lubatud_korrused"].value != 7


def test_regex_preserves_all_candidates_and_selects_best(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text="Täisehitus 25%\nTäisehitus 30%\n",
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["taisehitus_pct"]

    assert field.value == 25
    assert [candidate.value for candidate in field.candidates] == [25, 30]


def test_analyze_pdfs_returns_direct_regex_response(monkeypatch, tmp_path):
    pdf_path = tmp_path / "plan.pdf"
    page = PageText(
        pdf_path=pdf_path,
        page=3,
        text=(
            "Kaupmehe tn 19 krundi pind 1000 m2\n"
            "Täisehitus 25%\n"
            "Ehitusalune pind 250 m2\n"
            "Korruselisus 2\n"
            "Hoonete arv 1\n"
            "Katuse kalle 0-45\n"
            "Tulepüsivusklass TP-3\n"
        ),
        normalized_text=(
            "Kaupmehe tn 19 krundi pind 1000 m2\n"
            "Täisehitus 25%\n"
            "Ehitusalune pind 250 m2\n"
            "Korruselisus 2\n"
            "Hoonete arv 1\n"
            "Katuse kalle 0-45\n"
            "Tulepüsivusklass TP-3\n"
        ),
    )

    monkeypatch.setattr(analyzer, "check_ocr_runtime", lambda: OCRRuntime([], set()))
    monkeypatch.setattr(
        analyzer,
        "prepare_pdf_for_text",
        lambda raw_pdf, runtime=None, force_refresh=False: (raw_pdf, False),
    )
    monkeypatch.setattr(
        analyzer,
        "extract_pages_cached",
        lambda working_pdf, force_refresh=False: [page],
    )

    response = analyzer.analyze_pdfs([pdf_path], "Kaupmehe tn 19")

    assert response.building_right.fields["krundi_pind_m2"].value == 1000
    assert response.building_right.fields["taisehitus_pct"].value == 25
    assert "llm_status" not in response.meta.model_dump()
    assert "analysis_id" not in response.meta.model_dump()


def test_detail_plan_analysis_api_uses_highest_overlap_and_returns_json(monkeypatch):
    parcel = Parcel(
        gpd.GeoDataFrame(
            [{"l_aadress": "Kaupmehe tn 19", "geometry": Point(0, 0)}],
            crs="EPSG:3301",
        )
    )
    expected = DetailPlanAnalysisResponse(
        status=AnalysisStatus.PARTIAL,
        meta=DetailPlanMeta(address="Kaupmehe tn 19"),
        building_right=analyzer.empty_building_right(),
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

    assert response["status"] == "partial"
    assert response["meta"]["address"] == "Kaupmehe tn 19"
    assert "llm_status" not in response["meta"]


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
        api.return_detail_plan_analysis(
            type="address",
            searchable="Kaupmehe tn 19",
        )

    assert exc_info.value.status_code == 404


def test_detail_plan_analysis_api_returns_400_for_invalid_type():
    with pytest.raises(HTTPException) as exc_info:
        api.return_detail_plan_analysis(type="bad", searchable="Kaupmehe tn 19")

    assert exc_info.value.status_code == 400
