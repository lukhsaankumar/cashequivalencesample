"""Streamlit UI entry point. Run with: streamlit run cash_equivalents_mvp/ui/app.py"""
from __future__ import annotations

import datetime as dt

import streamlit as st

from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.pages import (
    dashboard,
    debugging,
    manual_inputs,
    outputs,
    responsibilities,
    review,
    settings,
    validation,
)
from cash_equivalents_mvp.ui.theme import IG_LOGO_SVG, inject_global_css

st.set_page_config(
    page_title="Cash and Cash Equivalents — Reporting",
    page_icon="\U0001F4C8",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(inject_global_css(), unsafe_allow_html=True)

st.markdown(
    f"""
    <div class="ig-header">
        <div>{IG_LOGO_SVG}</div>
        <div class="ig-header-right">
            Cash and Cash Equivalents &mdash; Automated Reporting<br/>
            <span style="opacity:0.75">Local MVP &middot; {dt.date.today().isoformat()}</span>
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown('<div class="ig-sidebar-title" style="font-size:1.05rem;padding:4px 0 14px 0;">'
                'CASH &amp; CASH EQUIVALENTS</div>', unsafe_allow_html=True)

    runs = state.get_db().list_runs()
    if runs:
        options = [r.run_id for r in runs]
        labels = {r.run_id: f"{r.report_date.isoformat()} • {r.status.value if hasattr(r.status,'value') else r.status}"
                  for r in runs}
        current = state.ensure_selected_run()
        idx = options.index(current) if current in options else 0
        picked = st.selectbox("Active run", options, index=idx, format_func=lambda rid: labels[rid])
        state.set_selected_run_id(picked)
    else:
        st.caption("No runs yet — create one from the Dashboard.")

    st.markdown('<hr class="ig-divider"/>', unsafe_allow_html=True)

PAGES = {
    "Dashboard": dashboard,
    "Responsibility Status": responsibilities,
    "Manual Uploads & Inputs": manual_inputs,
    "Review & Comparison": review,
    "Validation": validation,
    "Outputs & Downloads": outputs,
    "Debugging": debugging,
    "Settings": settings,
}

with st.sidebar:
    choice = st.radio("Navigate", list(PAGES.keys()), label_visibility="collapsed")

PAGES[choice].render()
