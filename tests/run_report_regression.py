#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Run a report-only P1-P5/P7-P9 regression without paying for a PPT draft."""

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research_sources import plan_search_queries, merge_search_results as shared_merge_search_results, assess_source_quality

from run_live_regression import (
    MAX_VERIFICATION_CLAIMS, namespace_evidence_groups, persist, post,
    save_resume_state, set_auth, verify_with_checkpoints,
)


def report_queries(plan, fallback):
    return plan_search_queries(plan, fallback)


def merge_search_results(results, limit):
    return shared_merge_search_results(results, limit)


def validate_deep_source_mix(records, decisions):
    gate = assess_source_quality({"questions": []}, records, {"decisions": decisions}, "deep")
    if not gate["passed"]:
        raise RuntimeError("深入报告来源门禁未通过：" + "；".join(gate["problems"]))
    kept_ids = set(gate["usable_source_ids"])
    return [item for item in records if item.get("source_id") in kept_ids]


def run_report(base, topic, tier):
    task = post(base, "/api/tasks", {"topic": topic, "tier": tier})["data"]
    task_id = task["task_id"]
    set_auth(task_id, task["owner_token"])
    state_path = save_resume_state(base, topic, tier, task_id, task["owner_token"])

    intent = post(base, "/api/intent", {"topic": topic, "tier": tier})["data"]
    persist(base, task_id, "P1", "intent_completed", intent, "intent")
    if intent.get("need_clarification"):
        raise RuntimeError("P1 需要用户选定方向或回答澄清问题；报告回归不能代选。")
    clarification = ""
    plan = post(base, "/api/plan", {"topic": topic, "tier": tier, "clarification": clarification, "intent": intent})["data"]
    persist(base, task_id, "P2", "plan_completed", plan, "plan")

    sources = post(base, "/api/search", {"topic": topic, "plan": plan, "tier": tier})["data"]
    if not sources["records"]:
        raise RuntimeError("没有检索到候选来源")
    persist(base, task_id, "P2", "search_completed", sources, "sources")

    screen_response = post(base, "/api/screen", {"topic": topic, "tier": tier, "plan": plan, "candidates": sources["records"], "queries": sources.get("queries", [])})
    screening = screen_response["data"]
    sources["records"] = screen_response.get("sources", sources["records"])
    if not screening.get("quality_gate", {}).get("passed", False):
        raise RuntimeError("来源质量门禁未通过：" + "；".join(screening.get("quality_gate", {}).get("problems", [])))
    persist(base, task_id, "P3", "screening_completed", screening, "screening")
    groups = []
    kept = [item for item in screening["decisions"] if item["status"] == "keep"]
    for index, decision in enumerate(kept, 1):
        source = next(item for item in sources["records"] if item["source_id"] == decision["source_id"])
        group = post(base, "/api/evidence", {"source_record": source, "question_ids": decision["question_ids"], "tier": tier})["data"]
        groups.append(group)
        persist(base, task_id, "P4", "evidence_source_completed", group, "evidence_source_%03d" % index)
    namespace_evidence_groups(groups)
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    if not evidence_records:
        raise RuntimeError("没有可提取证据")
    persist(base, task_id, "P4", "evidence_completed", {"groups": groups}, "evidence")

    contexts = [{"source_id": group["source_id"], "reading_scope": group["reading_scope"]} for group in groups]
    report = post(base, "/api/report", {"intent": intent, "plan": plan, "evidence_records": evidence_records, "figure_records": [item for group in groups for item in group["figure_records"]], "evidence_contexts": contexts, "tier": tier})["data"]
    persist(base, task_id, "P5", "report_completed", report, "report")

    evidence_ids = [item["evidence_id"] for item in evidence_records]
    empty_ppt = {"deck_title": "", "storyline": "", "pages": []}
    claims = post(base, "/api/claims", {"report": report, "ppt": empty_ppt, "evidence_ids": evidence_ids, "tier": tier})["data"]
    if len(claims.get("claims", [])) > MAX_VERIFICATION_CLAIMS:
        raise RuntimeError("报告声明超过核验停止线")
    persist(base, task_id, "P7", "report_claims_completed", claims, "claims")

    selected_ids = sorted({item["source_id"] for item in evidence_records})
    selected_sources = [item for item in sources["records"] if item["source_id"] in set(selected_ids)]
    verification = verify_with_checkpoints(base, task_id, topic, tier, claims, evidence_records, selected_sources)
    persist(base, task_id, "P8", "report_verification_completed", verification, "verification")

    placeholder_ppt = {
        "deck_title": "报告专用核验占位", "storyline": "本任务不生成PPT内容包", "pages": [{
            "page_id": "REPORT-ONLY", "title": "报告专用任务", "purpose": "仅用于确定性终稿装配",
            "on_slide_text": [], "visual_suggestion": "不交付", "speaker_notes": "",
            "evidence_ids": [], "figure_refs": [], "source_citations": [],
        }],
    }
    final = post(base, "/api/final", {
        "verification_results": verification, "draft_report": report, "draft_ppt": placeholder_ppt,
        "claims": claims["claims"], "claim_ids": [item["claim_id"] for item in claims["claims"]],
        "source_ids": selected_ids, "evidence_ids": evidence_ids,
        "evidence_version": groups[0]["evidence_version"], "tier": tier,
    })["data"]
    persist(base, task_id, "P9", "verified_report_completed", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    state_path.unlink(missing_ok=True)
    return {
        "task_id": task_id, "topic": topic, "sources": len(selected_sources),
        "evidence": len(evidence_records), "claims": len(claims["claims"]),
        "verification": verification["summary"], "report_characters": len(final["final_report"]["markdown"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topic")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    parser.add_argument("--tier", choices=("fast", "deep"), default="deep")
    args = parser.parse_args()
    print("REPORT_REGRESSION_RESULT=" + json.dumps(run_report(args.base, args.topic, args.tier), ensure_ascii=False))


if __name__ == "__main__":
    main()
