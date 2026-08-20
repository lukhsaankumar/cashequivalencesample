from cash_equivalents_mvp.config import source_material_dir
from cash_equivalents_mvp.parsers.docx_links import extract_hyperlinks, is_ig_internal

from tests.conftest import requires_source_material


@requires_source_material
def test_extracts_seven_hyperlinks_from_info_docx():
    urls = extract_hyperlinks(source_material_dir() / "Info.docx")
    assert len(urls) == 7


@requires_source_material
def test_unwraps_safelinks_to_real_bank_of_canada_url():
    urls = extract_hyperlinks(source_material_dir() / "Info.docx")
    assert any(u == "https://www.bankofcanada.ca/" for u in urls)


@requires_source_material
def test_flags_ig_internal_sources():
    urls = extract_hyperlinks(source_material_dir() / "Info.docx")
    internal = [u for u in urls if is_ig_internal(u)]
    public = [u for u in urls if not is_ig_internal(u)]
    assert len(internal) == 5  # 2 home.investorsgroup.com + 3 digital.lipperweb.com
    assert any("bankofcanada.ca" in u for u in public)
    assert any("bankrate.com" in u for u in public)


def test_is_ig_internal_classifies_sharepoint():
    assert is_ig_internal("https://446346262425.sharepoint.com/teams/IG-WPS/")
    assert not is_ig_internal("https://www.bankofcanada.ca/")
