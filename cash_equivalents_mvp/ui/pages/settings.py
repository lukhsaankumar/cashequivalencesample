"""Page 8 — Settings: source modes, freshness limits, template paths, renderer preference,
Fed Funds / HISA selection rules, Bankers' Acceptance flag. Read-only display for now — editing
writes back to config/*.yaml, which is out of scope for this pass (see ASSUMPTIONS.md)."""
from __future__ import annotations

import streamlit as st

from cash_equivalents_mvp.config import business_rules, sources_config
from cash_equivalents_mvp.config import settings as app_settings
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header


def render() -> None:
    page_header("Settings", "Source configuration, business rules, and renderer preference.")

    st.info("Settings are currently read-only in the UI (edit `config/*.yaml` directly and restart). "
            "Editable forms with validation are planned — see docs/production_backlog.md.")

    card_start("Sources")
    for source_id, cfg in sources_config().items():
        c1, c2, c3 = st.columns([2, 1, 3])
        c1.write(f"**{source_id}**")
        c2.markdown(f"`{cfg.get('mode', 'n/a')}`")
        auto = cfg.get("automatic", {})
        c3.caption(auto.get("url") or auto.get("folder") or auto.get("type", ""))
    card_end()

    card_start("Business rules")
    rules = business_rules()
    st.write(f"**Fed Funds rule:** `{rules['fed_funds']['rule']}` "
             f"({rules['fed_funds']['rule_status']})")
    st.write(f"**HISA CDN summary product:** {rules['hisa_summary_selection']['cdn']['provider']}")
    st.write(f"**HISA US summary product:** {rules['hisa_summary_selection']['us']['provider']}")
    st.write(f"**Bankers' Acceptance enabled:** {rules['bankers_acceptance']['enabled']} "
             f"({rules['bankers_acceptance']['status']})")
    st.write(f"**Money market comparison table enabled:** {rules['money_market_comparison_table']['enabled']} "
             f"({rules['money_market_comparison_table']['status']})")
    card_end()

    card_start("Renderer preference")
    st.write(app_settings()["renderer"]["preference"])
    card_end()

    card_start("Output paths")
    st.write(f"Templates: {app_settings()['templates']}")
    st.write(f"Output directory: `{app_settings()['output_dir']}`")
    st.write(f"Upload directory: `{app_settings()['upload_dir']}`")
    card_end()
