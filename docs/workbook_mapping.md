# Workbook Mapping

Verified cell-level mapping between source data and the EN report workbook
(`20260511 Cash and Cash Equivalents EN.xlsx`), established by dumping formulas *and* cached
values for every target sheet with openpyxl (`scripts/dump_cells.py`) and cross-checking against
the historical fixture values in the master prompt. FR coordinates are identical (see
`source_inventory.md`); only sheet names differ, per `config/workbook_map_fr.yaml`.

This file is the human-readable version of `config/workbook_map_en.yaml` /
`workbook_map_fr.yaml`, which the application actually loads at runtime. Row numbers here are
**not** hardcoded into responsibility logic — providers are located by provider/fund-code identity
within each block at runtime, and a `WORKBOOK_LABEL_MISMATCH` error is raised if a header no longer
matches, exactly as required by the "do not blindly trust ranges" instruction.

## Report date

| Cell | Content |
|---|---|
| `Cover!I29` | The single master date. Everything else (`HISA!G1`, `TBills!G1`, `Money Market Funds!G1`, `Executive Summary!P1`) is a formula chain rooted in the defined name `Date` → `Cover!$I$29`. |

## Canada Prime / US Fed Funds

| Cell | Content | Verified |
|---|---|---|
| `Cash!D30` | Label `"Canada - Bank Prime Rate "` | yes |
| `Cash!D31` | Prime rate, decimal (e.g. `0.0445`) | yes, matches historical fixture 4.45% |
| `Cash!H30` | Label `"US - Federal Funds Rate "` | yes |
| `Cash!H31` | Fed Funds report value, decimal (e.g. `0.0375`) | yes, matches historical fixture 3.75% |

Before writing, the responsibility re-reads `D30`/`H30` and asserts they still contain the expected
label text (case/whitespace-insensitive substring match) — this is the `WORKBOOK_LABEL_MISMATCH`
guard required by the master prompt.

## Treasury Bills (`TBills` sheet)

| Block | Maturity dates | Term-days (formula, not written) | Rates |
|---|---|---|---|
| Canadian | `A15,C15,E15,G15,I15` | `A17,C17,E17,G17,I17` = `=DAYS(date,$G$1)&" days"` | `A19,C19,E19,G19,I19` |
| US | `A24,C24,E24,G24,I24` | `A26,C26,E26,G26,I26` (same formula) | `A28,C28,E28,G28,I28` |

The term-days cells are **existing formulas**, not written by the pipeline — writing the maturity
date is sufficient; Excel recalculates the day count against `$G$1` (the report date) automatically.
This is exactly the "do not rely solely on a source-provided day count" instruction: the source PDF
prints its own day counts (`40`, `68`, `96`...) which are discarded in favour of Excel's own
`maturity − report_date` formula.

## Cashable GICs & Term Deposits (`Cashable & Term Deposits` sheet)

| Range | Content | Providers (in row order) |
|---|---|---|
| `F18:F25` | Cashable GIC rate (1yr term), input | BMO, BMO Mortgage GIC, BMO Trust Company, Bank of Nova Scotia, Equitable Bank, Equitable Trust, Home Bank GIC, Home Trust GIC |
| `E32:J43` | Term deposit rates, 30/60/90/120/180/270-day buckets, input | B2B, BMO, BMO Mortgage, BMO Trust, BNS, Equitable Bank, Equitable Trust, Home Bank, Home Trust, Laurentian, Manulife, National Bank |
| `A57` / `B58` | `=INDEX/MATCH(MAX(...))` over `A15:A26`/`F15:F26` | **real MAX formula** — highest cashable rate, not hardcoded |
| `E62:J62` | `=INDEX/MATCH(MAX(...))` per column over `E32:E43`...`J32:J43` | **real MAX formula** — highest term-deposit rate per bucket |

Row 17 (B2B) and row 26 (National Bank) have no cashable-GIC rate in the source (`#N/A`) and their
`F` cells are correctly left blank in the report — confirmed both in the report workbook and in the
source `GIC Rates.xlsx!Eng!E95:E96` (`#N/A`).

## GIC 1yr–5yr (`GIC 1yr-5yr` sheet)

