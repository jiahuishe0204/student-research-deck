"""Tencent SCF entrypoint for one recoverable workflow stage."""

from __future__ import annotations

import os
from pathlib import Path

from scf_app import build_workflow
from scf_config import load_scf_config
from scf_worker import execute_worker_event
from preauth_budget import PostgresPreAuthDailyBudget


ROOT = Path(__file__).resolve().parent


def _connect_database(database_url: str):
    """Connect with a pure-Python driver first for SCF portability."""
    try:
        import pg8000.dbapi
        from urllib.parse import urlparse, unquote

        parsed = urlparse(database_url)
        if parsed.scheme not in {"postgresql", "postgres"}:
            raise ValueError("DATABASE_URL 必须是 PostgreSQL 连接串")
        return pg8000.dbapi.connect(
            user=unquote(parsed.username or ""),
            password=unquote(parsed.password or ""),
            host=parsed.hostname or "",
            port=parsed.port or 5432,
            database=(parsed.path or "/").lstrip("/"),
            ssl_context=True,
        )
    except ImportError:
        # Retain compatibility with environments that still package psycopg.
        try:
            import psycopg
            return psycopg.connect(database_url)
        except ImportError as exc:  # pragma: no cover - cloud diagnostic
            raise RuntimeError("SCF 缺少 PostgreSQL 驱动，请部署 requirements-scf.txt") from exc


def main_handler(event, context, *, connection=None, workflow=None):
    """SCF-compatible handler; dependency injection keeps local tests offline."""
    config = load_scf_config()
    owned_connection = connection is None
    if owned_connection:
        connection = _connect_database(config.database_url)
    try:
        workflow = workflow or build_workflow(
            ROOT,
            daily_budget_ledger=PostgresPreAuthDailyBudget(connection),
        )
        try:
            return execute_worker_event(connection, workflow, event)
        except Exception as exc:
            # SCF truncates traceback bodies; keep a short, secret-free cause
            # visible in the platform log so a failed stage is diagnosable.
            print(f"WORKFLOW_ERROR {type(exc).__name__}: {str(exc)[:800]}")
            raise
    finally:
        if owned_connection:
            connection.close()


__all__ = ["main_handler"]
