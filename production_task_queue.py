"""PostgreSQL-backed production task creation and durable job queue."""

from __future__ import annotations

import json
import uuid


VALID_TIERS = frozenset({"fast", "deep"})
VALID_STAGES = frozenset("P%d" % number for number in range(1, 10))


def _json(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class PostgresTaskQueue:
    def __init__(self, connection):
        self.connection = connection

    def create_task(self, *, user_id, topic, tier):
        topic = str(topic or "").strip()
        tier = str(tier or "").strip()
        if not 2 <= len(topic) <= 500 or tier not in VALID_TIERS:
            raise ValueError("任务主题或版本无效")
        task_id = "TASK-" + uuid.uuid4().hex[:12]
        job_id = str(uuid.uuid4())
        cursor = self.connection.cursor()
        try:
            cursor.execute(
                """SELECT state FROM free_entitlements WHERE user_id=%s FOR UPDATE""",
                (str(user_id),),
            )
            row = cursor.fetchone()
            if not row or row[0] != "available":
                raise PermissionError("当前账户没有可用任务额度")
            cursor.execute(
                """INSERT INTO research_tasks
                       (task_id,user_id,topic,tier,status,current_stage,expires_at)
                     VALUES (%s,%s,%s,%s,'queued','P1',CURRENT_TIMESTAMP + INTERVAL '7 days')""",
                (task_id, str(user_id), topic, tier),
            )
            cursor.execute(
                """UPDATE free_entitlements SET state='reserved',task_id=%s,updated_at=CURRENT_TIMESTAMP
                     WHERE user_id=%s AND state='available'""",
                (task_id, str(user_id)),
            )
            cursor.execute(
                """INSERT INTO research_task_jobs
                       (job_id,task_id,job_key,stage,status,payload)
                     VALUES (%s,%s,'P1','P1','pending',%s::jsonb)""",
                (job_id, task_id, _json({"topic": topic, "tier": tier})),
            )
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            raise
        return {"task_id": task_id, "topic": topic, "tier": tier,
                "status": "queued", "current_stage": "P1"}

    def task_progress(self, *, user_id, task_id):
        cursor = self.connection.cursor()
        cursor.execute(
            """SELECT t.task_id,t.topic,t.tier,t.status,t.current_stage,t.created_at,t.updated_at,
                      j.result
                 FROM research_tasks t
                 LEFT JOIN LATERAL (
                     SELECT result FROM research_task_jobs
                      WHERE task_id=t.task_id AND status='succeeded'
                      ORDER BY updated_at DESC LIMIT 1
                 ) j ON TRUE
                WHERE t.task_id=%s AND t.user_id=%s""",
            (str(task_id), str(user_id)),
        )
        row = cursor.fetchone()
        if not row:
            raise LookupError("任务不存在")
        result = dict(zip(("task_id", "topic", "tier", "status", "current_stage",
                           "created_at", "updated_at", "stage_result"), row))
        for name in ("created_at", "updated_at"):
            if hasattr(result[name], "isoformat"):
                result[name] = result[name].isoformat()
        return result

    def claim_next(self, *, lease_seconds=900):
        lease_seconds = int(lease_seconds)
        if not 30 <= lease_seconds <= 3600:
            raise ValueError("任务租约必须在 30-3600 秒之间")
        token = str(uuid.uuid4())
        cursor = self.connection.cursor()
        cursor.execute(
            """WITH candidate AS (
                   SELECT job_id FROM research_task_jobs
                    WHERE status IN ('pending','retryable_failed') AND attempt<3
                      AND available_at<=CURRENT_TIMESTAMP
                      AND (lease_until IS NULL OR lease_until<CURRENT_TIMESTAMP)
                    ORDER BY created_at FOR UPDATE SKIP LOCKED LIMIT 1
               )
               UPDATE research_task_jobs j
                  SET status='running',attempt=attempt+1,lease_token=%s,
                      lease_until=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                      updated_at=CURRENT_TIMESTAMP
                 FROM candidate WHERE j.job_id=candidate.job_id
               RETURNING j.job_id,j.task_id,j.stage,j.attempt,j.payload""",
            (token, lease_seconds),
        )
        row = cursor.fetchone()
        if not row:
            self.connection.commit()
            return None
        cursor.execute(
            """UPDATE research_tasks SET status='running',current_stage=%s,updated_at=CURRENT_TIMESTAMP
                 WHERE task_id=%s AND status='queued'""",
            (row[2], row[1]),
        )
        self.connection.commit()
        return {"job_id": str(row[0]), "task_id": row[1], "stage": row[2],
                "attempt": row[3], "payload": row[4], "lease_token": token}

    def finish(self, job, *, result=None, error_code=None, retry_delay_seconds=None):
        token = str(job["lease_token"])
        cursor = self.connection.cursor()
        if error_code is None:
            status = "succeeded"
            available_at_sql = "available_at"
        elif retry_delay_seconds is not None:
            status = "retryable_failed"
            available_at_sql = "CURRENT_TIMESTAMP + (%s * INTERVAL '1 second')"
        else:
            status = "permanent_failed"
            available_at_sql = "available_at"
        params = [status, _json(result) if result is not None else None, error_code]
        if retry_delay_seconds is not None:
            params.append(max(1, int(retry_delay_seconds)))
        params.extend((str(job["job_id"]), token))
        cursor.execute(
            """UPDATE research_task_jobs
                  SET status=%s,result=%s::jsonb,error_code=%s,available_at=""" + available_at_sql + """,
                      lease_token=NULL,lease_until=NULL,updated_at=CURRENT_TIMESTAMP
                WHERE job_id=%s AND status='running' AND lease_token=%s
                  AND lease_until>=CURRENT_TIMESTAMP RETURNING task_id""",
            tuple(params),
        )
        row = cursor.fetchone()
        if not row:
            self.connection.rollback()
            return False
        if status == "permanent_failed":
            cursor.execute(
                """UPDATE research_tasks SET status='failed',updated_at=CURRENT_TIMESTAMP
                     WHERE task_id=%s AND status='running'""", (row[0],),
            )
            cursor.execute(
                """UPDATE free_entitlements SET state='available',task_id=NULL,updated_at=CURRENT_TIMESTAMP
                     WHERE task_id=%s AND state='reserved'""", (row[0],),
            )
        elif status == "succeeded":
            cursor.execute(
                """UPDATE research_tasks SET updated_at=CURRENT_TIMESTAMP
                     WHERE task_id=%s AND status='running'""", (row[0],),
            )
        self.connection.commit()
        return True


__all__ = ["PostgresTaskQueue"]