| Block | Range | Providers |
|---|---|---|
| Annual Pay | `E14:I25` (1yr–5yr) | same 12-provider order as term deposits |
| Compound | `E30:I41` | same 12 |
| Monthly Pay | `E46:I57` | same 12 |

**Validated parity rule**: for every provider/term, `Annual` and `Compound` values are identical in
the current report (e.g. B2B 1yr = `0.0331` in both `E14` and `E30`). The Money-Market/GIC
validation layer checks this and raises `GIC_ANNUAL_COMPOUND_PARITY_MISMATCH` (warning, not
blocking) if they diverge on the next update — the master prompt calls this out explicitly as a
rule to check but doesn't say it's always true; here it's empirically true for every row in the May
11 snapshot, so the validator treats a mismatch as worth a human's attention rather than a hard
failure (rates *can* legitimately diverge; the check exists to catch mapping/offset bugs).

## Source: `GIC Rates.xlsx!Eng` → report range mapping

All five ranges from the master prompt were individually verified cell-by-cell (see
`docs/source_inventory.md` for the block layout) and are correct as stated:

```
Eng!E89:E96  (Cashables, 8 providers, "Annual" col)     → Cashable & Term Deposits!F18:F25
Eng!E69:J80  (Short-Term Deposits, 12 providers)        → Cashable & Term Deposits!E32:J43
Eng!E9:I20   (Payout GICs, term=ANNUAL, 12 providers)   → GIC 1yr-5yr!E14:I25
Eng!E45:I56  (Compound GICs, 12 providers)              → GIC 1yr-5yr!E30:I41
Eng!E26:I37  (Payout GICs, term=MONTHLY, 12 providers)  → GIC 1yr-5yr!E46:I57
```

Row order in the source and destination is identical (B2B, BMO, BMO Mortgage, BMO Trust, BNS,
Equitable Bank, Equitable Trust, Home Bank, Home Trust, Laurentian, Manulife, National Bank — with
the 8-provider Cashables block dropping Laurentian/Manulife/National). The application matches by
**provider code** (e.g. `BNSGICR`, `HOBKGICP`) read from column B/D of the source, not by row
position, so a future re-ordering in the source is tolerated; a provider that disappears entirely
raises `PARSER_PROVIDER_MISSING`.

Percentage scale: source cells are bare numbers (`1.75` meaning 1.75%); canonical storage is
`Decimal("0.0175")`. Confirmed end-to-end: `Eng!E92` (`BNSGICR`) = `1.75` → report `F21` = `0.0175`.

## HISA (`HISA` sheet)

| Range | Content |
|---|---|
| `A22:H52` (with header at 22) | Detailed provider table: Issuer, Fund Code, Minimum, Maximum, Corporate Eligible, CDIC, Yield. CDN block rows 23–40, US block rows 43–52. |
| `N12` | `=A30` — CDN "Highest Rate Formula" name, hardcoded to row 30 |
| `N13` | `=H30` — CDN "Highest Rate Formula" rate, hardcoded to row 30 |
| `N16` | `=A43` — USD equivalent, hardcoded to row 43 |
| `N17` | `=H43` — USD equivalent rate, hardcoded to row 43 |

