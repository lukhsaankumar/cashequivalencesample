from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from cash_equivalents_mvp.config import source_material_dir  # noqa: E402
from cash_equivalents_mvp.database import Database  # noqa: E402
from cash_equivalents_mvp.models import Run  # noqa: E402
from cash_equivalents_mvp.responsibilities.base import RunContext  # noqa: E402

HISTORICAL_REPORT_DATE = date(2026, 5, 11)

requires_source_material = pytest.mark.skipif(
    not source_material_dir().exists() or not any(source_material_dir().iterdir()),
    reason="source_material/ fixtures not present in this environment",
)


@pytest.fixture
def tmp_db(tmp_path) -> Database:
    db = Database(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def run_context(tmp_db, tmp_path) -> RunContext:
    run = Run(report_date=HISTORICAL_REPORT_DATE)
    tmp_db.create_run(run)
    run_dir = tmp_path / "run"
    run_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=run.run_id, report_date=run.report_date, run_dir=run_dir,
                       db=tmp_db, manual_uploads_dir=upload_dir)


def make_context(tmp_db, tmp_path, report_date=HISTORICAL_REPORT_DATE) -> RunContext:
    run = Run(report_date=report_date)
    tmp_db.create_run(run)
    run_dir = tmp_path / f"run_{run.run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    upload_dir = tmp_path / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    return RunContext(run_id=run.run_id, report_date=run.report_date, run_dir=run_dir,
                       db=tmp_db, manual_uploads_dir=upload_dir)
