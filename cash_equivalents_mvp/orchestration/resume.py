"""Resume-after-manual-input logic (master prompt §10): when a manual upload satisfies one failed
responsibility, invalidate exactly its downstream responsibilities — never unrelated successful
ones — so they rerun against the new data.
"""
from __future__ import annotations

from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ResponsibilityStatus
from cash_equivalents_mvp.orchestration.graph import downstream_of


def invalidate_downstream(db: Database, run_id: str, responsibility_id: str) -> list[str]:
    """Marks every responsibility downstream of responsibility_id as PENDING (never touches
    responsibility_id itself, which the caller has just finished running, or anything outside
    its downstream set). Returns the list of ids invalidated, in dependency order."""
    downstream = downstream_of(responsibility_id)
    for rid in downstream:
        db.set_responsibility_status(run_id, rid, ResponsibilityStatus.PENDING)
    return downstream
