"""CSV fallback parser for GIC rates.

No real 'GIC Rates(Eng).csv' export was supplied in this environment (see
docs/source_inventory.md) so two shapes are supported:

1. Canonical structured schema (documented here, what the manual-upload CSV form expects):
   code,dealer,block,term_years,bucket_days,min,rate
   e.g. BNSGICR,Bank of Nova Scotia,cashables,1,,1000,1.75

2. A "GIC Rates(Eng)"-style wide export mirroring the xlsx Eng sheet's annual-pay block
   (code,dealer,min,1 year,2 year,3 year,4 year,5 year) is also accepted, detected by header.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

PARSER_VERSION = "gic_csv-1.0"

_WIDE_YEAR_HEADERS = {"1 year", "2 year", "3 year", "4 year", "5 year"}


def parse_gic_rates_csv(path: Path) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise ValueError("PARSER_NO_ROWS: CSV has no header row")
        fieldnames = {h.strip() for h in reader.fieldnames}
        rows: list[dict[str, Any]] = []

        if _WIDE_YEAR_HEADERS.issubset(fieldnames):
            for line in reader:
                code = (line.get("code") or "").strip()
                if not code:
                    continue
                for term_years, header in [(1, "1 year"), (2, "2 year"), (3, "3 year"),
                                            (4, "4 year"), (5, "5 year")]:
                    rows.append({
                        "block": "annual",
                        "code": code,
                        "dealer": (line.get("dealer") or "").strip() or None,
                        "min": line.get("min"),
                        "term_years": term_years,
                        "bucket_days": None,
                        "raw_value": line.get(header),
                    })
        elif {"code", "block", "rate"}.issubset(fieldnames):
            for line in reader:
                code = (line.get("code") or "").strip()
                if not code:
                    continue
                term_years_str = line.get("term_years") or None
                bucket_days_str = line.get("bucket_days") or None
                rows.append({
                    "block": (line.get("block") or "").strip(),
                    "code": code,
                    "dealer": (line.get("dealer") or "").strip() or None,
                    "min": line.get("min"),
                    "term_years": int(term_years_str) if term_years_str else None,
                    "bucket_days": int(bucket_days_str) if bucket_days_str else None,
                    "raw_value": line.get("rate"),
                })
        else:
            raise ValueError(
                "PARSER_NO_ROWS: CSV header did not match either the canonical schema "
                "(code,dealer,block,term_years,bucket_days,min,rate) or the wide annual-pay export "
                f"(got columns: {sorted(fieldnames)})"
            )

    if not rows:
        raise ValueError("PARSER_NO_ROWS: CSV contained no data rows")
    return rows
