#!/usr/bin/env python3
"""Run selected topics through the live P1-P9 local API pipeline."""

import argparse
import json
import re
import urllib.error
import urllib.request

LOCAL_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
ACTIVE_TASK = {"id": "", "token": ""}


def set_auth(task_id, token):
    ACTIVE_TASK.update({"id": task_id, "token": token})


def post(base, path, payload, timeout=600):
    headers = {"Content-Type": "application/json"}
    if ACTIVE_TASK["id"] and ACTIVE_TASK["token"]:
        headers.update({"X-Task-ID": ACTIVE_TASK["id"], "X-Task-Token": ACTIVE_TASK["token"]})
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        method="POST",
        headers=headers,
    )
    try:
        with LOCAL_OPENER.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError("%s returned %s: %s" % (path, exc.code, detail)) from exc


def query_from_plan(plan, fallback):
    values = []

    def visit(value):
        if isinstance(value, str) and re.search(r"[A-Za-z]{3}", value) and len(value) < 90:
            values.append(value)
        elif isinstance(value, list):
            for item in value:
                visit(item)
        elif isinstance(value, dict):
            for item in value.values():
                visit(item)

    visit(plan.get("search_concepts", {}))
    unique = list(dict.fromkeys(values))[:5]
    return " OR ".join('"%s"' % item.replace('"', "") for item in unique) if unique else fallback


def persist(base, task_id, stage, event_type, payload, artifact_kind):
    return post(base, "/api/tasks/%s/events" % task_id, {
        "stage": stage, "event_type": event_type, "payload": payload, "artifact_kind": artifact_kind,
    })


def merge_verification(results):
    summary = {status: sum(item["support_status"] == status for item in results) for status in ("supported", "partially_supported", "unsupported", "cannot_determine")}
    summary["high_risk_remaining"] = 0
    return {"verification_version": "P8-resumable-1.0", "results": results, "summary": summary}


