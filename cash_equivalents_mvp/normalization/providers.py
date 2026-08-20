"""Provider identity resolution from GIC/HISA product codes.

Product codes observed in GIC Rates.xlsx and the report workbook follow
<PREFIX><SUFFIX> where PREFIX identifies the provider and SUFFIX identifies the product family:
  R = redeemable/cashable (1yr term)     e.g. BNSGICR
  P = payout / short-term deposit        e.g. BNSGICP
  G = GIC 1yr-5yr (annual/compound/monthly, disambiguated by which block it's in) e.g. BNSG
Some providers use a bare 3-letter prefix (BNS, EQB...), others 4 (HOBK, HTC not 3+1).
"""
from __future__ import annotations

import functools
import re

from cash_equivalents_mvp.config import provider_aliases


@functools.lru_cache(maxsize=1)
def _prefixes() -> list[str]:
    # longest first so "HOBK" matches before a hypothetical shorter "HO" prefix would
    return sorted(provider_aliases().keys(), key=len, reverse=True)


def normalize_code(code: str) -> str:
    return re.sub(r"\s+", "", code or "").upper()


def provider_name_for_code(code: str) -> str | None:
    """Resolve a product code (e.g. 'BNSGICR', ' BNSGICP', 'HOBKGICR') to a canonical provider name."""
    norm = normalize_code(code)
    for prefix in _prefixes():
        if norm.startswith(prefix):
            return provider_aliases()[prefix]
    return None


def provider_prefix_for_code(code: str) -> str | None:
    norm = normalize_code(code)
    for prefix in _prefixes():
        if norm.startswith(prefix):
            return prefix
    return None


def same_provider(code_a: str, code_b: str) -> bool:
    """True if two product codes belong to the same provider (e.g. BNSGICR vs BNSG)."""
    a, b = provider_prefix_for_code(code_a), provider_prefix_for_code(code_b)
    return a is not None and a == b