**Important finding, not obvious from the master prompt alone**: unlike the Cashable/Term-Deposit
and Money-Market-Funds sheets (which use real `INDEX/MATCH(MAX(...))` formulas), the HISA "highest
rate" cells are **hardcoded row references**, not a MAX formula. Row 30 (`IG Equitable Bank High
Interest`, 2.05%) is well below several BNS rows (row 27: 2.10%, row 29: 2.10% corporate) — those
are deliberately excluded because they apply only above the $100,000 CDIC-eligible tier per the
enhanced trade edit described in `HISA!A19`. This is the concrete instance of the master prompt's
"do not implement `summary_rate = max(...)`" instruction: the current process already encodes a
manual product-selection decision, not a formula. The application's `hisa.py` responsibility stores
this as `config/business_rules.yaml: hisa_summary_selection` (row identity by provider+fund-code,
not row number) and raises a review warning (`HISA_SUMMARY_RULE_UNCONFIRMED` /
`HISA_HIGHER_RATE_EXCLUDED`) whenever a numerically higher CDN or US rate exists outside the
selected row, without ever silently changing the selection.

## Money Market

Two distinct, unrelated data points share the "money market" name in this workbook:

1. **IG Mackenzie current yield** (master prompt §7.6) — plain text strings, not formulas:
   `Executive Summary!A25` = `"Current Yield 2.00%"` (CAD), `Executive Summary!A28` =
   `"Current Yield 2.82%"` (US). The responsibility writes the full formatted string, not a bare
   number, because that's what the cell actually contains.
2. **Competitor money-market mutual fund comparison** (`Money Market Funds` sheet, hidden) — a real
   `INDEX/MATCH(MAX(...))` table over `A17:A26`/`J17:J26` (CAD) and `A32:A41`/`J32:J41` (US) that
   feeds `Executive Summary!A61/F61/H61/M61`. No hyperlink or source in `Info.docx` covers this
   table; it is out of the explicit scope of §7.6. Implemented as `MANUAL_REQUIRED`-only with
   `status: BUSINESS_SCOPE_UNCONFIRMED` in `config/business_rules.yaml`, matching the treatment the
   master prompt prescribes for Bankers' Acceptances.

## French workbook formatting (not a coordinate mirror of EN)

Verified by dumping the FR workbook's `Espèces` (Cash), `Bons du Trésor` (TBills), `CEIE` (HISA),
`CPG et dépôts à terme`, and `CPG 1 an-5 ans` sheets:

| Sheet | Coordinates vs EN | Value representation |
|---|---|---|
| `Page couverture!I29` (report date) | identical | date, same as EN |
| `CPG et dépôts à terme` | identical | numeric `Decimal`, French number format applied via cell style |
| `CPG 1 an-5 ans` | identical | numeric `Decimal`, same as EN |
| `Bons du Trésor` maturity dates | identical | date |
| `Bons du Trésor` rate cells | identical coordinates | **literal French text**, e.g. `"2,23%"` |
| `Espèces` (Prime/Fed Funds) | **different**: `E31`/`E32` (Prime), `H31`/`H32` (Fed Funds) vs EN's `D30`/`D31`, `H30`/`H31` | **literal French text**, e.g. `"4,45%"` |
| `CEIE` (HISA) | row offsets vs EN not individually confirmed (spot check showed EQB rows at 33/35 in FR vs 30/32 in EN, and the "highest rate" formula cells live at different coordinates than EN's `N12/N13/N16/N17` — not fully traced) | **literal French text**, e.g. `"1,80%"` |
| `Sommaire!A25`/`A28` (money market) | identical | literal text, e.g. `"Taux courant 2%"` / `"Taux courant 2,82%"` — whole-percent values drop the decimal point, others show 2dp |

This was not anticipated by the master prompt's assumption that only "language and locale
formatting differ" — here two different *data types* (number vs. pre-formatted text) coexist across
sheets in the same French workbook. `reporting/mappings.py` handles this per-section via the
`value_format` flag (`numeric` / `french_percent_text` / `french_percent_text_trim_zero`) in
`config/workbook_map_fr.yaml`, and the French Output Responsibility (`responsibilities/french_output.py`)
still writes from the same canonical `Decimal` — it just formats it differently before the write,
and validates numeric parity by re-parsing the French text back to a `Decimal` and comparing to the
EN cell, rather than assuming a literal value match.

For sheets where the exact FR row offset was not individually re-verified against every provider
(`HISA`), the writer locates the target row by fund-code identity within a generous scan window
(`config/workbook_map_fr.yaml: hisa.discovery: scan`) instead of a hardcoded row number, and raises
`WORKBOOK_MAPPING_INVALID` if a code isn't found in the window — the same fail-closed behaviour
used everywhere else in the pipeline when a mapping can't be trusted blindly.

## Bankers Acceptance

Sheet exists (hidden, `Bankers Acceptance` / `Acceptations bancaires`) with conditional formatting
and a calculator area, but is not present in either 7-page reference PDF (it's excluded from the
print area / not in the visible page set). Implemented as `bankers_acceptance_enabled = false`,
`status: BUSINESS_SCOPE_UNCONFIRMED`, per the master prompt.
