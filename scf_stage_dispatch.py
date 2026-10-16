"""Translate worker payloads into explicit WorkflowService calls."""

from __future__ import annotations

from scf_stage_registry import get_stage_spec


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


__all__ = ["dispatch_stage"]
