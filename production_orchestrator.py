"""Deterministic transitions between durable P1-P9 production jobs."""

from __future__ import annotations

import os

from epo_ops import EPOClient
from patsnap_mcp import PatsnapMCPClient
from retrieval import search_all, search_patsnap_literature
from research_sources import merge_search_results, plan_patsnap_queries, plan_search_queries
from production_task_queue import p8_recovery_job_key


P8_BATCH_SIZE = 4


def _data(result):
    value = (result or {}).get("data")
    # P7 results produced by older worker versions persisted the full
    # (data, usage, metadata) tuple as a JSON array. Accept that legacy shape
    # so an already-paid successful stage can resume its transition safely.
    if (isinstance(value, list) and len(value) == 3 and
            isinstance(value[0], dict) and isinstance(value[1], dict)):
        value = value[0]
    if not isinstance(value, dict):
        raise RuntimeError("阶段结果格式无效")
    return value


def _one(queue, task_id, stage, job_key=None):
    jobs = queue.stage_jobs(task_id=task_id, stage=stage)
    if job_key is not None:
        jobs = [item for item in jobs if item["job_key"] == job_key]
    if len(jobs) != 1 or jobs[0]["status"] != "succeeded":
        raise RuntimeError("%s 阶段结果尚未就绪" % stage)
    return jobs[0]


def _patent_client(root):
    provider = os.environ.get("PATENT_PROVIDER", "").strip().lower()
    if provider in ("none", "disabled"):
        return None
    if provider in ("patsnap", "patsnap_mcp", "patsnap_mcp_cn") or (
            not provider and os.environ.get("PATSNAP_MCP_API_KEY", "").strip()):
        return PatsnapMCPClient.from_environment()
    return EPOClient.from_environment(root / "data" / "private" / "epo-usage.sqlite3")


def retrieve_sources(topic, plan, tier, *, root):
    queries = plan_search_queries(plan, topic)
    patent_client = _patent_client(root)
    batches = [search_all(query, per_source=4 if tier == "deep" else 3,
                          patent_client=patent_client if index == 0 else None,
                          patent_query=query, include_patsnap=False)
               for index, query in enumerate(queries)]
    if os.environ.get("PATSNAP_API_KEY", "").strip():
        cache = {}
        for query in plan_patsnap_queries(plan, topic):
            try:
                batches.append({"query": "Patsnap: " + query,
                                "records": search_patsnap_literature(query, 2, detail_cache=cache),
                                "errors": []})
            except Exception as exc:
                batches.append({"query": "Patsnap: " + query, "records": [],
                                "errors": [{"source": "Patsnap", "error": type(exc).__name__}]})
    result = merge_search_results(batches, 24 if tier == "deep" else 12)
    result["topic"] = topic
    return result


