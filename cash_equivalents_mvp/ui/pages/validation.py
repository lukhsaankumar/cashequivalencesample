"""Page 5 — Validation: blocking errors, warnings, and informational checks, by responsibility."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header


def render() -> None:
    page_header("Validation", "Every rule that ran for this run, grouped by severity.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    findings = db.get_findings(run_id)

    blocking = [f for f in findings if f.severity == "blocking"]
    warnings = [f for f in findings if f.severity == "warning"]
    info = [f for f in findings if f.severity not in ("blocking", "warning")]

    c1, c2, c3 = st.columns(3)
    c1.metric("Blocking Errors", len(blocking))
    c2.metric("Warnings", len(warnings))
    c3.metric("Informational", len(info))

    def _table(items, empty_msg):
        if not items:
            st.caption(empty_msg)
            return
        df = pd.DataFrame([{
            "Responsibility": f.responsibility_id, "Rule": f.rule_id,
            "Message": f.message, "Location": f.location or "",
        } for f in items])
        st.dataframe(df, width='stretch', hide_index=True)

    card_start("Blocking Errors")
    _table(blocking, "No blocking errors.")
    card_end()

    card_start("Warnings")
    _table(warnings, "No warnings.")
    card_end()

    card_start("Informational Checks")
    _table(info, "No informational findings.")
    card_end()

    st.download_button(
        "Download validation_report.json",
        pd.DataFrame([f.model_dump(mode="json") for f in findings]).to_json(orient="records", indent=2),
        file_name="validation_report.json", mime="application/json",
    )
