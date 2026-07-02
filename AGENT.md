# Detail-Plan PDF Analyzer Handoff

## Project Purpose
This project analyzes Estonian detail-plan PDFs and extracts parcel/building-right fields for a selected parcel/detail plan. The current system downloads/caches PDFs, OCRs when needed, extracts normalized page text, selects relevant evidence chunks, runs regex/cadastre/derived extraction, and returns a structured JSON response through `/api/detail-plan-analysis`. An optional LLM-assisted resolver can verify unresolved regex candidates when enabled.

## Current Pipeline Architecture
Main orchestration lives in `backend/detailplan_analyzer/analyzer.py`.

Flow:
1. API receives `type` + `searchable` in `backend/api/api.py`.
2. Parcel is found by address or cadastre code.
3. Highest-overlap detail plan is selected.
4. `analyze_detail_plan()` downloads/caches relevant PDFs.
5. `analyze_pdfs()` checks OCR runtime, prepares PDFs, extracts/caches page text.
6. Page-level chunks are selected via `select_relevant_chunks()`.
7. Field-specific evidence windows are added via `select_field_evidence_chunks()`.
8. `extract_building_rights()` runs regex extraction, parcel/cadastre enrichment, and derived checks.
9. Response is `DetailPlanAnalysisResponse` with `meta`, `building_right.fields`, `sources`, and `setup_issues`.

Important files:
- `backend/detailplan_analyzer/analyzer.py`: high-level orchestration.
- `backend/detailplan_analyzer/extraction.py`: OCR/text extraction, page cache, chunk/window selection.
- `backend/detailplan_analyzer/rules.py`: compatibility facade for older imports.
- `backend/detailplan_analyzer/rule_specs.py`: field specs, regex patterns, and parsers.
- `backend/detailplan_analyzer/rule_engine.py`: candidate generation and field selection orchestration.
- `backend/detailplan_analyzer/candidate_scoring.py`: candidate scoring, ranking, and direct-fill gating.
- `backend/detailplan_analyzer/address_scoped.py`: selected-address table/window extraction.
- `backend/detailplan_analyzer/enrichment.py`: cadastre and derived enrichment.
- `backend/detailplan_analyzer/addressing.py`: selected-address parsing and matching helpers.
- `backend/detailplan_analyzer/models.py`: Pydantic response/candidate/evidence schema.
- `backend/detailplan_analyzer/pdfs.py`: download/OCR/cache helpers.
- `backend/tests/test_detailplan_analyzer.py`: current regression coverage.
- `scripts/run_sample_detailplan_regex_analysis.py`: batch sample analysis to generate `data/detail_downloads/<id>/result.json`.
- `scripts/run_detailplan_regex_analysis.py`: local single-PDF entrypoint.

Production data files are expected in `data/` with descriptive names:
`cadastre.gpkg`, `detail_plans.gpkg`, `points_of_interest.gpkg`,
`noise_areas.gpkg`, `heritage_points.gpkg`, `land_restrictions.gpkg`,
`noise_vector_tiles/`, and `default_poi_settings.json`. Cadastre vector tiles
are generated from `data/cadastre.gpkg` with `scripts/build_vector_tiles.sh` into
ignored `data/cadastre_vector_tiles/`; do not commit the `.pbf` tile tree.
Runtime PDF/OCR caches live under `data/detail_downloads/`; local user settings
are written to `data/user_poi_settings.json`. Legacy/sample datasets belong in
ignored `test_data/`.

## Current Schema
Each field is an `ExtractedField`:
- `key`, `label`, `value`, `unit`, `confidence`, `source_type`, `evidence`
- `candidates: list[RegexCandidate]`
- `needs_review: list[ReviewItem]`

Each candidate has:
- `field_key`, `label`, `value`, `raw_value`, `unit`
- `confidence`, `source_type`, `pattern_name`
- `evidence: {pdf, page, text}` where `text` is the matched line/span
- LLM-ready metadata: `rank`, `score`, `quality`, `reasons`, `flags`, `context`

`context` is the surrounding local window, not the whole page. `evidence.text` should remain the directly cited matched text. Do not lose `pdf`/`page`.

## Regex Candidate Generation And Ranking
Field specs are in `FIELD_SPECS` in `rule_specs.py` and are re-exported from `rules.py`. Current fields include:
- `krundi_pind_m2`
- `taisehitus_pct`
- `brutopind_m2`
- `ehitusalune_pind_m2`
- `lubatud_korrused`
- `hoonete_lubatud_korgused_m`
- `hoonete_arv`
- `katusekalle`
- `tulepusivusklass`

