# Security

This application handles internal IG Wealth Management rate data and, transiently, uploaded
source files. Treat everything under `source_material/` and `local_data/` as confidential.

## What this application never does

- **Never sends email.** There is no send function anywhere in this codebase.
  `reporting/email_draft.py` builds a `.eml` file with empty `To`/`Cc`/`Bcc` headers and nothing
  else touches SMTP, Graph, or any mail transport. `responsibilities/package.py`'s `validate()`
  fails the run if any of those headers are non-empty.
- **Never bypasses authentication.** Sources behind the IG VPN / SSO (`home.investorsgroup.com`,
  `digital.lipperweb.com`, `*.sharepoint.com`) are attempted with a plain HTTP GET; if that fails,
  the responsibility falls through to `MANUAL_REQUIRED`. No credential is stored, guessed, or
  brute-forced.
- **Never stores credentials in the repo, database, or logs.** There are currently no credentialed
  sources configured (`config/sources.yaml` only lists unauthenticated endpoints and file-watch
  folders). If a future production deployment adds one, `config.py` deliberately has no
  credential-loading path — see `docs/production_backlog.md`.
- **Never uploads report content to a third party.** No analytics, no telemetry, no crash
  reporting, no AI/LLM call is made with source or output data at runtime.

## Untrusted input handling

- **Uploaded filenames are never trusted.** `security.sanitize_filename()` strips every path
  component and disallowed character before a filename touches the filesystem;
  `security.safe_join()` additionally refuses any resolved path that would land outside the target
  directory. Both are exercised by fault-injection tests (`tests/fault_injection/`) and unit tests
  (`tests/unit/test_security.py`).
- **Zip extraction is zip-slip safe.** `security.safe_extract_zip()` sanitizes every member name
  before extracting.
- **File type/extension is validated** (`security.validate_extension()`) before a manual upload is
  parsed; a wrong extension fails with `FILE_TYPE_INVALID` rather than being parsed speculatively.
- **Uploaded workbooks/CSVs are opened read-only and never executed.** `openpyxl` parses cell
  values only; macros are never enabled or run.

## Provenance and audit

Every `RateRecord` carries `source_artifact_id`, `extraction_method`, and (for manual overrides)
`manually_overridden` / `override_reason` / `override_user`. Every `SourceArtifact` carries a
SHA-256 of the file it came from. Overrides without a reason are rejected with
`MANUAL_OVERRIDE_REASON_MISSING` at the responsibility level, not just enforced in the UI.

## What is deliberately not logged

- Recipient email addresses (the historical `.eml` fixture's `To` header is read structurally
  during bootstrap but never echoed into `docs/`, logs, or console output — see
  `parsers/historical_email.py`'s `parse_eml_summary()`).
- Full HTML page bodies from scraped sources.
- Raw workbook contents (logs reference cell coordinates and provenance, not full sheet dumps).
- Any credential, token, or session cookie.

## Local data hygiene

`.gitignore` excludes `source_material/`, `local_data/`, and every generated `.xlsx`/`.xlsm`/
`.pdf`/`.csv`/`.eml` from version control. To clear all confidential local state between sessions:

```powershell
Remove-Item -Recurse -Force local_data\runs\*, local_data\uploads\*, local_data\raw_sources\*, local_data\database\*, local_data\logs\*
```

(`source_material/` is left untouched — it's the read-only approved template/source set, not
run-generated state.)

## Corporate network TLS inspection (`SOURCE_TLS_TRUST_FAILURE`)

Some corporate networks run outbound HTTPS through a proxy that performs SSL/TLS inspection —
the proxy re-signs every HTTPS connection with its own internal root CA so it can inspect
traffic, which is invisible to a normal browser (the corporate CA is pushed to the OS trust store
via Group Policy) but breaks Python's `httpx`/`requests`, which only trust the bundled `certifi`
CA list by default. This shows up as `SOURCE_TLS_TRUST_FAILURE` — the underlying error looks like
`[SSL: CERTIFICATE_VERIFY_FAILED] certificate verify failed: self-signed certificate in
certificate chain`.

**This is expected on such a network and does not indicate a code bug** — every collector's HTTP
call goes through `collectors/http.py: classify_http_exception()`, which recognizes this exact
failure and reports it distinctly from "source unreachable" / "needs VPN" so it isn't confused
with the other, unrelated `SOURCE_AUTH_REQUIRED` cases.

**Fix:**

```powershell
pip install -e ".[dev,windows,corp-network]"
# or, if already installed:
pip install pip-system-certs
```

This patches Python (via a `.pth` file loaded at interpreter startup) to validate certificates
against the Windows certificate store instead of only `certifi`'s bundled list — since the
corporate root CA is already in the Windows store (that's how your browser trusts it), this is
usually a complete fix with no other configuration. Restart the terminal/venv after installing.

If a source still fails after installing `pip-system-certs`, the corporate proxy is likely
blocking or redirecting that specific domain outright (not just re-signing it) — that needs an
IT-side allowlist change, not a client-side fix, and will still correctly fall through to a
manual upload in the meantime.

## Known gaps (tracked, not silently ignored)

- The Streamlit app has no authentication of its own — it's designed to run on `localhost` for a
  single local operator, not to be exposed on a shared network. See
  `docs/production_backlog.md` for the identity/RBAC work a real deployment needs.
- Settings are currently read/write only via `config/*.yaml` on disk (the Settings UI page is
  read-only) — there's no in-app secret store because there are no secrets to store yet.
