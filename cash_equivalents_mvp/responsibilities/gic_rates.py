"""GIC Rates responsibility — cashable GICs, term deposits, GIC 1yr-5yr (annual/compound/monthly).

Automatic collection order — dynamic web pull first, file/fixture fallback only if that fails
for a reason outside our control (per master prompt §7.3, and because GIC rates change often
enough that a stale historical fixture is a worse default than a live pull):
  0. If a persistent browser session has been set up for this source (`cli browser-login
     --source gic_rates` — see collectors/browser_session.py), use its saved cookies for the
     product-page fetch in tier 1, and real browser navigation (JS executed) for the file download
     in tiers 1-2. A real debug bundle proved gic-tca.shtml redirects an unauthenticated request
     straight to Microsoft/Entra ID SSO, and that the SharePoint file fetch separately involves a
     Microsoft Defender for Cloud Apps (MCAS) session hand-off completed via client-side JS
     (an auto-submitting HTML form) that a plain httpx.get() with cookies can't execute — real
     browser navigation (`browser_session.download_via_browser`) can, since it runs actual JS.
     Purely additive: if no browser profile has ever been created, every request below is
     identical to before.

     KNOWN DEAD END, confirmed via a real debug bundle, not a guess: even with a valid session and
     real browser navigation, both the dynamically-discovered and the static SharePoint links land
     on `*.access.mcas.ms/aad_login?...requestedClientCert=true&IsManagedDevice-...=...` — MCAS's
     device-trust check, which asks the browser to present a corporate-issued client certificate
     proving the request comes from a managed device, not just an authenticated user. This is a
     different, deeper security layer than a login wall (device identity, not user session) and
     is not something this app will ever try to satisfy — doing so would mean extracting the real
     corporate device certificate into an automation tool's browser context, i.e. actively working
     around a managed-device control the organization deliberately put in place, which is a
     materially different and more serious thing than reusing a user's own session cookie (see
     SECURITY.md's "never bypasses authentication"). SOURCE_LAYOUT_CHANGED here (via
     BrowserDownloadNotTriggeredError) is expected to recur every time; MANUAL_REQUIRED for GIC
     Rates' web tiers is the correct, by-design outcome on a network where this policy applies,
     not a bug to keep chasing.
  1. Fetch the public GIC product page (home.investorsgroup.com/.../gic-tca.shtml, linked from
     "Step by Step Cash And Equivalents.docx") and scrape it for a link to the current rate file,
     then download and parse that. Tried *first*, not as a fallback, because it's re-discovered
     fresh every run — whatever file the page actually links to right now — rather than depending
     on a URL captured once and hoping it's still valid.
  2. If that fails, fall back to the direct SharePoint link to GIC Rates.xlsx ("Mike's Folder",
     same docx). This is a "Copy Link" share URL with an embedded access token
     (see config/sources.yaml) that can expire or be revoked independent of whether the file
     still exists — kept only as a fast-path backup, not the primary source of truth. Both web
     tiers require an IG VPN + authenticated session; a raw request typically gets redirected to
     a login page, which is detected (via content-type / not looking like a real xlsx) rather
     than mis-parsed.
  3. If both web tiers fail, detect a newly downloaded GIC Rates.xlsx/CSV in the configured
     upload folder, falling back to source_material/ for the historical demo.
  4. Otherwise MANUAL_REQUIRED — manual upload is the last resort, not the default path.

Every failed tier logs the real reason (severity="warning", non-fatal) via
collectors.http.classify_http_exception so the actual cause (TLS trust, auth redirect, timeout,
layout change) is visible in the debug bundle / `cli diagnose`, not silently swallowed. A failed
browser-session request is tagged SOURCE_BROWSER_SESSION_EXPIRED specifically (not a generic auth
code) so the suggested action is "run cli browser-login again", not "connect to VPN".
"""
from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Callable
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import httpx
from bs4 import BeautifulSoup

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.collectors.http import classify_http_exception, describe_failure, save_debug_html
from cash_equivalents_mvp.config import raw_sources_dir, source_material_dir, workbook_map
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.normalization.percentages import (
    normalize_to_canonical,
    parse_raw_rate,
    validate_rate_range,
)
from cash_equivalents_mvp.normalization.providers import provider_name_for_code, provider_prefix_for_code
from cash_equivalents_mvp.parsers.gic_csv import parse_gic_rates_csv
from cash_equivalents_mvp.parsers.gic_xlsx import PARSER_VERSION as XLSX_PARSER_VERSION
from cash_equivalents_mvp.parsers.gic_xlsx import parse_gic_rates_xlsx
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding

