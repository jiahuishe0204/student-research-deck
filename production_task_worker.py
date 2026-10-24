"""Claim and execute one durable production research job."""

from __future__ import annotations

from scf_stage_dispatch import dispatch_stage


def execute_next_job(queue, workflow):
    job = queue.claim_next()
    if job is None:
        return {"accepted": False, "reason": "empty"}
    try:
        if hasattr(workflow, "set_task_context"):
            workflow.set_task_context(job["task_id"])
        result = dispatch_stage(workflow, job["stage"], job["payload"])
    except Exception as exc:
        retry_delay = 60 if int(job.get("attempt", 1)) < 3 else None
        queue.finish(job, error_code=type(exc).__name__, retry_delay_seconds=retry_delay)
        raise
    if not queue.finish(job, result=result):
        raise RuntimeError("任务队列租约已失效，拒绝旧 Worker 提交结果")
    return {"accepted": True, "task_id": job["task_id"], "stage": job["stage"],
            "status": "succeeded", "result": result}


__all__ = ["execute_next_job"]
