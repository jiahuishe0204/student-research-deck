#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Resume a report-only regression from persisted task artifacts."""

import argparse
import json
from pathlib import Path

from resume_live_regression import artifact, get, merge_verification
from run_live_regression import (
    MAX_VERIFICATION_CLAIMS, namespace_evidence_groups, persist, post,
    query_from_plan, select_pro_claim_ids, set_auth,
)
from workflow_validation import validate_report


def resume(state):
    base, task_id = state["base"], state["task_id"]
    set_auth(task_id, state["owner_token"])
    task = get(base, "/api/tasks/%s" % task_id)["data"]
    intent = artifact(task, "intent")
    if intent is None:
        intent = post(base, "/api/intent", {"topic": task["topic"], "tier": task["tier"]})["data"]
        persist(base, task_id, "P1", "intent_completed", intent, "intent")
    plan = artifact(task, "plan")
    if plan is None:
        if intent.get("need_clarification"):
            raise RuntimeError("P1 尚待用户选定方向或回答澄清问题，不能自动续跑 P2")
        clarification = ""
        plan = post(base, "/api/plan", {"topic": task["topic"], "tier": task["tier"], "clarification": clarification, "intent": intent})["data"]
        persist(base, task_id, "P2", "plan_completed", plan, "plan")
    source_artifact = artifact(task, "sources")
    if source_artifact is None:
        source_artifact = post(base, "/api/search", {"topic": task["topic"], "plan": plan, "tier": task["tier"]})["data"]
        persist(base, task_id, "P2", "search_completed", source_artifact, "sources")
    sources = source_artifact["records"]
    screening = artifact(task, "screening")
    if screening is None:
        response = post(base, "/api/screen", {"topic": task["topic"], "tier": task["tier"], "plan": plan, "candidates": sources, "queries": source_artifact.get("queries", [])})
        screening = response["data"]
        sources = response.get("sources", sources)
        source_artifact["records"] = sources
        persist(base, task_id, "P2", "search_finalized", source_artifact, "sources")
        persist(base, task_id, "P3", "screening_completed", screening, "screening")
    if not screening.get("quality_gate", {}).get("passed", False):
        reassessed = post(base, "/api/reassess-sources", {})
        screening = reassessed["data"]
        sources = reassessed["sources"]
    if not screening.get("quality_gate", {}).get("passed", False):
        raise RuntimeError("P3 来源质量门禁未通过：" + "；".join(screening.get("quality_gate", {}).get("problems", [])))
    evidence_artifact = artifact(task, "evidence")
    if evidence_artifact is None:
        groups = []
        for index, decision in enumerate((item for item in screening["decisions"] if item["status"] == "keep"), 1):
            saved = artifact(task, "evidence_source_%03d" % index)
            if saved is None:
                source = next(item for item in sources if item["source_id"] == decision["source_id"])
                saved = post(base, "/api/evidence", {"source_record": source, "question_ids": decision["question_ids"], "tier": task["tier"]})["data"]
                persist(base, task_id, "P4", "evidence_source_completed", saved, "evidence_source_%03d" % index)
            groups.append(saved)
        namespace_evidence_groups(groups)
        persist(base, task_id, "P4", "evidence_completed", {"groups": groups}, "evidence")
    else:
        groups = evidence_artifact["groups"]
        namespace_evidence_groups(groups)
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    source_ids = sorted({item["source_id"] for item in evidence_records})
    selected_sources = [item for item in sources if item["source_id"] in set(source_ids)]
    report = artifact(task, "report")
    if report is not None:
        try:
            validate_report(report, evidence_ids, task["tier"])
        except ValueError:
            report = None
    if report is None:
        contexts = [{"source_id": group["source_id"], "reading_scope": group["reading_scope"]} for group in groups]
        report = post(base, "/api/report", {"intent": intent, "plan": plan, "evidence_records": evidence_records, "figure_records": [item for group in groups for item in group["figure_records"]], "evidence_contexts": contexts, "tier": task["tier"]})["data"]
        persist(base, task_id, "P5", "report_completed", report, "report")
    claims = artifact(task, "claims")
    if claims is None:
        claims = post(base, "/api/claims", {"report": report, "ppt": {"deck_title":"","storyline":"","pages":[]}, "evidence_ids": evidence_ids, "tier": task["tier"]})["data"]
        if len(claims.get("claims", [])) > MAX_VERIFICATION_CLAIMS:
            raise RuntimeError("报告声明超过核验停止线")
        persist(base, task_id, "P7", "report_claims_completed", claims, "claims")
    verification = artifact(task, "verification")
    if verification is None:
        saved_cache = {kind: value["data"] for kind, value in task["artifacts"].items()}
        pro_claim_ids = select_pro_claim_ids(claims)
        results = []
        for index in range(0, len(claims["claims"]), 4):
            kind = "verification_batch_%03d" % (index // 4 + 1)
            saved = saved_cache.get(kind)
            if saved is None:
                partial = {"claim_set_version": claims["claim_set_version"], "claims": claims["claims"][index:index + 4], "extraction_notes": []}
                saved = post(base, "/api/verify", {"claims": partial, "evidence_records": evidence_records, "source_records": selected_sources, "pro_claim_ids": pro_claim_ids, "tier": task["tier"]})["data"]
                persist(base, task_id, "P8", "verification_batch_completed", saved, kind)
            results.extend(saved["results"])
        verification = merge_verification(results, claims)
        persist(base, task_id, "P8", "report_verification_completed", verification, "verification")
    final = artifact(task, "final_delivery")
    if final is None:
        placeholder = {"deck_title":"报告专用核验占位","storyline":"本任务不生成PPT内容包","pages":[{"page_id":"REPORT-ONLY","title":"报告专用任务","purpose":"仅用于确定性终稿装配","on_slide_text":[],"visual_suggestion":"不交付","speaker_notes":"","evidence_ids":[],"figure_refs":[],"source_citations":[]}]}
        final = post(base, "/api/final", {"verification_results":verification,"draft_report":report,"draft_ppt":placeholder,"claims":claims["claims"],"claim_ids":[item["claim_id"] for item in claims["claims"]],"source_ids":source_ids,"evidence_ids":evidence_ids,"evidence_version":groups[0]["evidence_version"],"tier":task["tier"]})["data"]
        persist(base, task_id, "P9", "verified_report_completed", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    return {"task_id":task_id,"topic":task["topic"],"sources":len(selected_sources),"evidence":len(evidence_records),"claims":len(claims["claims"]),"verification":verification["summary"],"report_characters":len(final["final_report"]["markdown"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state-file", required=True)
    args = parser.parse_args()
    path = Path(args.state_file).resolve()
    result = resume(json.loads(path.read_text(encoding="utf-8")))
    path.unlink(missing_ok=True)
    print("REPORT_RESUME_RESULT=" + json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
