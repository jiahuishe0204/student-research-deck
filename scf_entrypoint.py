"""Tencent SCF entrypoint for one recoverable workflow stage."""

from __future__ import annotations

import os
from pathlib import Path

from scf_app import build_workflow
from scf_config import load_scf_config
from scf_worker import execute_worker_event


ROOT = Path(__file__).resolve().parent


def _connect_database(database_url: str):
    """Import the PostgreSQL driver only inside the cloud runtime."""
    try:
        import psycopg
    except ImportError as exc:  # pragma: no cover - deployment diagnostic
        raise RuntimeError("SCF 部署包缺少 psycopg PostgreSQL 驱动") from exc
    return psycopg.connect(database_url)


def main_handler(event, context, *, connection=None, workflow=None):
    """SCF-compatible handler; dependency injection keeps local tests offline."""
    config = load_scf_config()
    owned_connection = connection is None
    if owned_connection:
        connection = _connect_database(config.database_url)
    try:
        workflow = workflow or build_workflow(ROOT)
        return execute_worker_event(connection, workflow, event)
    finally:
        if owned_connection:
            connection.close()


__all__ = ["main_handler"]
