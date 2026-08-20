"""Bilingual (EN/FR) numeric parity check — re-reads both saved workbooks and compares actual
cell values, rather than assuming parity because both were written from the same canonical
Decimal. Catches a class of bug the "write once, format twice" design doesn't rule out by
construction: a stale re-read, a mis-targeted FR cell, or a mapping-config drift between
workbook_map_en.yaml and workbook_map_fr.yaml.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

import openpyxl

from cash_equivalents_mvp.normalization.percentages import parse_french_percent_text


@dataclass
class ParityResult:
    ok: bool
    mismatches: list[str] = field(default_factory=list)


def _read_en_numeric(wb, sheet: str, cell: str) -> Decimal | None:
    value = wb[sheet][cell].value
    if value is None:
        return None
    return Decimal(str(value))


def _read_fr_value(wb, sheet: str, cell: str, value_format: str) -> Decimal | None:
    value = wb[sheet][cell].value
    if value is None:
        return None
    if value_format == "numeric":
        return Decimal(str(value))
    return parse_french_percent_text(str(value))


def check_bilingual_parity(en_path: Path, fr_path: Path, wmap_en: dict, wmap_fr: dict) -> ParityResult:
    """Compares the Prime, Fed Funds, and money-market-yield cells between EN and FR — the cells
    whose coordinates and value_format are both individually verified (see workbook_mapping.md).
    A full every-cell reconciliation is future work; see ASSUMPTIONS.md.
    """
    wb_en = openpyxl.load_workbook(en_path, data_only=True)
    wb_fr = openpyxl.load_workbook(fr_path, data_only=True)
    mismatches: list[str] = []

    for section in ("prime", "fed_funds"):
        en_cfg, fr_cfg = wmap_en[section], wmap_fr[section]
        en_sheet = wmap_en["sheets"][en_cfg["sheet"]]
        fr_sheet = wmap_fr["sheets"][fr_cfg["sheet"]]
        en_val = _read_en_numeric(wb_en, en_sheet, en_cfg["value_cell"])
        fr_val = _read_fr_value(wb_fr, fr_sheet, fr_cfg["value_cell"], fr_cfg.get("value_format", "numeric"))
        if en_val is None or fr_val is None:
            mismatches.append(f"{section}: missing value (EN={en_val}, FR={fr_val})")
        elif en_val != fr_val:
            mismatches.append(f"{section}: EN={en_val} != FR={fr_val}")

    mm_en, mm_fr = wmap_en["money_market_text"], wmap_fr["money_market_text"]
    en_sheet = wmap_en["sheets"][mm_en["sheet"]]
    fr_sheet = wmap_fr["sheets"][mm_fr["sheet"]]
    for cell_key in ("cad_cell", "us_cell"):
        en_text = wb_en[en_sheet][mm_en[cell_key]].value or ""
        fr_text = wb_fr[fr_sheet][mm_fr[cell_key]].value or ""
        try:
            # Compare as numbers, not digit strings: FR's "trim_zero" convention legitimately
            # renders 2.00% as "2%" (see normalization/percentages.py) while EN keeps "2.00%" —
            # same value, different precision, not a real mismatch.
            en_num = Decimal("".join(c for c in en_text if c.isdigit() or c == "."))
            fr_num = Decimal("".join(c for c in fr_text if c.isdigit() or c == ",").replace(",", "."))
        except Exception:
            mismatches.append(f"money_market {cell_key}: could not parse EN={en_text!r} / FR={fr_text!r}")
            continue
        if en_num != fr_num:
            mismatches.append(f"money_market {cell_key}: EN={en_text!r} ({en_num}) != FR={fr_text!r} ({fr_num})")

    return ParityResult(ok=not mismatches, mismatches=mismatches)
