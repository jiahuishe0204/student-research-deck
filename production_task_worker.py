"""Claim and execute one durable production research job."""

from __future__ import annotations

from pathlib import Path

from production_orchestrator import advance, retrieve_sources
from research_sources import screen_sources_with_quality
from scf_stage_dispatch import dispatch_stage


def _stage_result(value):
    if isinstance(value, tuple) and len(value) == 2:
        return {"data": value[0], "usage": value[1]}
    return {"data": value, "usage": {"prompt_tokens": 0, "completion_tokens": 0,
                                       "total_tokens": 0, "attempts": 0}}


def _dispatch(workflow, job, root):
    if job["stage"] != "P3":
        return dispatch_stage(workflow, job["stage"], job["payload"])
    payload = job["payload"]
    if payload.get("mode") == "retrieve":
        return retrieve_sources(payload["topic"], payload["plan"], payload["tier"],
                                root=Path(root)), {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0,
        }
    screening, usage, sources, _ = screen_sources_with_quality(
        workflow, payload["topic"], payload["plan"], payload["sources"], payload["tier"],
        queries=(payload.get("search") or {}).get("queries", []),
    )
    return {"screening": screening, "sources": sources}, usage


def execute_next_job(queue, workflow, *, root=None, advance_job=advance):
    transition = queue.claim_transition()
    if transition is not None:
        try:
            next_stage = advance_job(queue, transition, transition["result"], root=Path(root or "."))
        except Exception as exc:
            queue.finish_transition(transition, error_code=type(exc).__name__)
            raise
        if not queue.finish_transition(transition):
            raise RuntimeError("阶段推进租约已失效，拒绝旧 Worker 提交状态")
        return {"accepted": True, "task_id": transition["task_id"],
                "stage": transition["stage"], "status": "advanced", "next": next_stage}
    job = queue.claim_next()
    if job is None:
        return {"accepted": False, "reason": "empty"}
    try:
        if hasattr(workflow, "set_task_context"):
            workflow.set_task_context(job["task_id"])
        result = _stage_result(_dispatch(workflow, job, Path(root or ".")))
    except Exception as exc:
        retry_delay = 60 if int(job.get("attempt", 1)) < 3 else None
        queue.finish(job, error_code=type(exc).__name__, retry_delay_seconds=retry_delay)
        raise
    if not queue.finish(job, result=result):
        raise RuntimeError("任务队列租约已失效，拒绝旧 Worker 提交结果")
    return {"accepted": True, "task_id": job["task_id"], "stage": job["stage"],
            "status": "succeeded", "next": "transition_pending", "result": result}


__all__ = ["execute_next_job"]
