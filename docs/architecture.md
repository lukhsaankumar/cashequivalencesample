# Architecture

## Data flow

```
source_material/ (read-only)  +  live public APIs  +  manual uploads
              |
    8 collector responsibilities  (independent — gic_rates, canada_prime, us_fed_funds,
              |                    money_market, treasury_bills, hisa, template, report_date)
              v
    canonical RateRecord rows, stored in SQLite (Decimal, never float)
              |
    workbook_rendering  — populate EN+FR working copies (openpyxl, cell values only),
              |            then recalculate through Excel COM / LibreOffice
              v
    pdf_export  — export EN+FR to PDF, validate page count / no formula errors
              |
    package  — zip + unsent .eml draft
```

The Excel workbook is the publication source of truth; the PDF is a rendered output of it, never
edited directly. See the master prompt's own framing of this rule — it's the one architectural
constraint every responsibility is built around.

## Why a Responsibility interface

Every business function (`responsibilities/*.py`) implements the same four-stage pipeline
(`collect_automatic` → `normalize` → `validate` → `persist`), orchestrated once by
`responsibilities/base.py: Responsibility.run_automatic()` / `run_manual()`. This buys:

- **Uniform status tracking** — every responsibility's state lives in one `responsibility_state`
  SQLite table, queried the same way by the CLI, the UI, and the orchestrator.
- **Uniform error capture** — every failure becomes a `ResponsibilityError` with a structured
  `error_code`, `stage`, `retryable` flag, and `suggested_action`, not an ad-hoc exception message.
- **Uniform retry policy** — `orchestration/retries.py` retries only responsibilities/errors
  explicitly marked retryable, with backoff, before falling back to `MANUAL_REQUIRED`.
- **A resume story that's correct by construction** — `orchestration/resume.py:
  invalidate_downstream()` walks the static dependency graph (`orchestration/graph.py`), so
  "rerun this and only what depends on it" is a graph query, not a per-responsibility ad-hoc rule.

## Why Workbook Rendering and French Output are one responsibility

The master prompt's dependency graph shows `english_workbook` and `french_workbook` as separate
DAG nodes. Here they're merged into one `workbook_rendering` responsibility. Reasoning: both
languages are written from the *same* canonical `Decimal` in the *same* function call
(`reporting/mappings.py`), formatted differently at write time
(`normalization/percentages.py: french_percent_text` etc.) rather than independently re-derived —
so bilingual numeric parity is structural, not something a downstream reconciliation stage has to
notice went wrong. A dedicated `validation/bilingual.py: check_bilingual_parity()` still re-opens
both saved files and compares actual values as a second line of defense (it caught two real bugs
during development — see `ASSUMPTIONS.md`), but that's a validation step inside the same
responsibility, not a separate DAG node with its own retry/resume semantics that would need to
open/close the same Excel session twice for no benefit.

## Why openpyxl for writes, Excel COM for recalculation

openpyxl can set a cell's `.value` without touching anything else on the sheet — formulas,
conditional formatting, merged cells, print areas, and styles it doesn't explicitly modify are
left exactly as they were. It cannot, however, *recalculate* formulas — cells with cached values
keep their old cached value until something else recalculates the workbook. Excel COM
(`reporting/excel_com.py`) does that: `Workbook.Open` → write is already done by openpyxl at this
point → `Application.CalculateFullRebuild()` → `Save()`. This two-tool split means the write path
never risks Excel accidentally "helping" by reformatting a cell, and the recalculation path never
has to reimplement Excel's formula engine.

## Renderer auto-detection

`reporting/renderer_selection.py: select_renderer()` tries each entry in
`config/settings.yaml: renderer.preference` (`["excel_com", "libreoffice"]` by default) and picks
the first one whose `is_available()` returns `True`. Both implementations share a `WorkbookRenderer`
`Protocol` (`recalculate_and_save`, `export_pdf`), so `workbook_rendering.py` and `pdf_export.py`
never need to know which one is actually running.

## Background execution

`orchestration/worker.py` wraps `RunManager.execute_run()` / `submit_manual_input()` in a
`ThreadPoolExecutor`, with an in-memory `_in_flight` set preventing two overlapping executions of
the same run from racing on the same SQLite rows. This is deliberately the simplest mechanism that
satisfies "the UI must not block" for a local single-user tool — not a separate OS process or
message queue. See `docs/production_backlog.md` for what a shared/multi-user deployment would
need instead.

## Persistence

SQLite (`database.py`), explicit hand-written schema and queries rather than an ORM, because every
table (`runs`, `responsibility_state`, `rate_records`, `source_artifacts`,
`responsibility_errors`, `validation_findings`, `manual_inputs`) needs to be individually
auditable — this data may include internal rate information, and every query touching it should
be readable in one place, not generated.

## Where each master-prompt file-tree entry landed

Most of `config.py`, `database.py`, `security.py`, `audit.py`, `responsibilities/`,
`orchestration/`, `parsers/`, `normalization/`, `validation/`, `reporting/`, `ui/`, `cli.py` match
the master prompt's proposed structure directly. Two deliberate deviations, both explained above
and in `ASSUMPTIONS.md`: French Output has no separate `responsibilities/french_output.py` (folded
into `workbook_rendering.py`), and there's no standalone worker *process* (thread pool inside the
same process instead).
