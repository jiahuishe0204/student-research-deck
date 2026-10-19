"""PostgreSQL transactional-outbox claim and completion primitives."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import random
import uuid


TERMINAL = frozenset({"succeeded", "permanent_failed", "unknown"})


def backoff_seconds(attempt, jitter=None):
    if not isinstance(attempt, int) or attempt < 1:
        raise ValueError("attempt 必须为正整数")
    base = min(3600, 15 * (2 ** min(attempt - 1, 8)))
    fraction = random.random() if jitter is None else float(jitter)
    return int(base + base * 0.25 * max(0.0, min(fraction, 1.0)))


def claim_event(connection, lease_seconds=120):
    if not 30 <= int(lease_seconds) <= 900:
        raise ValueError("事件租约必须为30—900秒")
    token = str(uuid.uuid4())
    cursor = connection.cursor()
    cursor.execute(
        """
        WITH candidate AS (
            SELECT event_id FROM delivery_events
             WHERE status IN ('pending','retryable_failed')
               AND available_at <= CURRENT_TIMESTAMP
               AND (lease_until IS NULL OR lease_until < CURRENT_TIMESTAMP)
               AND attempt_count < 8
             ORDER BY available_at, created_at
             FOR UPDATE SKIP LOCKED LIMIT 1
        )
        UPDATE delivery_events e
           SET status='running', attempt_count=attempt_count+1,
               lease_token=%s, lease_until=CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
               updated_at=CURRENT_TIMESTAMP
          FROM candidate WHERE e.event_id=candidate.event_id
        RETURNING e.event_id,e.event_type,e.task_id,e.user_id,e.payload,e.attempt_count
        """,
        (token, int(lease_seconds)),
    )
    row = cursor.fetchone()
    connection.commit()
    if not row:
        return None
    return {"lease_token": token, "event_id": row[0], "event_type": row[1],
            "task_id": row[2], "user_id": row[3], "payload": row[4], "attempt_count": row[5]}


def finish_event(connection, event_id, lease_token, status, *, provider_request_id=None,
                 error_code=None, retry_delay_seconds=None):
    allowed = TERMINAL | {"retryable_failed"}
    if status not in allowed:
        raise ValueError("事件结束状态无效")
    if status == "retryable_failed" and retry_delay_seconds is None:
        raise ValueError("可重试失败必须提供退避时间")
    cursor = connection.cursor()
    cursor.execute(
        """
        UPDATE delivery_events
           SET status=%s, provider_request_id=%s, last_error_code=%s,
               available_at=CASE WHEN %s='retryable_failed'
                   THEN CURRENT_TIMESTAMP + (%s * INTERVAL '1 second') ELSE available_at END,
               lease_token=NULL, lease_until=NULL, updated_at=CURRENT_TIMESTAMP
         WHERE event_id=%s AND status='running' AND lease_token=%s
           AND lease_until >= CURRENT_TIMESTAMP
        RETURNING event_id
        """,
        (status, provider_request_id, error_code, status, int(retry_delay_seconds or 0),
         str(event_id), str(lease_token)),
    )
    row = cursor.fetchone()
    connection.commit()
    return bool(row)


def classify_provider_failure(*, http_status=None, error_code="", ambiguous=False):
    if ambiguous:
        return "unknown"
    code = str(error_code or "").lower()
    if http_status == 429 or (http_status is not None and int(http_status) >= 500):
        return "retryable_failed"
    if any(term in code for term in ("throttl", "timeout", "internal", "unavailable")):
        return "retryable_failed"
    return "permanent_failed"


__all__ = ["backoff_seconds", "claim_event", "finish_event", "classify_provider_failure"]
