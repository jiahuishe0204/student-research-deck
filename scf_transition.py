"""Deterministic transitions for the PostgreSQL-backed P1-P9 worker queue.

The planner is deliberately side-effect free apart from read-only queue queries.
It runs before the current lease is committed, so the current result is merged
in-memory with prior succeeded results when constructing the next payload.
"""

from __future__ import annotations

import json

from scf_handler import WorkerEventError
from scf_queue_contracts import parse_queue_job_key, queue_job_key


P8_BATCH_SIZE = 6


def _decoded(value):
    if isinstance(value, str):
        value = json.loads(value)
    if not isinstance(value, dict):
        raise WorkerEventError("队列中保存的阶段结果不是 JSON 对象")
    return value


def _stage_rows(connection, task_id, stage):
    cursor = connection.cursor()
    cursor.execute(
        """SELECT job_key,result FROM research_task_jobs
             WHERE task_id=%s AND stage=%s AND status='succeeded'
             ORDER BY job_key,attempt""",
        (str(task_id), str(stage)),
    )
    rows = []
    for row in cursor.fetchall():
        parsed = parse_queue_job_key(row[0])
        if parsed and parsed[0] == str(stage):
            rows.append((parsed[1], _decoded(row[1])))
    return rows


def _with_current(connection, job, result):
    rows = _stage_rows(connection, job["task_id"], job["stage"])
    rows = [(key, value) for key, value in rows if key != job["work_item_id"]]
    rows.append((job["work_item_id"], result))
    return sorted(rows, key=lambda row: row[0])


def _data(result, stage):
    value = result.get("data") if isinstance(result, dict) else None
    if not isinstance(value, dict):
        raise WorkerEventError(stage + " 阶段结果缺少 data 对象")
    return value


def _job(task_id, stage, payload, work_item_id="main"):
    return {
        "task_id": str(task_id), "stage": stage, "work_item_id": work_item_id,
        "attempt": 1, "payload": payload,
    }


def _source_context(connection, task_id):
    rows = _stage_rows(connection, task_id, "P3")
    if not rows:
        raise WorkerEventError("P4 完成后找不到已保存的 P3 检索结果")
    p3 = _data(rows[-1][1], "P3")
    sources = p3.get("sources")
    screening = p3.get("screening")
    if not isinstance(sources, list) or not isinstance(screening, dict):
        raise WorkerEventError("P3 结果缺少来源或筛选结构")
    by_id = {item.get("source_id"): item for item in sources if isinstance(item, dict) and item.get("source_id")}
    decisions = screening.get("decisions")
    if not isinstance(decisions, list):
        raise WorkerEventError("P3 筛选结果缺少 decisions")
    kept = [item for item in decisions if isinstance(item, dict) and item.get("status") == "keep"]
    return p3, by_id, kept


def _evidence_context(connection, task_id, current_job=None, current_result=None):
    p3, source_by_id, _ = _source_context(connection, task_id)
    p4_rows = (_with_current(connection, current_job, current_result)
               if current_job and current_job["stage"] == "P4"
               else _stage_rows(connection, task_id, "P4"))
    evidence, figures = [], []
    for _, envelope in p4_rows:
        data = _data(envelope, "P4")
        evidence.extend(item for item in data.get("evidence_records", []) if isinstance(item, dict))
        figures.extend(item for item in data.get("figure_records", []) if isinstance(item, dict))
    seen = set()
    evidence = [item for item in evidence if item.get("evidence_id") and not (item["evidence_id"] in seen or seen.add(item["evidence_id"]))]
    seen_figures = set()
    figures = [item for item in figures if item.get("figure_id") and not (item["figure_id"] in seen_figures or seen_figures.add(item["figure_id"]))]
    source_ids = {item.get("source_id") for item in evidence if item.get("source_id")}
    source_records = [source_by_id[source_id] for source_id in source_by_id if source_id in source_ids]
    return p3, source_records, evidence, figures


def _outstanding(connection, task_id, stage, except_work_item_id):
    cursor = connection.cursor()
    cursor.execute(
        """SELECT 1 FROM research_task_jobs
             WHERE task_id=%s AND stage=%s AND status IN ('pending','running')
               AND job_key<>%s LIMIT 1""",
        (str(task_id), stage, except_work_item_id),
    )
    return cursor.fetchone() is not None


