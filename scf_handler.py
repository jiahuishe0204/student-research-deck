"""腾讯云 SCF worker 的最小事件入口。

第一阶段只负责校验事件契约，不执行科研阶段。这样可以先在本地验证
SCF 传入事件的形状，再接入 PostgreSQL、阶段领取和 WorkflowService。
"""

from __future__ import annotations

from typing import Any, Mapping


VALID_STAGES = frozenset(f"P{index}" for index in range(1, 10))


class WorkerEventError(ValueError):
    """事件不符合 worker 契约。"""


def validate_worker_event(event: Any) -> dict[str, Any]:
    """校验并规范化一个 SCF worker 事件。

    事件暂定格式：
    ``{"task_id": "TASK-...", "stage": "P1", "attempt": 1, "payload": {}}``。
    该函数不读取密钥、不访问网络，也不改变任务状态。
    """

    if not isinstance(event, Mapping):
        raise WorkerEventError("worker 事件必须是 JSON 对象")

    task_id = str(event.get("task_id") or "").strip()
    if not task_id or len(task_id) > 128:
        raise WorkerEventError("task_id 必须是 1-128 个字符")

    stage = str(event.get("stage") or "").strip().upper()
    if stage not in VALID_STAGES:
        raise WorkerEventError("stage 必须是 P1-P9")

    attempt = event.get("attempt", 1)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 100:
        raise WorkerEventError("attempt 必须是 1-100 的整数")

    payload = event.get("payload", {})
    if not isinstance(payload, Mapping):
        raise WorkerEventError("payload 必须是 JSON 对象")

    return {
        "task_id": task_id,
        "stage": stage,
        "attempt": attempt,
        "payload": dict(payload),
    }


def handler(event: Any, context: Any = None) -> dict[str, Any]:
    """SCF 入口的第一阶段实现：校验事件并返回可观测结果。"""

    normalized = validate_worker_event(event)
    return {
        "ok": True,
        "accepted": True,
        "task_id": normalized["task_id"],
        "stage": normalized["stage"],
        "attempt": normalized["attempt"],
        "next": "database_claim",
    }


__all__ = ["VALID_STAGES", "WorkerEventError", "validate_worker_event", "handler"]
