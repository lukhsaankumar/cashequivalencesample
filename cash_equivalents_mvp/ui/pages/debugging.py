"""Page 7 — Debugging: stage timeline, per-responsibility logs, sanitized tracebacks, env diagnostics."""
from __future__ import annotations

import io
import platform
import sys
import zipfile

import streamlit as st

from cash_equivalents_mvp.config import settings as app_settings
from cash_equivalents_mvp.orchestration.graph import topological_order
from cash_equivalents_mvp.reporting.renderer_selection import select_renderer
from cash_equivalents_mvp.ui import state
from cash_equivalents_mvp.ui.components import card_end, card_start, page_header


def render() -> None:
    page_header("Debugging", "Stage timeline, structured errors, and a downloadable debug bundle.")

    run_id = state.ensure_selected_run()
    if not run_id:
        st.info("No run selected. Create one from the Dashboard.")
        return

    db = state.get_db()
    states = db.all_responsibility_states(run_id)

    card_start("Stage timeline")
    order = topological_order()
    for rid in order:
        s = states.get(rid)
        if not s:
            continue
        st.write(f"`{s['updated_at']}` — **{rid}** → {s['status']} (attempt {s['attempts']})")
    card_end()

    card_start("Errors")
    errors = db.get_errors(run_id)
    if not errors:
        st.caption("No errors recorded for this run.")
    for e in errors:
        with st.expander(f"{e.responsibility_id} · {e.error_code} · {e.stage}"):
            st.write(f"**Message:** {e.message}")
            st.write(f"**Retryable:** {e.retryable} · **Severity:** {e.severity}")
            st.write(f"**Suggested action:** {e.suggested_action}")
            if e.sanitized_traceback:
                st.code(e.sanitized_traceback, language="text")
    card_end()

    card_start("Environment")
    renderer_name, _renderer = select_renderer(app_settings()["renderer"]["preference"])
    st.write(f"**Python:** {sys.version.split()[0]} · **Platform:** {platform.platform()}")
    st.write(f"**Renderer detected:** {renderer_name or 'none (Excel/LibreOffice not found)'}")
    card_end()

    if st.button("Generate debug bundle (debug_bundle.zip)"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("responsibility_states.json", str(states))
            zf.writestr("errors.json", "\n".join(e.model_dump_json() for e in errors))
            zf.writestr("findings.json", "\n".join(f.model_dump_json() for f in db.get_findings(run_id)))
            zf.writestr("environment.txt",
                        f"python={sys.version}\nplatform={platform.platform()}\nrenderer={renderer_name}\n")
        st.download_button("Download debug_bundle.zip", buf.getvalue(), file_name="debug_bundle.zip",
                            mime="application/zip")
