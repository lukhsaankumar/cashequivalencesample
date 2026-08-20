# Assumptions

Every conservative assumption made while building this MVP, why it was made, and where it's
exposed as configuration or a review warning rather than silently baked in.

## Business rules explicitly marked unconfirmed

| Rule | Assumption | Where it's exposed |
|---|---|---|
| Fed Funds report value | `UPPER_BOUND` of the target range | `config/business_rules.yaml: fed_funds.rule` + `rule_status: UNCONFIRMED_BUSINESS_RULE`; surfaced as a `FED_RULE_UNCONFIRMED` warning on every run |
| HISA "highest rate" selection | The current workbook's hardcoded row references (`HISA!N12/N13/N16/N17`) reflect a deliberate CDIC-tier business decision, not a formula to generalize | `config/business_rules.yaml: hisa_summary_selection`, identity-keyed (provider name + fund code), never row number. A numerically higher excluded rate raises `HISA_HIGHER_RATE_EXCLUDED`, never a silent switch |
| Bankers' Acceptance | Out of scope — sheet exists but isn't in either 7-page reference PDF | `config/business_rules.yaml: bankers_acceptance.enabled = false`, `status: BUSINESS_SCOPE_UNCONFIRMED` |
| Money Market comparison table (`Money Market Funds` sheet, CIBC/TD/etc.) | Out of scope — no hyperlink or documented source anywhere in the supplied material | `config/business_rules.yaml: money_market_comparison_table.enabled = false`, `status: BUSINESS_SCOPE_UNCONFIRMED` |
| T-bill commission / net rate | Never calculated — the workbook explicitly directs advisors to a separate commission calculator | `config/business_rules.yaml: tbill_commission.calculate_net_rate = false` |

## Percentage scaling

GIC Rates.xlsx (and any manually uploaded structured CSV matching its shape) is assumed to
**always** store bare percent numbers regardless of magnitude — `0.50` means 0.50%, not an
already-canonical 50%. This was not obvious from the master prompt's "values > 1 imply percent
form" heuristic alone; that heuristic actively mis-scaled real short-term-deposit rates like
`0.50` (misread as 50%) during testing (see `normalization/percentages.py`'s `source_convention`
parameter and the bug it fixes). Manual-entry numeric override fields (Prime, Fed Funds bounds,
money-market yields) use the more conservative "auto" heuristic instead, since those really are
ambiguous free-text entry points where either convention is plausible.

## French workbook value representation

Assumed, then individually verified per section (see `docs/workbook_mapping.md`), that:
- `Cashable & Term Deposits`, `GIC 1yr-5yr`, `TBills` maturity dates, and the report-date cell are
  coordinate-identical to EN with plain numeric values.
- `Cash` (Prime/Fed Funds), `TBills` rate cells, and `HISA` yield cells store a **literal
  pre-formatted French-locale text string** (`"4,45%"`) rather than a number.
- `Cash`'s FR coordinates differ from EN's (`E31/E32`, `H31/H32` vs `D30/D31`, `H30/H31`).
- `HISA`'s exact FR row offsets from EN were **not** individually re-verified for every one of the
  ~30 providers (only a handful were spot-checked). Rather than risk a wrong hardcoded row number,
  `write_hisa()` locates the target row by fund-code identity within a generous scan window
  (`config/workbook_map_fr.yaml: hisa.discovery: scan`) and raises a mapping warning if a code
  isn't found, instead of assuming a coordinate that was never confirmed.
- The Executive Summary money-market convention ("2.00%" → "2%", "2.82%" stays "2,82%") is assumed
  to be "drop the decimal point only when both decimal digits are zero" — inferred from the two
  examples in the historical fixture, not from a written spec. Implemented as
  `french_percent_text_trim_zero()`.

## Workbook Rendering / French Output as one responsibility, not two

The master prompt's dependency graph lists `english_workbook` and `french_workbook` as separate
stages. This implementation merges them into one `workbook_rendering` responsibility because:
splitting them would mean opening/writing/closing each language's Excel COM session twice for no
benefit, and — more importantly — writing both languages from the *same* canonical `Decimal` in
the *same* function call is what makes bilingual numeric parity structurally guaranteed rather
than something a separate reconciliation pass has to catch after the fact. A dedicated
`check_bilingual_parity()` validator (`validation/bilingual.py`) still runs as a second line of
defense, re-reading both saved files and comparing actual cell values rather than trusting the
"same Decimal" argument alone — it caught (and helped fix) two real bugs during development.

## GIC Rates(Eng).csv fallback schema

No real `GIC Rates(Eng).csv` export was supplied in this environment (see
`docs/source_inventory.md`). `parsers/gic_csv.py` supports two shapes: a canonical structured
schema (`code,dealer,block,term_years,bucket_days,min,rate`) documented as the manual-upload CSV
format, and a "wide" export mirroring the xlsx `Eng` sheet's annual-pay block header row. Both are
unit-tested against synthetic fixtures; neither has been validated against a real CSV export from
the actual source system.

## Historical regression validates the published workbook, not a fresh run

`tests/regression/test_historical_may11.py` reads the already-published
`20260511 Cash and Cash Equivalents EN/FR.xlsx` directly. It does **not** run the live pipeline
against today's `GIC Rates.xlsx` / NBF PDF snapshots and assert the May-11 numbers come out the
other end — those source files are dated ~August 2026 (see `docs/source_inventory.md`'s NBF PDF
discussion) and will naturally produce different values than the frozen May-11 fixture. This
matches the master prompt's own framing: "Use the May 11, 2026 package as a historical fixture
only... Do not represent these values as current."

## Money Market / HISA / GIC "automatic" collection in this environment

`home.investorsgroup.com`, `digital.lipperweb.com`, and `*.sharepoint.com` are unreachable without
the IG corporate VPN and an authenticated session — this environment has neither. Every
responsibility that depends on one of these sources has a fully implemented automatic collector
(tested against the real Bank of Canada and FRED public APIs, which **do** work here) that will
attempt the real request every run; outside the VPN it fails fast with the real error the request
produced (`SOURCE_AUTH_REQUIRED`, connection error, etc.) and falls through to `MANUAL_REQUIRED`,
never a fabricated success. GIC Rates, Treasury Bills, and HISA additionally fall back to reading
straight from the corresponding file already present in `source_material/` for the historical
demo — documented inline in each responsibility as a "historical-demo convenience," analogous to
what a file-watch folder would provide in production once the VPN path is configured.

## Code quality tooling scope

`ruff` is configured with a scoped `select` (`F`, `RUF`, `BLE`, `DTZ`, `S`, `PLW`) rather than a
broad default, with a short documented ignore list (`BLE001`, `DTZ003`, `DTZ011`, `S110`, `UP036`,
`S603`) for patterns that are deliberate, not oversights — see `pyproject.toml` for the reasoning
attached to each. `mypy` runs clean (`Success: no issues found in 61 source files`) at
`python_version = "3.12"` (the interpreter actually used here; `3.11` in the original config broke
on a numpy stub using 3.12-only syntax). Style-only rule families (line length, import order,
general modernization) were intentionally left unscoped rather than reformatting the whole
codebase in this pass.
