"""Extracts hyperlink targets from a .docx file's relationship table, unwrapping Outlook
Safelinks so the real destination URL is what gets returned. Used at bootstrap time to build
docs/source_inventory.md and to identify which sources need the IG VPN — see that doc.
"""
from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import docx

PARSER_VERSION = "docx_links-1.0"


def _unwrap_safelink(url: str) -> str:
    parsed = urlparse(url)
    if "safelinks.protection.outlook.com" not in parsed.netloc:
        return url
    qs = parse_qs(parsed.query)
    real = qs.get("url")
    return unquote(real[0]) if real else url


def extract_hyperlinks(path: Path) -> list[str]:
    """Returns unwrapped, deduplicated hyperlink URLs found in the document's relationships."""
    doc = docx.Document(str(path))
    rels = doc.part.rels
    urls = [
        _unwrap_safelink(rel.target_ref)
        for rel in rels.values()
        if rel.reltype.endswith("hyperlink") and rel.target_ref
    ]
    seen: list[str] = []
    for u in urls:
        if u not in seen:
            seen.append(u)
    return seen


def is_ig_internal(url: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    return "investorsgroup.com" in netloc or "lipperweb.com" in netloc or "sharepoint.com" in netloc
