"""Canonical data model. All rates are Decimal, never float."""
from __future__ import annotations

import enum
import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class ResponsibilityStatus(str, enum.Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    SUCCESS_WITH_WARNINGS = "SUCCESS_WITH_WARNINGS"
    RETRYING = "RETRYING"
    AUTOMATIC_FAILED = "AUTOMATIC_FAILED"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    MANUAL_UPLOADED = "MANUAL_UPLOADED"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    BLOCKED = "BLOCKED"
    SKIPPED = "SKIPPED"
    COMPLETE = "COMPLETE"


TERMINAL_STATUSES = {
    ResponsibilityStatus.COMPLETE,
    ResponsibilityStatus.SKIPPED,
}

FAILURE_STATUSES = {
    ResponsibilityStatus.AUTOMATIC_FAILED,
    ResponsibilityStatus.MANUAL_REQUIRED,
    ResponsibilityStatus.VALIDATION_FAILED,
    ResponsibilityStatus.BLOCKED,
}


class RunStatus(str, enum.Enum):
    CREATED = "CREATED"
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    NEEDS_MANUAL_INPUT = "NEEDS_MANUAL_INPUT"
    VALIDATION_FAILED = "VALIDATION_FAILED"
    READY_FOR_REVIEW = "READY_FOR_REVIEW"
    APPROVED = "APPROVED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class Run(BaseModel):
    model_config = ConfigDict(use_enum_values=False)

    run_id: str = Field(default_factory=lambda: new_id("run"))
    report_date: date
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = None
    completed_at: datetime | None = None
    status: RunStatus = RunStatus.CREATED
    renderer: str | None = None
    source_manifest_hash: str | None = None
    approved_at: datetime | None = None
    approved_by: str | None = None
    output_dir: str | None = None


class SourceArtifact(BaseModel):
    artifact_id: str = Field(default_factory=lambda: new_id("art"))
    run_id: str
    responsibility_id: str
    filename: str
    sha256: str
    source_url: str | None = None
    retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    effective_at: datetime | None = None
    collection_method: str
    mime_type: str
    local_path: str
    parser_version: str
    freshness_status: str = "unknown"


class RateRecord(BaseModel):
    record_id: str = Field(default_factory=lambda: new_id("rec"))
    run_id: str
    responsibility_id: str
    category: str
    provider: str | None = None
    product_name: str | None = None
    product_code: str | None = None
    currency: str
    account_type: str | None = None
    interest_type: str | None = None
    payment_frequency: str | None = None
    maturity_date: date | None = None
    term_days: int | None = None
    term_years: int | None = None
    rate: Decimal
    gross_or_net: str = "gross"
    minimum_purchase: Decimal | None = None
    maximum_purchase: Decimal | None = None
    corporate_eligible: bool | None = None
    insurance_eligible: bool | None = None
    redeemable: bool | None = None
    source_artifact_id: str | None = None
    source_page_or_sheet: str | None = None
    source_cell_or_location: str | None = None
    source_effective_at: datetime | None = None
    extraction_method: str = "unknown"
    extraction_confidence: Decimal | None = None
    selection_rule_id: str | None = None
    selection_reason: str | None = None
    manually_overridden: bool = False
    override_reason: str | None = None
    override_user: str | None = None
    validation_status: str = "unvalidated"


class ResponsibilityError(BaseModel):
    run_id: str
    responsibility_id: str
    stage: str
    error_code: str
    severity: str = "error"
    retryable: bool = False
    message: str
    expected: str | None = None
    actual: str | None = None
    exception_type: str | None = None
    sanitized_traceback: str | None = None
    source_artifact_id: str | None = None
    occurred_at: datetime = Field(default_factory=datetime.utcnow)
    suggested_action: str = ""


class ValidationFinding(BaseModel):
    run_id: str
    responsibility_id: str
    rule_id: str
    severity: str  # blocking | warning | info
    message: str
    location: str | None = None
    occurred_at: datetime = Field(default_factory=datetime.utcnow)


class ManualInput(BaseModel):
    """Payload submitted from the Manual Uploads and Inputs UI page."""

    responsibility_id: str
    kind: str  # "file" | "numeric" | "structured"
    file_path: str | None = None
    original_filename: str | None = None
    numeric_fields: dict[str, str] = Field(default_factory=dict)
    structured_rows: list[dict] = Field(default_factory=list)
    effective_date: date | None = None
    override_reason: str
    submitted_by: str = "local_user"
    submitted_at: datetime = Field(default_factory=datetime.utcnow)


class CollectionResult(BaseModel):
    """Output of collect_automatic / parse_manual_input before normalization."""

    ok: bool
    status: ResponsibilityStatus
    raw_rows: list[dict] = Field(default_factory=list)
    artifact: SourceArtifact | None = None
    error: ResponsibilityError | None = None
    warnings: list[str] = Field(default_factory=list)
    override_reason: str | None = None  # set by parse_manual_input; normalize() must audit it
    override_user: str | None = None


class ValidationResult(BaseModel):
    ok: bool
    findings: list[ValidationFinding] = Field(default_factory=list)

    @property
    def has_blocking(self) -> bool:
        return any(f.severity == "blocking" for f in self.findings)