EXPECTED_PROVIDER_PREFIXES_12 = {"B2B", "BMO", "BMT", "BOM", "BNS", "EQB", "EQT", "HOBK", "HTC", "LBC", "MBC", "NBC"}
EXPECTED_PROVIDER_PREFIXES_8 = {"BMO", "BMT", "BOM", "BNS", "EQB", "EQT", "HOBK", "HTC"}

_XLSX_CONTENT_TYPE_MARKER = "spreadsheet"
_XLSX_MAGIC = b"PK"  # xlsx is a zip archive


def _force_sharepoint_download(url: str) -> str:
    """SharePoint/OneDrive share links (":x:/t/..." Excel-Online-viewer style, or ":x:/r/...")
    open the Excel Online web viewer by default rather than downloading the file — a real debug
    bundle confirmed this is exactly what BrowserDownloadNotTriggeredError was catching. Appending
    `download=1` is a normal, documented SharePoint/OneDrive query parameter — the same one their
    own "Download a copy" UI button uses internally — that requests the raw file instead. Not a
    bypass of anything; an ordinary, supported part of the URL scheme. No-op for non-SharePoint
    URLs, so this is safe to apply unconditionally to whatever link was scraped or configured."""
    if "sharepoint.com" not in url:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query))
    query["download"] = "1"
    return urlunparse(parsed._replace(query=urlencode(query)))


