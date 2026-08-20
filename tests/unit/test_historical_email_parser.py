from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.parsers.historical_email import extract_attachments, parse_eml_summary

from tests.conftest import requires_source_material

EML_NAME = "Cash and Cash Equivalent - May 4th, 2026.eml"


@requires_source_material
def test_parse_eml_summary_never_exposes_recipient_address():
    summary = parse_eml_summary(source_material_dir() / EML_NAME)
    assert "to" not in summary
    assert "@" not in str(summary)  # no email address anywhere in the structural summary
    assert summary["has_recipient"] is True  # structurally present (a boolean), but not echoed


@requires_source_material
def test_parse_eml_summary_finds_four_attachments():
    summary = parse_eml_summary(source_material_dir() / EML_NAME)
    assert len(summary["attachments"]) == 4
    names = {a["filename"] for a in summary["attachments"]}
    assert any(n.endswith(".pdf") for n in names)
    assert any(n.endswith(".xlsx") for n in names)


@requires_source_material
def test_extract_attachments_writes_real_files(tmp_path):
    dest = tmp_path / "extracted"
    extracted = extract_attachments(source_material_dir() / EML_NAME, dest)
    assert len(extracted) == 4
    for p in extracted:
        assert p.exists()
        assert p.parent == dest.resolve()
        assert p.stat().st_size > 0


@requires_source_material
def test_extract_attachments_sanitizes_and_cannot_escape_dest_dir(tmp_path):
    dest = tmp_path / "extracted"
    extracted = extract_attachments(source_material_dir() / EML_NAME, dest)
    for p in extracted:
        assert dest.resolve() in p.resolve().parents
