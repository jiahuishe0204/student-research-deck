"""PostgreSQL-backed queue primitives for database-driven SCF stages.

These helpers are intentionally separate from the current event-driven worker
entrypoint until the stage-to-stage payload planner is wired and reviewed.
"""

from __future__ import annotations

import json
import uuid

from scf_handler import WorkerEventError, validate_worker_event
from scf_queue_contracts import queue_job_key
from scf_stage_dispatch import dispatch_queued_stage


def normalize_stage_result(result):
    """Convert WorkflowService return shapes into a stable JSON-safe envelope.

    Most stages return ``(data, usage)`` and claim extraction/verification may
    return ``(data, usage, metadata)``. Persisting those raw tuples makes the
    next-stage planner depend on positional conventions and obscures usage.
    """
    if isinstance(result, tuple):
        if len(result) == 2:
            data, usage = result
            metadata = None
        elif len(result) == 3:
            data, usage, metadata = result
        else:
            raise WorkerEventError("阶段返回值必须是 data、usage 或 data、usage、metadata")
    else:
        data, usage, metadata = result, {}, None
    if not isinstance(usage, dict):
        raise WorkerEventError("阶段 usage 必须是对象")
    envelope = {"data": data, "usage": usage}
    if metadata is not None:
        if not isinstance(metadata, dict):
            raise WorkerEventError("阶段 metadata 必须是对象")
        envelope["metadata"] = metadata
    try:
        json.dumps(envelope, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise WorkerEventError("阶段结果必须可序列化为 JSON") from exc
    return envelope


def enqueue_stage(connection, task_id: str, stage: str, payload: dict, attempt: int = 1, *, work_item_id: str = "main") -> bool:
    """Persist a work item; duplicate task/stage/item/attempt is idempotent."""
    event = validate_worker_event({
        "task_id": task_id,
        "stage": stage,
        "work_item_id": work_item_id,
        "attempt": attempt,
        "payload": payload,
    })
    cursor = connection.cursor()
    cursor.execute(
        """
        INSERT INTO research_task_jobs
            (job_id, task_id, job_key, stage, attempt, status, payload,
             available_at, lease_token, created_at, updated_at,
             transition_status, transition_attempts)
        VALUES (%s, %s, %s, %s, %s, 'pending', %s::jsonb,
                NOW(), NULL, NOW(), NOW(), 'not_ready', 0)
        ON CONFLICT (task_id, job_key) DO NOTHING
        RETURNING task_id
        """,
        (
            str(uuid.uuid4()), event["task_id"],
            queue_job_key(event["stage"], event["work_item_id"], event["attempt"]),
            event["stage"], event["attempt"], json.dumps(event["payload"], ensure_ascii=False),
        ),
    )
    inserted = cursor.fetchone()
    connection.commit()
    return bool(inserted)


def claim_next_stage(connection, lease_seconds: int = 900):
    """Atomically claim the oldest available stage, skipping locked workers."""
    if not isinstance(lease_seconds, int) or isinstance(lease_seconds, bool) or not 30 <= lease_seconds <= 86400:
        raise WorkerEventError("lease_seconds 必须在 30-86400 秒之间")

    lease_token = str(uuid.uuid4())
    cursor = connection.cursor()
    cursor.execute(
        """
        WITH candidate AS (
            SELECT job_id
              FROM research_task_jobs
             WHERE (status = 'pending' AND available_at <= NOW())
                OR (status = 'running' AND lease_until < NOW())
             ORDER BY available_at, created_at, task_id, stage, job_key
             FOR UPDATE SKIP LOCKED
             LIMIT 1
        )
        UPDATE research_task_jobs AS job
           SET status = 'running',
               lease_until = NOW() + (%s * INTERVAL '1 second'),
               lease_token = %s,
               updated_at = NOW()
          FROM candidate
         WHERE job.job_id = candidate.job_id
        RETURNING job.job_id, job.task_id, job.stage, job.job_key, job.attempt,
                  job.payload, job.lease_token
        """,
        (lease_seconds, lease_token),
    )
    row = cursor.fetchone()
    if row:
        # The claim and public task progress must move together. Otherwise a
        # durable job can be running while the user-facing task stays queued.
        cursor.execute(
            """
            UPDATE research_tasks
               SET status = 'running', current_stage = %s, updated_at = NOW()
             WHERE task_id = %s AND status IN ('queued','running')
            """,
            (str(row[2]), str(row[1])),
        )
    connection.commit()
    if not row:
        return None
    job_id, task_id, stage, job_key, attempt, payload, returned_token = row
    from scf_queue_contracts import parse_queue_job_key
    parsed_key = parse_queue_job_key(job_key)
    work_item_id = parsed_key[1] if parsed_key else "main"
    if isinstance(payload, str):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise RuntimeError("数据库队列 payload 不是 JSON 对象")
    return {
        "task_id": str(task_id),
        "job_id": str(job_id),
        "job_key": str(job_key),
        "stage": str(stage),
        "work_item_id": str(work_item_id),
        "attempt": int(attempt),
        "payload": payload,
        "lease_token": str(returned_token),
    }


def complete_stage_and_enqueue_next(connection, job: dict, result, next_jobs=None) -> bool:
    """Fence completion and enqueue successor stage jobs in one transaction.

    ``next_jobs`` is prepared by the stage-aware planner, because P3/P4/P8 can
    fan out or batch work. A stale worker cannot publish output or advance work.
    """
    if not isinstance(job, dict) or not job.get("lease_token"):
        raise WorkerEventError("队列任务缺少租约令牌")
    current = validate_worker_event(job)
    if next_jobs is None:
        normalized_next_jobs = []
    elif isinstance(next_jobs, dict):
        normalized_next_jobs = [validate_worker_event(next_jobs)]
    elif isinstance(next_jobs, (list, tuple)):
        normalized_next_jobs = [validate_worker_event(item) for item in next_jobs]
    else:
        raise WorkerEventError("下一阶段任务必须是对象列表")
    if any(item["task_id"] != current["task_id"] for item in normalized_next_jobs):
        raise WorkerEventError("下一阶段必须属于同一任务")

    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            UPDATE research_task_jobs
               SET status = 'succeeded', result = %s::jsonb,
                   lease_until = NULL, transition_status = 'done', updated_at = NOW()
             WHERE job_id = %s AND status = 'running' AND lease_token = %s
               AND lease_until >= NOW()
            RETURNING task_id
            """,
            (
                json.dumps(result, ensure_ascii=False), str(job["job_id"]), str(job["lease_token"]),
            ),
        )
        finished = cursor.fetchone()
        if not finished:
            connection.rollback()
            return False

        for next_event in normalized_next_jobs:
            cursor.execute(
                """
                INSERT INTO research_task_jobs
                    (job_id, task_id, job_key, stage, attempt, status, payload,
                     available_at, created_at, updated_at, transition_status, transition_attempts)
                VALUES (%s, %s, %s, %s, %s, 'pending', %s::jsonb,
                        NOW(), NOW(), NOW(), 'not_ready', 0)
                ON CONFLICT (task_id, job_key) DO NOTHING
                """,
                (
                    str(uuid.uuid4()), next_event["task_id"],
                    queue_job_key(next_event["stage"], next_event["work_item_id"], next_event["attempt"]),
                    next_event["stage"], next_event["attempt"],
                    json.dumps(next_event["payload"], ensure_ascii=False),
                ),
            )

        # Select the earliest outstanding stage after successors have been
        # inserted. This preserves P8 batch progress while any P8 work item is
        # still queued/running. P9 deliberately does not mark the task
        # completed: delivery storage/publication must finish first.
        cursor.execute(
            """
            UPDATE research_tasks AS task
               SET current_stage = COALESCE(
                       (SELECT queued.stage
                          FROM research_task_jobs AS queued
                         WHERE queued.task_id = task.task_id
                           AND queued.status IN ('pending','running')
                         ORDER BY array_position(ARRAY['P1','P2','P3','P4','P5','P6','P7','P8','P9'], queued.stage),
                                  queued.job_key, queued.attempt
                         LIMIT 1),
                       task.current_stage),
                   status = 'running',
                   updated_at = NOW()
             WHERE task.task_id = %s AND task.status IN ('queued','running')
            """,
            (current["task_id"],),
        )
        connection.commit()
        return True
    except Exception:
        connection.rollback()
        raise


def fail_stage(connection, job: dict) -> bool:
    """Mark a currently leased attempt failed without silently retrying it."""
    if not isinstance(job, dict) or not job.get("lease_token"):
        raise WorkerEventError("队列任务缺少租约令牌")
    event = validate_worker_event(job)
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE research_task_jobs
           SET status = 'permanent_failed', lease_until = NULL, lease_token = NULL, updated_at = NOW()
         WHERE job_id = %s AND status = 'running' AND lease_token = %s
           AND lease_until >= NOW()
        RETURNING task_id
        """,
        (str(job.get("job_id") or ""), str(job["lease_token"])),
    )
    updated = cursor.fetchone()
    connection.commit()
    return bool(updated)


