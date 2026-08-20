"""Parses the NBF/NBCN T-bill rate PDF (single page, fixed-layout text — not a real PDF table).

Verified against source_material/NBF T bill rates.pdf (see docs/source_inventory.md):
    26/06/17  2.23  99.756    A03AS5      ...      26/06/16  3.52
    26/07/15  2.23  99.586    A03AS7               26/07/14  3.51
    ...
CAD rows: date(YY/MM/DD) yield% price identifier — 5 rows.
US rows: date(YY/MM/DD) yield% only, printed to the right of the CAD block — 5 rows.
"""
from __future__ import annotations

import re
from pathlib import Path

import fitz  # PyMuPDF

from cash_equivalents_mvp.normalization.dates import parse_yy_mm_dd

PARSER_VERSION = "nbf_tbill_pdf-1.0"

# CAD row: date, yield, price, identifier
_CAD_ROW = re.compile(
    r"(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<yield>\d+\.\d+)\s+(?P<price>\d+\.\d+)\s+(?P<id>[A-Z0-9]+)"
)
# US row: 'DD/MM/DD  yield' appearing after the "US BILLS" marker, one date+yield pair per line
_US_ROW = re.compile(r"(?P<date>\d{2}/\d{2}/\d{2})\s+(?P<yield>\d+\.\d+)\s*$", re.MULTILINE)


def parse_nbf_tbill_text(text: str) -> dict[str, list[dict]]:
    cad_rows = []
    for m in _CAD_ROW.finditer(text):
        cad_rows.append({
            "maturity_date": parse_yy_mm_dd(m.group("date")),
            "yield_raw": m.group("yield"),
            "price": m.group("price"),
            "identifier": m.group("id"),
        })

    us_marker = text.find("US BILLS")
    us_section = text[us_marker:] if us_marker != -1 else text
    us_rows = []
    for line in us_section.splitlines():
        us_match = _US_ROW.search(line.strip())
        if us_match:
            us_rows.append({
                "maturity_date": parse_yy_mm_dd(us_match.group("date")),
                "yield_raw": us_match.group("yield"),
                "price": None,
                "identifier": None,
            })

    if not cad_rows and not us_rows:
        raise ValueError("PARSER_NO_ROWS: no T-bill rows matched in NBF PDF text")

    return {"CAD": cad_rows, "USD": us_rows}


def parse_nbf_tbill_pdf(path: Path) -> dict[str, list[dict]]:
    doc = fitz.open(path)
    try:
        text = "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()
    return parse_nbf_tbill_text(text)
