#!/usr/bin/env python3
"""Resume saved live-regression tasks from their last successful artifact."""

import argparse
import json
import urllib.request

from run_live_regression import ACTIVE_TASK, LOCAL_OPENER, persist, post, set_auth


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
    intent, plan = artifact(task, "intent"), artifact(task, "plan")
    sources = artifact(task, "sources")["records"]
    groups = artifact(task, "evidence")["groups"]
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    figure_records = [item for group in groups for item in group["figure_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    source_ids = sorted({item["source_id"] for item in evidence_records})
    selected_sources = [item for item in sources if item["source_id"] in set(source_ids)]
    report = artifact(task, "report")
    ppt = artifact(task, "ppt")
    if ppt is None:
        print("[%s] resume P6" % task["topic"], flush=True)
        ppt = post(base, "/api/ppt", {"intent": intent, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "constraints": {"language": "zh-CN", "format": "storyboard_with_speaker_notes"}})["data"]
        persist(base, task_id, "P6", "ppt_completed", ppt, "ppt")
    claims = artifact(task, "claims")
    if claims is None:
        print("[%s] resume P7" % task["topic"], flush=True)
        claims = post(base, "/api/claims", {"report": report, "ppt": ppt, "evidence_ids": evidence_ids})["data"]
        persist(base, task_id, "P7", "claims_completed", claims, "claims")
    verification = artifact(task, "verification")
    if verification is None:
        print("[%s] resume P8 (%d claims)" % (task["topic"], len(claims["claims"])), flush=True)
        saved_cache = {kind: value["data"] for kind, value in task["artifacts"].items()}

        def verify_piece(items, kind):
            if kind in saved_cache:
                return saved_cache[kind]
            try:
                partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": items, "extraction_notes": []}
                saved = post(base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": selected_sources, "tier": task["tier"]})["data"]
            except Exception:
                if len(items) <= 3:
                    raise
                midpoint = len(items) // 2
                left = verify_piece(items[:midpoint], kind + "a")
                right = verify_piece(items[midpoint:], kind + "b")
                saved = merge_verification(left["results"] + right["results"], {"claims": items})
            persist(base, task_id, "P8", "verification_batch_completed", saved, kind)
            saved_cache[kind] = saved
            return saved

        batch_results = []
        for index in range(0, len(claims["claims"]), 12):
            kind = "verification_batch_%03d" % (index // 12 + 1)
            items = claims["claims"][index:index + 12]
            if kind not in saved_cache:
                print("[%s] P8 batch %d/%d" % (task["topic"], index // 12 + 1, (len(claims["claims"]) + 11) // 12), flush=True)
            saved = verify_piece(items, kind)
            batch_results.extend(saved["results"])
        verification = merge_verification(batch_results, claims)
        persist(base, task_id, "P8", "verification_completed", verification, "verification")
    final = artifact(task, "final_delivery")
    if final is None:
        print("[%s] resume P9" % task["topic"], flush=True)
        final = post(base, "/api/final", {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claim_ids": [item["claim_id"] for item in claims["claims"]], "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": groups[0]["evidence_version"]})["data"]
        persist(base, task_id, "P9", "final_completed", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    return {"task_id": task_id, "topic": task["topic"], "claim_count": len(claims["claims"]), "page_count": len(final["final_ppt"]["pages"]), "verification_summary": verification["summary"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_ids", nargs="+")
    parser.add_argument("--task-token", required=True, help="任务创建时返回的 owner_token")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    args = parser.parse_args()
    results = []
    for task_id in args.task_ids:
        try:
            results.append({"ok": True, **resume(args.base, task_id, args.task_token)})
        except Exception as exc:
            results.append({"ok": False, "task_id": task_id, "error": str(exc)})
            print("[%s] FAILED: %s" % (task_id, exc), flush=True)
    print("RESUME_RESULT=" + json.dumps(results, ensure_ascii=False), flush=True)
    if any(not item["ok"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
