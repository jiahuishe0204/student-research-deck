"""Small orchestration boundary between SCF events and stage executors."""

from __future__ import annotations

from typing import Any, Callable

from scf_claims import claim_stage
from scf_handler import validate_worker_event


def run_claimed_stage(connection, event: Any, executor: Callable[[dict], dict]) -> dict:
    """Claim an event and execute it only when this worker owns the lease."""

    normalized = validate_worker_event(event)
    claimed = claim_stage(
        connection,
        normalized["task_id"],
        normalized["stage"],
        normalized["attempt"],
    )
    if not claimed:
        return {
            "ok": True,
            "accepted": False,
            "reason": "stage_already_running_or_completed",
            "task_id": normalized["task_id"],
            "stage": normalized["stage"],
            "attempt": normalized["attempt"],
        }
    result = executor(normalized)
    if not isinstance(result, dict):
        raise TypeError("阶段执行器必须返回 JSON 对象")
    return {
        "ok": True,
        "accepted": True,
        "task_id": normalized["task_id"],
        "stage": normalized["stage"],
        "attempt": normalized["attempt"],
        "result": result,
    }


__all__ = ["run_claimed_stage"]
