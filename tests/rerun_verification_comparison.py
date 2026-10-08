#!/usr/bin/env python3
"""Re-run P8/P9 for an existing topic while reusing its fixed P1-P7 artifacts."""

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from run_live_regression import merge_verification, post, persist, set_auth
from workflow_service import WorkflowService


def load_baseline(database, task_id):
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    task = connection.execute("SELECT task_id,topic,tier FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not task:
        raise ValueError("基线任务不存在")
    rows = connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,)).fetchall()
    artifacts = {row["kind"]: json.loads(row["payload_json"]) for row in rows}
    required = {"claims", "evidence", "sources", "report", "ppt", "final_delivery"}
    missing = sorted(required - set(artifacts))
    if missing:
        raise ValueError("基线缺少产物：" + ",".join(missing))
    return dict(task), artifacts


def metrics(final, claims, verification):
    report = final["final_report"]["markdown"]
    pages = final["final_ppt"]["pages"]
    actions = {name: 0 for name in ("kept", "revised", "removed", "marked_unverified")}
    for item in final.get("change_log", []):
        actions[item["action"]] = actions.get(item["action"], 0) + 1
    return {
        "report_characters": len(report),
        "report_headings": sum(line.startswith("#") for line in report.splitlines()),
        "ppt_pages": len(pages),
        "ppt_on_slide_characters": sum(len(text) for page in pages for text in page.get("on_slide_text", [])),
        "ppt_speaker_note_characters": sum(len(page.get("speaker_notes", "")) for page in pages),
        "claims": len(claims["claims"]),
        "verification_summary": verification["summary"],
        "change_actions": actions,
        "open_issues": len(final.get("open_issues", [])),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_task_id")
    parser.add_argument("--database", default="data/tasks.sqlite3")
    parser.add_argument("--base", default="http://127.0.0.1:4181")
    parser.add_argument("--resume-state")
    parser.add_argument("--reuse-baseline-for-missing", action="store_true")
    args = parser.parse_args()

    task, artifacts = load_baseline(args.database, args.baseline_task_id)
    if args.resume_state:
        state_path = Path(args.resume_state)
        state = json.loads(state_path.read_text(encoding="utf-8"))
        task_id, owner_token = state["task_id"], state["owner_token"]
    else:
        created = post(args.base, "/api/tasks", {"topic": task["topic"], "tier": task["tier"]})["data"]
        task_id, owner_token = created["task_id"], created["owner_token"]
        state_path = Path("data/private") / ("verification-comparison-%s.json" % task_id)
        state_path.write_text(json.dumps({"task_id": task_id, "owner_token": owner_token, "baseline_task_id": args.baseline_task_id}, ensure_ascii=False), encoding="utf-8")
        os.chmod(state_path, 0o600)
        for stage, kind in (("P2", "sources"), ("P4", "evidence"), ("P5", "report"), ("P6", "ppt"), ("P7", "claims")):
            persist(args.base, task_id, stage, "baseline_artifact_reused", artifacts[kind], kind)
    set_auth(task_id, owner_token)

    evidence_records = [item for group in artifacts["evidence"]["groups"] for item in group["evidence_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    selected_ids = {item["source_id"] for item in evidence_records}
    source_records = [item for item in artifacts["sources"]["records"] if item["source_id"] in selected_ids]
    claims = artifacts["claims"]

    evidence_by_id = {item["evidence_id"]: item for item in evidence_records}
    strong_types = {"causal", "efficacy", "safety", "approval"}
    strong = [item for item in claims["claims"] if item.get("claim_type") in strong_types and item.get("risk_level") in ("medium", "high")]
    standard = [item for item in claims["claims"] if item not in strong]
    dynamic_batches = WorkflowService._verification_batches(standard, evidence_by_id, False) + WorkflowService._verification_batches(strong, evidence_by_id, True)
    connection = sqlite3.connect(args.database)
    saved_rows = connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=? AND kind LIKE 'verification_dynamic_%'", (task_id,)).fetchall()
    saved = {kind: json.loads(payload) for kind, payload in saved_rows}
    results = []
    baseline_by_claim = {item["claim_id"]: item for item in artifacts["verification"]["results"]}
    reused_claim_ids = []
    for index, batch in enumerate(dynamic_batches, 1):
        kind = "verification_dynamic_%03d" % index
        if kind not in saved:
            if args.reuse_baseline_for_missing:
                missing_ids = [item["claim_id"] for item in batch]
                if any(claim_id not in baseline_by_claim for claim_id in missing_ids):
                    raise ValueError("基线缺少待复用声明")
                reused_claim_ids.extend(missing_ids)
                saved[kind] = merge_verification([baseline_by_claim[claim_id] for claim_id in missing_ids])
                persist(args.base, task_id, "P8", "baseline_verification_reused", saved[kind], kind)
            else:
                print("[%s] dynamic P8 batch %d/%d" % (task["topic"], index, len(dynamic_batches)), flush=True)
                partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": batch, "extraction_notes": []}
                saved[kind] = post(args.base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": source_records, "tier": task["tier"]})["data"]
                persist(args.base, task_id, "P8", "verification_batch_completed", saved[kind], kind)
        results.extend(saved[kind]["results"])
    order = {item["claim_id"]: index for index, item in enumerate(claims["claims"])}
    results.sort(key=lambda item: order[item["claim_id"]])
    verification = merge_verification(results)
    persist(args.base, task_id, "P8", "verification_completed", verification, "verification")
    response = post(args.base, "/api/final", {
        "verification_results": verification,
        "draft_report": artifacts["report"],
        "draft_ppt": artifacts["ppt"],
        "claims": claims["claims"],
        "claim_ids": [item["claim_id"] for item in claims["claims"]],
        "source_ids": sorted(selected_ids),
        "evidence_ids": evidence_ids,
        "evidence_version": artifacts["evidence"]["groups"][0]["evidence_version"],
        "tier": task["tier"],
    })
    final = response["data"]
    persist(args.base, task_id, "P9", "final_completed", final, "final_delivery")
    post(args.base, "/api/tasks/%s/complete" % task_id, {})
    state_path.unlink(missing_ok=True)
    connection = sqlite3.connect(args.database)
    reused_rows = connection.execute("SELECT payload_json FROM events WHERE task_id=? AND event_type='baseline_verification_reused'", (task_id,)).fetchall()
    reused_claim_ids = []
    for (payload_json,) in reused_rows:
        reused_claim_ids.extend(item["claim_id"] for item in json.loads(payload_json).get("results", []))

    print("COMPARISON_RESULT=" + json.dumps({
        "baseline_task_id": args.baseline_task_id,
        "comparison_task_id": task_id,
        "baseline": metrics(artifacts["final_delivery"], claims, artifacts["verification"]),
        "comparison": metrics(final, claims, verification),
        "reused_baseline_claims": reused_claim_ids,
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