def plan_next_stage(connection, job: dict, result: dict):
    """Construct the next durable jobs for one completed result envelope."""
    stage = str(job.get("stage", "")).upper()
    task_id = str(job.get("task_id", ""))
    payload = job.get("payload")
    if not task_id or not isinstance(payload, dict) or not isinstance(result, dict):
        raise WorkerEventError("阶段转换输入无效")
    tier = payload.get("tier", "fast")

    if stage == "P2":
        plan = _data(result, stage)
        return [_job(task_id, "P3", {
            "topic": payload["topic"], "intent": payload["intent"],
            "plan": plan, "tier": tier,
        })]

    if stage == "P3":
        data = _data(result, stage)
        sources = data.get("sources")
        screening = data.get("screening")
        if not isinstance(sources, list) or not isinstance(screening, dict):
            raise WorkerEventError("P3 结果缺少来源或筛选结果")
        source_by_id = {item.get("source_id"): item for item in sources if isinstance(item, dict) and item.get("source_id")}
        jobs = []
        for decision in screening.get("decisions", []):
            if not isinstance(decision, dict) or decision.get("status") != "keep":
                continue
            source_id = decision.get("source_id")
            source = source_by_id.get(source_id)
            if not source:
                raise WorkerEventError("P3 keep 决策没有对应来源：" + str(source_id))
            ids = decision.get("question_ids") or []
            jobs.append(_job(task_id, "P4", {
                "source_record": source, "question_ids": ids, "tier": tier,
                "intent": payload.get("intent"), "plan": payload.get("plan"),
            }, "source:" + str(source_id)))
        if not jobs:
            return [_job(task_id, "P9", {
                "action": "publish", "completion_status": "partial",
                "final_delivery": _insufficient_evidence_delivery(payload.get("topic", "科研调研"), screening),
                "source_records": [], "tier": tier,
            }, "publish")]
        return jobs

    if stage == "P4":
        if _outstanding(connection, task_id, "P4", job.get("job_key") or queue_job_key("P4", job["work_item_id"], job.get("attempt", 1))):
            return []
        p3, source_records, evidence, figures = _evidence_context(connection, task_id, job, result)
        intent = payload.get("intent")
        plan = payload.get("plan")
        if not isinstance(intent, dict) or not isinstance(plan, dict):
            raise WorkerEventError("P4 任务缺少可恢复的 intent/plan 上下文")
        return [_job(task_id, "P5", {
            "intent": intent, "plan": plan, "evidence": evidence,
            "evidence_contexts": [], "figure_records": figures,
            "sources": source_records, "tier": tier,
        })]

    if stage == "P5":
        p3, source_records, evidence, figures = _evidence_context(connection, task_id)
        return [_job(task_id, "P6", {
            "intent": payload["intent"], "plan": payload["plan"],
            "report": _data(result, stage), "evidence": evidence,
            "figure_records": figures, "sources": source_records,
            "constraints": {}, "tier": tier,
        })]

    if stage == "P6":
        _, source_records, evidence, figures = _evidence_context(connection, task_id)
        return [_job(task_id, "P7", {
            "report": payload["report"], "ppt": _data(result, stage),
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "tier": tier,
        })]

    if stage == "P7":
        claims = _data(result, stage)
        items = claims.get("claims")
        if not isinstance(items, list) or not items:
            raise WorkerEventError("P7 未产生可核验主张，不能继续 P8")
        _, source_records, evidence, _ = _evidence_context(connection, task_id)
        jobs = []
        for offset in range(0, len(items), P8_BATCH_SIZE):
            index = offset // P8_BATCH_SIZE + 1
            jobs.append(_job(task_id, "P8", {
                "claims": {**claims, "claims": items[offset:offset + P8_BATCH_SIZE]},
                "evidence": evidence, "sources": source_records,
                "tier": tier,
            }, "batch:%04d" % index))
        return jobs

    if stage == "P8":
        if _outstanding(connection, task_id, "P8", job.get("job_key") or queue_job_key("P8", job["work_item_id"], job.get("attempt", 1))):
            return []
        rows = _with_current(connection, job, result)
        # The current payload carries only this batch. Gather the canonical full
        # claim set from P7 and merge completed batch results in stable order.
        p7_rows = _stage_rows(connection, task_id, "P7")
        if not p7_rows:
            raise WorkerEventError("P8 汇总时找不到已保存的 P7 声明集合")
        full_claims = _data(p7_rows[-1][1], "P7")
        claims_by_id = {item.get("claim_id"): item for item in full_claims.get("claims", []) if isinstance(item, dict)}
        verifications = []
        for _, envelope in rows:
            batch_data = _data(envelope, "P8")
            verifications.extend(item for item in batch_data.get("results", []) if isinstance(item, dict))
        expected = set(claims_by_id)
        actual = {item.get("claim_id") for item in verifications}
        if actual != expected:
            raise WorkerEventError("P8 批次汇总不完整，拒绝进入 P9")
        result_order = {claim_id: index for index, claim_id in enumerate(claims_by_id)}
        verifications.sort(key=lambda item: result_order[item["claim_id"]])
        summary = {key: sum(item.get("support_status") == key for item in verifications)
                   for key in ("supported", "partially_supported", "unsupported", "cannot_determine")}
        summary["high_risk_remaining"] = 0
        verification = {"verification_version": "P8-queue-batched-1.0", "results": verifications, "summary": summary}
        _, source_records, evidence, figures = _evidence_context(connection, task_id)
        report = _stage_data(connection, task_id, "P5")
        ppt = _stage_data(connection, task_id, "P6")
        return [_job(task_id, "P9", {
            "verification": verification, "report": report, "ppt": ppt,
            "completion_status": "partial" if report.get("status") == "insufficient_evidence" else "completed",
            "claims": full_claims, "source_ids": [item["source_id"] for item in source_records],
            "evidence_ids": [item["evidence_id"] for item in evidence],
            "evidence_version": "1.0", "evidence_records": evidence,
            "source_records": source_records, "figure_records": figures,
            "tier": tier,
        })]

    if stage == "P9":
        if payload.get("action") == "publish":
            return []
        return [_job(task_id, "P9", {
            "action": "publish", "completion_status": payload.get("completion_status", "completed"),
            "final_delivery": _data(result, stage),
            "source_records": payload.get("source_records", []), "tier": tier,
        }, "publish")]

    raise WorkerEventError("未知工作阶段：" + stage)


