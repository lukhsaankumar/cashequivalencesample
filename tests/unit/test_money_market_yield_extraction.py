"""Unit tests for money_market.py's _extract_current_yield / _YIELD_PATTERN — the actual page
structure was captured twice via a real rendered debug HTML (browser_session.render_authenticated_page)
against a genuinely signed-in Lipper session, not guessed: a two-cell table row where the label
carries its own "(%)" and the value has no trailing "%" at all. An earlier version of the regex
excluded "%" from the gap between "yield" and the number, which broke on the label's own "(%)"
and never matched a single real page.
"""
from __future__ import annotations

from cash_equivalents_mvp.responsibilities.money_market import _extract_current_yield

# Real structure, reduced to the essential row — captured from a real rendered Lipper page.
REAL_TABLE_ROW_HTML = """
<table><tbody>
<tr><td class="">NAV ($)</td><td class="" style="text-align: right;">10.0000 (as of 8/20/2026)</td></tr>
<tr><td class="">MER (%)</td><td class="" style="text-align: right;">0.49 (as of 3/31/2026)</td></tr>
<tr><td class="">Fund Codes - NL</td><td class="" style="text-align: right;">IGI1632</td></tr>
<tr><td class="">Current Yield (%)</td><td class="" style="text-align: right;">1.88 (8/20/2026)</td></tr>
</tbody></table>
"""


def test_extracts_real_table_row_format():
    assert _extract_current_yield(REAL_TABLE_ROW_HTML) == "1.88"


def test_does_not_confuse_mer_row_with_current_yield():
    mer_only_html = """
    <table><tbody>
    <tr><td>MER (%)</td><td>0.49 (as of 3/31/2026)</td></tr>
    </tbody></table>
    """
    assert _extract_current_yield(mer_only_html) is None


def test_still_matches_older_synthetic_inline_format():
    """Backward compatible with the simpler "Current Yield 2.00%" inline-text shape used by
    existing test fixtures (test_http_responsibility_contracts.py's LIPPER_HTML) — the fix widens
    what's matched, it doesn't narrow it."""
    assert _extract_current_yield("<html><body>Current Yield 2.00%</body></html>") == "2.00"


def test_returns_none_when_no_yield_present():
    assert _extract_current_yield("<html><body>Nothing relevant here.</body></html>") is None
