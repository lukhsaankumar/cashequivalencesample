import hashlib
from datetime import date
from decimal import Decimal

from cash_equivalents_mvp.audit import sha256_bytes, sha256_file
from cash_equivalents_mvp.models import RateRecord, ResponsibilityError, Run, RunStatus


def test_sha256_file_matches_hashlib(tmp_path):
    p = tmp_path / "sample.txt"
    p.write_bytes(b"hello world")
    assert sha256_file(p) == hashlib.sha256(b"hello world").hexdigest()


def test_sha256_bytes():
    assert sha256_bytes(b"abc") == hashlib.sha256(b"abc").hexdigest()


def test_run_serialization_roundtrip():
    run = Run(report_date=date(2026, 5, 11), status=RunStatus.CREATED)
    restored = Run.model_validate_json(run.model_dump_json())
    assert restored.run_id == run.run_id
    assert restored.report_date == date(2026, 5, 11)
    assert restored.status == RunStatus.CREATED


def test_rate_record_preserves_decimal_precision():
    rec = RateRecord(run_id="r1", responsibility_id="gic_rates", category="gic",
                      currency="CAD", rate=Decimal("0.0205"))
    restored = RateRecord.model_validate_json(rec.model_dump_json())
    assert restored.rate == Decimal("0.0205")
    assert isinstance(restored.rate, Decimal)


def test_responsibility_error_serialization_has_no_credentials_field():
    err = ResponsibilityError(run_id="r1", responsibility_id="gic_rates", stage="collect_automatic",
                               error_code="FILE_MISSING", message="no file found")
    payload = err.model_dump()
    assert "credentials" not in payload
    assert "password" not in str(payload).lower()
