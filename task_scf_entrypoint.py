"""Timer entrypoint that executes one durable production research job."""

from __future__ import annotations

from pathlib import Path

from production_task_queue import PostgresTaskQueue
from production_task_worker import execute_next_job
from scf_app import build_workflow
from scf_config import load_scf_config
from scf_entrypoint import _connect_database


ROOT = Path(__file__).resolve().parent


def main_handler(event, context=None, *, connection=None, workflow=None):
    config = load_scf_config()
    owned = connection is None
    connection = connection or _connect_database(config.database_url)
    try:
        return execute_next_job(PostgresTaskQueue(connection), workflow or build_workflow(ROOT), root=ROOT)
    finally:
        if owned:
            connection.close()


__all__ = ["main_handler"]
