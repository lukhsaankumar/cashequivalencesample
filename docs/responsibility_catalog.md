# Responsibility Catalog

Every responsibility, its automatic source, manual fallback, and key target cells. Coordinates are
verified against the real source files — see `docs/workbook_mapping.md` for how.

## template

**File:** `responsibilities/templates.py` · **Depends on:** nothing
Locates `source_material/20260511 Cash and Cash Equivalents {EN,FR}.xlsx`, copies both into the
run directory, verifies the copies aren't the source files and contain the expected sheet names.
**Manual fallback:** upload replacement `.xlsx` templates.

## report_date

**File:** `responsibilities/report_date.py` · **Depends on:** nothing
The date chosen at run creation. Target: `Cover!I29` (both EN and FR — identical coordinates) —
every other date display on every sheet is a formula chained back to this one cell via the
defined name `Date`. **Manual fallback:** re-enter the date.

## gic_rates

**File:** `responsibilities/gic_rates.py` · **Depends on:** nothing
Cashable GICs, term deposits, and GIC 1yr–5yr (annual/compound/monthly). Automatic: detects
`GIC Rates.xlsx`/CSV in the watched upload folder, falling back to `source_material/` for the
historical demo. **Manual fallback:** upload `GIC Rates.xlsx` or a structured CSV. Targets:
`Cashable & Term Deposits!F18:F25` / `!E32:J43`, `GIC 1yr-5yr!E14:I25` / `!E30:I41` / `!E46:I57` —
see `docs/workbook_mapping.md` for the full source→destination range table.

## canada_prime

**File:** `responsibilities/canada_prime.py` · **Depends on:** nothing
Automatic: Bank of Canada Valet API, series `V80691311` — **public, verified working from this
environment**. Target: `Cash!D31` (EN, numeric) / `Espèces!E32` (FR, French percent text — note the
different column/row from EN). **Manual fallback:** numeric rate + source date + reason.

## us_fed_funds

**File:** `responsibilities/fed_funds.py` · **Depends on:** nothing
Automatic: FRED (St. Louis Fed) CSV endpoints for `DFEDTARU`/`DFEDTARL` — **public, verified
working**. Report value = configured rule applied to lower/upper bound
(`config/business_rules.yaml: fed_funds.rule`, default `UPPER_BOUND`,
`UNCONFIRMED_BUSINESS_RULE`). Target: `Cash!H31` / `Espèces!H32`. **Manual fallback:** lower,
upper, and optionally an explicit selected value + reason.

## money_market

**File:** `responsibilities/money_market.py` · **Depends on:** nothing
IG Premium (CAD) / IG Mackenzie US (USD) current yield. Automatic: Lipper fund profile pages
(`digital.lipperweb.com`) linked from `Info.docx` — **requires IG VPN + authenticated session, not
reachable from this environment**. Target: `Executive Summary!A25` / `A28` — these are literal text
strings (`"Current Yield 2.00%"`), not numeric cells. **Manual fallback:** CAD yield + US yield +
reason.

## treasury_bills

**File:** `responsibilities/treasury_bills.py` · **Depends on:** nothing
Canadian and US T-bill rates. Automatic: watches a download folder (and `source_material/` for the
demo) for an NBF/NBCN PDF; NBIN itself is login-gated so live scraping isn't attempted. Term days
are always recomputed from `maturity_date − report_date`, never trusted from the source PDF's own
printed day count. Targets: `TBills!A15..I15` (maturity dates) / `A19..I19` (rates), CAD block;
`A24..I24` / `A28..I28`, US block. **Manual fallback:** upload an NBF/NBCN PDF or text sheet.

## hisa

**File:** `responsibilities/hisa.py` · **Depends on:** nothing
Detailed CDN/US High-Interest Savings Account roster (~30 providers). Automatic: attempts the
`home.investorsgroup.com` product page (VPN-gated, expected to fail here), then a structured
CSV/XLSX in the upload folder, then falls back to reading the roster straight out of the current
EN report workbook's own `HISA` sheet for the historical demo. **Never** computes
`max(all_visible_rates)` — the "highest rate" product is configured by identity
(`config/business_rules.yaml: hisa_summary_selection`), and a numerically higher excluded rate
raises a warning, never a silent switch. **Manual fallback:** upload CSV/XLSX or enter structured
rows directly.

## workbook_rendering

**File:** `responsibilities/workbook_rendering.py` · **Depends on:** all 8 collectors above
Populates every mapped cell in the EN and FR working copies from the collectors' `RateRecord`s
(`reporting/mappings.py`), then recalculates through Excel COM (or LibreOffice) and saves. Also
where French Output happens — see `docs/architecture.md` for why it isn't a separate stage.
Validates: no formula-error text in any visible sheet's print area, and EN/FR bilingual numeric
parity (`validation/bilingual.py`). **No separate manual fallback** — it's a "re-render" trigger,
not a data source.

## pdf_export

**File:** `responsibilities/pdf_export.py` · **Depends on:** `workbook_rendering`
Exports exactly the 7 report sheets (Cover, Executive Summary, Cash, TBills, HISA, Cashable & Term
Deposits, GIC 1yr-5yr — not the visible-but-not-printed `Data Lists` sheet) to PDF, one page each.
Validates page count = 7, no blank pages, no formula-error text in the rendered PDF text.

## package

**File:** `responsibilities/package.py` · **Depends on:** `pdf_export`
Copies the final EN/FR workbooks and PDFs into the outputs folder, builds the unsent `.eml` draft
(empty `To`/`Cc`/`Bcc`, factual body, four attachments), and zips everything. Validates every
output file exists and the email draft truly has no addressed recipients.
