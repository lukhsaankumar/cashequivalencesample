"""Treasury-Bill responsibility — Canadian and US T-bill rates from an NBF/NBCN rate sheet PDF.

Automatic collection order:
  0. If a persistent browser session has been set up (`cli browser-login --source
     treasury_bills`), fetch the NBIN landing page (config/sources.yaml's automatic.url) using it,
     scrape it for a link to the current rate-sheet PDF, then download that via real browser
     navigation (JS executed, headless=False — same reasoning as gic_rates.py: if this tenant also
     enforces a device-trust check, only a real visible browser negotiating on an actually-enrolled
     machine has a chance at it; see browser_session.download_via_browser's docstring). NBIN
     (nbin.ca) is a separate, third-party vendor site — its login almost certainly has nothing to
     do with IGM's own Microsoft/Entra ID tenant, so a session established via `browser-login
     --source gic_rates` will very likely NOT cover it; it needs its own `cli browser-login
     --source treasury_bills` to sign in against NBIN specifically. No profile created yet -> this
     tier is a complete no-op, identical to before.

     This is a genuinely new tier, not a refinement of an old one: NBIN's real authenticated page
     structure had never been seen by this codebase before browser-session support existed (the
     old version of this file only ever did a bare reachability probe, never real extraction). The
     scrape logic below is a best-effort first pass, not something verified against a real captured
     page — same as gic_rates.py's PDF-link scraper before it. Any structure mismatch saves the
     actual HTML via collectors.http.save_debug_html rather than silently guessing wrong, exactly
     like every other web-pull tier in this codebase.
  1. Otherwise (or if the web tier fails), detect a newly downloaded T-bill PDF in the configured
     upload folder, falling back to source_material/ for the historical demo — matching master
     prompt step 2 ("monitor a configured download folder").
  2. Otherwise MANUAL_REQUIRED.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.collectors import browser_session
from cash_equivalents_mvp.collectors.http import classify_http_exception, describe_failure, save_debug_html
from cash_equivalents_mvp.config import raw_sources_dir, source_material_dir
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    SourceArtifact,
    ValidationResult,
)
from cash_equivalents_mvp.normalization.dates import term_days
from cash_equivalents_mvp.normalization.percentages import parse_and_normalize_rate
from cash_equivalents_mvp.parsers.nbf_tbill import PARSER_VERSION, parse_nbf_tbill_pdf
from cash_equivalents_mvp.responsibilities.base import Responsibility, RunContext
from cash_equivalents_mvp.validation.common import check_rate_range, finding

_PDF_CONTENT_TYPE_MARKER = "pdf"
_PDF_MAGIC = b"%PDF"


class TreasuryBillsResponsibility(Responsibility):
    responsibility_id = "treasury_bills"
    display_name = "Treasury Bills"
    dependencies = ()

    def _find_pdf_link_on_page(self, context: RunContext, page_url: str, timeout: float,
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
            debug_path = save_debug_html(context.run_id, "nbin_page_session_expired", resp.text)
            self._record_error(
                context, "collect_automatic", "SOURCE_BROWSER_SESSION_EXPIRED",
                f"{page_url} redirected to a login page even with a saved browser session — the "
                f"session has expired. Run: python -m cash_equivalents_mvp.cli browser-login "
                f"--source treasury_bills. Actual response saved to {debug_path}.",
                severity="warning",
            )
            raise browser_session.BrowserSessionExpiredError(page_url)

        soup = BeautifulSoup(resp.text, "lxml")
        for a in soup.find_all("a", href=True):
            href = str(a["href"])  # bs4 types this as str | AttributeValueList; hrefs are always str
            text = a.get_text(" ", strip=True).lower()
            if href.lower().endswith(".pdf"):
                return urljoin(page_url, href)
            if "rate" in text and ("t-bill" in text or "tbill" in text or "treasury" in text):
                return urljoin(page_url, href)

        # No matching link — save the actual HTML instead of guessing why next time. NBIN's real
        # authenticated page structure has never been confirmed against this scraper; whoever is
        # diagnosing a repeat of this (see docs/debugging.md) can open this file directly to see
        # exactly what came back and fix the link-matching heuristic above against real evidence.
        debug_path = save_debug_html(context.run_id, "nbin_page", resp.text)
        self._record_error(
            context, "collect_automatic", "SOURCE_LAYOUT_CHANGED",
            f"No T-bill rate PDF link found on {page_url} — page layout may have changed, or this "
            f"page requires an authenticated session to show its real content. Actual response "
            f"saved to {debug_path} for inspection.",
            severity="warning",
        )
        return None

    def _download_pdf(self, context: RunContext, url: str, timeout: float,
                       get_fn: Callable = httpx.get, using_browser_session: bool = False,
                       browser_profile: str | None = None) -> tuple[Path | None, bool]:
        """Mirrors gic_rates.py's _download_xlsx — same tiering, same reasoning, just for a PDF's
        magic bytes instead of an xlsx's. Returns (saved path, used_browser_download)."""
        if browser_profile:
            try:
                content = browser_session.download_via_browser(browser_profile, url, timeout, headless=False)
            except browser_session.BrowserDownloadNotTriggeredError as exc:
                self._record_error(context, "collect_automatic", "SOURCE_LAYOUT_CHANGED",
                                    f"{url}: {exc}", severity="warning")
                return None, False
            # BrowserSessionExpiredError intentionally not caught here — propagates to
            # collect_automatic, which downgrades every remaining tier to plain HTTP.
            if content is not None:
                dest_dir = raw_sources_dir() / context.run_id
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / "nbin_tbill_web.pdf"
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
        looks_like_pdf = _PDF_CONTENT_TYPE_MARKER in content_type or resp.content[:4] == _PDF_MAGIC
        if not looks_like_pdf:
            if using_browser_session and browser_session.is_login_page(str(resp.url), resp.text):
                debug_path = save_debug_html(context.run_id, "nbin_pdf_download_expired", resp.text)
                self._record_error(
                    context, "collect_automatic", "SOURCE_BROWSER_SESSION_EXPIRED",
                    f"{url} redirected to a login page even with a saved browser session — the "
                    f"session has expired. Run: python -m cash_equivalents_mvp.cli browser-login "
                    f"--source treasury_bills. Actual response saved to {debug_path}.",
                    severity="warning",
                )
                raise browser_session.BrowserSessionExpiredError(url)
            self._record_error(
                context, "collect_automatic", "SOURCE_AUTH_REQUIRED",
                f"{url} returned {content_type!r}, not a PDF — likely redirected to a login page. "
                f"Requires an authenticated session.",
                severity="warning",
            )
            return None, False

        dest_dir = raw_sources_dir() / context.run_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / "nbin_tbill_web.pdf"
        dest.write_bytes(resp.content)
        return dest, False

    def collect_automatic(self, context: RunContext) -> CollectionResult:
        cfg = context.source_config(self.responsibility_id).get("automatic", {})
        url = cfg.get("url")
        timeout = cfg.get("timeout_seconds", 15)
        browser_profile = cfg.get("browser_profile")

        web_path: Path | None = None
        web_method: str | None = None

        get_fn: Callable = httpx.get
        using_browser_session = False
        client = None
        if browser_profile:
            client = browser_session.authenticated_client(browser_profile, timeout)
            if client is not None:
                get_fn, using_browser_session = client.get, True

        if url:
            pdf_link = None
            try:
                pdf_link = self._find_pdf_link_on_page(context, url, timeout, get_fn=get_fn,
                                                        using_browser_session=using_browser_session)
            except browser_session.BrowserSessionExpiredError:
                # Already logged inside the helper. Downgrade to plain HTTP for the download tier
                # rather than retrying the same known-expired session again below.
                get_fn, using_browser_session, browser_profile, pdf_link = httpx.get, False, None, None

            if pdf_link:
                used_browser_download = False
                try:
                    web_path, used_browser_download = self._download_pdf(
                        context, pdf_link, timeout, get_fn=get_fn,
                        using_browser_session=using_browser_session, browser_profile=browser_profile)
                except browser_session.BrowserSessionExpiredError:
                    get_fn, using_browser_session, browser_profile = httpx.get, False, None
                    web_path, used_browser_download = self._download_pdf(
                        context, pdf_link, timeout, get_fn=get_fn,
                        using_browser_session=using_browser_session, browser_profile=browser_profile)
                if web_path:
                    web_method = ("web_scraped_authenticated" if (using_browser_session or used_browser_download)
                                  else "web_scraped")

        if client is not None:
            client.close()

        if web_path is not None:
            try:
                parsed = parse_nbf_tbill_pdf(web_path)
            except Exception as exc:
                self._record_error(context, "collect_automatic", "PARSER_NO_ROWS",
                                    f"Downloaded file from {url} did not parse as expected NBF "
                                    f"T-bill PDF layout: {exc}", severity="warning", exc=exc)
            else:
                artifact = SourceArtifact(
                    run_id=context.run_id, responsibility_id=self.responsibility_id,
                    filename=web_path.name, sha256=sha256_file(web_path),
                    collection_method=web_method or "web", source_url=url,
                    mime_type="application/pdf", local_path=str(web_path), parser_version=PARSER_VERSION,
                )
                rows = [{"currency": cur, **row} for cur, items in parsed.items() for row in items]
                return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows,
                                         artifact=artifact)

        # Web tier failed (or isn't configured) — fall through to file-based tiers, unchanged.
        folder = Path(cfg.get("folder", "local_data/uploads/tbills"))
        candidates = sorted(folder.glob("*.pdf")) if folder.exists() else []
        smd = source_material_dir()
        candidates += sorted(smd.glob("NBF T bill rates*.pdf")) + sorted(smd.glob("NBF*.pdf"))

        if not candidates:
            err = ResponsibilityError(
                run_id=context.run_id, responsibility_id=self.responsibility_id, stage="collect_automatic",
                error_code="FILE_MISSING", message="No NBF/NBCN T-bill rate PDF found.",
                suggested_action="Upload the NBF/NBCN PDF or text rate sheet on the Manual Uploads page.",
            )
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        path = candidates[0]
        try:
            parsed = parse_nbf_tbill_pdf(path)
        except Exception as exc:
            err = ResponsibilityError(run_id=context.run_id, responsibility_id=self.responsibility_id,
                                       stage="collect_automatic", error_code="PARSER_NO_ROWS", message=str(exc))
            return CollectionResult(ok=False, status=ResponsibilityStatus.MANUAL_REQUIRED, error=err)

        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id, filename=path.name,
            sha256=sha256_file(path), collection_method="file_watch_detected",
            mime_type="application/pdf", local_path=str(path), parser_version=PARSER_VERSION,
        )
        rows = [{"currency": cur, **row} for cur, items in parsed.items() for row in items]
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact)

    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult:
        if not manual_input.file_path:
            raise ValueError("Treasury Bills manual input requires an uploaded file")
        if not manual_input.override_reason:
            raise ValueError("MANUAL_OVERRIDE_REASON_MISSING")
        path = Path(manual_input.file_path)
        parsed = parse_nbf_tbill_pdf(path)
        artifact = SourceArtifact(
            run_id=context.run_id, responsibility_id=self.responsibility_id,
            filename=manual_input.original_filename or path.name, sha256=sha256_file(path),
            collection_method="manual_upload", mime_type="application/pdf",
            local_path=str(path), parser_version=PARSER_VERSION,
        )
        rows = [{"currency": cur, **row} for cur, items in parsed.items() for row in items]
        return CollectionResult(ok=True, status=ResponsibilityStatus.SUCCESS, raw_rows=rows, artifact=artifact,
                                 override_reason=manual_input.override_reason,
                                 override_user=manual_input.submitted_by)

    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]:
        records = []
        for row in collection.raw_rows:
            rate = parse_and_normalize_rate(row["yield_raw"])
            days = term_days(row["maturity_date"], context.report_date)
            records.append(RateRecord(
                run_id=context.run_id, responsibility_id=self.responsibility_id,
                category="tbill", provider="Government of Canada" if row["currency"] == "CAD" else "US Treasury",
                product_code=row.get("identifier"), currency=row["currency"],
                maturity_date=row["maturity_date"], term_days=days, rate=rate, gross_or_net="gross",
                source_artifact_id=collection.artifact.artifact_id if collection.artifact else None,
                extraction_method="deterministic_regex" if collection.artifact and collection.artifact.mime_type == "application/pdf" else "manual_entry",
                manually_overridden=bool(collection.override_reason),
                override_reason=collection.override_reason,
                override_user=collection.override_user,
            ))
        return records

    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult:
        findings = []
        rid = self.responsibility_id
        if not records:
            findings.append(finding(context.run_id, rid, "PARSER_NO_ROWS", "blocking", "No T-bill records produced"))
            return ValidationResult(ok=False, findings=findings)

        for r in records:
            findings += check_rate_range(context.run_id, rid, r.rate, f"TBills/{r.currency}/{r.maturity_date}")
            if r.term_days is not None and r.term_days < 0:
                findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "blocking",
                                         f"{r.currency} bill maturing {r.maturity_date} is before report date {context.report_date}"))

        cad = [r for r in records if r.currency == "CAD"]
        usd = [r for r in records if r.currency == "USD"]
        if len(cad) != 5:
            findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "warning",
                                     f"Expected 5 Canadian T-bill maturities, found {len(cad)}"))
        if len(usd) != 5:
            findings.append(finding(context.run_id, rid, "TBILL_TERM_DAY_MISMATCH", "warning",
                                     f"Expected 5 US T-bill maturities, found {len(usd)}"))

        return ValidationResult(ok=not any(f.severity == "blocking" for f in findings), findings=findings)
