"""Page 1 — Dashboard: run list, headline metrics, and run-level actions."""
from __future__ import annotations

import datetime as dt

import streamlit as st

from cash_equivalents_mvp.config import settings as app_settings
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.orchestration.graph import build_registry
from cash_equivalents_mvp.reporting.renderer_selection import select_renderer
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, metric_row, page_header, status_badge


def render() -> None:
    page_header("Dashboard", "Weekly runs of the Cash and Cash Equivalents EN/FR reporting package.")

    db = state.get_db()
    mgr = state.get_manager()

    _, renderer = select_renderer(app_settings()["renderer"]["preference"])
    renderer_ok = renderer is not None

    card_start("Start a new run")
    c1, c2, c3 = st.columns([2, 1, 1])
    with c1:
        report_date = st.date_input("Report date", value=dt.date.today())
    with c2:
        st.markdown("<br/>", unsafe_allow_html=True)
        create_clicked = st.button("Create New Run", width='stretch')
    with c3:
        st.markdown("<br/>", unsafe_allow_html=True)
        run_clicked = st.button("Create + Run All", type="primary", width='stretch')
    if not renderer_ok:
        st.warning("No workbook renderer detected (Microsoft Excel or LibreOffice). Runs can still "
                   "collect rates, but Workbook Rendering / PDF Export will fail until one is installed. "
                   "Run `python -m cash_equivalents_mvp.cli doctor` for details.")
    card_end()

    if create_clicked or run_clicked:
        run = mgr.create_run(report_date)
        state.set_selected_run_id(run.run_id)
        if run_clicked:
            with st.spinner("Running all responsibilities..."):
                mgr.execute_run(run.run_id)
        st.rerun()

    runs = db.list_runs()
    if not runs:
        st.info("No runs yet. Create one above to get started.")
        return

    total = len(runs)
    latest = runs[0]
    latest_states = db.all_responsibility_states(latest.run_id)
    n_complete = sum(1 for s in latest_states.values() if s["status"] == ResponsibilityStatus.COMPLETE.value)
    n_manual = sum(1 for s in latest_states.values() if s["status"] == ResponsibilityStatus.MANUAL_REQUIRED.value)
    n_warn = sum(1 for f in db.get_findings(latest.run_id) if f.severity == "warning")

    metric_row([
        ("Total Runs", str(total)),
        ("Latest Run Status", latest.status.value if hasattr(latest.status, "value") else str(latest.status)),
        ("Responsibilities Complete", f"{n_complete}/{len(latest_states) or len(build_registry())}"),
        ("Needing Manual Input", str(n_manual)),
        ("Warnings (latest)", str(n_warn)),
    ])

    st.markdown("#### Run history")
    for run in runs:
        rid = run.run_id
        run_states = db.all_responsibility_states(rid)
        n_ok = sum(1 for s in run_states.values() if s["status"] == ResponsibilityStatus.COMPLETE.value)
        n_total = len(build_registry())
        pct = int(100 * n_ok / n_total) if n_total else 0

        card_start()
        c1, c2, c3, c4 = st.columns([2, 2, 3, 2])
        with c1:
            st.markdown(f"**{run.report_date.isoformat()}**")
            st.caption(rid)
        with c2:
            status_val = run.status.value if hasattr(run.status, "value") else str(run.status)
            st.markdown(status_badge(status_val, kind="run"), unsafe_allow_html=True)
        with c3:
            st.progress(pct / 100, text=f"{n_ok}/{n_total} responsibilities complete")
        with c4:
            bc1, bc2 = st.columns(2)
            with bc1:
                if st.button("Open", key=f"open_{rid}", width='stretch'):
                    state.set_selected_run_id(rid)
                    st.rerun()
            with bc2:
                if st.button("Retry Failed", key=f"retry_{rid}", width='stretch'):
                    with st.spinner("Retrying failed responsibilities..."):
                        mgr.retry_failed(rid)
                    st.rerun()
        card_end()
