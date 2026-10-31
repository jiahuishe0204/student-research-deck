"""PostgreSQL stage-claim contract for the SCF worker."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from scf_handler import VALID_STAGES, WorkerEventError


def claim_stage(connection, task_id: str, stage: str, attempt: int, lease_seconds: int = 900, *, work_item_id: str = "main"):
    """Atomically claim one task-stage-work-item-attempt.

    The caller supplies an open PostgreSQL connection. The function commits only
    its own claim transaction and returns a unique fencing token when this
    worker owns the lease. A duplicate claim returns None; an expired lease may
    be reclaimed with a new token so the old worker can no longer finalize it.
    """

    task_id = str(task_id or "").strip()
    stage = str(stage or "").strip().upper()
    work_item_id = str(work_item_id or "").strip()
    if (
        not task_id
        or stage not in VALID_STAGES
        or not work_item_id
        or len(work_item_id) > 128
        or any(not (char.isascii() and (char.isalnum() or char in ":_-")) for char in work_item_id)
        or not isinstance(attempt, int)
        or isinstance(attempt, bool)
        or attempt < 1
    ):
        raise WorkerEventError("无效的阶段领取参数")
    if not isinstance(lease_seconds, int) or not 30 <= lease_seconds <= 86400:
        raise WorkerEventError("lease_seconds 必须在 30-86400 秒之间")

    now = datetime.now(timezone.utc)
    lease_token = str(uuid.uuid4())
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO task_stage_attempts
            (task_id, stage, work_item_id, attempt, status, lease_until, lease_token, updated_at)
        VALUES (%s, %s, %s, %s, 'running', %s, %s, %s)
        ON CONFLICT (task_id, stage, work_item_id, attempt) DO NOTHING
        RETURNING task_id
        """,
        (task_id, stage, work_item_id, attempt, now.timestamp() + lease_seconds, lease_token, now),
    )
    inserted = cursor.fetchone()
    if inserted:
        connection.commit()
        return lease_token

    cursor.execute(
        """
        UPDATE task_stage_attempts
           SET status = 'running', lease_until = %s, lease_token = %s, updated_at = %s
         WHERE task_id = %s AND stage = %s AND work_item_id = %s AND attempt = %s
           AND status = 'running' AND lease_until < %s
        RETURNING task_id
        """,
        (now.timestamp() + lease_seconds, lease_token, now, task_id, stage, work_item_id, attempt, now.timestamp()),
    )
    reclaimed = cursor.fetchone()
    connection.commit()
    return lease_token if reclaimed else None


def finish_stage(connection, task_id: str, stage: str, attempt: int, lease_token: str, status: str, *, work_item_id: str = "main"):
    """Mark an owned attempt as succeeded or failed."""
    if status not in {"succeeded", "failed"}:
        raise WorkerEventError("阶段结束状态无效")
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE task_stage_attempts
           SET status = %s, lease_until = 0, updated_at = CURRENT_TIMESTAMP
         WHERE task_id = %s AND stage = %s AND work_item_id = %s AND attempt = %s AND status = 'running'
           AND lease_token = %s AND lease_until >= EXTRACT(EPOCH FROM CURRENT_TIMESTAMP)
        RETURNING task_id
        """,
        (status, str(task_id), str(stage).upper(), str(work_item_id), attempt, str(lease_token)),
    )
    updated = cursor.fetchone()
    connection.commit()
    return bool(updated)


CLAIMS_MIGRATION_SQL = """
CREATE TABLE IF NOT EXISTS task_stage_attempts (
    task_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK (stage IN ('P1','P2','P3','P4','P5','P6','P7','P8','P9')),
    work_item_id TEXT NOT NULL DEFAULT 'main' CHECK (work_item_id ~ '^[A-Za-z0-9:_-]{1,128}$'),
    attempt INTEGER NOT NULL CHECK (attempt >= 1),
    status TEXT NOT NULL CHECK (status IN ('running','succeeded','failed')),
    lease_until DOUBLE PRECISION NOT NULL,
    lease_token UUID NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (task_id, stage, work_item_id, attempt)
);
"""


__all__ = ["CLAIMS_MIGRATION_SQL", "claim_stage", "finish_stage"]
