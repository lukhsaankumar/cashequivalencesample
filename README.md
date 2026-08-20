# Cash and Cash Equivalents — Automated Reporting MVP

A local, code-first application that produces the weekly English and French Cash and Cash
Equivalents reporting package: collects rates from public and (where reachable) internal sources,
lets you supply anything it couldn't reach automatically, populates and recalculates the approved
EN/FR Excel templates through Microsoft Excel, exports 7-page bilingual PDFs, and packages
everything for download — never sending anything automatically.

See `docs/architecture.md` for how the pieces fit together, `docs/source_inventory.md` /
`docs/workbook_mapping.md` for exactly what was verified against the real source files, and
`ASSUMPTIONS.md` for every judgment call made along the way.

## Installation

Requires Python 3.11+ (developed and tested on 3.12) and, on Windows, Microsoft Excel for
workbook recalculation and PDF export.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev,windows]"
```

`pywin32` (the `windows` extra) is required for the Excel COM renderer. If Excel isn't installed,
install LibreOffice instead — the app auto-detects whichever is available
(`config/settings.yaml: renderer.preference`), preferring Excel COM.

Run `python -m cash_equivalents_mvp.cli doctor` after installing to confirm the environment is
ready — it checks Python version, every dependency, `source_material/` templates, directory
writability, and renderer availability.

## Windows Excel prerequisites

Excel COM automation (`reporting/excel_com.py`) opens Excel invisibly via `win32com.client`,
forces a full recalculation (`CalculateFullRebuild`), saves, and exports PDF. This requires a
real, licensed Excel installation on the machine running the app — it cannot run headless in a
container without Excel installed. Each COM call runs inside its own `CoInitialize`/
`CoUninitialize` pair so it's safe to call from a background thread.

## LibreOffice fallback

If Excel isn't available, `reporting/libreoffice.py` shells out to `soffice --headless` for
recalculation-on-load and PDF export. It cannot force Excel's "full rebuild" recalculation mode,
so treat it as a genuine fallback, not a perfect substitute — see `docs/architecture.md`.

## Launching the UI and worker

```powershell
streamlit run cash_equivalents_mvp/ui/app.py
```

Opens on `http://localhost:8501`. There is no separate worker process to start — background
execution happens via `orchestration/worker.py`'s thread pool, invoked directly from the UI/CLI;
see `docs/architecture.md` for why a local single-user MVP doesn't need a separate process.

## Starting a run

From the UI: **Dashboard → pick a report date → Create New Run** (or **Create + Run All** to run
every responsibility immediately). From the CLI:

```powershell
python -m cash_equivalents_mvp.cli create-run --report-date 2026-05-11
python -m cash_equivalents_mvp.cli execute --run-id <run_id>
```

Or run the full historical demo end-to-end in one command:

```powershell
python -m cash_equivalents_mvp.cli demo
```

## How automatic collection works

Each responsibility (`responsibilities/*.py`) tries its configured automatic source first —
public HTTP APIs (Bank of Canada, FRED), a watched download folder, or (for the historical demo)
the matching file already in `source_material/`. Sources behind the IG VPN/SSO
(`home.investorsgroup.com`, `digital.lipperweb.com`, `*.sharepoint.com`) are attempted but expected
to fail outside the VPN — see `docs/source_inventory.md`. A failure never crashes the run; it
marks that one responsibility `MANUAL_REQUIRED` and everything independent of it keeps going.

## How manual fallback works

**Manual Uploads and Inputs** (UI page 3) shows only responsibilities that need attention, with
the exact control each one needs — a file uploader for GIC Rates/Treasury Bills/HISA, numeric
fields for Prime/Fed Funds/Money Market. Every override requires a reason, which is stored on
every resulting record (`manually_overridden`, `override_reason`, `override_user`).

## How to resume a run

Submitting a manual input on the Manual Uploads page reruns exactly that responsibility, then
exactly its downstream responsibilities (`orchestration/resume.py: invalidate_downstream`) —
`workbook_rendering → pdf_export → package` if the input feeds the workbook, nothing beyond that.
Everything unrelated (already-successful collectors) is left untouched. The CLI equivalent is
`retry-failed`, which does the same for every currently-failed responsibility.

## How to review output

**Review & Comparison** (page 4) shows current vs. previous week's values, filterable by
category/currency/status. **Validation** (page 5) separates blocking errors from warnings —
warnings (like `HISA_HIGHER_RATE_EXCLUDED` or `FED_RULE_UNCONFIRMED`) don't block the run but are
worth reading before approving.

## How to download files

**Outputs and Downloads** (page 6) lists the EN/FR workbooks, EN/FR PDFs, the unsent `.eml` draft,
and the ZIP package for the selected run, each with a SHA-256 and a real download button.

## How to generate a debug bundle

**Debugging** (page 7) shows the stage timeline and every structured error for the selected run,
and has a **Generate debug bundle** button that zips responsibility states, errors, findings, and
environment info for offline diagnosis.

## Known limitations

- Money Market, HISA, and the SharePoint copy of GIC Rates cannot be automatically retrieved
  outside the IG corporate VPN in this environment — see `ASSUMPTIONS.md`.
- The Fed Funds `UPPER_BOUND` rule and the HISA "highest rate" product selection are both flagged
  `UNCONFIRMED_BUSINESS_RULE` — real business decisions inferred from the historical example, not
  confirmed in writing.
- Bankers' Acceptance and the `Money Market Funds` sheet's competitor comparison table are
  implemented as disabled/manual-only, `BUSINESS_SCOPE_UNCONFIRMED` — see `ASSUMPTIONS.md`.
- The Review page's record-level override form is a visual stub (button disabled) — use the
  Manual Uploads page for the responsibilities that need correcting instead.
- Settings are read-only in the UI; edit `config/*.yaml` and restart to change them.

## Clearing confidential local data

```powershell
Remove-Item -Recurse -Force local_data\runs\*, local_data\uploads\*, local_data\raw_sources\*, local_data\database\*, local_data\logs\*
```

See `SECURITY.md` for the full data-handling policy.

## Tests

```powershell
pytest tests/ -q
pytest --cov=cash_equivalents_mvp --cov-report=term-missing
```

178 tests, all passing (1 appropriately skipped) as of the last full run — unit, responsibility
contract, GIC mapping, fault-injection, historical regression (against the real published May 11
2026 workbook), full end-to-end integration (real Excel COM), and UI smoke tests. No test requires
internet access. See `docs/debugging.md` for how to read a failure.
