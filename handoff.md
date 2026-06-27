# Golden Case Test Set Handoff

## Goal

Create a small, durable golden regression test set for the detail-plan PDF analyzer. The immediate purpose is to catch cases where the regex layer confidently returns a wrong value, especially from table rows, address numbers, neighboring parcels, existing-building context, or repeated values.

The LLM resolver should not become a broad parser. Regex/cadastre/derived extraction should produce candidate values and evidence. The LLM should only resolve or reject ambiguous candidates from supplied evidence.

## Current State

The analyzer pipeline is documented in `AGENT.md`. Important current files:

- `backend/detailplan_analyzer/rules.py`: regex specs, candidate scoring, cadastre enrichment, derived enrichment.
- `backend/detailplan_analyzer/llm_resolver.py`: local LLM resolver after regex extraction.
- `backend/detailplan_analyzer/analyzer.py`: orchestration and resolver opt-in.
- `backend/detailplan_analyzer/models.py`: response/candidate schema.
- `backend/tests/test_detailplan_analyzer.py`: current unit/regression tests.
- `scripts/run_sample_detailplan_regex_analysis.py`: samples detail plans and writes result JSON.
- `scripts/run_detailplan_llm_resolver.py`: runs the local LLM resolver from address, cadastre code, sample size, local PDF, or result JSON.

The LLM resolver currently appends `source_type="llm"` candidates and can apply them to `ExtractedField.value`, but it should remain secondary. It should not compensate for bad regex captures like address number `13`.

## Known Bad Case: Sinilille tn 13

Use this as the first golden case.

Observed wrong outputs:

- `taisehitus_pct`
  - Current wrong value: `20.0`
  - Evidence line: `Max täisehituse % 20% 16% 16%`
  - Expected behavior: do not auto-fill `20` just because it is first. This is a multi-value table row. For the selected parcel/address the expected value is likely `16%`, but verify from parcel/detail-plan context before locking the golden expected value.

- `katusekalle`
  - Current wrong value: `"13"`
  - Evidence line: `Katusekalle:Sinililletn,13 0° - 40° ...`
  - Expected value for `Sinilille tn 13`: `0-40`
  - Root issue: regex captures the address number instead of the roof-pitch range.

- `hoonete_arv`
  - Current wrong value: `13`
  - Evidence line: `Hoonete arv krundil: Sinilille tn.13— 1 elamu ja 2 abihoonet, Sinilille tn,13a — 1 elamu`
  - Expected value for `Sinilille tn 13`: `3`
  - Root issue: regex captures the address number instead of summing/selecting building-count evidence.

## Recommended Test Strategy

Start with fixture-based golden tests, not snapshot tests of entire response JSON. Full snapshots will be too brittle because candidates, scores, and metadata may legitimately change.

Create a compact fixture format such as:

```json
[
  {
    "id": "sinilille_tn_13",
    "type": "address",
    "searchable": "Sinilille tn 13",
    "expected": {
      "taisehitus_pct": {
        "value": 16.0,
        "unit": "%"
      },
      "katusekalle": {
        "value": "0-40",
        "unit": "degrees"
      },
      "hoonete_arv": {
        "value": 3,
        "unit": null
      }
    }
  }
]
```

Prefer address or cadastre-code inputs over local PDF paths so the test mirrors the real user flow:

1. Find parcel in cadastre data.
2. Select highest-overlap detail plan.
3. Pass parcel attributes into analysis.
4. Assert selected fields.

If tests need to avoid network/OCR in CI, cache or fixture the PDF/page text separately, but keep the golden case definition tied to parcel/detail-plan identity.

## First Implementation Steps

1. Confirm the exact selected parcel/detail-plan for `Sinilille tn 13`.
   - Use `scripts/run_detailplan_llm_resolver.py --address "Sinilille tn 13" --max-fields 0 --output /tmp/sinilille_selection.json`.
   - Inspect `meta.detail_plan`, `meta.parcel_context`, selected PDFs, and field evidence.

2. Add a fixture file.
   - Suggested path: `backend/tests/fixtures/detailplan_golden_cases.json`.
   - Keep the fixture small and human-editable.
   - Include only fields with known expected answers.

3. Add a golden test helper.
   - Resolve address/cadastre from local GPKGs.
   - Run deterministic analysis with `enable_llm_resolver=False` first.
   - Assert expected field values and units.
   - Mark the initial Sinilille case as failing only if the workflow supports expected failures; otherwise fix the regex before merging the test.

4. Fix regex/candidate scoring for the failing fields.
   - `katusekalle`: require a roof-pitch-like value/range after the label; do not accept address numbers adjacent to `tn`, `tn.`, or street names.
   - `hoonete_arv`: reject address-number captures; prefer patterns with explicit building nouns, e.g. `1 elamu ja 2 abihoonet`.
   - `taisehitus_pct`: downrank or review evidence lines with multiple percentages unless selected parcel/column context is clear.

5. Add deterministic ambiguity flags.
   - Multi-value line/table row.
   - Address-like number near captured value.
   - Multiple parcel labels in one evidence context.
   - Existing/neighborhood/reference-plan context.

6. Only after regex candidates are sane, expand LLM review policy.
   - Strong, clean single regex result: keep deterministic.
   - Strong but flagged result: do not auto-fill or mark for LLM verification.
   - Weak/conflicting candidates: LLM can resolve from candidates.
   - Cadastre-backed `kasutusotstarve`/`omandivorm`: keep deterministic.

## Acceptance Criteria For The First Golden Case

For `Sinilille tn 13`, the deterministic analyzer should no longer return:

- `taisehitus_pct = 20.0` from `20% 16% 16%` without review.
- `katusekalle = "13"` from an address.
- `hoonete_arv = 13` from an address.

Preferred final behavior:

- If regex can confidently identify the selected parcel values:
  - `taisehitus_pct = 16.0`
  - `katusekalle = "0-40"`
  - `hoonete_arv = 3`
- If it cannot identify the selected parcel deterministically:
  - leave `value = null`
  - keep ranked candidates/evidence
  - add `needs_review`
  - let the LLM resolver decide only from supplied candidate/context evidence.

## Useful Commands

Run the current deterministic analyzer sample:

```bash
poetry run python scripts/run_sample_detailplan_regex_analysis.py 5 --seed 42 --overwrite
```

Run LLM resolver from a real parcel/address flow:

```bash
poetry run python scripts/run_detailplan_llm_resolver.py \
  --address "Sinilille tn 13" \
  --max-fields 0 \
  --output /tmp/sinilille_selection.json
```

Run analyzer tests:

```bash
poetry run pytest backend/tests/test_detailplan_analyzer.py
```

Run all backend tests:

```bash
poetry run pytest backend/tests
```

## Guardrails

- Do not treat `data/detail_downloads` generated outputs as source changes.
- Do not make the LLM parse whole pages/PDFs by default.
- Do not broaden LLM verification to every accepted regex field until golden tests exist.
- Keep regex/cadastre extraction usable without importing or initializing an LLM client.
- Add new abstractions only if they make fixture loading or golden assertions simpler.
