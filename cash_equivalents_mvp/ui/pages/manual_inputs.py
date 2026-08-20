"""Page 3 — Manual Uploads and Inputs: the primary fallback page. Shows only responsibilities
that are failed / manual-required / stale, with the exact upload or override control each needs.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from cash_equivalents_mvp.config import upload_dir
from cash_equivalents_mvp.models import ManualInput, ResponsibilityStatus
from cash_equivalents_mvp.orchestration.graph import build_registry
from cash_equivalents_mvp.security import sanitize_filename
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header, status_badge

NEEDS_ATTENTION = {
    ResponsibilityStatus.MANUAL_REQUIRED.value,
    ResponsibilityStatus.AUTOMATIC_FAILED.value,
    ResponsibilityStatus.VALIDATION_FAILED.value,
    ResponsibilityStatus.BLOCKED.value,
}

FILE_UPLOAD_RESPS = {
    "gic_rates": (["xlsx", "csv"], "GIC Rates.xlsx or a structured CSV"),
    "treasury_bills": (["pdf", "txt"], "NBF/NBCN PDF or text rate sheet"),
    "hisa": (["csv", "xlsx"], "HISA CSV or XLSX roster"),
    "template": (["xlsx"], "Replacement EN or FR .xlsx template"),
}

NUMERIC_FORMS = {
    "canada_prime": ["rate"],
    "us_fed_funds": ["lower", "upper", "selected_value"],
    "money_market": ["cad_yield", "us_yield"],
}


def _save_upload(run_id: str, responsibility_id: str, uploaded_file) -> Path:
    folder = upload_dir() / run_id / responsibility_id
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / sanitize_filename(uploaded_file.name)
    dest.write_bytes(uploaded_file.getbuffer())
    return dest


def render() -> None:
    page_header("Manual Uploads and Inputs",
                "Only responsibilities that need attention are shown here. Supplying one reruns "
                "just that responsibility and everything downstream of it.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    mgr = state.get_manager()
    registry = build_registry()
    states = db.all_responsibility_states(run_id)

    pending = [rid for rid, s in states.items() if s["status"] in NEEDS_ATTENTION]

    if not pending:
        st.success("Nothing needs manual attention right now for this run.")
        return

    for rid in pending:
        resp = registry.get(rid)
        if resp is None:
            continue
        s = states[rid]
        errors = db.get_errors(run_id, rid)
        last_error = errors[-1] if errors else None

        card_start()
        c1, c2 = st.columns([4, 1])
        with c1:
            st.markdown(f"**{resp.display_name}**")
        with c2:
            st.markdown(status_badge(s["status"]), unsafe_allow_html=True)

        if last_error:
            st.caption(f"Automatic result: **{last_error.error_code}** — {last_error.message}")

        reason = st.text_input("Reason for override / manual entry", key=f"reason_{rid}",
                                placeholder="e.g. VPN unavailable in this environment")

        if rid in FILE_UPLOAD_RESPS:
            exts, hint = FILE_UPLOAD_RESPS[rid]
            st.caption(f"Expected: {hint}")
            uploaded = st.file_uploader("Upload file", type=exts, key=f"upload_{rid}")
            if st.button("Submit", key=f"submit_{rid}", disabled=uploaded is None):
                if not reason.strip():
                    st.error("A reason is required before submitting an override.")
                elif uploaded is None:
                    st.error("No file selected.")
                else:
                    path = _save_upload(run_id, rid, uploaded)
                    mi = ManualInput(responsibility_id=rid, kind="file", file_path=str(path),
                                      original_filename=uploaded.name, override_reason=reason)
                    with st.spinner(f"Reprocessing {resp.display_name} and downstream stages..."):
                        mgr.submit_manual_input(run_id, mi)
                    st.rerun()

        elif rid in NUMERIC_FORMS:
            fields = NUMERIC_FORMS[rid]
            cols = st.columns(len(fields))
            values = {}
            for col, field in zip(cols, fields):
                with col:
                    values[field] = st.text_input(field.replace("_", " ").title(), key=f"{rid}_{field}")
            if st.button("Submit", key=f"submit_{rid}"):
                if not reason.strip():
                    st.error("A reason is required before submitting an override.")
                elif not values.get(fields[0]):
                    st.error(f"{fields[0].replace('_',' ').title()} is required.")
                else:
                    mi = ManualInput(responsibility_id=rid, kind="numeric",
                                      numeric_fields={k: v for k, v in values.items() if v},
                                      override_reason=reason)
                    with st.spinner(f"Reprocessing {resp.display_name} and downstream stages..."):
                        mgr.submit_manual_input(run_id, mi)
                    st.rerun()
        else:
            st.caption("This responsibility has no dedicated manual-input form yet; use Retry on the "
                       "Responsibility Status page once the automatic source is reachable.")

        card_end()