def advance(queue, job, result, *, root, publisher=None):
    """Persist only the next inputs; never let a model choose the transition."""
    task_id, stage, payload = job["task_id"], job["stage"], job["payload"]
    data = _data(result)
    if stage == "P1":
        return "awaiting_clarification"
    if stage == "P2":
        queue.enqueue(task_id=task_id, job_key="P3:retrieve", stage="P3", payload={
            "mode": "retrieve", "topic": payload["topic"], "plan": data,
            "tier": payload["tier"], "intent": payload["intent"],
        })
        return "P3:retrieve"
    if stage == "P3":
        if job.get("job_key") == "P3:retrieve":
            queue.enqueue(task_id=task_id, job_key="P3:screen", stage="P3", payload={
                "mode": "screen", "topic": payload["topic"], "plan": payload["plan"],
                "sources": data["records"], "tier": payload["tier"],
                "intent": payload["intent"], "search": data,
            })
            return "P3:screen"
        screening = data.get("screening", data)
        sources = data.get("sources", payload["sources"])
        if not screening.get("quality_gate", {}).get("passed", True):
            raise RuntimeError("来源质量门未通过")
        kept = [item for item in screening["decisions"] if item["status"] == "keep"]
        source_by_id = {item["source_id"]: item for item in sources}
        for decision in kept:
            source = source_by_id.get(decision["source_id"])
            if source:
                queue.enqueue(task_id=task_id, job_key="P4:" + decision["source_id"], stage="P4",
                              payload={"source_record": source, "question_ids": decision["question_ids"],
                                       "tier": payload["tier"]})
        if not kept:
            raise RuntimeError("筛选后没有可提取的来源")
        return "P4"
    if stage == "P4":
        p4_jobs = queue.stage_jobs(task_id=task_id, stage="P4")
        if not p4_jobs or any(item["status"] != "succeeded" for item in p4_jobs):
            return "P4"
        p1 = _one(queue, task_id, "P1")
        p2 = _one(queue, task_id, "P2")
        p3 = _one(queue, task_id, "P3", "P3:screen")
        groups = [_data(item["result"]) for item in p4_jobs]
        evidence = [record for group in groups for record in group.get("evidence_records", [])]
        figures = [record for group in groups for record in group.get("figure_records", [])]
        if not evidence:
            raise RuntimeError("保留来源没有可提取证据")
        queue.enqueue(task_id=task_id, job_key="P5", stage="P5", payload={
            "intent": _data(p1["result"]), "plan": _data(p2["result"]),
            "evidence": evidence, "evidence_contexts": [{"source_id": group.get("source_id"),
                "reading_scope": group.get("reading_scope")} for group in groups],
            "figure_records": figures, "sources": p3["payload"]["sources"],
            "tier": p3["payload"]["tier"],
        })
        return "P5"
    if stage == "P5":
        queue.enqueue(task_id=task_id, job_key="P6", stage="P6", payload={
            **payload, "report": data, "constraints": {"language": "zh-CN",
            "format": "storyboard_with_speaker_notes"},
        })
        return "P6"
    if stage == "P6":
        queue.enqueue(task_id=task_id, job_key="P7", stage="P7", payload={
            "report": payload["report"], "ppt": data,
            "evidence_ids": [item["evidence_id"] for item in payload["evidence"]],
            "tier": payload["tier"], "evidence": payload["evidence"],
            "sources": payload["sources"], "figure_records": payload["figure_records"],
        })
        return "P7"
    if stage == "P7":
        claims = data.get("claims")
        if not isinstance(claims, list) or not claims:
            raise RuntimeError("P7 未产生可核验主张")
        for offset in range(0, len(claims), P8_BATCH_SIZE):
            batch_claims = claims[offset:offset + P8_BATCH_SIZE]
            queue.enqueue(task_id=task_id,
                          job_key=p8_recovery_job_key(batch_claims, prefix="P8:batch:"),
                          stage="P8", payload={
                "claims": {**data, "claims": batch_claims},
                "all_claims": data,
                "evidence": payload["evidence"], "sources": payload["sources"],
                "tier": payload["tier"], "report": payload["report"],
                "ppt": payload["ppt"], "figure_records": payload["figure_records"],
            })
        return "P8:%d-batches" % ((len(claims) + P8_BATCH_SIZE - 1) // P8_BATCH_SIZE)
    if stage == "P8":
        p8_jobs = queue.stage_jobs(task_id=task_id, stage="P8")
        if not p8_jobs or any(item["status"] != "succeeded" for item in p8_jobs):
            return "P8:awaiting-batches"
        verifications = []
        for item in p8_jobs:
            result_data = _data(item["result"])
            verifications.extend(result_data.get("results", []))
        full_claims = payload.get("all_claims", payload["claims"])
        expected_ids = {item.get("claim_id") for item in full_claims.get("claims", [])}
        actual_ids = {item.get("claim_id") for item in verifications}
        if actual_ids != expected_ids:
            raise RuntimeError("P8 持久化批次未覆盖全部主张")
        order = {item.get("claim_id"): index for index, item in enumerate(full_claims.get("claims", []))}
        verifications.sort(key=lambda item: order[item["claim_id"]])
        verification = {"verification_version": "P8-queue-batched-1.0", "results": verifications,
                        "summary": {status: sum(item.get("support_status") == status for item in verifications)
                                    for status in ("supported", "partially_supported", "unsupported", "cannot_determine")}}
        verification["summary"]["high_risk_remaining"] = 0
        queue.enqueue(task_id=task_id, job_key="P9", stage="P9", payload={
            "verification": verification, "report": payload["report"], "ppt": payload["ppt"],
            "claims": full_claims["claims"],
            "source_ids": sorted({item["source_id"] for item in payload["evidence"]}),
            "evidence_ids": [item["evidence_id"] for item in payload["evidence"]],
            "evidence_version": "1.0", "evidence_records": payload["evidence"],
            "source_records": payload["sources"], "figure_records": payload["figure_records"],
        })
        return "P9"
    if stage == "P9":
        if publisher is None:
            raise RuntimeError("P9 缺少私有交付物发布器")
        publisher(task_id, data, payload)
        return "completed"
    raise ValueError("未知生产阶段")


__all__ = ["advance", "retrieve_sources"]
