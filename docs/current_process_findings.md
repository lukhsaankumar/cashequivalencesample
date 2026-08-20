# Current Process Findings

Observations about the existing manual weekly process, derived from `Step by Step Cash And
Equivalents.docx`, `Info.docx`, the historical `.eml`, and the workbooks themselves. These inform
where the MVP encodes a firm rule vs. exposes a configuration/review warning.

## The process today is manual copy/paste into a single master workbook

`Step by Step Cash And Equivalents.docx` describes a human opening several browser tabs
(`home.investorsgroup.com` product pages, NBIN, a SharePoint copy of `GIC Rates.xlsx`) and
Bank of Canada / bankrate.com, then typing values into the report workbook by hand, saving EN and
FR copies, exporting PDFs from Excel, and emailing the four attachments. The historical `.eml`
confirms the exact deliverable shape: one email, no CC, HTML body with plain factual language,
four attachments (EN/FR × xlsx/pdf).

## Two "highest rate" mechanisms coexist, and they are not interchangeable

- **Cashable GICs, Term Deposits, and the competitor Money-Market comparison table** genuinely use
  `INDEX/MATCH(MAX(...))` Excel formulas. These are safe to leave untouched — write the input rows,
  let Excel pick the max.
- **HISA's "highest rate"** is a hardcoded reference to a specific row (`=A30`, `=H30` etc.), not a
  MAX formula, and it deliberately excludes numerically higher BNS rates that only apply above the
  $100,000 CDIC threshold. Blindly generalizing "pick the highest visible rate" (which the master
  prompt explicitly warns against) would silently start recommending a rate a client cannot actually
  get in a CDIC-safe way. This is the single most important behavioural finding from inspecting the
  real file: **the two tables look the same but are not maintained the same way**, and any
  automation has to know which one it's touching.

## The report date is a single source of truth

Every date-dependent cell across sheets (`HISA!G1`, `TBills!G1`, `Money Market Funds!G1`,
`Executive Summary!P1`) is a formula chained back to one cell, `Cover!I29`. This was presumably
built this way specifically so a human only had to change one cell per language per week. The MVP
preserves and relies on this — the Report Date Responsibility writes exactly one cell per workbook.

## T-bill "days to maturity" is already Excel-native, not a copy/paste field

`TBills!A17` etc. is `=DAYS(A15,$G$1)&" days"` — the term length shown to the client is *always*
freshly computed from the report date and the maturity date already in the sheet, so the source PDF
provided term/day figures were never meant to be transcribed. The MVP recomputes independently in
Python for validation (`term_days = (maturity_date - report_date).days`) but relies on the existing
Excel formula for the value that ends up in the deliverable, per the master prompt's own
architecture rule (never overwrite formula cells).

## Money-market "yield" is two unrelated numbers wearing the same name

`Executive Summary!A25`/`A28` ("Current Yield 2.00%"/"2.82%") are the two numbers explicitly named
in master-prompt §7.6 (IG Premium CAD / IG Mackenzie US funds — sourced from the two Lipper profile
hyperlinks in `Info.docx`). The `Money Market Funds` sheet's `INDEX/MATCH(MAX(...))` comparison
table (CIBC/TD/etc.) is a *different* concept — a competitive shelf comparison — with no hyperlink
or documented source anywhere in the supplied material. Rather than guess a source for it, it is
flagged `BUSINESS_SCOPE_UNCONFIRMED` and left manual-only, consistent with how the master prompt
asks Bankers' Acceptances to be handled.

## Nearly every automatic source lives behind the IG corporate network

Of the seven hyperlinks recovered from `Info.docx` and `Step by Step Cash And Equivalents.docx`,
five point at `home.investorsgroup.com`, `digital.lipperweb.com`, or `*.sharepoint.com` — all
authenticated, VPN-gated IG-internal systems this environment cannot reach and, per instructions,
must not attempt to bypass. Only Bank of Canada (Prime) and a Federal Reserve source (Fed Funds —
implemented against FRED rather than the legacy `bankrate.com` link, since FRED is the actual
official/public source and has a stable API) and NBIN (T-bills — login-gated, so also manual in
practice) are candidates for real automatic retrieval outside the VPN. This is expected and is why
every responsibility is built with a working manual-fallback path as a first-class feature rather
than an afterthought — in the actual IG environment (on VPN, authenticated), the same automatic
collectors should reach `home.investorsgroup.com` and Lipper directly; that path is implemented but
untestable here, and is marked `MANUAL_REQUIRED` with the real error code the collector produced
(timeout/DNS/connection-refused) rather than a fabricated success.

## GIC percentage scale is a real, recurring failure mode worth guarding

`GIC Rates.xlsx` stores rates as bare numbers (`1.75` for 1.75%) while the report workbook stores
canonical decimals (`0.0175`). A single mis-scaled paste would produce `175.00%` or `0.0175%`
instead of `1.75%` — exactly the failure mode called out in the master prompt. The normalization
layer treats *any* parsed value `> 1` as "already in percent form, needs /100" and any value
`<= 1` as "already canonical," which is unambiguous for real GIC/HISA/T-bill rates (all comfortably
under 100% and usually under 1 in canonical form) but is validated with an explicit range check
(0%–20%) after scaling as a second line of defence, per §7.3's validation rules.
