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

### If your project folder is inside a OneDrive-synced directory

Create the virtualenv **outside** the OneDrive tree — OneDrive's file locking/sync interferes with
`pip`/`uv`'s hardlinking and shows up as `Access is denied` / `failed to hardlink` errors during
install, even with `--link-mode=copy`. Keep the project source in OneDrive if you like; just put
`.venv` somewhere else:

```powershell
uv venv C:\venvs\<project-name>
C:\venvs\<project-name>\Scripts\Activate.ps1
cd "<your OneDrive project folder>"
uv pip install -e ".[dev,windows]" --link-mode=copy
```

To recreate the venv from scratch later: `Remove-Item -Recurse -Force C:\venvs\<project-name>`,
then repeat the two `uv` commands above.

### If your network does TLS inspection (corporate proxy)

Some corporate networks re-sign outbound HTTPS with an internal root CA, which breaks Python's
and Node's default certificate trust (`[SSL: CERTIFICATE_VERIFY_FAILED] ... self-signed
certificate in certificate chain`). Two separate fixes are needed — one for Python (`pip`/`httpx`
calls this app makes itself), one for Node (only needed if you install the `browser-auth` extra,
since `playwright install` downloads the browser binary through a bundled Node.js downloader with
its own separate trust store). Full detail and copy-paste commands are in `SECURITY.md` under
"Corporate network TLS inspection" — short version:

```powershell
# Python side (covers every httpx/pip call this app makes):
uv pip install -e ".[dev,windows,corp-network]" --link-mode=copy

# Node side (only if you're also installing browser-auth — see below):
$pemPath = "$env:USERPROFILE\corporate-root-cas.pem"
foreach ($cert in Get-ChildItem Cert:\LocalMachine\Root) {
    $b64 = [System.Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
    "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----" | Add-Content -Path $pemPath -Encoding ascii
}
[Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $pemPath, "User")
```
(Paste the Node block as one multi-line block, or run each line separately — pasting it collapsed
onto a single line breaks PowerShell's parser.)

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

## Automating SSO-gated sources (GIC Rates, Money Market, HISA, Treasury Bills)

These sources sit behind interactive corporate SSO (confirmed via a real captured Microsoft/Entra
ID login redirect, not assumed) — a plain HTTP request can never get past that. Optionally, a
persistent browser session lets automatic collection get past it too, using a session *you*
create by signing in yourself once:

```powershell
uv pip install -e ".[dev,windows,browser-auth]" --link-mode=copy
playwright install chromium   # one-time; see "If your network does TLS inspection" above if this fails
python -m cash_equivalents_mvp.cli browser-login --source gic_rates
```

The last command opens a visible browser window — sign in exactly as you normally would (password,
MFA); the window closes itself once you're past the login page. All four sources share one saved
profile (`igm_default` in `config/sources.yaml`), but each source's own site needs its own sign-in
the first time (a session established for gic_rates doesn't cover a different domain like
digital.lipperweb.com or nbin.ca — run `browser-login --source <id>` once per source; each login
adds to the saved profile rather than replacing it). Check status any time with `cli
browser-status`; clear all saved sessions with `cli browser-logout --profile igm_default`. Nothing
about this stores a password — see `SECURITY.md`'s "Persistent authenticated browser sessions"
section for exactly what is and isn't saved. Entirely optional: skip this and every source falls
back to plain HTTP, then file/manual upload, exactly as before.

The same sign-in is also available from the Dashboard page, in the "Browser-authenticated
sources" panel above **Start a new run** — click **Sign in** next to a source and the same real,
visible browser window opens (Playwright controls a separate native window, not something that
renders inside the page itself). Fully optional and skippable there too; a new run starts
regardless of whether any source is signed in.

GIC Rates' and Treasury Bills' file downloads run with a **visible** browser window, deliberately
— some tenants additionally require a corporate-managed-device certificate to reach SharePoint/
similar resources, which only a real, visible browser negotiation (on a machine IT has actually
enrolled) has any chance of completing; a hidden/headless browser can't participate in that
negotiation at all. This only works when run on a machine your organization has enrolled — it will
never work on a generic cloud/Linux host with no device enrollment, and no code change can make it
work there, since the certificate itself doesn't exist on such a machine. See SECURITY.md.

## How to generate a debug bundle

**Debugging** (page 7) shows the stage timeline and every structured error for the selected run,
and has a **Generate debug bundle** button that zips responsibility states, errors, findings, and
environment info for offline diagnosis.

## Known limitations

- Money Market and HISA are automatable with the optional browser-session setup above (Money
  Market confirmed working end-to-end). GIC Rates' and Treasury Bills' file downloads can hit two
  separate, stacked Microsoft Defender for Cloud Apps checks: a device-trust check on general
  access (a corporate-managed-device certificate requirement — handled with a visible, not
  hidden, browser window so a real IT-enrolled machine gets a fair shot at it) and, confirmed by a
  real blocked attempt, a stricter, separate DLP check specifically on downloads that a device can
  pass the first check and still fail. Neither is something this app attempts to route around —
  both only ever resolve on a machine/account your organization recognizes as managed for that
  purpose; see SECURITY.md for exactly what is and isn't attempted, and the real block message
  Microsoft returns. Treasury Bills' NBIN scrape is also unverified against NBIN's real authenticated page structure
  (never captured before this) — a first attempt will likely need a follow-up fix once real
  evidence comes back, the same way Money Market's did.
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
Remove-Item -Recurse -Force local_data\runs\*, local_data\uploads\*, local_data\raw_sources\*, local_data\database\*, local_data\logs\*, local_data\browser_profiles\*
```

(The last one signs out every saved browser-session profile — omit it if you want to keep those.)
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
