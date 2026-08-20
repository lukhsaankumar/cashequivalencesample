import zipfile
from pathlib import Path

import pytest

from cash_equivalents_mvp.security import safe_extract_zip, safe_join, sanitize_filename, validate_extension


def test_sanitize_filename_strips_path_components():
    assert sanitize_filename("../../etc/passwd") == "passwd"
    assert sanitize_filename("C:\\Windows\\System32\\evil.xlsx") == "evil.xlsx"


def test_sanitize_filename_strips_unsafe_characters():
    assert sanitize_filename('weird<>:"|?*name.csv') == "weird_______name.csv"


def test_sanitize_filename_rejects_hidden_file_trick():
    assert not sanitize_filename("..hidden").startswith(".")


def test_sanitize_filename_empty_becomes_unnamed():
    assert sanitize_filename("") == "unnamed"
    assert sanitize_filename("///") == "unnamed"


def test_validate_extension_accepts_known():
    assert validate_extension("GIC Rates.xlsx") == ".xlsx"


def test_validate_extension_rejects_unknown():
    with pytest.raises(ValueError, match="FILE_TYPE_INVALID"):
        validate_extension("malware.exe")


def test_safe_join_blocks_path_traversal(tmp_path):
    # Two layers of defense: sanitize_filename() strips directory components first (so
    # "../../../etc/passwd" is already reduced to "passwd" before the traversal check even
    # runs), and safe_join()'s own resolved-path check is what would fire if a name somehow
    # got through with separators intact. Either way, the result must stay inside base_dir.
    base = tmp_path / "uploads"
    base.mkdir()
    result = safe_join(base, "../../../etc/passwd")
    assert result.parent == base.resolve()
    assert result.name == "passwd"


def test_safe_join_result_is_always_a_direct_child_of_base_dir(tmp_path):
    # sanitize_filename() guarantees no separators survive, so safe_join()'s own resolved-path
    # check is unreachable through the public API — this pins that invariant down explicitly
    # rather than leaving it as an untested assumption.
    base = tmp_path / "uploads"
    base.mkdir()
    for attempt in ("../evil.txt", "..\\..\\evil.txt", "/etc/evil.txt", "a/b/../../evil.txt"):
        result = safe_join(base, attempt)
        assert result.parent == base.resolve()


def test_safe_join_allows_normal_filename(tmp_path):
    base = tmp_path / "uploads"
    base.mkdir()
    result = safe_join(base, "GIC Rates.xlsx")
    assert result.parent == base.resolve()


def test_safe_extract_zip_blocks_zip_slip(tmp_path):
    zip_path = tmp_path / "evil.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../evil.txt", "pwned")

    dest = tmp_path / "extract_dest"
    with zipfile.ZipFile(zip_path) as zf:
        extracted = safe_extract_zip(zf, dest)

    # zip-slip member is sanitized down to a plain filename inside dest, never escapes it
    assert all(dest.resolve() in p.parents or p.parent == dest.resolve() for p in extracted)
    assert not (tmp_path / "evil.txt").exists()
