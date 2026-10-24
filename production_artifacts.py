"""Render and publish the three private artifacts produced by P9."""

from __future__ import annotations

import json


def build_final_artifacts(task_id, final_delivery, stage_payload):
    if not isinstance(final_delivery, dict) or not isinstance(stage_payload, dict):
        raise ValueError("P9 交付输入无效")
    report = final_delivery.get("final_report") or {}
    ppt = final_delivery.get("final_ppt") or {}
    markdown = str(report.get("markdown") or "").strip()
    pages = ppt.get("pages")
    sources = stage_payload.get("source_records")
    evidence = stage_payload.get("evidence_records")
    if not markdown or not isinstance(pages, list) or not pages:
        raise ValueError("P9 缺少报告或 PPT 内容")
    if not isinstance(sources, list) or not isinstance(evidence, list):
        raise ValueError("P9 缺少参考文献或证据记录")
    suffix = str(task_id).replace("-", "_")
    return (
        {"artifact_id": "REPORT_" + suffix, "kind": "report", "extension": "md",
         "content_type": "text/markdown; charset=utf-8", "body": markdown + "\n"},
        {"artifact_id": "PPTCONTENT_" + suffix, "kind": "ppt_content", "extension": "json",
         "content_type": "application/json", "body": json.dumps(
             {"deck_title": ppt.get("deck_title"), "storyline": ppt.get("storyline"), "pages": pages},
             ensure_ascii=False, indent=2)},
        {"artifact_id": "REFERENCES_" + suffix, "kind": "references", "extension": "json",
         "content_type": "application/json", "body": json.dumps(
             {"sources": sources, "evidence_records": evidence,
              "evidence_version": stage_payload.get("evidence_version", "1.0")},
             ensure_ascii=False, indent=2)},
    )


def publish_final_artifacts(lifecycle, task_id, final_delivery, stage_payload):
    published = []
    for artifact in build_final_artifacts(task_id, final_delivery, stage_payload):
        published.append(lifecycle.publish(task_id=task_id, **artifact))
    return published


__all__ = ["build_final_artifacts", "publish_final_artifacts"]
