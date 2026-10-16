"""PostgreSQL stage-claim contract for the SCF worker."""

from __future__ import annotations

from datetime import datetime, timezone

from scf_handler import VALID_STAGES, WorkerEventError


def claim_stage(connection, task_id: str, stage: str, attempt: int, lease_seconds: int = 900):
    """Atomically claim one task-stage-attempt.

    The caller supplies an open PostgreSQL connection. The function commits only
    its own claim transaction and returns True when this worker owns the lease.
    A duplicate claim returns False; an expired lease may be reclaimed.
    """

    task_id = str(task_id or "").strip()
    stage = str(stage or "").strip().upper()
    if not task_id or stage not in VALID_STAGES or not isinstance(attempt, int) or isinstance(attempt, bool) or attempt < 1:
        raise WorkerEventError("无效的阶段领取参数")
    if not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 86400:
        raise WorkerEventError("lease_seconds 必须在 30-86400 秒之间")

    now = datetime.now(timezone.utc)
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO task_stage_attempts
            (task_id, stage, attempt, status, lease_until, updated_at)
        VALUES (%s, %s, %s, 'running', %s, %s)
        ON CONFLICT (task_id, stage, attempt) DO NOTHING
        RETURNING task_id
        """,
        (task_id, stage, attempt, now.timestamp() + lease_seconds, now),
    )
    inserted = cursor.fetchone()
    if inserted:
        connection.commit()
        return True

    cursor.execute(
        """
        UPDATE task_stage_attempts
           SET status = 'running', lease_until = %s, updated_at = %s
         WHERE task_id = %s AND stage = %s AND attempt = %s
           AND status = 'running' AND lease_until < %s
        RETURNING task_id
        """,
        (now.timestamp() + lease_seconds, now, task_id, stage, attempt, now.timestamp()),
    )
    reclaimed = cursor.fetchone()
    connection.commit()
    return bool(reclaimed)


def finish_stage(connection, task_id: str, stage: str, attempt: int, status: str):
    """Mark an owned attempt as succeeded or failed."""
    if status not in {"succeeded", "failed"}:
        raise WorkerEventError("阶段结束状态无效")
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE task_stage_attempts
           SET status = %s, lease_until = 0, updated_at = CURRENT_TIMESTAMP
         WHERE task_id = %s AND stage = %s AND attempt = %s AND status = 'running'
        RETURNING task_id
        """,
        (status, str(task_id), str(stage).upper(), attempt),
    )
    updated = cursor.fetchone()
    connection.commit()
    return bool(updated)


CLAIMS_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS task_stage_attempts (
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('P1','P2','P3','P4','P5','P6','P7','P8','P9')),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    lease_until DOUBLE PRECISION NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (task_id, stage, attempt)
);
"""


__all__ = ["CLAIMS_MIGRATION_SQL", "claim_stage", "finish_stage"]
