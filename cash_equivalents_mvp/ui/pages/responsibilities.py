"""Page 2 — Responsibility Status: one card per responsibility for the selected run."""
from __future__ import annotations

import streamlit as st

from cash_equivalents_mvp.orchestration.graph import DEPENDENCIES, build_registry, topological_order
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header, status_badge


def render() -> None:
    page_header("Responsibility Status", "Automatic source, freshness, records extracted, and errors per responsibility.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    mgr = state.get_manager()
    registry = build_registry()
    states = db.all_responsibility_states(run_id)
    order = topological_order()

    for rid in order:
        resp = registry[rid]
        s = states.get(rid, {"status": "PENDING", "attempts": 0, "updated_at": "-", "detail": None})
        errors = db.get_errors(run_id, rid)
        findings = [f for f in db.get_findings(run_id) if f.responsibility_id == rid]
        records = db.get_rate_records(run_id, rid)

        card_start()
        c1, c2, c3 = st.columns([3, 2, 2])
        with c1:
            st.markdown(f"**{resp.display_name}**")
            deps = DEPENDENCIES.get(rid, ())
            st.caption(f"id: {rid}" + (f" · depends on: {', '.join(deps)}" if deps else ""))
        with c2:
            st.markdown(status_badge(s["status"]), unsafe_allow_html=True)
        with c3:
            st.caption(f"Attempts: {s['attempts']} · Updated: {s['updated_at']}")

        mc1, mc2, mc3 = st.columns(3)
        mc1.metric("Records extracted", len(records))
        mc2.metric("Warnings", sum(1 for f in findings if f.severity == "warning"))
        mc3.metric("Errors", len(errors))

        if errors:
            latest = errors[-1]
            st.error(f"**{latest.error_code}** ({latest.stage}): {latest.message}\n\n"
                      f"Suggested action: {latest.suggested_action}")
        for f in findings:
            if f.severity == "warning":
                st.warning(f"`{f.rule_id}` — {f.message}")

        bc1, bc2, _bc3 = st.columns([1, 1, 4])
        with bc1:
            if st.button("Retry", key=f"retry_resp_{rid}"):
                with st.spinner(f"Retrying {resp.display_name}..."):
                    mgr.execute_run(run_id, only=[rid])
                st.rerun()
        with bc2, st.popover("View evidence"):
            artifacts = [a for a in db.get_artifacts(run_id) if a.responsibility_id == rid]
            if not artifacts:
                st.caption("No source artifacts recorded yet.")
            for a in artifacts:
                st.write(f"**{a.filename}**")
                st.caption(f"method: {a.collection_method} · sha256: {a.sha256[:16] or '(n/a)'}...")
        card_end()
