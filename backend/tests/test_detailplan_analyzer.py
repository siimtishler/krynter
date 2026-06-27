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
    SourceType,
)
from backend.detailplan_analyzer.llm_resolver import (
    LLMFieldResolution,
    LLMResolverDecision,
    OllamaResolverProvider,
    apply_resolution,
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


def test_regex_extracts_roof_pitch_alternatives_and_kinnistu_size(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=4,
        text=(
            "Raudtee tn 109 kinnistu on suurusega 1421 m². "
            "Maksimaalseks täisehituseks võib olla 17%\n"
            "Planeeritud kruntide sihtotstarve ja suurus:\n"
            "Raudtee tn 109 krundile antud maa kasutamise sihtotstarve "
            "(elamumaa) ei näe ette\n"
            "Katusekalle\n"
            "0-13 ˚ või 45-48\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    fields = result.fields

    assert fields["krundi_pind_m2"].value == 1421
    assert fields["kasutusotstarve"].value == "elamumaa"
    assert fields["katusekalle"].value == "0-13 või 45-48"


def test_regex_preserves_all_candidates_and_marks_conflict(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text="Täisehitus 25%\nTäisehitus 30%\n",
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["taisehitus_pct"]

    assert field.value is None
    assert [candidate.value for candidate in field.candidates] == [25, 30]
    assert field.candidates[0].rank == 1
    assert field.candidates[0].quality == "strong"
    assert field.candidates[0].score is not None
    assert field.needs_review


def test_strong_single_candidate_fills_direct_value(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text="Krundi ehitusõigus\nLubatud suurim täisehitus 25%\n",
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["taisehitus_pct"]

    assert field.value == 25
    assert field.candidates[0].quality == "strong"
    assert field.candidates[0].context


def test_floor_false_positive_is_not_direct_value(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=3,
        text=(
            "Kontaktvööndis on erinevaid kõrgusi ja mahte.\n"
            "Suurem korruselisus avaks huvitavad vaated kõikidesse ilmakaartesse.\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["lubatud_korrused"]

    assert field.value is None
    assert field.candidates == []
    assert field.needs_review


def test_table_like_floor_candidate_is_kept_and_selected(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=3,
        text=(
            "Krundi ehitusõigus\n"
            "Hoonete suurim lubatud maapealne korruselisus\n"
            "4 (hoone I)\n"
            "Hoonete suurim lubatud maa-alune korruselisus\n"
            "-1 (hoone I)\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["lubatud_korrused"]

    assert field.value == "4 (hoone I)"
    assert any(candidate.raw_value == "4 (hoone I)" for candidate in field.candidates)
    assert any(
        "underground_floor_context" in candidate.flags for candidate in field.candidates
    )


@pytest.mark.parametrize(
    "text",
    [
        "Piirdeaia maksimaalne kõrgus maapinnast on 1,5 m.\n",
        "Krundid piirata traatvõrkaiaga (kõrgus kuni 2,0m).\n",
    ],
)
def test_fence_height_candidate_is_not_direct_building_height(tmp_path, text):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=5,
        text=text,
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["hoonete_lubatud_korgused_m"]

    assert field.value is None
    assert field.candidates
    assert field.candidates[0].quality == "weak"
    assert "not_building_height" in field.candidates[0].flags


def test_maximum_building_height_beats_fence_height_candidate(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=5,
        text=(
            "Paariselamu maksimaalne kõrgus olemasolevast maapinnast "
            "katuseharjale on 8,5m.\n"
            "Piire: puidust või võrgust, kõrgusega kuni 1,5m.\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])
    field = result.fields["hoonete_lubatud_korgused_m"]

    assert field.value == "8,5"
    assert any(candidate.value == "8,5" for candidate in field.candidates)
    fence_candidates = [
        candidate for candidate in field.candidates if candidate.value == "1,5"
    ]
    assert fence_candidates
    assert fence_candidates[0].quality == "weak"
    assert "not_building_height" in fence_candidates[0].flags


def test_cadastre_context_fills_missing_area_land_use_and_ownership():
    result = extract_building_rights(
        [],
        parcel_attributes={
            "tunnus": "78404:407:0017",
            "pindala": 1424,
            "siht1": "ELAMUMAA",
            "so_prts1": 100,
            "omvorm": "Eraomand",
        },
    )
    fields = result.fields

    assert fields["krundi_pind_m2"].value == 1424
    assert fields["krundi_pind_m2"].source_type == "cadastre"
    assert fields["kasutusotstarve"].value == "elamumaa 100%"
    assert fields["omandivorm"].value == "Eraomand"


def test_cadastre_land_use_and_ownership_skip_regex_when_context_exists(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text=("Sihtotstarve: on elamumaa.\n" "Omandivorm: avalik tekst\n"),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights(
        [chunk],
        parcel_attributes={
            "siht1": "ELAMUMAA",
            "so_prts1": 75,
            "siht2": "ARIMAA",
            "so_prts2": 25,
            "omvorm": "Eraomand",
        },
    )

    assert result.fields["kasutusotstarve"].value == "elamumaa 75%, arimaa 25%"
    assert result.fields["kasutusotstarve"].source_type == "cadastre"
    assert len(result.fields["kasutusotstarve"].candidates) == 1
    assert result.fields["kasutusotstarve"].needs_review == []
    assert result.fields["omandivorm"].value == "Eraomand"
    assert result.fields["omandivorm"].source_type == "cadastre"


def test_pdf_area_is_preferred_when_close_to_cadastre_and_derived_values_verify(
    tmp_path,
):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=3,
        text=(
            "Raudtee tn 109 kinnistu on suurusega 1421 m². "
            "Maksimaalseks täisehituseks võib olla 17%\n"
            "ehitusalune pind võib olla kuni 241 m².\n"
        ),
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights(
        [chunk],
        parcel_attributes={"pindala": 1424},
    )
    fields = result.fields

    assert fields["krundi_pind_m2"].value == 1421
    assert fields["krundi_pind_m2"].source_type == "regex"
    assert any(
        candidate.source_type == "cadastre"
        for candidate in fields["krundi_pind_m2"].candidates
    )
    assert fields["ehitusalune_pind_m2"].value == 241
    assert not fields["ehitusalune_pind_m2"].needs_review
    assert not fields["taisehitus_pct"].needs_review


def test_missing_footprint_and_coverage_are_derived(tmp_path):
    footprint_missing = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text="Krundi pind 1000 m²\nTäisehitus 25%\n",
        score=10,
        reasons=["test"],
    )
    footprint_result = extract_building_rights([footprint_missing])

    assert footprint_result.fields["ehitusalune_pind_m2"].value == 250
    assert footprint_result.fields["ehitusalune_pind_m2"].source_type == "derived"

    coverage_missing = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=2,
        text="Krundi pind 1000 m²\nEhitusalune pind 250 m²\n",
        score=10,
        reasons=["test"],
    )
    coverage_result = extract_building_rights([coverage_missing])

    assert coverage_result.fields["taisehitus_pct"].value == 25
    assert coverage_result.fields["taisehitus_pct"].source_type == "derived"


def test_building_count_derives_from_safe_floor_building_type_text(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=4,
        text="Korruselisus\nElamu 2, abihoone 1\n",
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])

    assert result.fields["lubatud_majade_ehitamise_arv"].value == 2
    assert result.fields["lubatud_majade_ehitamise_arv"].source_type == "derived"
    assert result.fields["hoonete_arv"].value == 2


def test_building_count_is_not_derived_from_ambiguous_floor_alternatives(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=2,
        text="Korruselisus: väikeelamul 2, kortermajal kuni 3\n",
        score=10,
        reasons=["test"],
    )

    result = extract_building_rights([chunk])

    assert result.fields["lubatud_majade_ehitamise_arv"].value is None
    assert result.fields["hoonete_arv"].value is None


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
    monkeypatch.setattr(
        analyzer.config,
        "detail_plan_llm_resolver_enabled",
        False,
    )

    class FailingProvider:
        def resolve_field(self, request):
            raise AssertionError("LLM resolver should not be called by default")

    response = analyzer.analyze_pdfs(
        [pdf_path],
        "Kaupmehe tn 19",
        llm_provider=FailingProvider(),
    )

    assert response.building_right.fields["krundi_pind_m2"].value == 1000
    assert response.building_right.fields["taisehitus_pct"].value == 25
    candidate_dump = response.model_dump(mode="json")["building_right"]["fields"][
        "taisehitus_pct"
    ]["candidates"][0]
    assert candidate_dump["rank"] == 1
    assert candidate_dump["quality"] == "strong"
    assert candidate_dump["score"] is not None
    assert candidate_dump["context"]
    assert "llm_status" not in response.meta.model_dump()
    assert "analysis_id" not in response.meta.model_dump()


def test_enabled_llm_resolver_applies_accepted_candidate(monkeypatch, tmp_path):
    pdf_path = tmp_path / "plan.pdf"
    page = PageText(
        pdf_path=pdf_path,
        page=2,
        text=(
            "Kaupmehe tn 19 detailplaneering\n"
            "Krundi pind 1000 m2\n"
            "Täisehitus 25%\n"
            "Täisehitus 30%\n"
        ),
        normalized_text=(
            "Kaupmehe tn 19 detailplaneering\n"
            "Krundi pind 1000 m2\n"
            "Täisehitus 25%\n"
            "Täisehitus 30%\n"
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

    class FakeProvider:
        def __init__(self):
            self.calls = []

        def resolve_field(self, request):
            self.calls.append(request)
            if request.field_key != "taisehitus_pct":
                return LLMFieldResolution(
                    field_key=request.field_key,
                    decision=LLMResolverDecision.NO_ANSWER,
                    confidence=0.0,
                    reason="No supplied evidence.",
                )
            return LLMFieldResolution(
                field_key="taisehitus_pct",
                decision=LLMResolverDecision.ACCEPTED_CANDIDATE,
                value=request.candidates[0].value,
                unit="%",
                confidence=0.91,
                evidence=request.candidates[0].evidence,
                candidate_rank=request.candidates[0].rank,
                reason="Top candidate is the applicable parcel value.",
            )

    provider = FakeProvider()

    response = analyzer.analyze_pdfs(
        [pdf_path],
        "Kaupmehe tn 19",
        enable_llm_resolver=True,
        llm_provider=provider,
    )

    field = response.building_right.fields["taisehitus_pct"]
    assert field.value == 25
    assert field.source_type == SourceType.LLM
    assert field.evidence == field.candidates[0].evidence
    assert field.needs_review == []
    assert field.candidates[-1].source_type == SourceType.LLM
    assert field.candidates[-1].pattern_name == "llm_accepted_candidate"
    assert "krundi_pind_m2" not in {call.field_key for call in provider.calls}
    assert not any(
        review.key == "taisehitus_pct"
        for review in response.building_right.needs_review
    )


def test_llm_resolver_skips_parcel_backed_land_use_and_ownership(
    monkeypatch,
    tmp_path,
):
    pdf_path = tmp_path / "plan.pdf"
    page = PageText(
        pdf_path=pdf_path,
        page=1,
        text="Täisehitus 25%\nTäisehitus 30%\n",
        normalized_text="Täisehitus 25%\nTäisehitus 30%\n",
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

    class RecordingProvider:
        def __init__(self):
            self.field_keys = []

        def resolve_field(self, request):
            self.field_keys.append(request.field_key)
            return LLMFieldResolution(
                field_key=request.field_key,
                decision=LLMResolverDecision.NO_ANSWER,
                confidence=0.0,
            )

    provider = RecordingProvider()

    response = analyzer.analyze_pdfs(
        [pdf_path],
        "Kaupmehe tn 19",
        parcel_attributes={
            "siht1": "ELAMUMAA",
            "so_prts1": 100,
            "omvorm": "Eraomand",
        },
        enable_llm_resolver=True,
        llm_provider=provider,
    )

    assert "kasutusotstarve" not in provider.field_keys
    assert "omandivorm" not in provider.field_keys
    assert response.building_right.fields["kasutusotstarve"].source_type == "cadastre"
    assert response.building_right.fields["omandivorm"].source_type == "cadastre"


def test_invalid_llm_resolution_leaves_regex_field_unchanged(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=1,
        text="Täisehitus 25%\nTäisehitus 30%\n",
        score=10,
        reasons=["test"],
    )
    field = extract_building_rights([chunk]).fields["taisehitus_pct"]

    assert field.value is None
    assert field.needs_review

    assert not apply_resolution(
        field,
        LLMFieldResolution(
            field_key="krundi_pind_m2",
            decision=LLMResolverDecision.ACCEPTED_CANDIDATE,
            value=25,
            unit="%",
            confidence=0.9,
            candidate_rank=1,
        ),
    )
    assert field.value is None
    assert field.source_type is None
    assert field.needs_review

    assert not apply_resolution(
        field,
        LLMFieldResolution(
            field_key="taisehitus_pct",
            decision=LLMResolverDecision.CORRECTED_CANDIDATE,
            value=25,
            unit="%",
            confidence=0.9,
            evidence={
                "pdf": "other.pdf",
                "page": 99,
                "text": "Unsupported evidence",
            },
        ),
    )
    assert field.value is None
    assert field.source_type is None
    assert field.needs_review

    assert not apply_resolution(
        field,
        LLMFieldResolution(
            field_key="taisehitus_pct",
            decision=LLMResolverDecision.ACCEPTED_CANDIDATE,
            value=25,
            unit="%",
            confidence=0.4,
            candidate_rank=1,
        ),
    )
    assert field.value is None
    assert field.source_type is None
    assert field.needs_review


def test_llm_resolution_rejects_non_building_height_candidate(tmp_path):
    chunk = TextChunk(
        pdf_path=tmp_path / "plan.pdf",
        page=14,
        text=(
            "Lubatud koormus kinnistes metall-ladudes kõrgusega 12 m: "
            "4 kuni 6 tn/m2.\n"
        ),
        score=10,
        reasons=["test"],
    )
    field = extract_building_rights([chunk]).fields["hoonete_lubatud_korgused_m"]

    assert field.value is None
    assert field.candidates

    assert not apply_resolution(
        field,
        LLMFieldResolution(
            field_key="hoonete_lubatud_korgused_m",
            decision=LLMResolverDecision.ACCEPTED_CANDIDATE,
            value="12",
            unit="m",
            confidence=0.9,
            candidate_rank=field.candidates[0].rank,
        ),
    )
    assert field.value is None
    assert field.source_type is None
    assert field.needs_review


def test_detail_plan_analysis_api_passes_explicit_llm_flag(monkeypatch):
    captured: dict = {}
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

    monkeypatch.setattr(api, "find_parcel_by_address", lambda address: parcel)
    monkeypatch.setattr(
        api,
        "highest_overlap_detail_plan",
        lambda parcel: {"sysid": "1", "failid": "https://example.test/files"},
    )

    def fake_analyze_detail_plan(
        detail_plan,
        address,
        parcel_attributes=None,
        force_refresh=False,
        enable_llm_resolver=None,
    ):
        captured["enable_llm_resolver"] = enable_llm_resolver
        return expected

    monkeypatch.setattr(api, "analyze_detail_plan", fake_analyze_detail_plan)

    response = api.return_detail_plan_analysis(
        type="address",
        searchable="Kaupmehe tn 19",
        enable_llm_resolver=True,
    )

    assert response["status"] == "partial"
    assert captured["enable_llm_resolver"] is True


def test_ollama_provider_parses_json_response(monkeypatch):
    captured: dict = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "response": (
                    '{"field_key":"taisehitus_pct",'
                    '"decision":"accepted_candidate",'
                    '"value":25,'
                    '"unit":"%",'
                    '"confidence":0.88,'
                    '"source_type":"llm",'
                    '"candidate_rank":1,'
                    '"reason":"Selected from evidence."}'
                )
            }

    def fake_post(url, json, timeout):
        captured["url"] = url
        captured["json"] = json
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(
        "backend.detailplan_analyzer.llm_resolver.httpx.post", fake_post
    )

    provider = OllamaResolverProvider(
        base_url="http://ollama.test",
        model="qwen3:8b",
        timeout_s=12,
    )
    resolution = provider.resolve_field(
        request=provider_request("taisehitus_pct", "Täisehitus", "%")
    )

    assert captured["url"] == "http://ollama.test/api/generate"
    assert captured["json"]["model"] == "qwen3:8b"
    assert captured["json"]["format"] == "json"
    assert captured["timeout"] == 12
    assert resolution.field_key == "taisehitus_pct"
    assert resolution.decision == LLMResolverDecision.ACCEPTED_CANDIDATE
    assert resolution.source_type == SourceType.LLM


def provider_request(field_key: str, label: str, unit: str | None):
    from backend.detailplan_analyzer.llm_resolver import LLMFieldRequest

    return LLMFieldRequest(field_key=field_key, label=label, unit=unit)


def test_detail_plan_analysis_api_uses_highest_overlap_and_returns_json(monkeypatch):
    captured: dict = {}
    parcel = Parcel(
        gpd.GeoDataFrame(
            [
                {
                    "l_aadress": "Kaupmehe tn 19",
                    "pindala": 1000,
                    "siht1": "ELAMUMAA",
                    "geometry": Point(0, 0),
                }
            ],
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

    def fake_analyze_detail_plan(
        detail_plan,
        address,
        parcel_attributes=None,
        force_refresh=False,
    ):
        captured["parcel_attributes"] = parcel_attributes
        return expected

    monkeypatch.setattr(api, "analyze_detail_plan", fake_analyze_detail_plan)

    response = api.return_detail_plan_analysis(
        type="cadastre_code",
        searchable="123",
    )

    assert response["status"] == "partial"
    assert response["meta"]["address"] == "Kaupmehe tn 19"
    assert "llm_status" not in response["meta"]
    assert captured["parcel_attributes"]["pindala"] == 1000


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
