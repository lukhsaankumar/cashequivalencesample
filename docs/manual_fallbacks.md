# Manual Fallbacks

What to do when a responsibility shows `MANUAL_REQUIRED` on the **Manual Uploads and Inputs** page,
per responsibility. Every override requires a reason — it's stored on every resulting record.

| Responsibility | What to supply | Accepted format |
|---|---|---|
| `template` | Replacement EN/FR workbook(s) | `.xlsx` |
| `gic_rates` | Current GIC rate sheet | `GIC Rates.xlsx` or a structured CSV (`code,dealer,block,term_years,bucket_days,min,rate`) |
| `canada_prime` | Current Bank of Canada Prime rate | Numeric field (e.g. `4.45`) + source date |
| `us_fed_funds` | Current Fed Funds target range | Lower + upper numeric fields; optionally an explicit selected value overriding the configured rule |
| `money_market` | Current IG Premium (CAD) / IG Mackenzie US yields | Two numeric fields |
| `treasury_bills` | Current NBF/NBCN rate sheet | PDF or text file |
| `hisa` | Current HISA roster | CSV/XLSX upload, or structured rows entered directly (provider, fund code, currency, rate, minimum, maximum) |

## Why these specific responsibilities need manual fallback most often

`money_market` and `hisa`'s primary sources (`digital.lipperweb.com`,
`home.investorsgroup.com`) and `gic_rates`'s SharePoint copy require the IG corporate VPN and an
authenticated session. Outside that network, expect all three to land on `MANUAL_REQUIRED` every
run — this is normal, not a bug, and is exactly what the automatic-first / manual-fallback design
is for. `canada_prime` and `us_fed_funds` use genuinely public APIs (Bank of Canada, FRED) and
should succeed automatically whenever there's ordinary internet access.

## What happens after you submit

The responsibility reruns with your input, then — only if it succeeds — every responsibility
downstream of it reruns automatically (`workbook_rendering → pdf_export → package` for any
collector; nothing for `template`/`report_date` unless something else depends on the timing).
Nothing unrelated already marked successful is touched. If validation fails on the new data (e.g.
a rate outside 0–20%, a T-bill maturity before the report date), the responsibility shows
`VALIDATION_FAILED` with the specific rule that failed on the Validation page — fix the input and
resubmit.

## Reviewing what changed

The **Review and Comparison** page shows the current run's values against the previous run's, so
you can confirm a manual entry landed where expected before approving.