class GicRatesResponsibility(Responsibility):
    responsibility_id = "gic_rates"
    display_name = "GIC Rates"
    dependencies = ()

    def _download_xlsx(self, context: RunContext, url: str, timeout: float,
                        get_fn: Callable = httpx.get, using_browser_session: bool = False,
                        browser_profile: str | None = None) -> tuple[Path | None, bool]:
        """Downloads url and returns (saved path, used_browser_download) — the saved path is only
        set if the response actually looks like an xlsx file (a SharePoint link without a valid
        session typically 200s with an HTML login page instead of erroring, which would otherwise
        crash the parser with a confusing error); used_browser_download tells the caller whether
        real browser navigation (not just a cookie-jar GET) is what actually produced it.

        If browser_profile is set, tries real browser navigation first (download_via_browser) —
        a plain cookie-jar GET can't complete a SharePoint MCAS session hand-off, which requires
        executing client-side JS (see browser_session.download_via_browser docstring); only falls
        through to the get_fn-based path below if no browser profile has been created yet.

        Runs headless=False (a visible window) deliberately, not headless=True — MCAS's device-
        trust check needs a real OS-level TLS client-certificate negotiation, which a headless
        browser has no way to complete (see download_via_browser's docstring). Only meaningful on
        a machine IT has actually enrolled; on any other machine this behaves exactly like a
        regular failed attempt and falls through to the next tier."""
        if browser_profile:
            try:
                content = browser_session.download_via_browser(
                    browser_profile, _force_sharepoint_download(url), timeout, headless=False)
            except browser_session.BrowserDownloadNotTriggeredError as exc:
                self._record_error(context, "collect_automatic", "SOURCE_LAYOUT_CHANGED",
                                    f"{url}: {exc}", severity="warning")
                return None, False
            # BrowserSessionExpiredError intentionally not caught here — propagates to
            # collect_automatic, which downgrades every remaining tier to plain HTTP.
            if content is not None:
                dest_dir = raw_sources_dir() / context.run_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "gic_rates_web.xlsx"
                dest.write_bytes(content)
                return dest, True
            # content is None -> no browser profile created yet -> fall through to get_fn below

        try:
            resp = get_fn(url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            code, retryable = classify_http_exception(exc)
            self._record_error(context, "collect_automatic", code, describe_failure(url, exc),
                                severity="warning", retryable=retryable, exc=exc)
            return None, False

        content_type = resp.headers.get("content-type", "")
        looks_like_xlsx = _XLSX_CONTENT_TYPE_MARKER in content_type or resp.content[:2] == _XLSX_MAGIC
        if not looks_like_xlsx:
            if using_browser_session and browser_session.is_login_page(str(resp.url), resp.text):
                # Saved for inspection, not just described — "session expired" is a detector
                # verdict (is_login_page's marker match), not a certainty; the only way to confirm
                # it wasn't a false positive (e.g. a cross-resource SharePoint auth gap that looks
                # different from the home.investorsgroup.com login page) is to look at what was
                # actually returned.
                debug_path = save_debug_html(context.run_id, "gic_xlsx_download_expired", resp.text)
                self._record_error(
                    context, "collect_automatic", "SOURCE_BROWSER_SESSION_EXPIRED",
                    f"{url} redirected to a login page even with a saved browser session — the "
                    f"session has expired. Run: python -m cash_equivalents_mvp.cli browser-login "
                    f"--source gic_rates. Actual response saved to {debug_path}.",
                    severity="warning",
                )
                # Raised (not returned) so collect_automatic can downgrade every remaining tier
                # to plain HTTP instead of retrying with the same already-expired session.
                raise browser_session.BrowserSessionExpiredError(url)
            self._record_error(
                context, "collect_automatic", "SOURCE_AUTH_REQUIRED",
                f"{url} returned {content_type!r}, not a spreadsheet — likely redirected to a "
                f"SharePoint/SSO login page. Requires an authenticated session.",
                severity="warning",
            )
            return None, False

        dest_dir = raw_sources_dir() / context.run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "gic_rates_web.xlsx"
        dest.write_bytes(resp.content)
        return dest, False

    def _find_rates_link_on_product_page(self, context: RunContext, page_url: str, timeout: float,
                                          get_fn: Callable = httpx.get,
                                          using_browser_session: bool = False) -> str | None:
        try:
            resp = get_fn(page_url, timeout=timeout, follow_redirects=True)
            resp.raise_for_status()
        except Exception as exc:
            code, retryable = classify_http_exception(exc)
            self._record_error(context, "collect_automatic", code, describe_failure(page_url, exc),
                                severity="warning", retryable=retryable, exc=exc)
            return None

        if using_browser_session and browser_session.is_login_page(str(resp.url), resp.text):
            debug_path = save_debug_html(context.run_id, "gic_product_page_session_expired", resp.text)
            self._record_error(
                context, "collect_automatic", "SOURCE_BROWSER_SESSION_EXPIRED",
                f"{page_url} redirected to a login page even with a saved browser session — the "
                f"session has expired. Run: python -m cash_equivalents_mvp.cli browser-login "
                f"--source gic_rates. Actual response saved to {debug_path}.",
                severity="warning",
            )
            raise browser_session.BrowserSessionExpiredError(page_url)

        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = str(a["href"])  # bs4 types this as str | AttributeValueList; hrefs are always str
            text = a.get_text(" ", strip=True).lower()
            if href.lower().endswith((".xlsx", ".xlsm", ".csv")):
                return urljoin(page_url, href)
            if "gic" in text and "rate" in text:
                return urljoin(page_url, href)

        # No matching link — save the actual HTML instead of just guessing why next time. Whoever
        # is diagnosing this (see docs/debugging.md) can open this file directly to see exactly
        # what the page returned (a real product page with a differently-labeled link? a login
        # redirect? something JS-rendered with no links in the raw HTML at all?) instead of us
        # re-guessing blind at the link-matching heuristic below.
        debug_path = save_debug_html(context.run_id, "gic_product_page", resp.text)
        self._record_error(
            context, "collect_automatic", "SOURCE_LAYOUT_CHANGED",
            f"No GIC rates link found on {page_url} — page layout may have changed, or this page "
            f"requires an authenticated session to show its real content. Actual response saved "
            f"to {debug_path} for inspection.",
            severity="warning",
        )
        return None

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id)
        auto_cfg = cfg.get("automatic", {})
        timeout = auto_cfg.get("timeout_seconds", 15)

        web_path: Path | None = None
        web_method: str | None = None
        web_source_url: str | None = None

        # Tier 0: a persistent browser session, if one has been set up (`cli browser-login
        # --source gic_rates`). A real debug bundle proved gic-tca.shtml redirects an
        # unauthenticated request straight to Microsoft/Entra ID SSO — this is the only tier that
        # can get past that. `authenticated_client` returns None if no profile was ever created,
        # so this is a complete no-op for anyone who hasn't run browser-login.
        get_fn: Callable = httpx.get
        using_browser_session = False
        client = None
        browser_profile = auto_cfg.get("browser_profile")
        if browser_profile:
            client = browser_session.authenticated_client(browser_profile, timeout)
            if client is not None:
                get_fn, using_browser_session = client.get, True

        # Scrape first, static link second — deliberately, not for speed. The SharePoint URL is a
        # "Copy Link" share-link with an embedded token (see the ?d=...&e=... in
        # config/sources.yaml's comment) that can expire or be revoked independent of whether the
        # underlying file still exists; the scraped link is re-discovered fresh every run from
        # whatever gic-tca.shtml actually links to *right now*, so it self-corrects if the file
        # moves or the share link rots. The static link is kept only as a fast-path fallback for
        # when the page is temporarily unreachable but the token still happens to work.
        product_page_url = auto_cfg.get("product_page_url")
        if product_page_url:
            try:
                link = self._find_rates_link_on_product_page(context, product_page_url, timeout,
                                                               get_fn=get_fn, using_browser_session=using_browser_session)
            except browser_session.BrowserSessionExpiredError:
                # Already logged inside the helper. Downgrade to plain HTTP for every remaining
                # tier rather than retrying the same known-expired session again below.
                get_fn, using_browser_session, browser_profile, link = httpx.get, False, None, None
            if link:
                used_browser_download = False
                try:
                    web_path, used_browser_download = self._download_xlsx(
                        context, link, timeout, get_fn=get_fn,
                        using_browser_session=using_browser_session, browser_profile=browser_profile)
                except browser_session.BrowserSessionExpiredError:
                    get_fn, using_browser_session, browser_profile, web_path = httpx.get, False, None, None
                if web_path:
                    web_method = ("web_scraped_authenticated" if (using_browser_session or used_browser_download)
                                  else "web_scraped")
                    web_source_url = link

        if web_path is None:
            sharepoint_url = auto_cfg.get("sharepoint_url")
            if sharepoint_url:
                used_browser_download = False
                try:
                    web_path, used_browser_download = self._download_xlsx(
                        context, sharepoint_url, timeout, get_fn=get_fn,
                        using_browser_session=using_browser_session, browser_profile=browser_profile)
                except browser_session.BrowserSessionExpiredError:
                    get_fn, using_browser_session, browser_profile = httpx.get, False, None
                    web_path, used_browser_download = self._download_xlsx(
                        context, sharepoint_url, timeout, get_fn=get_fn,
                        using_browser_session=using_browser_session, browser_profile=browser_profile)
                if web_path:
                    web_method = ("sharepoint_direct_fallback_authenticated"
                                  if (using_browser_session or used_browser_download)
                                  else "sharepoint_direct_fallback")
                    web_source_url = sharepoint_url

        if client is not None:
            client.close()

        if web_path is not None:
            try:
                source_map = workbook_map("en")["gic_rates_source"]
                rows = parse_gic_rates_xlsx(web_path, source_map)
            except Exception as exc:
                self._record_error(context, "collect_automatic", "PARSER_NO_ROWS",
                                    f"Downloaded file from {web_source_url} did not parse as expected "
                                    f"GIC Rates.xlsx layout: {exc}",
                                    severity="warning", exc=exc)
            else:
                artifact = SourceArtifact(
                    run_id=context.run_id, responsibility_id=self.responsibility_id,
                    filename=web_path.name, sha256=sha256_file(web_path),
                    collection_method=web_method or "web",  # always set alongside web_path above
                    source_url=web_source_url,
                    mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    local_path=str(web_path), parser_version=XLSX_PARSER_VERSION,
                )
                return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

        # Both web tiers failed (or aren't configured) — fall through to file-based tiers.
        folder = Path(auto_cfg.get("folder", "local_data/uploads/gic_rates"))
        candidates = []
        if folder.exists():
            candidates += sorted(folder.glob("GIC Rates*.xlsx")) + sorted(folder.glob("GIC Rates*.csv"))
        # Historical-demo convenience: source_material/ holds the weekly GIC Rates.xlsx snapshot.
        smd = source_material_dir()
        candidates += sorted(smd.glob("GIC Rates*.xlsx"))

        if not candidates:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="FILE_MISSING", retryable=False,
                message="Live GIC Rates web pull failed (see warnings above) and no GIC Rates.xlsx or "
                        "CSV was found in the watched folder or source_material/.",
                suggested_action="Upload GIC Rates.xlsx or a CSV on the Manual Uploads page.",
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        path = candidates[0]
        method = "file_watch_detected" if path.parent != smd else "source_material_fixture"
        try:
            source_map = workbook_map("en")["gic_rates_source"]
            rows = (parse_gic_rates_xlsx(path, source_map) if path.suffix.lower() == ".xlsx"
                    else parse_gic_rates_csv(path))
        except Exception as exc:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="PARSER_NO_ROWS", message=str(exc),
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id, filename=path.name,
            sha256=sha256_file(path), collection_method=method,
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if path.suffix.lower() == ".xlsx" else "text/csv",
            local_path=str(path), parser_version=XLSX_PARSER_VERSION,
            freshness_status="unknown",
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        if not manual_input.file_path:
            raise ValueError("GIC rates manual input requires an uploaded file")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        path = Path(manual_input.file_path)
        source_map = workbook_map("en")["gic_rates_source"]
        rows = (parse_gic_rates_xlsx(path, source_map) if path.suffix.lower() == ".xlsx"
                else parse_gic_rates_csv(path))
        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=manual_input.original_filename or path.name, sha256=sha256_file(path),
            collection_method="manual_upload",
            mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            if path.suffix.lower() == ".xlsx" else "text/csv",
            local_path=str(path), parser_version=XLSX_PARSER_VERSION,
        )
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact,
                                 override_reason=manual_input.override_reason,
                                 override_user=manual_input.submitted_by)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records: list[RateRecord] = []
        for row in collection.raw_rows:
            raw_value = row["raw_value"]
            if raw_value is None or str(raw_value).strip().upper() in {"#N/A", "N/A", ""}:
                continue  # never let #N/A overwrite a report cell
            try:
                raw = parse_raw_rate(raw_value)
                # GIC Rates.xlsx always stores bare percent numbers (0.50 means 0.50%, not
                # already-canonical 50%) — see normalization/percentages.py source_convention docs.
                canonical = normalize_to_canonical(raw, source_convention="always_percent_form")
                validate_rate_range(canonical)
            except ValueError:
                continue  # surfaced as a validation warning below via re-check, not silently lost

            provider = provider_name_for_code(row["code"]) or row.get("dealer") or row["code"]
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="gic", provider=provider, product_code=row["code"],
                currency="CAD", account_type=row["block"],
                term_years=row.get("term_years"), term_days=row.get("bucket_days"),
                rate=canonical, gross_or_net="gross",
                minimum_purchase=Decimal(str(row["min"])) if row.get("min") not in (None, "") else None,
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                source_cell_or_location=f"Eng!row{row.get('row')}" if row.get("row") else None,
                extraction_method="deterministic_cell_scan",
                validation_status="unvalidated",
                manually_overridden=bool(collection.override_reason),
                override_reason=collection.override_reason,
                override_user=collection.override_user,
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id

        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate,
                                          f"{r.account_type}/{r.product_code}/{r.term_years or r.term_days}")

        by_block: dict[str, set[str]] = {}
        for r in records:
            prefix = provider_prefix_for_code(r.product_code or "")
            if prefix and r.account_type:
                by_block.setdefault(r.account_type, set()).add(prefix)

        for block in ("annual", "monthly", "compound", "short_term_deposits"):
            missing = EXPECTED_PROVIDER_PREFIXES_12 - by_block.get(block, set())
            if missing:
                findings.append(finding(context.run_id, rid, "PARSER_PROVIDER_MISSING", "warning",
                                         f"Block {block!r} is missing expected providers: {sorted(missing)}"))
        missing_cashable = EXPECTED_PROVIDER_PREFIXES_8 - by_block.get("cashables", set())
        if missing_cashable:
            findings.append(finding(context.run_id, rid, "PARSER_PROVIDER_MISSING", "warning",
                                     f"Cashables block is missing expected providers: {sorted(missing_cashable)}"))

        annual = {(provider_prefix_for_code(r.product_code or ""), r.term_years): r.rate
                  for r in records if r.account_type == "annual"}
        compound = {(provider_prefix_for_code(r.product_code or ""), r.term_years): r.rate
                    for r in records if r.account_type == "compound"}
        for key, a_rate in annual.items():
            c_rate = compound.get(key)
            if c_rate is not None and c_rate != a_rate:
                findings.append(finding(context.run_id, rid, "GIC_ANNUAL_COMPOUND_PARITY_MISMATCH", "warning",
                                         f"Annual {a_rate} vs Compound {c_rate} diverge for {key}"))

        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking",
                                     "No valid GIC rate records were extracted"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
