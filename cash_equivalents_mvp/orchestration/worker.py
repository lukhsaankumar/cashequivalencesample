"""Background worker: runs a RunManager pipeline in a daemon thread so callers (the UI, the CLI's
`execute` command run with --background) never block. Progress is visible immediately because
every responsibility writes its status to SQLite as it goes (database.py) — the UI just re-reads
the same database from its own process/thread, no IPC needed.

This satisfies master prompt §10/§15's "the UI must not block while responsibilities run" with the
simplest mechanism that works for a local single-user MVP: a thread pool, not a separate OS
process or message queue. See docs/production_backlog.md for why a real deployment would want a
proper job queue instead.
"""
from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from cash_equivalents_mvp.models import ManualInput
from cash_equivalents_mvp.orchestration.manager import RunManager

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="ceq-worker")
_lock = threading.Lock()
_in_flight: set[str] = set()


def is_running(run_id: str) -> bool:
    with _lock:
        return run_id in _in_flight


def submit_execute(mgr: RunManager, run_id: str, only: list[str] | None = None) -> bool:
    """Returns False (and does nothing) if this run already has a background execution in flight —
    prevents two overlapping executions of the same run from racing on the same SQLite rows."""
    with _lock:
        if run_id in _in_flight:
            return False
        _in_flight.add(run_id)

    def _run():
        try:
            mgr.execute_run(run_id, only=only)
        finally:
            with _lock:
                _in_flight.discard(run_id)

    _executor.submit(_run)
    return True


def submit_manual_input(mgr: RunManager, run_id: str, manual_input: ManualInput) -> bool:
    with _lock:
        if run_id in _in_flight:
            return False
        _in_flight.add(run_id)

    def _run():
        try:
            mgr.submit_manual_input(run_id, manual_input)
        finally:
            with _lock:
                _in_flight.discard(run_id)

    _executor.submit(_run)
    return True
