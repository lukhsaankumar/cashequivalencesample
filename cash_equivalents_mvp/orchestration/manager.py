"""RunManager — creates runs and executes the responsibility DAG, synchronously.

Independent collectors (§10) could run in a thread pool for wall-clock speed, but are executed
sequentially here for simplicity and deterministic logs; each is already fast (local file read or
a single HTTP call). The background/non-blocking requirement (§10, §15) is satisfied at the
worker layer (orchestration/worker.py), which runs a whole RunManager.execute_run() call in a
background thread so the CLI/UI caller never blocks.
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from cash_equivalents_mvp.config import output_root_dir, upload_dir
from cash_equivalents_mvp.database import Database
from cash_equivalents_mvp.models import ManualInput, ResponsibilityStatus, Run, RunStatus
from cash_equivalents_mvp.orchestration.graph import (
    DEPENDENCIES,
    build_registry,
    downstream_of,
    topological_order,
)
from cash_equivalents_mvp.orchestration.resume import invalidate_downstream
from cash_equivalents_mvp.responsibilities.base import RunContext

TERMINAL_OK = {ResponsibilityStatus.COMPLETE, ResponsibilityStatus.SKIPPED}
BLOCKING = {ResponsibilityStatus.AUTOMATIC_FAILED, ResponsibilityStatus.MANUAL_REQUIRED,
            ResponsibilityStatus.VALIDATION_FAILED, ResponsibilityStatus.BLOCKED}


class RunManager:
    def __init__(self, db: Database):
        self.db = db

    def create_run(self, report_date: date) -> Run:
        run = Run(report_date=report_date, status=RunStatus.CREATED)
        run_dir = output_root_dir() / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        run.output_dir = str(run_dir)
        self.db.create_run(run)
        return run

    def _context(self, run: Run) -> RunContext:
        if run.output_dir is None:
            raise ValueError(f"Run {run.run_id} has no output_dir — was it created via create_run()?")
        return RunContext(
            run_id=run.run_id, report_date=run.report_date, run_dir=Path(run.output_dir),
            db=self.db, manual_uploads_dir=upload_dir(),
        )

    def execute_run(self, run_id: str, only: list[str] | None = None) -> RunStatus:
        run = self.db.get_run_or_raise(run_id)
        run.status = RunStatus.RUNNING
        run.started_at = run.started_at or datetime.utcnow()
        self.db.save_run(run)

        context = self._context(run)
        registry = build_registry()
        order = topological_order()
        if only:
            order = [rid for rid in order if rid in only]

        any_blocking = False
        for rid in order:
            deps = DEPENDENCIES[rid]
            dep_statuses = [self.db.get_responsibility_status(run_id, d) for d in deps]
            if any(s not in TERMINAL_OK for s in dep_statuses):
                self.db.set_responsibility_status(run_id, rid, ResponsibilityStatus.SKIPPED,
                                                    detail={"reason": "blocked_dependency"})
                any_blocking = True
                continue

            resp = registry[rid]
            status = resp.run_automatic(context)
            if status in BLOCKING:
                any_blocking = True

        run.status = self._compute_run_status(run_id, any_blocking)
        if run.status == RunStatus.COMPLETE:
            run.completed_at = datetime.utcnow()
        self.db.save_run(run)
        return run.status

    def _compute_run_status(self, run_id: str, any_blocking: bool) -> RunStatus:
        states = self.db.all_responsibility_states(run_id)
        if any(s["status"] == ResponsibilityStatus.MANUAL_REQUIRED.value for s in states.values()):
            return RunStatus.NEEDS_MANUAL_INPUT
        if any(s["status"] == ResponsibilityStatus.VALIDATION_FAILED.value for s in states.values()):
            return RunStatus.VALIDATION_FAILED
        if any_blocking:
            return RunStatus.FAILED
        if states.get("package", {}).get("status") == ResponsibilityStatus.COMPLETE.value:
            return RunStatus.READY_FOR_REVIEW
        return RunStatus.FAILED

    def submit_manual_input(self, run_id: str, manual_input: ManualInput) -> ResponsibilityStatus:
        """Reruns exactly one responsibility with the supplied manual input, then reruns every
        downstream responsibility (never unrelated successful ones) — master prompt §10."""
        run = self.db.get_run_or_raise(run_id)
        context = self._context(run)
        self.db.save_manual_input(manual_input, run_id)

        registry = build_registry()
        resp = registry[manual_input.responsibility_id]
        status = resp.run_manual(context, manual_input)

        if status == ResponsibilityStatus.COMPLETE:
            downstream = [rid for rid in invalidate_downstream(self.db, run_id, manual_input.responsibility_id)
                          if rid in registry]
            self.execute_run(run_id, only=downstream)

        run = self.db.get_run_or_raise(run_id)
        run.status = self._compute_run_status(run_id, status not in TERMINAL_OK)
        self.db.save_run(run)
        return status

    def retry_failed(self, run_id: str) -> RunStatus:
        states = self.db.all_responsibility_states(run_id)
        failed = [rid for rid, s in states.items()
                  if s["status"] in {ResponsibilityStatus.AUTOMATIC_FAILED.value,
                                     ResponsibilityStatus.VALIDATION_FAILED.value}]
        to_run = set(failed)
        for rid in failed:
            to_run.update(downstream_of(rid))
        for rid in to_run:
            self.db.set_responsibility_status(run_id, rid, ResponsibilityStatus.PENDING)
        return self.execute_run(run_id, only=list(to_run))

    def approve_run(self, run_id: str, approved_by: str) -> Run:
        run = self.db.get_run_or_raise(run_id)
        run.status = RunStatus.APPROVED
        run.approved_at = datetime.utcnow()
        run.approved_by = approved_by
        self.db.save_run(run)
        return run
