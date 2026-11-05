"""Translate worker payloads into explicit WorkflowService calls."""

from __future__ import annotations

from scf_stage_registry import get_stage_spec


def dispatch_queued_stage(workflow, stage: str, payload: dict, *, research_pipeline_fn=None,
                          research_pipeline_options=None, delivery_publisher_fn=None):
    """Dispatch a database-claimed stage, with P3 retrieval injected explicitly.

    P3 can call public and licensed external providers. Requiring the pipeline
    dependency to be injected makes provider selection and cost policy an
    explicit runtime configuration instead of silently inheriting machine
    environment or credentials.
    """
    if str(stage).upper() == "P9" and isinstance(payload, dict) and payload.get("action") == "publish":
        if not callable(delivery_publisher_fn):
            raise RuntimeError("P9 私有交付发布器未配置；已拒绝把任务标记为完成")
        return delivery_publisher_fn(payload), {
            "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0,
        }, {"delivery": "private_cos_atomic_three_artifact"}
    if str(stage).upper() != "P3":
        return dispatch_stage(workflow, stage, payload)
    if not isinstance(payload, dict):
        raise TypeError("阶段 payload 必须是 JSON 对象")
    missing = [name for name in ("topic", "plan", "tier") if name not in payload]
    if missing:
        raise ValueError(f"P3 缺少输入：{', '.join(missing)}")
    if not callable(research_pipeline_fn):
        raise RuntimeError("P3 检索流程未显式配置；为避免意外外部请求，已停止执行")

    result = research_pipeline_fn(
        workflow,
        topic=payload["topic"],
        plan=payload["plan"],
        tier=payload["tier"],
        **(research_pipeline_options or {}),
    )
    if not isinstance(result, dict):
        raise TypeError("P3 检索流程必须返回对象")
    sources = result.get("sources")
    screening = result.get("screening")
    usage = result.get("usage", {})
    if not isinstance(sources, dict) or not isinstance(sources.get("records"), list):
        raise ValueError("P3 检索流程缺少来源记录")
    if not isinstance(screening, dict) or not isinstance(usage, dict):
        raise ValueError("P3 检索流程缺少筛选结果或 usage")
    data = {
        "sources": sources["records"],
        "screening": screening,
        "supplemental_search": bool(result.get("supplemental_search", False)),
    }
    metadata = {"retrieval_query_count": len(sources.get("queries", []))}
    return data, usage, metadata


def dispatch_stage(workflow, stage: str, payload: dict):
    """Dispatch one stage without guessing arguments or silently dropping data."""

    spec = get_stage_spec(stage)
    if not isinstance(payload, dict):
        raise TypeError("阶段 payload 必须是 JSON 对象")
    method = getattr(workflow, spec.method, None)
    if method is None or not callable(method):
        raise AttributeError(f"WorkflowService 缺少 {spec.method}")

    missing = [name for name in spec.reads if name not in payload]
    if missing:
        raise ValueError(f"{spec.stage} 缺少输入：{', '.join(missing)}")

    if spec.stage == "P1":
        return method(payload["topic"], payload["tier"])
    if spec.stage == "P2":
        return method(payload["topic"], payload.get("clarification", ""), payload["tier"], payload["intent"])
    if spec.stage == "P3":
        return method(payload["topic"], payload["plan"], payload["sources"], payload["tier"])
    if spec.stage == "P4":
        return method(payload["source_record"], payload["question_ids"], payload["tier"])
    if spec.stage == "P5":
        return method(payload["intent"], payload["plan"], payload["evidence"], payload["tier"], payload.get("evidence_contexts", []), payload.get("figure_records", []))
    if spec.stage == "P6":
        return method(payload["intent"], payload["report"], payload["evidence"], payload.get("figure_records", []), payload.get("constraints", {}), payload["tier"], payload.get("plan"), payload.get("sources", []))
    if spec.stage == "P7":
        return method(payload["report"], payload["ppt"], payload["evidence_ids"], payload["tier"])
    if spec.stage == "P8":
        return method(payload["claims"], payload["evidence"], payload["sources"], payload["tier"], payload.get("pro_claim_ids"))
    if spec.stage == "P9":
        return method(payload["verification"], payload["report"], payload["ppt"], payload["claims"], payload["source_ids"], payload["evidence_ids"], payload.get("evidence_version", "1.0"), payload.get("evidence_records"), payload.get("source_records"), payload.get("figure_records"))
    raise ValueError("未实现的阶段")


__all__ = ["dispatch_stage", "dispatch_queued_stage"]
