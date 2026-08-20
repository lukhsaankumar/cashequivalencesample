"""Filename sanitization, path traversal prevention, safe archive extraction."""
from __future__ import annotations

import re
import zipfile
from pathlib import Path

_UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

ALLOWED_EXTENSIONS = {
    ".xlsx", ".xlsm", ".csv", ".pdf", ".txt", ".eml", ".docx", ".png", ".jpg", ".jpeg",
}

ALLOWED_MIME_BY_EXT = {
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
    ".csv": {"text/csv", "application/vnd.ms-excel", "text/plain"},
    ".pdf": {"application/pdf"},
    ".txt": {"text/plain"},
}


def sanitize_filename(name: str) -> str:
    """Strip directory components and disallowed characters. Never trust an uploaded filename."""
    name = Path(name).name  # drops any path component, defeats ../ and absolute paths
    name = _UNSAFE_CHARS.sub("_", name).strip()
    name = name.lstrip(".")  # no hidden-file / relative tricks
    if not name:
        name = "unnamed"
    return name[:200]


def validate_extension(filename: str, allowed: set[str] | None = None) -> str:
    ext = Path(filename).suffix.lower()
    allowed = allowed or ALLOWED_EXTENSIONS
    if ext not in allowed:
        raise ValueError(f"FILE_TYPE_INVALID: extension {ext!r} not in {sorted(allowed)}")
    return ext


def safe_join(base_dir: Path, filename: str) -> Path:
    """Join a sanitized filename onto base_dir, refusing anything that escapes it."""
    base_dir = base_dir.resolve()
    candidate = (base_dir / sanitize_filename(filename)).resolve()
    if base_dir not in candidate.parents and candidate != base_dir:
        raise ValueError(f"Path traversal attempt blocked for {filename!r}")
    return candidate


def safe_extract_zip(zf: zipfile.ZipFile, dest_dir: Path) -> list[Path]:
    """Extract a zip, rejecting any member that would escape dest_dir (zip-slip guard)."""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    for member in zf.infolist():
        if member.is_dir():
            continue
        target = safe_join(dest_dir, Path(member.filename).name)
        with zf.open(member) as src, open(target, "wb") as out:
            out.write(src.read())
        extracted.append(target)
    return extracted
