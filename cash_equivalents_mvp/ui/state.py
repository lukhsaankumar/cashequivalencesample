"""Shared Streamlit session helpers: DB/RunManager singletons and the currently-selected run."""
from __future__ import annotations

import streamlit as st

from cash_equivalents_mvp.config import database_path
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.orchestration.manager import RunManager


@st.cache_resource
def get_db() -> Database:
    return Database(database_path())


@st.cache_resource
def get_manager() -> RunManager:
    return RunManager(get_db())


def selected_run_id() -> str | None:
    return st.session_state.get("selected_run_id")


def set_selected_run_id(run_id: str) -> None:
    st.session_state["selected_run_id"] = run_id


def ensure_selected_run() -> str | None:
    """Falls back to the most recently created run if none is explicitly selected."""
    rid = selected_run_id()
    if rid:
        return rid
    runs = get_db().list_runs()
    if runs:
        set_selected_run_id(runs[0].run_id)
        return runs[0].run_id
    return None
