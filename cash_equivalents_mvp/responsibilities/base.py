"""Responsibility interface. Every business function (GIC rates, Prime, T-bills, ...)
implements this and gets uniform status tracking, retries, and error capture for free
via `execute()` / `run_manual()`, called by the orchestrator."""
from __future__ import annotations

import traceback
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from cash_equivalents_mvp.config import business_rules, settings, sources_config, workbook_map
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import (
    CollectionResult,
    ManualInput,
    RateRecord,
    ResponsibilityError,
    ResponsibilityStatus,
    ValidationResult,
)


@dataclass
class RunContext:
    run_id: str
    report_date: date
    run_dir: Path
    db: Database
    manual_uploads_dir: Path

    def source_config(self, responsibility_id: str) -> dict:
        return sources_config().get(responsibility_id, {})

    def business_rules(self) -> dict:
        return business_rules()

    def workbook_map(self, language: str) -> dict:
        return workbook_map(language)

    def settings(self) -> dict:
        return settings()


class Responsibility(ABC):
    responsibility_id: str
    display_name: str
    dependencies: tuple[str, ...] = ()
    max_retries: int = 2
    retryable_error_codes: tuple[str, ...] = (
        "SOURCE_HTTP_TIMEOUT", "SOURCE_HTTP_403",
    )

    # ---- interface methods every subclass implements ----
    @abstractmethod
    def collect_automatic(self, context: RunContext) -> CollectionResult: ...

    @abstractmethod
    def parse_manual_input(self, context: RunContext, manual_input: ManualInput) -> CollectionResult: ...

    @abstractmethod
    def normalize(self, context: RunContext, collection: CollectionResult) -> list[RateRecord]: ...

    @abstractmethod
    def validate(self, context: RunContext, records: list[RateRecord]) -> ValidationResult: ...

    def persist(self, context: RunContext, records: list[RateRecord]) -> None:
        context.db.clear_rate_records(context.run_id, self.responsibility_id)
        context.db.save_rate_records(records)

    # ---- shared orchestration, not overridden by subclasses ----
    def _set_status(self, context: RunContext, status: ResponsibilityStatus,
                     attempts: int | None = None, **detail) -> None:
        context.db.set_responsibility_status(context.run_id, self.responsibility_id, status,
                                              attempts=attempts, detail=detail or None)

    def _record_error(self, context: RunContext, stage: str, error_code: str, message: str,
                       *, retryable: bool = False, severity: str = "error",
                       expected: str | None = None, actual: str | None = None,
                       exc: BaseException | None = None) -> ResponsibilityError:
        err = ResponsibilityError(
            run_id=context.run_id,
            responsibility_id=self.responsibility_id,
            stage=stage,
            error_code=error_code,
            severity=severity,
            retryable=retryable,
            message=message,
            expected=expected,
            actual=actual,
            exception_type=type(exc).__name__ if exc else None,
            sanitized_traceback=_sanitize_traceback(exc) if exc else None,
            suggested_action=_suggest_action(error_code),
        )
        context.db.save_error(err)
        return err

    def run_automatic(self, context: RunContext) -> ResponsibilityStatus:
        """Full pipeline: collect_automatic -> normalize -> validate -> persist.

        collect_automatic is retried in-process for transient errors (SOURCE_HTTP_TIMEOUT etc,
        per retryable_error_codes) before falling back to MANUAL_REQUIRED — see orchestration/retries.py.
        """
        from cash_equivalents_mvp.orchestration.retries import collect_with_retries

        self._set_status(context, ResponsibilityStatus.RUNNING)
        try:
            collection, attempts = collect_with_retries(
                lambda: self.collect_automatic(context), self.max_retries, self.retryable_error_codes,
            )
        except Exception as exc:  # collector raised instead of returning a CollectionResult
            self._record_error(context, "collect_automatic", "SOURCE_NOT_CONFIGURED", str(exc), exc=exc)
            self._set_status(context, ResponsibilityStatus.AUTOMATIC_FAILED, attempts=1)
            return ResponsibilityStatus.AUTOMATIC_FAILED

        if not collection.ok:
            if collection.error:
                context.db.save_error(collection.error)
            self._set_status(context, ResponsibilityStatus.MANUAL_REQUIRED, attempts=attempts,
                              last_automatic_error=collection.error.error_code if collection.error else None)
            return ResponsibilityStatus.MANUAL_REQUIRED

        return self._finish_pipeline(context, collection)

    def run_manual(self, context: RunContext, manual_input: ManualInput) -> ResponsibilityStatus:
        self._set_status(context, ResponsibilityStatus.RUNNING)
        try:
            collection = self.parse_manual_input(context, manual_input)
        except Exception as exc:
            self._record_error(context, "parse_manual_input", "FILE_TYPE_INVALID", str(exc), exc=exc)
            self._set_status(context, ResponsibilityStatus.VALIDATION_FAILED)
            return ResponsibilityStatus.VALIDATION_FAILED

        if not collection.ok:
            if collection.error:
                context.db.save_error(collection.error)
            self._set_status(context, ResponsibilityStatus.VALIDATION_FAILED)
            return ResponsibilityStatus.VALIDATION_FAILED

        status = self._finish_pipeline(context, collection)
        if status in (ResponsibilityStatus.SUCCESS, ResponsibilityStatus.SUCCESS_WITH_WARNINGS,
                      ResponsibilityStatus.COMPLETE):
            self._set_status(context, ResponsibilityStatus.MANUAL_UPLOADED)
            self._set_status(context, status)
        return status

    def _finish_pipeline(self, context: RunContext, collection: CollectionResult) -> ResponsibilityStatus:
        try:
            records = self.normalize(context, collection)
        except Exception as exc:
            self._record_error(context, "normalize", "PARSER_NO_ROWS", str(exc), exc=exc)
            self._set_status(context, ResponsibilityStatus.VALIDATION_FAILED)
            return ResponsibilityStatus.VALIDATION_FAILED

        try:
            result = self.validate(context, records)
        except Exception as exc:
            self._record_error(context, "validate", "WORKBOOK_MAPPING_INVALID", str(exc), exc=exc)
            self._set_status(context, ResponsibilityStatus.VALIDATION_FAILED)
            return ResponsibilityStatus.VALIDATION_FAILED

        context.db.clear_findings(context.run_id, self.responsibility_id)
        context.db.save_findings(result.findings)

        if result.has_blocking:
            self._set_status(context, ResponsibilityStatus.VALIDATION_FAILED)
            return ResponsibilityStatus.VALIDATION_FAILED

        self.persist(context, records)
        status = (ResponsibilityStatus.SUCCESS_WITH_WARNINGS if result.findings
                  else ResponsibilityStatus.SUCCESS)
        self._set_status(context, status, record_count=len(records))
        self._set_status(context, ResponsibilityStatus.COMPLETE, record_count=len(records))
        return ResponsibilityStatus.COMPLETE


def _sanitize_traceback(exc: BaseException) -> str:
    """Traceback text only — never includes local variable values, which could contain
    credentials or full source payloads."""
    lines = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return "".join(lines)[-4000:]


_SUGGESTIONS = {
    "SOURCE_AUTH_REQUIRED": "Connect to the IG VPN and an authenticated session, or upload the file manually.",
    "SOURCE_HTTP_403": "The source blocked the request. Upload the file manually.",
    "SOURCE_HTTP_TIMEOUT": "Retry, or upload the file manually if the source stays unreachable.",
    "FILE_MISSING": "Upload the required file on the Manual Uploads page.",
    "FILE_TYPE_INVALID": "Upload a file of the expected type.",
    "PARSER_NO_ROWS": "Check the uploaded file matches the expected format.",
    "PARSER_PROVIDER_MISSING": "The expected provider row was not found; verify the source file is current.",
    "PERCENTAGE_SCALE_AMBIGUOUS": "Verify the rate value manually before approving.",
    "WORKBOOK_LABEL_MISMATCH": "The workbook template layout may have changed; re-verify the mapping.",
}


def _suggest_action(error_code: str) -> str:
    return _SUGGESTIONS.get(error_code, "Review the error details and retry or supply manual input.")
