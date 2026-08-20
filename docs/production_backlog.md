# Production Backlog

Documented but explicitly **not implemented** in this MVP, per the master prompt's scope
boundaries (§3, §21). Each item below is a real integration point this codebase already has a
seam for, not a vague aspiration.

## SharePoint template / source retrieval

`responsibilities/templates.py` and `responsibilities/gic_rates.py` currently read from
`source_material/` (a local approved-copy folder). The real approved templates and the GIC Rates
weekly file live in SharePoint (`docs/source_inventory.md` has the exact URLs, found in
`Step by Step Cash And Equivalents.docx`'s hyperlinks). A production version would add a
`sharepoint` collection method to `config/sources.yaml`, authenticated via the organization's SSO,
and a corresponding collector — the `Responsibility.collect_automatic()` interface doesn't change.

## Outlook draft creation via Microsoft Graph

`reporting/email_draft.py` writes a standalone `.eml` file today. Production would instead create
a real Outlook draft (still never send) via the Graph API's `POST /me/messages` with
`isDraft: true`, so the advisor can review and send from their own mailbox rather than downloading
an `.eml`.

## Organization identity and RBAC

The Streamlit app has no login. A shared deployment needs per-user identity (who approved this
run?), and role separation between "can run/upload" and "can approve for distribution."
`Run.approved_by` already exists as a field — it's currently just a free-text `"local_user"`.

## Enterprise scheduler

`config/settings.yaml: schedule` is present but informational only — nothing currently triggers a
run automatically on a cron schedule. A production deployment would wire this to the
organization's existing job scheduler (or a proper task queue) rather than relying on a human to
click "Create + Run All" every week.

## Centralized audit logging

Logs currently live in `local_data/logs/<run_id>.jsonl`, one file per machine. Production would
ship these to a centralized log store so an audit trail survives a workstation reimage and can be
queried across runs/users.

## Secrets management

There are currently no credentialed sources configured, so there's nothing to store. When
authenticated sources (Lipper, home.investorsgroup.com, SharePoint) are added, credentials belong
in an OS-level credential store or a proper secrets manager — never in `config/*.yaml`, never in
SQLite, never logged. `config.py` has no credential-loading path today, deliberately.

## Approved connectors: Advantage Plus, NBCN, Eikon

`config/sources.yaml`'s `treasury_bills` source watches a download folder because NBIN
(nbin.ca) is login-gated. A production deployment with an approved NBCN or Advantage Plus API
connector would replace the file-watch collector with a real API call — same
`Responsibility.collect_automatic()` contract.

## Gemini / AI review-agent integration

Explicitly out of scope by the master prompt's own instructions (§3: "Using an LLM at runtime,"
"Allowing Gemini, Claude, or Copilot to invent financial values" are both listed as out of scope).
No LLM call exists anywhere in the runtime pipeline; this stays that way in production too.

## Governed distribution list / maker-checker approval

`Run.approve_run()` exists as a single-approver gate. Production would add a second approval step
(maker-checker) before a package is considered ready to send, and the actual recipient list would
come from a governed, centrally-maintained distribution list rather than being entered ad hoc —
matching the master prompt's explicit prohibition on importing a recipient list into the UI.

## Automatic sending after formal approval

Never implemented, and not planned to be added casually — per the master prompt, sending stays a
human action even after all the automation above exists. If it's ever built, it should require the
maker-checker approval above plus the Outlook-draft integration, so the human is always the one
who clicks send.
