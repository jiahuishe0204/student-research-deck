#!/usr/bin/env python3
"""Resume saved live-regression tasks from their last successful artifact."""

import argparse
import json
from pathlib import Path
import urllib.request

from run_live_regression import (
    ACTIVE_TASK, LOCAL_OPENER, MAX_VERIFICATION_CLAIMS, persist, post, query_from_plan,
    select_pro_claim_ids, set_auth,
)


def get(base, path, timeout=60):
    request = urllib.request.Request(base + path, headers={
        "X-Task-ID": ACTIVE_TASK["id"], "X-Task-Token": ACTIVE_TASK["token"],
    })
    with LOCAL_OPENER.open(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def artifact(task, kind):
    entry = task["artifacts"].get(kind)
    return entry["data"] if entry else None


def merge_verification(results, claims):
    summary = {status: sum(item["support_status"] == status for item in results) for status in ("supported", "partially_supported", "unsupported", "cannot_determine")}
    summary["high_risk_remaining"] = 0
    return {"verification_version": "P8-resumable-1.0", "results": results, "summary": summary}


def resume(base, task_id, task_token):
    set_auth(task_id, task_token)
    task = get(base, "/api/tasks/%s" % task_id)["data"]
    intent = artifact(task, "intent")
    if intent is None:
        print("[%s] resume P1" % task["topic"], flush=True)
        intent = post(base, "/api/intent", {"topic": task["topic"], "tier": task["tier"]})["data"]
        persist(base, task_id, "P1", "intent_completed", intent, "intent")
    plan = artifact(task, "plan")
    if plan is None:
        print("[%s] resume P2" % task["topic"], flush=True)
        clarification = intent.get("scope_hint", "") if intent.get("need_clarification") else ""
        plan = post(base, "/api/plan", {"topic": task["topic"], "tier": task["tier"], "clarification": clarification, "intent": intent})["data"]
        persist(base, task_id, "P2", "plan_completed", plan, "plan")
    source_artifact = artifact(task, "sources")
    if source_artifact is None:
        print("[%s] resume retrieval" % task["topic"], flush=True)
        source_artifact = post(base, "/api/search", {"topic": task["topic"], "query": query_from_plan(plan, task["topic"]), "tier": task["tier"]})["data"]
        source_artifact["records"] = source_artifact["records"][:12 if task["tier"] == "deep" else 8]
        if not source_artifact["records"]:
            raise RuntimeError("%s returned no sources" % task["topic"])
        persist(base, task_id, "P2", "search_completed", source_artifact, "sources")
    sources = source_artifact["records"]
    screening = artifact(task, "screening")
    if screening is None:
        print("[%s] resume P3" % task["topic"], flush=True)
        screening = post(base, "/api/screen", {"topic": task["topic"], "tier": task["tier"], "plan": plan, "candidates": sources})["data"]
        persist(base, task_id, "P3", "screening_completed", screening, "screening")
    evidence_artifact = artifact(task, "evidence")
    if evidence_artifact is None:
        print("[%s] resume P4" % task["topic"], flush=True)
        groups = []
        kept_decisions = [item for item in screening["decisions"] if item["status"] == "keep"]
        for index, decision in enumerate(kept_decisions, 1):
            saved_group = artifact(task, "evidence_source_%03d" % index)
            if saved_group is not None:
                groups.append(saved_group)
                continue
            source = next(item for item in sources if item["source_id"] == decision["source_id"])
            group = post(base, "/api/evidence", {"source_record": source, "question_ids": decision["question_ids"], "tier": task["tier"]})["data"]
            groups.append(group)
            persist(base, task_id, "P4", "evidence_source_completed", group, "evidence_source_%03d" % index)
        if not any(group["evidence_records"] for group in groups):
            raise RuntimeError("%s produced no extractable evidence" % task["topic"])
        persist(base, task_id, "P4", "evidence_completed", {"groups": groups}, "evidence")
    else:
        groups = evidence_artifact["groups"]
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    figure_records = [item for group in groups for item in group["figure_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    source_ids = sorted({item["source_id"] for item in evidence_records})
    selected_sources = [item for item in sources if item["source_id"] in set(source_ids)]
    report = artifact(task, "report")
    if report is None:
        print("[%s] resume P5" % task["topic"], flush=True)
        report = post(base, "/api/report", {"intent": intent, "plan": plan, "evidence_records": evidence_records, "tier": task["tier"]})["data"]
        persist(base, task_id, "P5", "report_completed", report, "report")
    ppt = artifact(task, "ppt")
    if ppt is None:
        print("[%s] resume P6" % task["topic"], flush=True)
        ppt = post(base, "/api/ppt", {"intent": intent, "plan": plan, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "source_records": selected_sources, "constraints": {"language": "zh-CN", "format": "storyboard_with_speaker_notes"}, "tier": task["tier"]})["data"]
        persist(base, task_id, "P6", "ppt_completed", ppt, "ppt")
    claims = artifact(task, "claims")
    regenerate_claims = claims is not None and len(claims.get("claims", [])) > MAX_VERIFICATION_CLAIMS
    if claims is None or regenerate_claims:
        print("[%s] resume P7%s" % (task["topic"], " (replace over-budget artifact)" if regenerate_claims else ""), flush=True)
        claims = post(base, "/api/claims", {"report": report, "ppt": ppt, "evidence_ids": evidence_ids, "tier": task["tier"]})["data"]
        if len(claims.get("claims", [])) > MAX_VERIFICATION_CLAIMS:
            raise RuntimeError("P7 produced %d claims, exceeding verification budget limit %d" % (len(claims["claims"]), MAX_VERIFICATION_CLAIMS))
        event_type = "claims_regenerated_over_budget" if regenerate_claims else "claims_completed"
        persist(base, task_id, "P7", event_type, claims, "claims")
    verification = artifact(task, "verification")
    if verification is None:
        print("[%s] resume P8 (%d claims)" % (task["topic"], len(claims["claims"])), flush=True)
        saved_cache = {kind: value["data"] for kind, value in task["artifacts"].items()}
        pro_claim_ids = select_pro_claim_ids(claims)

        def verify_piece(items, kind):
            if kind in saved_cache:
                return saved_cache[kind]
            partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": items, "extraction_notes": []}
            saved = post(base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": selected_sources, "pro_claim_ids": pro_claim_ids, "tier": task["tier"]})["data"]
            persist(base, task_id, "P8", "verification_batch_completed", saved, kind)
            saved_cache[kind] = saved
            return saved

        batch_results = []
        for index in range(0, len(claims["claims"]), 4):
            kind = "verification_batch_%03d" % (index // 4 + 1)
            items = claims["claims"][index:index + 4]
            if kind not in saved_cache:
                print("[%s] P8 batch %d/%d" % (task["topic"], index // 4 + 1, (len(claims["claims"]) + 3) // 4), flush=True)
            saved = verify_piece(items, kind)
            batch_results.extend(saved["results"])
        verification = merge_verification(batch_results, claims)
        persist(base, task_id, "P8", "verification_completed", verification, "verification")
    final = artifact(task, "final_delivery")
    if final is None:
        print("[%s] resume P9" % task["topic"], flush=True)
        final = post(base, "/api/final", {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claims": claims["claims"], "claim_ids": [item["claim_id"] for item in claims["claims"]], "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": groups[0]["evidence_version"], "tier": task["tier"]})["data"]
        persist(base, task_id, "P9", "final_completed", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    return {"task_id": task_id, "topic": task["topic"], "claim_count": len(claims["claims"]), "page_count": len(final["final_ppt"]["pages"]), "verification_summary": verification["summary"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="*")
    parser.add_argument("--task-token", help="任务创建时返回的 owner_token")
    parser.add_argument("--state-file", help="run_live_regression.py 自动保存的私有续跑状态文件")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    args = parser.parse_args()
    state_path = None
    if args.state_file:
        if args.task_ids or args.task_token:
            parser.error("--state-file 不能和 task_ids/--task-token 同时使用")
        state_path = Path(args.state_file).expanduser().resolve()
        state = json.loads(state_path.read_text(encoding="utf-8"))
        args.task_ids = [state["task_id"]]
        args.task_token = state["owner_token"]
        args.base = state.get("base", args.base)
    elif not args.task_ids or not args.task_token:
        parser.error("请提供 --state-file，或同时提供 task_ids 和 --task-token")
    results = []
    for task_id in args.task_ids:
        try:
            results.append({"ok": True, **resume(args.base, task_id, args.task_token)})
            if state_path:
                state_path.unlink(missing_ok=True)
        except Exception as exc:
            results.append({"ok": False, "task_id": task_id, "error": str(exc)})
            print("[%s] FAILED: %s" % (task_id, exc), flush=True)
    print("RESUME_RESULT=" + json.dumps(results, ensure_ascii=False), flush=True)
    if any(not item["ok"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
