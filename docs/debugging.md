# Debugging

## Reading a failure

Every failure is attributable to exactly one responsibility and one stage
(`collect_automatic` / `parse_manual_input` / `normalize` / `validate`), with a structured
`error_code` — see the **Debugging** UI page or `cli.py diagnose --run-id <id>`. The error codes
match the master prompt's own list (`SOURCE_HTTP_403`, `FILE_MISSING`, `PARSER_NO_ROWS`,
`WORKBOOK_LABEL_MISMATCH`, `PDF_PAGE_COUNT_MISMATCH`, etc.) — grep `responsibilities/*.py` for a
given code to find exactly where it's raised.

```powershell
python -m cash_equivalents_mvp.cli diagnose --run-id <run_id>
```

prints every responsibility's status, then every structured error with its stage, message, and
`suggested_action`.

## Sanitized tracebacks

`responsibilities/base.py: _sanitize_traceback()` captures the exception traceback text (never
local variable values, which could contain source payloads) and truncates to the last 4000
characters — enough to find the failing line without risking a credential or full-document leak
in the stored error record.

## The debug bundle

**Debugging → Generate debug bundle** (or read `local_data/runs/<run_id>/` directly) zips
responsibility states, structured errors, validation findings, and environment info
(Python version, platform, detected renderer). It intentionally excludes source file contents and
raw workbook dumps.

## Common failure patterns and what they mean

| Symptom | Likely cause | Where to look |
|---|---|---|
| A collector is stuck on `MANUAL_REQUIRED` every run | Its source needs the IG VPN (`money_market`, `hisa`, `gic_rates`'s SharePoint path) | `docs/source_inventory.md`, `docs/manual_fallbacks.md` |
| `workbook_rendering` fails with `EXCEL_NOT_INSTALLED` | Neither Excel nor LibreOffice detected | `python -m cash_equivalents_mvp.cli doctor` |
| `WORKBOOK_LABEL_MISMATCH` | The template's label text near a target cell doesn't match what the mapping expects — template layout may have changed | `config/workbook_map_en.yaml` / `_fr.yaml`, `docs/workbook_mapping.md` |
| `WORKBOOK_MAPPING_INVALID` / a provider "unmatched" warning | A provider code in the source no longer appears in the destination workbook's scan window | `reporting/mappings.py: _write_gic_block` / `write_hisa` |
| `PDF_PAGE_COUNT_MISMATCH` (not 7) | A sheet was added/removed from the template's visible set, or `Data Lists` started being exported | `responsibilities/pdf_export.py: REPORT_SHEET_ALIASES` |
| `BILINGUAL_PARITY_FAILED` | EN and FR ended up with different values for the same underlying rate — since both are written from one canonical `Decimal` in the same pass, this points at a mapping-config bug, not a data bug | `validation/bilingual.py`, `config/workbook_map_fr.yaml` |
| `TBILL_TERM_DAY_MISMATCH` | A T-bill's maturity date is before the report date — check the source PDF is current, or that the report date is right | `responsibilities/treasury_bills.py` |

## Running the test suite for diagnosis

```powershell
pytest tests/ -q --tb=short           # full suite
pytest tests/unit -q                   # fast, no source_material or Excel needed
pytest tests/regression -q             # historical fixture checks
pytest tests/integration -q            # real Excel COM run (slow, ~1-2 min)
```

`tests/conftest.py: requires_source_material` auto-skips anything needing `source_material/` if
it's not present; `tests/integration/test_full_pipeline_integration.py`'s `requires_renderer`
auto-skips if neither Excel nor LibreOffice is available. Neither ever requires internet access.

`local_data/test_results/test_summary.json` (regenerate with
`python scripts/generate_test_summary.py` after a `pytest --junitxml=...` run) groups any failures
by responsibility and test type.
