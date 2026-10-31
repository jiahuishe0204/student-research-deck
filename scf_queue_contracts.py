"""Stable identities for durable database queue jobs."""

from __future__ import annotations

from urllib.parse import quote, unquote


def queue_job_key(stage: str, work_item_id: str = "main", attempt: int = 1) -> str:
    stage = str(stage or "").upper()
    work_item_id = str(work_item_id or "main")
    if stage not in {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"}:
        raise ValueError("队列阶段无效")
    if not 1 <= int(attempt) <= 3:
        raise ValueError("队列尝试次数必须在 1-3 之间")
    return "queue:%s:%s:%d" % (stage, quote(work_item_id, safe="-_"), int(attempt))


def parse_queue_job_key(value: str):
    parts = str(value or "").split(":", 3)
    if len(parts) != 4 or parts[0] != "queue":
        return None
    try:
        stage, work_item_id, attempt = parts[1], unquote(parts[2]), int(parts[3])
        if stage not in {"P1", "P2", "P3", "P4", "P5", "P6", "P7", "P8", "P9"} or not 1 <= attempt <= 3:
            return None
        return stage, work_item_id, attempt
    except (TypeError, ValueError):
        return None
