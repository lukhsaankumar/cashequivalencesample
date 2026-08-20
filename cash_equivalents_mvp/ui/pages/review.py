"""Page 4 — Review and Comparison: week-over-week values, exceptions only, controlled overrides."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from cash_equivalents_mvp.normalization.records import compare_records
from cash_equivalents_mvp.orchestration.graph import COLLECTOR_IDS
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header


def render() -> None:
    page_header("Review and Comparison", "Current vs. previous week, by category and provider. "
                "This page is for exceptions and verification only — it is not where the report is built.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    runs = db.list_runs()
    current_run = next(r for r in runs if r.run_id == run_id)
    earlier = [r for r in runs if r.report_date < current_run.report_date]
    previous_run = max(earlier, key=lambda r: r.report_date) if earlier else None

    current_records = []
    previous_records = []
    for rid in COLLECTOR_IDS:
        current_records += db.get_rate_records(run_id, rid)
        if previous_run:
            previous_records += db.get_rate_records(previous_run.run_id, rid)

    if not current_records:
        st.info("No rate records collected yet for this run.")
        return

    rows = compare_records(previous_records, current_records)
    df = pd.DataFrame(rows)

    card_start("Filters")
    c1, c2, c3 = st.columns(3)
    with c1:
        categories = sorted(df["category"].dropna().unique().tolist())
        cat_filter = st.multiselect("Category", categories, default=categories)
    with c2:
        currencies = sorted(df["currency"].dropna().unique().tolist())
        cur_filter = st.multiselect("Currency", currencies, default=currencies)
    with c3:
        status_filter = st.multiselect("Status", sorted(df["status"].unique().tolist()),
                                        default=sorted(df["status"].unique().tolist()))
    card_end()

    filtered = df[df["category"].isin(cat_filter) & df["currency"].isin(cur_filter) & df["status"].isin(status_filter)]

    if not previous_run:
        st.caption("No earlier run exists yet for week-over-week comparison — showing this week's values only.")

    st.dataframe(
        filtered[["category", "provider", "product", "currency", "term", "previous_value",
                  "current_value", "change", "status"]],
        width='stretch', hide_index=True,
    )

    st.download_button("Download comparison.csv", filtered.to_csv(index=False).encode("utf-8"),
                        file_name="comparison.csv", mime="text/csv")

    st.markdown("#### Manual correction (override)")
    card_start()
    st.caption("Overrides require a reason and are fully audited. Prefer the Manual Uploads page for "
               "missing sources — use this only for correcting an individual value.")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.text_input("Record identifier")
    with c2:
        st.text_input("New value")
    with c3:
        st.text_input("Reviewer name")
    st.text_area("Reason for override", height=70)
    st.button("Submit override", disabled=True, help="Wire-up pending — record-level override API not yet exposed.")
    card_end()
