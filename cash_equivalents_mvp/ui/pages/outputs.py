"""Page 6 — Outputs and Downloads: the completed deliverables for the selected run."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from cash_equivalents_mvp.audit import sha256_file
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header

_ICONS = {".xlsx": "\U0001F4D7", ".pdf": "\U0001F4C4", ".eml": "\U00002709", ".zip": "\U0001F5C3"}


def _mime_for(path: Path) -> str:
    return {
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".pdf": "application/pdf",
        ".eml": "message/rfc822",
        ".zip": "application/zip",
        ".json": "application/json",
        ".csv": "text/csv",
    }.get(path.suffix.lower(), "application/octet-stream")


def render() -> None:
    page_header("Outputs and Downloads", "Final English/French workbooks, PDFs, validation report, "
                "audit manifest, unsent email draft, and the ZIP package.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    run = db.get_run_or_raise(run_id)
    if run.output_dir is None:
        st.info("This run has no output directory yet.")
        return
    run_dir = Path(run.output_dir)
    outputs_dir = run_dir / "outputs"

    if not outputs_dir.exists() or not any(outputs_dir.iterdir()):
        st.info("No outputs yet. Complete the run (Dashboard → Retry Failed, or wait for pending "
                "responsibilities) to produce the EN/FR workbooks, PDFs, and package.")
        return

    status_val = run.status.value if hasattr(run.status, "value") else str(run.status)
    if status_val in ("READY_FOR_REVIEW",):
        st.success("Outputs are ready for review. Approve below once verified.")
        if st.button("Approve this run"):
            state.get_manager().approve_run(run_id, approved_by="local_user")
            st.rerun()
    elif status_val == "APPROVED":
        st.success(f"Approved by {run.approved_by} at {run.approved_at}.")

    files = sorted(outputs_dir.iterdir(), key=lambda p: p.name)
    for f in files:
        card_start()
        c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
        with c1:
            icon = _ICONS.get(f.suffix.lower(), "\U0001F4C1")
            st.markdown(f"**{icon} {f.name}**")
        with c2:
            size_kb = f.stat().st_size / 1024
            st.caption(f"{size_kb:,.0f} KB")
        with c3:
            st.caption(f"sha256: {sha256_file(f)[:16]}...")
        with c4:
            st.download_button("Download", data=f.read_bytes(), file_name=f.name,
                                mime=_mime_for(f), key=f"dl_{f.name}", width='stretch')
        card_end()

    mapping_reports = list(run_dir.glob("mapping_report_*.json"))
    if mapping_reports:
        with st.expander("Workbook mapping report"):
            for mr in mapping_reports:
                st.write(f"**{mr.name}**")
                st.code(mr.read_text(encoding="utf-8"), language="json")
