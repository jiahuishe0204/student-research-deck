"""Publish a queue-completed report/PPT-content/references package privately."""

from __future__ import annotations

import json
import uuid

from delivery_lifecycle import DeliveryLifecycle
from delivery_repository import PostgresDeliveryRepository
from production_config import load_cos_config, load_delivery_common_config
from tencent_delivery import TencentCosArtifactStore


def artifact_bodies(final_delivery, source_records):
    if not isinstance(final_delivery, dict):
        raise ValueError("最终交付必须是对象")
    report = final_delivery.get("final_report")
    ppt = final_delivery.get("final_ppt")
    if not isinstance(report, dict) or not str(report.get("markdown") or "").strip():
        raise ValueError("最终报告内容为空")
    if not isinstance(ppt, dict) or not isinstance(ppt.get("pages"), list) or not ppt["pages"]:
        raise ValueError("演示逐页内容为空")
    sources = [
        {key: source.get(key) for key in ("source_id", "source", "title", "authors", "journal", "year", "url", "access")}
        for source in source_records if isinstance(source, dict) and source.get("source_id")
    ]
    references = {
        "topic": report.get("title", "科研调研"),
        "source_ids": final_delivery.get("source_ids", []),
        "sources": sources,
        "evidence_ids": final_delivery.get("evidence_ids", []),
        "open_issues": final_delivery.get("open_issues", []),
    }
    return {
        "report": (str(report.get("markdown")), "md", "text/markdown; charset=utf-8"),
        "ppt_content": (json.dumps(ppt, ensure_ascii=False, indent=2), "json", "application/json"),
        "references": (json.dumps(references, ensure_ascii=False, indent=2), "json", "application/json"),
    }


def publish_final_delivery(connection, payload, *, environ=None, repository=None,
                           artifact_store=None, clock=None):
    """Upload three deterministic private artifacts; DB publishes only at 3/3."""
    task_id = str(payload.get("task_id") or "").strip()
    final_delivery = payload.get("final_delivery")
    source_records = payload.get("source_records") or []
    completion_status = payload.get("completion_status", "completed")
    if not task_id or completion_status not in {"completed", "partial"}:
        raise ValueError("最终交付的任务标识或状态无效")
    if repository is None or artifact_store is None:
        common = load_delivery_common_config(environ)
        cos = load_cos_config(environ)
        repository = repository or PostgresDeliveryRepository(connection, common.public_origin)
        artifact_store = artifact_store or TencentCosArtifactStore.from_config(cos)
    lifecycle = DeliveryLifecycle(repository, artifact_store, clock=clock)
    outcomes = {}
    for kind, (body, extension, content_type) in artifact_bodies(final_delivery, source_records).items():
        artifact_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "student-research-deck:%s:%s" % (task_id, kind)))
        outcomes[kind] = lifecycle.publish(
            task_id=task_id,
            artifact_id=artifact_id,
            kind=kind,
            extension=extension,
            body=body,
            content_type=content_type,
            completion_status=completion_status,
        )
    if outcomes.get("references", {}).get("status") != "published":
        raise RuntimeError("报告、演示内容和参考来源未完成原子发布")
    return {"status": "published", "completion_status": completion_status,
            "artifact_kinds": sorted(outcomes)}


__all__ = ["artifact_bodies", "publish_final_delivery"]