Regex runs over page chunks and field-specific windows. If a `TextChunk.field_key` is set, it only applies to that field. Candidates are scored using pattern confidence plus context boosts/penalties. Strong contexts include terms like `ehitusõigus`, `hoonestustingimused`, `krundi ehitusõigus`, `põhinäitajad`, `lubatud`, `suurim`, `maksimaalne`. Weak contexts include `olemasolev`, `kontaktvöönd`, `naaber`, `piirdeaed`, `servituut`, `sisukord`, `visioon`, plus field-specific penalties.

Acceptance policy:
- Strong single/non-conflicting top candidates fill `field.value`.
- Weak or conflicting candidates leave `field.value = null`, preserve ranked candidates, and add `needs_review`.
- This is intentional: uncertain regex should not guess. The optional LLM resolver can resolve these review fields when enabled.

Special handling:
- Floors require a digit or Estonian number word; obvious descriptive false positives are rejected.
- Underground floor evidence is flagged and not treated as normal above-ground floors.
- Fence/setback heights are preserved as weak candidates but should not direct-fill building height.
- Derived enrichment checks coverage/footprint and safe building-count derivation.

## Parcel/Cadastre Context
Parcel context is compacted by `compact_parcel_context()` from keys:
`tunnus`, `pindala`, `siht1..3`, `so_prts1..3`, `omvorm`.

Current behavior:
- `krundi_pind_m2`: cadastre area is always added as a candidate. It overrides PDF area when the mismatch is significant and adds a review note.
- Land-use and ownership are not analyzer fields; they remain available from parcel attributes under `Aadress`.
- Derived candidates have `source_type="derived"` and should be treated as deterministic but lower confidence.

## Problematic Regex-Only Fields
Most likely to need LLM resolution:
- `lubatud_korrused`: table layouts, multiple buildings, above/below-ground distinctions, descriptive text near “korruselisus”.
- `hoonete_lubatud_korgused_m`: multiple relative/absolute heights, fence/setback heights, roof/ridge/eaves distinctions.
- `taisehitus_pct`, `ehitusalune_pind_m2`, `brutopind_m2`: multiple plots/buildings in one plan, tables, neighboring parcels.
- `katusekalle`: OCR/table formatting such as compact ranges.
- `tulepusivusklass`: multiple codes or generic fire-safety references.

## LLM Resolver Design
The LLM resolver runs as a resolver/verification layer after deterministic extraction, not as a replacement.

When to call:
- Only for fields with `value is null` and either `needs_review` or candidates exist.
- Optionally for high-risk accepted fields if a verification mode is enabled, but default should preserve strong deterministic regex behavior.
- Do not call for land-use or ownership; they are parcel attributes, not analyzer fields.
- Do not call for setup errors/no extracted text.

LLM input should be compact and field-scoped:
- Field key, label, expected unit/type.
- Current field object: `value`, `candidates`, `needs_review`.
- Ranked candidates with `rank`, `value`, `raw_value`, `score`, `quality`, `flags`, `evidence`, `context`.
- Parcel context from `meta.parcel_context`.
- Possibly relevant neighboring fields for consistency checks, e.g. area + coverage + footprint.
- Do not send whole PDFs or full pages by default. Use candidate contexts and field evidence windows. Only expand to a page snippet if candidates are missing but the field is required.

LLM output should be structured:
- `field_key`
- `value` or `null`
- `unit`
- `confidence`
- `decision`: e.g. `accepted_candidate`, `corrected_candidate`, `no_answer`, `conflict`
- `source_type`: `llm`
- `evidence`: exact `pdf`, `page`, and short quoted/normalized text from supplied evidence
- `candidate_rank` if selecting an existing candidate
- `reason`
- optional `flags` / `needs_review`

Preserve citations:
- The LLM must choose from supplied evidence where possible.
- If it corrects a candidate, it still needs a source span from `context` or `evidence.text`.
- Avoid outputs with no page/pdf unless explicitly derived or unavailable.

## Constraints
- LLM failures must leave deterministic regex/cadastre/derived results intact.
- LLM outputs require strict validation/coercion per field type/unit.
- Tests should mock LLM providers and avoid network dependencies.
- Generated `data/detail_downloads` outputs, `data/cadastre_vector_tiles`, and `data/user_poi_settings.json` are ignored and should not be treated as source changes.
- Keep regex behavior stable: high-confidence, non-conflicting deterministic values should not be overwritten by LLM unless a deliberate verification policy says so.
