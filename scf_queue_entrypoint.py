"""Parallel queue-backed SCF entrypoint used for blue/green validation.

Keep ``scf_entrypoint.main_handler`` untouched until this handler passes local
and cloud smoke checks and the terminal delivery path is wired.
"""

from __future__ import annotations

from pathlib import Path

from preauth_budget import PostgresPreAuthDailyBudget
from postgres_model_usage import PostgresModelUsageLedger
from scf_app import build_queued_stage_dispatcher, build_workflow
from scf_config import load_scf_config
from scf_queue import execute_queued_stage
from scf_transition import plan_next_stage


ROOT = Path(__file__).resolve().parent


def process_one_queued_stage(connection, workflow, stage_dispatcher, lease_seconds=900):
    """Run at most one durable queue item; safe to call from a timer trigger."""
    return execute_queued_stage(
        connection,
        workflow,
        lambda job, result: plan_next_stage(connection, job, result),
        lease_seconds=lease_seconds,
        stage_dispatcher=stage_dispatcher,
    )


def main_handler(event, context, *, connection=None, workflow=None,
                 stage_dispatcher=None, environ=None):
    """SCF-compatible queue handler; dependency injection keeps tests offline."""
    config = load_scf_config(environ)
    owned_connection = connection is None
    if owned_connection:
        from scf_entrypoint import _connect_database
        connection = _connect_database(config.database_url)
    try:
        workflow = workflow or build_workflow(
            ROOT, environ=environ,
            daily_budget_ledger=PostgresPreAuthDailyBudget(connection),
            usage_ledger=PostgresModelUsageLedger(connection),
        )
        if stage_dispatcher is None:
            from scf_terminal_delivery import publish_final_delivery
            publisher = lambda payload: publish_final_delivery(connection, payload, environ=environ)
            stage_dispatcher = build_queued_stage_dispatcher(
                environ, delivery_publisher_fn=publisher,
            )
        try:
            return process_one_queued_stage(connection, workflow, stage_dispatcher)
        except Exception as exc:
            print("QUEUED_WORKFLOW_ERROR %s: %s" % (type(exc).__name__, str(exc)[:800]))
            raise
    finally:
        if owned_connection:
            connection.close()


__all__ = ["main_handler", "process_one_queued_stage"]
