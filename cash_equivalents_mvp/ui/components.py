"""Small shared rendering helpers used across pages."""
from __future__ import annotations

import streamlit as st

_STATUS_BADGE = {
    "COMPLETE": "success", "SUCCESS": "success",
    "SUCCESS_WITH_WARNINGS": "warning", "RETRYING": "warning", "RUNNING": "info", "PENDING": "muted",
    "MANUAL_REQUIRED": "warning", "MANUAL_UPLOADED": "info",
    "AUTOMATIC_FAILED": "danger", "VALIDATION_FAILED": "danger", "BLOCKED": "danger",
    "SKIPPED": "muted",
}

_RUN_STATUS_BADGE = {
    "CREATED": "muted", "QUEUED": "muted", "RUNNING": "info",
    "NEEDS_MANUAL_INPUT": "warning", "VALIDATION_FAILED": "danger",
    "READY_FOR_REVIEW": "info", "APPROVED": "success", "COMPLETE": "success",
    "FAILED": "danger", "CANCELLED": "muted",
}


def status_badge(status: str, kind: str = "responsibility") -> str:
    table = _RUN_STATUS_BADGE if kind == "run" else _STATUS_BADGE
    css = table.get(status, "muted")
    label = status.replace("_", " ").title()
    return f'<span class="ig-badge ig-badge-{css}">{label}</span>'


def page_header(title: str, subtitle: str = "") -> None:
    st.markdown(f'<div class="ig-page-title">{title}</div>', unsafe_allow_html=True)
    if subtitle:
        st.markdown(f'<div class="ig-page-subtitle">{subtitle}</div>', unsafe_allow_html=True)


def metric_row(items: list[tuple[str, str]]) -> None:
    cols = st.columns(len(items))
    for col, (label, value) in zip(cols, items):
        with col:
            st.markdown(
                f'<div class="ig-metric"><div class="label">{label}</div>'
                f'<div class="value">{value}</div></div>',
                unsafe_allow_html=True,
            )


def card_start(title: str | None = None) -> None:
    st.markdown('<div class="ig-card">', unsafe_allow_html=True)
    if title:
        st.markdown(f"#### {title}")


def card_end() -> None:
    st.markdown("</div>", unsafe_allow_html=True)
