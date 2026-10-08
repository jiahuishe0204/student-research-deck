#!/usr/bin/env python3
"""Re-run P8/P9 for an existing topic while reusing its fixed P1-P7 artifacts."""

import argparse
import json
import os
import sqlite3
from pathlib import Path

from run_live_regression import post, persist, set_auth, verify_with_checkpoints


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
    args = parser.parse_args()

    task, artifacts = load_baseline(args.database, args.baseline_task_id)
    created = post(args.base, "/api/tasks", {"topic": task["topic"], "tier": task["tier"]})["data"]
    task_id, owner_token = created["task_id"], created["owner_token"]
    set_auth(task_id, owner_token)
    state_path = Path("data/private") / ("verification-comparison-%s.json" % task_id)
    state_path.write_text(json.dumps({"task_id": task_id, "owner_token": owner_token, "baseline_task_id": args.baseline_task_id}, ensure_ascii=False), encoding="utf-8")
    os.chmod(state_path, 0o600)

    for stage, kind in (("P2", "sources"), ("P4", "evidence"), ("P5", "report"), ("P6", "ppt"), ("P7", "claims")):
        persist(args.base, task_id, stage, "baseline_artifact_reused", artifacts[kind], kind)

    evidence_records = [item for group in artifacts["evidence"]["groups"] for item in group["evidence_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    selected_ids = {item["source_id"] for item in evidence_records}
    source_records = [item for item in artifacts["sources"]["records"] if item["source_id"] in selected_ids]
    claims = artifacts["claims"]

    verification = verify_with_checkpoints(args.base, task_id, task["topic"], task["tier"], claims, evidence_records, source_records)
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

    print("COMPARISON_RESULT=" + json.dumps({
        "baseline_task_id": args.baseline_task_id,
        "comparison_task_id": task_id,
        "baseline": metrics(artifacts["final_delivery"], claims, artifacts["verification"]),
        "comparison": metrics(final, claims, verification),
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
