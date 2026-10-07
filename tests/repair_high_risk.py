#!/usr/bin/env python3
"""Re-verify unresolved high-risk claims and rebuild the saved final delivery."""

import argparse
import json

from resume_live_regression import artifact, get, merge_verification
from run_live_regression import persist, post, set_auth


def repair(base, task_id, task_token):
    set_auth(task_id, task_token)
    task = get(base, "/api/tasks/%s" % task_id)["data"]
    claims = artifact(task, "claims")
    verification = artifact(task, "verification")
    groups = artifact(task, "evidence")["groups"]
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    source_ids = sorted({item["source_id"] for item in evidence_records})
    sources = [item for item in artifact(task, "sources")["records"] if item["source_id"] in set(source_ids)]
    results_by_id = {item["claim_id"]: item for item in verification["results"]}
    targets = [item for item in claims["claims"] if item["risk_level"] == "high" and results_by_id[item["claim_id"]]["support_status"] != "supported"]
    if targets:
        print("[%s] re-verify %d high-risk claims" % (task["topic"], len(targets)), flush=True)
        partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": targets, "extraction_notes": []}
        repaired = post(base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": sources, "tier": task["tier"]})["data"]
        for item in repaired["results"]:
            results_by_id[item["claim_id"]] = item
    ordered_results = [results_by_id[item["claim_id"]] for item in claims["claims"]]
    merged = merge_verification(ordered_results, claims)
    persist(base, task_id, "P8", "high_risk_repaired", merged, "verification")
    report, ppt = artifact(task, "report"), artifact(task, "ppt")
    final = post(base, "/api/final", {"verification_results": merged, "draft_report": report, "draft_ppt": ppt, "claim_ids": [item["claim_id"] for item in claims["claims"]], "source_ids": source_ids, "evidence_ids": evidence_ids, "evidence_version": groups[0]["evidence_version"]})["data"]
    persist(base, task_id, "P9", "final_rebuilt_after_high_risk_repair", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    return {"task_id": task_id, "topic": task["topic"], "reverified": len(targets), "verification_summary": merged["summary"], "page_count": len(final["final_ppt"]["pages"])}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--task-token", required=True, help="任务创建时返回的 owner_token")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    args = parser.parse_args()
    result = repair(args.base, args.task_id, args.task_token)
    print("REPAIR_RESULT=" + json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
