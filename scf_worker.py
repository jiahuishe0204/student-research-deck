"""Local-testable worker orchestration used by the future SCF handler."""

from __future__ import annotations

from scf_claims import claim_stage, finish_stage
from scf_handler import validate_worker_event
from scf_stage_dispatch import dispatch_stage


def execute_worker_event(connection, workflow, event):
    """Claim, dispatch, and persist terminal status for one stage attempt."""
    normalized = validate_worker_event(event)
    args = (normalized["task_id"], normalized["stage"], normalized["attempt"])
    lease_token = claim_stage(connection, *args, work_item_id=normalized["work_item_id"])
    if not lease_token:
        return {"accepted": False, "reason": "not_claimed", "task_id": normalized["task_id"]}
    try:
        set_task_context = getattr(workflow, "set_task_context", None)
        if callable(set_task_context):
            set_task_context(normalized["task_id"])
        result = dispatch_stage(workflow, normalized["stage"], normalized["payload"])
    except Exception:
        finish_stage(connection, *args, lease_token, "failed", work_item_id=normalized["work_item_id"])
        raise
    if not finish_stage(connection, *args, lease_token, "succeeded", work_item_id=normalized["work_item_id"]):
        raise RuntimeError("阶段租约已失效，拒绝旧 Worker 提交结果")
    return {"accepted": True, "status": "succeeded", "task_id": normalized["task_id"], "stage": normalized["stage"], "work_item_id": normalized["work_item_id"], "result": result}


__all__ = ["execute_worker_event"]
