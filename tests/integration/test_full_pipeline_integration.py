"""End-to-end integration test: the real DAG, through real Excel COM rendering, producing real
EN/FR workbooks and 7-page PDFs. Requires Microsoft Excel (or LibreOffice) to be installed —
skipped automatically if neither is available, since that's an environment fact, not something
this suite can fake convincingly (unlike HTTP/file sources, there's no meaningful way to mock
"Excel recalculated this workbook correctly").

This is slower than the rest of the suite (real Excel automation, ~30-90s) — kept in
tests/integration/ rather than tests/unit/ so the fast suite stays fast, but it still requires no
internet access and runs entirely offline, so it's part of the default `pytest` run in this repo.
"""
from __future__ import annotations

from datetime import date

import fitz
import openpyxl
import pytest

from cash_equivalents_mvp.config import database_path, settings
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ManualInput
from cash_equivalents_mvp.orchestration.manager import RunManager
from cash_equivalents_mvp.reporting.renderer_selection import select_renderer
from tests.conftest import requires_source_material

_renderer_name, _renderer = select_renderer(settings()["renderer"]["preference"])

requires_renderer = pytest.mark.skipif(
    _renderer is None, reason="Neither Microsoft Excel nor LibreOffice is available in this environment"
)


@requires_source_material
@requires_renderer
def test_full_pipeline_produces_real_seven_page_bilingual_package(tmp_path):
    db = Database(tmp_path / "integration.db")
    mgr = RunManager(db)
    run = mgr.create_run(date(2026, 5, 11))

    status = mgr.execute_run(run.run_id)
    states = db.all_responsibility_states(run.run_id)

    # money_market is expected to require manual input in this environment (Lipper needs the IG
    # VPN) — supply it, exactly like a real operator would on the Manual Uploads page.
    if states.get("money_market", {}).get("status") == "MANUAL_REQUIRED":
        mi = ManualInput(
            responsibility_id="money_market", kind="numeric",
            numeric_fields={"cad_yield": "2.00", "us_yield": "2.82"},
            override_reason="integration test: VPN unavailable, using historical fixture value",
        )
        mgr.submit_manual_input(run.run_id, mi)

    run = db.get_run(run.run_id)
    assert run.status.value == "READY_FOR_REVIEW", db.all_responsibility_states(run.run_id)

    from pathlib import Path
    outputs_dir = Path(run.output_dir) / "outputs"
    files = {f.name: f for f in outputs_dir.iterdir()}
    assert any(n.endswith("EN.xlsx") for n in files)
    assert any(n.endswith("FR.xlsx") for n in files)
    assert any(n.endswith("EN.pdf") for n in files)
    assert any(n.endswith("FR.pdf") for n in files)
    assert any(n.endswith(".eml") for n in files)
    assert any(n.endswith(".zip") for n in files)

    en_pdf = next(f for n, f in files.items() if n.endswith("EN.pdf"))
    fr_pdf = next(f for n, f in files.items() if n.endswith("FR.pdf"))
    for pdf_path in (en_pdf, fr_pdf):
        doc = fitz.open(pdf_path)
        try:
            assert doc.page_count == 7
            full_text = "\n".join(p.get_text() for p in doc)
            for token in ("#REF!", "#VALUE!", "#NAME?", "#DIV/0!"):
                assert token not in full_text
        finally:
            doc.close()

    en_xlsx = next(f for n, f in files.items() if n.endswith("EN.xlsx"))
    wb = openpyxl.load_workbook(en_xlsx, data_only=True)
    assert wb["Cash"]["D31"].value is not None  # Prime was written and recalculated
    assert wb["Cover"]["I29"].value.date() == date(2026, 5, 11)

    eml_path = next(f for n, f in files.items() if n.endswith(".eml"))
    import email
    with open(eml_path, "rb") as fh:
        msg = email.message_from_binary_file(fh)
    assert not msg.get("To", "").strip()
    assert not msg.get("Cc", "").strip()
    assert not msg.get("Bcc", "").strip()

    db.close()


@requires_source_material
@requires_renderer
def test_source_templates_remain_byte_identical_after_a_full_run(tmp_path):
    from cash_equivalents_mvp.audit import sha256_file
    from cash_equivalents_mvp.config import source_material_dir

    en_src = source_material_dir() / settings()["templates"]["en"]
    fr_src = source_material_dir() / settings()["templates"]["fr"]
    before_en, before_fr = sha256_file(en_src), sha256_file(fr_src)

    db = Database(tmp_path / "integration2.db")
    mgr = RunManager(db)
    run = mgr.create_run(date(2026, 5, 11))
    mgr.execute_run(run.run_id)
    db.close()

    assert sha256_file(en_src) == before_en
    assert sha256_file(fr_src) == before_fr
