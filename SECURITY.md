# Security

This application handles internal IG Wealth Management rate data and, transiently, uploaded
source files. Treat everything under `source_material/` and `local_data/` as confidential.

## What this application never does

- **Never sends email.** There is no send function anywhere in this codebase.
  `reporting/email_draft.py` builds a `.eml` file with empty `To`/`Cc`/`Bcc` headers and nothing
  else touches SMTP, Graph, or any mail transport. `responsibilities/package.py`'s `validate()`
  fails the run if any of those headers are non-empty.
- **Never bypasses authentication.** Sources behind the IG VPN / SSO (`home.investorsgroup.com`,
  `digital.lipperweb.com`, `*.sharepoint.com`) are attempted with a plain HTTP GET first; if that
  fails, an *optional* persistent browser session may be used instead (see below) — but that
  session only ever exists because the user personally, interactively signed in through a real
  login page. If neither is available, the responsibility falls through to `MANUAL_REQUIRED`. No
  credential is stored, guessed, autofilled, or brute-forced by this application at any point.
- **Never stores credentials in the repo, database, or logs.** `config/sources.yaml` lists only
  unauthenticated endpoints and file-watch folders; `config.py` deliberately has no
  credential-loading path — see `docs/production_backlog.md`. The one piece of session state this
  app can persist locally — browser cookies from a user-initiated login, see below — is not a
  credential (it contains no password or MFA secret) and is covered in its own section.
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
Remove-Item -Recurse -Force local_data\runs\*, local_data\uploads\*, local_data\raw_sources\*, local_data\database\*, local_data\logs\*, local_data\browser_profiles\*
```

(`local_data\browser_profiles\*` holds saved SSO session cookies — see "Persistent authenticated
browser sessions" below; clearing it signs out every saved profile and is equivalent to running
`cli browser-logout` for each one.)

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

**`playwright install chromium` hits the same proxy, but `pip-system-certs` does not fix it.**
That command downloads the actual browser binary through Playwright's own Node.js-based
downloader (bundled inside the `playwright` package, not your Python interpreter) — Node has a
completely separate TLS trust store from Python, so patching Python's never touches it. This
shows up as a Node stack trace ending in `Error: self-signed certificate in certificate chain` /
`code: 'SELF_SIGNED_CERT_IN_CHAIN'`, immediately after `pip install -e ".[browser-auth]"` succeeds
— it's an install-time failure, not something `classify_http_exception()` ever sees or classifies,
since it happens outside this application's own HTTP calls entirely.

**Fix:** export the same Windows-trusted root CA(s) to a PEM file and point Node at them via
`NODE_EXTRA_CA_CERTS`:

```powershell
$pemPath = "$env:USERPROFILE\corporate-root-cas.pem"
Remove-Item $pemPath -ErrorAction SilentlyContinue
foreach ($cert in Get-ChildItem Cert:\LocalMachine\Root) {
    $b64 = [System.Convert]::ToBase64String($cert.RawData, 'InsertLineBreaks')
    "-----BEGIN CERTIFICATE-----`n$b64`n-----END CERTIFICATE-----" | Add-Content -Path $pemPath -Encoding ascii
}
[Environment]::SetEnvironmentVariable("NODE_EXTRA_CA_CERTS", $pemPath, "User")
$env:NODE_EXTRA_CA_CERTS = $pemPath   # also set for the current session
playwright install chromium
```

If the corporate MITM CA is pushed to the per-user store instead of the machine store, add
`Cert:\CurrentUser\Root` to the `Get-ChildItem` list too. This is a one-time step per machine —
only needed for `playwright install`, never for normal application use afterward.

## Persistent authenticated browser sessions (SSO-gated sources, opt-in)

`gic_rates`, `money_market`, `hisa`, and `treasury_bills` are, per real captured evidence (a
`cli diagnose` debug bundle), genuinely gated by interactive corporate SSO — not a scraper bug. The
GIC product page redirects an unauthenticated request to a real Microsoft/Entra ID login page
(captured markers included `"sCompanyDisplayName":"IGMFinancial"` and a
`Shibboleth.sso/SAML2/POST` SAML redirect); no amount of header/regex tuning gets a plain
`httpx.get()` past that. `collectors/browser_session.py` (Playwright, optional — `pip install
-e ".[browser-auth]"` then `playwright install chromium`) adds a way past it that stays inside
every constraint above:

**What actually happens, step by step:**
1. You run `python -m cash_equivalents_mvp.cli browser-login --source gic_rates` (or any other
   configured source). This opens a normal, **visible** Chromium window at that source's real
   login-protected page.
2. You sign in yourself — username, password, MFA prompt — exactly as you would in your everyday
   browser. This app never sees, touches, or stores any of it; you're typing directly into
   Microsoft's / the source's own real login form, rendered by a real browser engine.
3. Once you're past the login page, the app detects it (by URL/content — the same login markers
   captured from the real debug bundle) and explicitly snapshots the resulting **session cookies**
   (Playwright's `context.storage_state()`) to `local_data/browser_profiles/<profile>/state.json`
   before closing the window — an explicit snapshot, not Chromium's own on-disk profile store,
   since a corporate SSO session cookie is typically a "session cookie" (no fixed expiry, by
   design, so it ends when the browser truly closes) and Chromium's profile persistence does not
   reliably carry those across separate automated runs the way an explicit snapshot does.
4. Automated runs afterward reuse that saved snapshot (`collectors/browser_session.py:
   authenticated_client` / `render_authenticated_page`) to make requests as your already-signed-in
   session — the same thing your browser does every time you reopen a tab without re-entering your
   password — and re-save it after each successful use, so any token refresh the site performs
   extends the saved session the same way it would if you'd left a real tab open. If the session
   has expired, the source correctly reports `SOURCE_BROWSER_SESSION_EXPIRED` and falls through to
   the next tier / `MANUAL_REQUIRED`, telling you to run `browser-login` again — it never tries to
   re-authenticate on its own.

**Why this doesn't violate "never bypasses authentication":** authentication still happens, in
full, every single time a session needs to be established or refreshed — by you, interactively, in
a real login form you can see. The app can reuse a session you already created; it cannot create
one, extend one past its natural expiry, or get past a login page on its own.

**What's stored locally, and what isn't:**
- Stored: session cookies and local storage for whatever site(s) you visited during that
  interactive login — the same category of data any browser profile holds after "stay signed in".
- Never stored: your password, MFA code/secret, or anything else you typed into the login form.
  It went straight into the real site's own login form and never passed through this
  application's code at all.
- `local_data/browser_profiles/` is under `local_data/`, already fully excluded by `.gitignore`
  (see "Local data hygiene" above) and included in that section's cleanup command.

**To revoke a session:** `cli browser-logout --profile igm_default` deletes the saved profile
directory outright (equivalent to signing out everywhere / clearing that browser profile). Do this
before handing off a machine, or any time you want to force a fresh interactive sign-in.

**Fully opt-in:** nothing above runs unless you explicitly install the `browser-auth` extra and run
`cli browser-login` yourself. Every responsibility's existing plain-HTTP and file-based tiers are
completely unaffected if you never do either — `config/sources.yaml`'s `browser_profile` keys are
inert until a matching profile actually exists on disk.

## Known gaps (tracked, not silently ignored)

- The Streamlit app has no authentication of its own — it's designed to run on `localhost` for a
  single local operator, not to be exposed on a shared network. See
  `docs/production_backlog.md` for the identity/RBAC work a real deployment needs.
- Settings are currently read/write only via `config/*.yaml` on disk (the Settings UI page is
  read-only) — there's no in-app secret store because there are no secrets to store yet.