def execute_queued_stage(connection, workflow, next_jobs_for_stage, lease_seconds: int = 900,
                         stage_dispatcher=dispatch_queued_stage):
    """Claim and execute one queued stage through an injected transition planner."""
    if not callable(next_jobs_for_stage):
        raise TypeError("必须提供阶段转换规划器")
    job = claim_next_stage(connection, lease_seconds)
    if job is None:
        return {"accepted": False, "reason": "queue_empty"}
    try:
        set_task_context = getattr(workflow, "set_task_context", None)
        if callable(set_task_context):
            set_task_context(job["task_id"])
        if not callable(stage_dispatcher):
            raise TypeError("必须提供阶段执行器")
        result = normalize_stage_result(stage_dispatcher(workflow, job["stage"], job["payload"]))
        next_jobs = next_jobs_for_stage(job, result)
        if next_jobs is None:
            next_jobs = []
        if not isinstance(next_jobs, (dict, list, tuple)):
            raise WorkerEventError("阶段转换规划器必须返回对象列表")
        if not complete_stage_and_enqueue_next(connection, job, result, next_jobs):
            return {"accepted": False, "reason": "lease_lost", "task_id": job["task_id"]}
    except Exception:
        fail_stage(connection, job)
        raise
    return {
        "accepted": True,
        "status": "succeeded",
        "task_id": job["task_id"],
        "stage": job["stage"],
        "result": result,
    }


__all__ = [
    "claim_next_stage",
    "complete_stage_and_enqueue_next",
    "enqueue_stage",
    "execute_queued_stage",
    "fail_stage",
    "normalize_stage_result",
]
