"""Common contract suite (master prompt §16.2) for the three file-sourced responsibilities:
gic_rates, treasury_bills, hisa. Uses the real source_material/ fixtures for the success path
(skipped if unavailable) and tmp_path-based missing/invalid files for the failure paths, which
never require source_material and always run.
"""
from __future__ import annotations

import pytest

from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ManualInput, ResponsibilityStatus
from cash_equivalents_mvp.responsibilities.gic_rates import GicRatesResponsibility
from cash_equivalents_mvp.responsibilities.hisa import HisaResponsibility
from cash_equivalents_mvp.responsibilities.treasury_bills import TreasuryBillsResponsibility
from tests.conftest import requires_source_material, make_context


def _db(tmp_path):
    return Database(tmp_path / "contract_test.db")


RESP_CLASSES = [
    pytest.param(GicRatesResponsibility, "gic_rates", id="gic_rates"),
    pytest.param(TreasuryBillsResponsibility, "treasury_bills", id="treasury_bills"),
    pytest.param(HisaResponsibility, "hisa", id="hisa"),
]


@requires_source_material
@pytest.mark.parametrize("resp_cls,responsibility_id", RESP_CLASSES)
def test_automatic_success_from_source_material_fixture(tmp_path, resp_cls, responsibility_id):
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, responsibility_id)
    assert len(records) >= 1
    assert all(r.source_artifact_id for r in records)  # provenance present


@requires_source_material
@pytest.mark.parametrize("resp_cls,responsibility_id", RESP_CLASSES)
def test_automatic_idempotent_rerun(tmp_path, resp_cls, responsibility_id):
    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    resp.run_automatic(ctx)
    first = len(ctx.db.get_rate_records(ctx.run_id, responsibility_id))
    resp.run_automatic(ctx)
    second = len(ctx.db.get_rate_records(ctx.run_id, responsibility_id))
    assert first == second
    assert first >= 1


@pytest.mark.parametrize("resp_cls,responsibility_id", RESP_CLASSES)
def test_automatic_permanent_failure_when_source_missing(tmp_path, monkeypatch, resp_cls, responsibility_id):
    # Point every "watched folder" / source_material fallback at an empty tmp dir so no file is
    # ever found — this is the FILE_MISSING permanent-failure path, never retried.
    empty_dir = tmp_path / "empty_source_material"
    empty_dir.mkdir()
    import cash_equivalents_mvp.responsibilities.gic_rates as gic_mod
    import cash_equivalents_mvp.responsibilities.hisa as hisa_mod
    import cash_equivalents_mvp.responsibilities.treasury_bills as tbill_mod
    monkeypatch.setattr(gic_mod, "source_material_dir", lambda: empty_dir)
    monkeypatch.setattr(hisa_mod, "source_material_dir", lambda: empty_dir)
    monkeypatch.setattr(tbill_mod, "source_material_dir", lambda: empty_dir)
    # The configured file_watch folders (local_data/uploads/{gic_rates,tbills}) are relative
    # paths that don't exist in a clean checkout, so no monkeypatch is needed for them; this
    # assumes the repo's local_data/uploads/ tree hasn't been seeded with matching fixtures by
    # something else (it isn't, by default — the UI writes into a per-run subfolder instead).

    resp = resp_cls()
    ctx = make_context(_db(tmp_path), tmp_path)
    status = resp.run_automatic(ctx)
    assert status == ResponsibilityStatus.MANUAL_REQUIRED
    errors = ctx.db.get_errors(ctx.run_id, responsibility_id)
    assert errors[-1].error_code in ("FILE_MISSING", "SOURCE_AUTH_REQUIRED")
    assert errors[-1].retryable is False


def test_gic_rates_manual_fallback_rejected_for_bad_file_type(tmp_path):
    resp = GicRatesResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    bad_file = tmp_path / "not_a_workbook.txt"
    bad_file.write_text("this is not a spreadsheet")
    mi = ManualInput(responsibility_id="gic_rates", kind="file", file_path=str(bad_file),
                      original_filename="not_a_workbook.txt", override_reason="test")
    status = resp.run_manual(ctx, mi)
    assert status == ResponsibilityStatus.VALIDATION_FAILED


def test_hisa_manual_fallback_accepted_with_structured_rows(tmp_path):
    resp = HisaResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    mi = ManualInput(
        responsibility_id="hisa", kind="structured",
        structured_rows=[{"provider": "Test Bank HISA", "fund_code": "TB100", "currency": "CAD",
                           "raw_rate": "2.05", "minimum": 500, "maximum": 100000}],
        override_reason="manual entry test",
    )
    status = resp.run_manual(ctx, mi)
    assert status == ResponsibilityStatus.COMPLETE
    records = ctx.db.get_rate_records(ctx.run_id, "hisa")
    assert len(records) == 1
    assert records[0].manually_overridden is True


def test_hisa_manual_fallback_rejected_without_reason(tmp_path):
    resp = HisaResponsibility()
    ctx = make_context(_db(tmp_path), tmp_path)
    mi = ManualInput(
        responsibility_id="hisa", kind="structured",
        structured_rows=[{"provider": "Test Bank HISA", "fund_code": "TB100", "currency": "CAD", "raw_rate": "2.05"}],
        override_reason="",
    )
    status = resp.run_manual(ctx, mi)
    assert status == ResponsibilityStatus.VALIDATION_FAILED