def _stage_data(connection, task_id, stage):
    rows = _stage_rows(connection, task_id, stage)
    if not rows:
        raise WorkerEventError("缺少已保存的 " + stage + " 阶段结果")
    return _data(rows[-1][1], stage)


def _insufficient_evidence_delivery(topic, screening):
    summary = screening.get("summary") if isinstance(screening, dict) else {}
    summary = summary if isinstance(summary, dict) else {}
    candidate_count = int(summary.get("candidate_count", 0) or 0)
    reserve_count = int(summary.get("reserve_count", 0) or 0)
    drop_count = int(summary.get("drop_count", 0) or 0)
    issues = summary.get("open_issues", [])
    if not isinstance(issues, list):
        issues = []
    note = "本次快速检索未得到可进一步提取、并能支持研究结论的来源。"
    report = "# %s\n\n## 结果状态\n\n%s\n\n## 检索与筛选记录\n\n候选来源：%d 条；保留：0 条；备选：%d 条；排除：%d 条。\n\n## 证据边界\n\n因此，本交付不对研究问题作实质性科学结论，也不把缺少资料解释为阴性结果。建议检查主题范围、时间限制和可访问的资料类型后重新检索。\n\n## 待解决问题\n\n%s\n" % (
        str(topic or "科研调研"), note, candidate_count, reserve_count, drop_count,
        "\n".join("- " + str(item) for item in issues) if issues else "- 需要进一步检索与人工复核。",
    )
    page = {
        "page_id": "SL-01", "title": "当前检索未形成可核验结论",
        "navigation_title": "证据不足", "purpose": "明确本轮检索的实际边界",
        "on_slide_text": ["目前未获得可支持科学结论的可核验证据。"],
        "visual_suggestion": "以简洁边界提示页呈现，不使用未经核验的图表。",
        "speaker_notes": "本页只说明本轮检索与筛选结果，不代表研究领域不存在相关证据。",
        "evidence_ids": [], "figure_refs": [], "source_citations": [],
    }
    return {
        "delivery_version": "P9-insufficient-evidence-1.0", "evidence_version": "1.0",
        "final_report": {"title": str(topic or "科研调研") + "（证据不足说明）", "markdown": report, "used_evidence_ids": []},
        "final_ppt": {"deck_title": str(topic or "科研调研") + "（本轮检索边界）", "storyline": "如实说明本轮未形成可核验证据", "pages": [page]},
        "verification_note": "未形成科学主张，故没有声称完成事实核验。",
        "open_issues": [note] + [str(item) for item in issues],
        "source_ids": [], "evidence_ids": [], "change_log": [],
    }


__all__ = ["P8_BATCH_SIZE", "plan_next_stage"]