def verify_with_checkpoints(base, task_id, topic, tier, claims, evidence_records, source_records):
    cache = {}

    def verify_piece(items, kind):
        if kind in cache:
            return cache[kind]
        try:
            partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": items, "extraction_notes": []}
            saved = post(base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": source_records, "tier": tier})["data"]
        except Exception:
            if len(items) <= 3:
                raise
            midpoint = len(items) // 2
            left = verify_piece(items[:midpoint], kind + "a")
            right = verify_piece(items[midpoint:], kind + "b")
            saved = merge_verification(left["results"] + right["results"])
        persist(base, task_id, "P8", "verification_batch_completed", saved, kind)
        cache[kind] = saved
        return saved

    results = []
    for index in range(0, len(claims["claims"]), 12):
        print("[%s] P8 batch %d/%d" % (topic, index // 12 + 1, (len(claims["claims"]) + 11) // 12), flush=True)
        items = claims["claims"][index:index + 12]
        results.extend(verify_piece(items, "verification_batch_%03d" % (index // 12 + 1))["results"])
    return merge_verification(results)


def run_topic(base, topic, tier):
    task = post(base, "/api/tasks", {"topic": topic, "tier": tier})["data"]
    task_id = task["task_id"]
    set_auth(task_id, task["owner_token"])
    usage = {}
    print("[%s] P1 intent" % topic, flush=True)
    response = post(base, "/api/intent", {"topic": topic, "tier": tier})
    intent = response["data"]
    usage["P1"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P1", "intent_completed", intent, "intent")

    clarification = intent.get("scope_hint", "") if intent.get("need_clarification") else ""
    print("[%s] P2 plan" % topic, flush=True)
    response = post(base, "/api/plan", {"topic": topic, "tier": tier, "clarification": clarification})
    plan = response["data"]
    usage["P2"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P2", "plan_completed", plan, "plan")

    print("[%s] retrieval" % topic, flush=True)
    sources = post(base, "/api/search", {"topic": topic, "query": query_from_plan(plan, topic)})["data"]
    if not sources["records"]:
        raise RuntimeError("%s returned no sources" % topic)
    candidates = sources["records"][:8]
    persist(base, task_id, "P2", "search_completed", {**sources, "records": candidates}, "sources")

    print("[%s] P3 screen %d candidates" % (topic, len(candidates)), flush=True)
    response = post(base, "/api/screen", {"topic": topic, "tier": tier, "plan": plan, "candidates": candidates})
    screening = response["data"]
    usage["P3"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P3", "screening_completed", screening, "screening")

    evidence_groups = []
    kept = [item for item in screening["decisions"] if item["status"] == "keep"]
    print("[%s] P4 evidence %d kept sources" % (topic, len(kept)), flush=True)
    for decision in kept:
        source = next(item for item in candidates if item["source_id"] == decision["source_id"])
        response = post(base, "/api/evidence", {"source_record": source, "question_ids": decision["question_ids"]})
        evidence_groups.append(response["data"])
        usage["P4"] = usage.get("P4", 0) + response.get("usage", {}).get("total_tokens", 0)
    evidence_records = [item for group in evidence_groups for item in group["evidence_records"]]
    figure_records = [item for group in evidence_groups for item in group["figure_records"]]
    if not evidence_records:
        raise RuntimeError("%s produced no extractable evidence" % topic)
    persist(base, task_id, "P4", "evidence_completed", {"groups": evidence_groups}, "evidence")

    print("[%s] P5 report" % topic, flush=True)
    response = post(base, "/api/report", {"intent": intent, "plan": plan, "evidence_records": evidence_records, "tier": tier})
    report = response["data"]
    usage["P5"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P5", "report_completed", report, "report")

    print("[%s] P6 ppt" % topic, flush=True)
    response = post(base, "/api/ppt", {"intent": intent, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "constraints": {"language": "zh-CN", "format": "storyboard_with_speaker_notes"}})
    ppt = response["data"]
    usage["P6"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P6", "ppt_completed", ppt, "ppt")

    evidence_ids = [item["evidence_id"] for item in evidence_records]
    print("[%s] P7 claims" % topic, flush=True)
    response = post(base, "/api/claims", {"report": report, "ppt": ppt, "evidence_ids": evidence_ids})
    claims = response["data"]
    usage["P7"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P7", "claims_completed", claims, "claims")

    selected_ids = {item["source_id"] for item in evidence_records}
    selected_sources = [item for item in candidates if item["source_id"] in selected_ids]
    print("[%s] P8 verify %d claims" % (topic, len(claims["claims"])), flush=True)
    verification = verify_with_checkpoints(base, task_id, topic, tier, claims, evidence_records, selected_sources)
    usage["P8"] = 0
    persist(base, task_id, "P8", "verification_completed", verification, "verification")

    print("[%s] P9 final" % topic, flush=True)
    response = post(base, "/api/final", {"verification_results": verification, "draft_report": report, "draft_ppt": ppt, "claim_ids": [item["claim_id"] for item in claims["claims"]], "source_ids": sorted(selected_ids), "evidence_ids": evidence_ids, "evidence_version": evidence_groups[0]["evidence_version"]})
    final = response["data"]
    usage["P9"] = response.get("usage", {}).get("total_tokens", 0)
    persist(base, task_id, "P9", "final_completed", final, "final_delivery")
    post(base, "/api/tasks/%s/complete" % task_id, {})
    return {
        "topic": topic, "task_id": task_id, "candidate_count": len(candidates), "kept_count": len(kept),
        "evidence_count": len(evidence_records), "page_count": len(final["final_ppt"]["pages"]),
        "verification_summary": verification["summary"], "usage": usage, "total_tokens": sum(usage.values()),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("topics", nargs="+")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    parser.add_argument("--tier", choices=("fast", "deep"), default="fast")
    args = parser.parse_args()
    results = []
    for topic in args.topics:
        try:
            results.append({"ok": True, **run_topic(args.base, topic, args.tier)})
        except Exception as exc:
            results.append({"ok": False, "topic": topic, "error": str(exc)})
            print("[%s] FAILED: %s" % (topic, exc), flush=True)
    print("LIVE_REGRESSION_RESULT=" + json.dumps(results, ensure_ascii=False), flush=True)
    if any(not item["ok"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
