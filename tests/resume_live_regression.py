#!/usr/bin/env python3
"""Resume saved live-regression tasks from their last successful artifact."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import urllib.request

try:
    from tests.run_live_regression import (
        ACTIVE_TASK, LOCAL_OPENER, MAX_VERIFICATION_CLAIMS, persist, post, query_from_plan,
        namespace_evidence_groups, select_pro_claim_ids, set_auth, choose_user_direction,
    )
except ImportError:  # Direct execution from the tests directory.
    from run_live_regression import (
        ACTIVE_TASK, LOCAL_OPENER, MAX_VERIFICATION_CLAIMS, persist, post, query_from_plan,
        namespace_evidence_groups, select_pro_claim_ids, set_auth, choose_user_direction,
    )
from workflow_validation import validate_claims, validate_final, validate_ppt, validate_report, validate_verification


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


def claim_identity(item):
    """Only byte-equivalent scientific claims may reuse an earlier review."""
    return (
        str(item.get("atomic_claim") or "").strip(),
        tuple(sorted(item.get("cited_evidence_ids") or [])),
        str(item.get("claim_type") or ""),
        str(item.get("risk_level") or ""),
        str(item.get("location_type") or ""),
        str(item.get("section_or_page_id") or ""),
        str(item.get("original_text") or "").strip(),
    )


def claims_fingerprint(claims):
    payload = [claim_identity(item) for item in (claims or {}).get("claims", [])]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def reuse_verified_claims(new_claims, old_claims, old_verification):
    old_by_id = {item.get("claim_id"): item for item in (old_claims or {}).get("claims", [])}
    verified_by_identity = {}
    for result in (old_verification or {}).get("results", []):
        old = old_by_id.get(result.get("claim_id"))
        if old is not None:
            verified_by_identity.setdefault(claim_identity(old), []).append(result)
    reused, pending = [], []
    for claim in new_claims.get("claims", []):
        matches = verified_by_identity.get(claim_identity(claim), [])
        if not matches:
            pending.append(claim)
            continue
        copied = copy.deepcopy(matches[0])
        copied["claim_id"] = claim["claim_id"]
        reused.append(copied)
    return reused, pending


def claims_locate_in_delivery(claims, report, ppt):
    report_text = str((report or {}).get("report_markdown") or "")
    pages = {str(page.get("page_id") or ""): page for page in (ppt or {}).get("pages", [])}
    for claim in (claims or {}).get("claims", []):
        original = str(claim.get("original_text") or "").strip()
        if not original:
            return False
        location = claim.get("location_type")
        if location == "report_section":
            haystack = report_text
        else:
            page = pages.get(str(claim.get("section_or_page_id") or ""), {})
            if location == "ppt_speaker_note":
                haystack = str(page.get("speaker_notes") or "")
            elif location == "ppt_visual":
                haystack = str(page.get("visual_suggestion") or "")
            elif location == "ppt_slide":
                haystack = "\n".join([str(page.get("title") or ""), str(page.get("purpose") or ""), *[str(item) for item in page.get("on_slide_text", [])]])
            else:
                return False
        candidates = [original]
        if "Claudin18.2" in original:
            candidates.append(original.replace("Claudin18.2", "CLDN18.2"))
        if "CLDN18.2" in original:
            candidates.append(original.replace("CLDN18.2", "Claudin18.2"))
        if not any(candidate in haystack for candidate in candidates):
            return False
    return True


def resume(base, task_id, task_token, selected_direction="", max_new_verification_claims=MAX_VERIFICATION_CLAIMS):
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
        direction_id = choose_user_direction(intent, selected_direction)
        plan = post(base, "/api/plan", {"topic": task["topic"], "tier": task["tier"], "direction_id": direction_id})["data"]
        persist(base, task_id, "P2", "plan_completed", plan, "plan")
    source_artifact = artifact(task, "sources")
    if source_artifact is None:
        print("[%s] resume retrieval" % task["topic"], flush=True)
        source_artifact = post(base, "/api/search", {"topic": task["topic"], "plan": plan, "tier": task["tier"]})["data"]
        if not source_artifact["records"]:
            raise RuntimeError("%s returned no sources" % task["topic"])
        persist(base, task_id, "P2", "search_completed", source_artifact, "sources")
    sources = source_artifact["records"]
    screening = artifact(task, "screening")
    if screening is None:
        print("[%s] resume P3" % task["topic"], flush=True)
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
    namespace_evidence_groups(groups)
    persist(base, task_id, "P4", "evidence_ids_namespaced", {"groups": groups}, "evidence")
    evidence_records = [item for group in groups for item in group["evidence_records"]]
    figure_records = [item for group in groups for item in group["figure_records"]]
    evidence_ids = [item["evidence_id"] for item in evidence_records]
    source_ids = sorted({item["source_id"] for item in evidence_records})
    selected_sources = [item for item in sources if item["source_id"] in set(source_ids)]
    report = artifact(task, "report")
    report_rebuilt = False
    if report is not None:
        try:
            validate_report(report, evidence_ids, task["tier"])
        except ValueError:
            report = None
    if report is None:
        print("[%s] resume P5" % task["topic"], flush=True)
        evidence_contexts = [{"source_id": group["source_id"], "reading_scope": group["reading_scope"]} for group in groups]
        report = post(base, "/api/report", {"intent": intent, "plan": plan, "evidence_records": evidence_records, "figure_records": figure_records, "evidence_contexts": evidence_contexts, "tier": task["tier"]})["data"]
        persist(base, task_id, "P5", "report_completed", report, "report")
        report_rebuilt = True
    ppt = None if report_rebuilt else artifact(task, "ppt")
    ppt_rebuilt = report_rebuilt
    if ppt is not None:
        try:
            validate_ppt(ppt, evidence_ids, [item["figure_id"] for item in figure_records], source_ids)
        except ValueError:
            ppt = None
    if ppt is None:
        print("[%s] resume P6" % task["topic"], flush=True)
        ppt = post(base, "/api/ppt", {"intent": intent, "plan": plan, "report": report, "evidence_records": evidence_records, "figure_records": figure_records, "source_records": selected_sources, "constraints": {"language": "zh-CN", "format": "storyboard_with_speaker_notes"}, "tier": task["tier"]})["data"]
        persist(base, task_id, "P6", "ppt_completed", ppt, "ppt")
        ppt_rebuilt = True
    prior_claims = artifact(task, "claims")
    prior_verification = artifact(task, "verification")
    prior_verification_basis = artifact(task, "verification_basis")
    can_reuse_prior_verification = bool(
        prior_verification_basis
        and prior_verification_basis.get("claims_fingerprint") == claims_fingerprint(prior_claims)
    )
    claims = None if ppt_rebuilt else prior_claims
    if claims is not None:
        try:
            validate_claims(claims, evidence_ids)
            if not claims_locate_in_delivery(claims, report, ppt):
                raise ValueError("P7 声明无法在当前 P5/P6 产物中定位")
        except ValueError:
            claims = None
    regenerate_claims = claims is not None and len(claims.get("claims", [])) > max_new_verification_claims
    claims_rebuilt = ppt_rebuilt or claims is None or regenerate_claims
    if claims is None or regenerate_claims:
        print("[%s] resume P7%s" % (task["topic"], " (replace over-budget artifact)" if regenerate_claims else ""), flush=True)
        claims = post(base, "/api/claims", {"report": report, "ppt": ppt, "evidence_ids": evidence_ids, "tier": task["tier"]})["data"]
        event_type = "claims_regenerated_over_budget" if regenerate_claims else "claims_completed"
        persist(base, task_id, "P7", event_type, claims, "claims")
    verification_basis = artifact(task, "verification_basis")
    verification_basis_valid = bool(
        verification_basis and verification_basis.get("claims_fingerprint") == claims_fingerprint(claims)
    )
    verification = None if claims_rebuilt or not verification_basis_valid else artifact(task, "verification")
    if verification is not None:
        try:
            validate_verification(verification, [item["claim_id"] for item in claims["claims"]], evidence_ids, claims["claims"])
        except ValueError:
            verification = None
    verification_rebuilt = claims_rebuilt or verification is None
    if verification is None:
        reused_results, pending_claims = (
            reuse_verified_claims(claims, prior_claims, prior_verification)
            if claims_rebuilt and can_reuse_prior_verification else ([], claims["claims"])
        )
        if len(pending_claims) > max_new_verification_claims:
            raise RuntimeError(
                "P8 尚有 %d 条变更声明需要重新核验，超过费用门禁 %d；已严格复用 %d 条未变化声明"
                % (len(pending_claims), max_new_verification_claims, len(reused_results))
            )
        print("[%s] resume P8 (%d claims: %d reused, %d changed)" % (
            task["topic"], len(claims["claims"]), len(reused_results), len(pending_claims)
        ), flush=True)
        saved_cache = task["artifacts"]
        claims_updated_at = str(task["artifacts"].get("claims", {}).get("updated_at") or "")
        pro_claim_ids = select_pro_claim_ids(claims)

        def verify_piece(items, kind):
            ids = [item["claim_id"] for item in items]
            fingerprint = claims_fingerprint({"claims": items})
            entry = saved_cache.get(kind)
            basis_entry = saved_cache.get(kind + "_basis")
            basis_matches = bool(
                basis_entry and basis_entry["data"].get("claims_fingerprint") == fingerprint
            )
            # Migrate only checkpoints written after the current claim set and
            # only after validating their exact IDs/content contract. This
            # safely recovers the in-progress run that predates basis records.
            timestamp_matches = bool(
                entry and claims_updated_at and str(entry.get("updated_at") or "") >= claims_updated_at
            )
            if entry and (basis_matches or timestamp_matches):
                try:
                    checked = validate_verification(entry["data"], ids, evidence_ids, items)
                except ValueError:
                    pass
                else:
                    if not basis_matches:
                        persist(base, task_id, "P8", "verification_batch_basis_migrated", {
                            "version": 1, "claims_fingerprint": fingerprint, "claim_ids": ids,
                        }, kind + "_basis")
                    return checked
            partial_claims = {"claim_set_version": claims["claim_set_version"], "claims": items, "extraction_notes": []}
            saved = post(base, "/api/verify", {"claims": partial_claims, "evidence_records": evidence_records, "source_records": selected_sources, "pro_claim_ids": pro_claim_ids, "tier": task["tier"]})["data"]
            persist(base, task_id, "P8", "verification_batch_completed", saved, kind)
            persist(base, task_id, "P8", "verification_batch_basis_recorded", {
                "version": 1, "claims_fingerprint": fingerprint, "claim_ids": ids,
            }, kind + "_basis")
            saved_cache[kind] = {"data": saved, "updated_at": "current"}
            saved_cache[kind + "_basis"] = {"data": {"claims_fingerprint": fingerprint}, "updated_at": "current"}
            return saved

        batch_results = list(reused_results)
        for index in range(0, len(pending_claims), 4):
            kind = "verification_current_batch_%03d" % (index // 4 + 1)
            items = pending_claims[index:index + 4]
            if kind not in saved_cache:
                print("[%s] P8 changed batch %d/%d" % (task["topic"], index // 4 + 1, (len(pending_claims) + 3) // 4), flush=True)
            saved = verify_piece(items, kind)
            batch_results.extend(saved["results"])
        verification = merge_verification(batch_results, claims)
        persist(base, task_id, "P8", "verification_completed", verification, "verification")
        persist(base, task_id, "P8", "verification_basis_recorded", {
            "version": 1, "claims_fingerprint": claims_fingerprint(claims), "claim_count": len(claims["claims"]),
        }, "verification_basis")
    final = None if verification_rebuilt else artifact(task, "final_delivery")
    if final is not None:
        try:
            validate_final(final, [item["claim_id"] for item in claims["claims"]], source_ids, evidence_ids, verification)
        except ValueError:
            final = None
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
    parser.add_argument("--selected-direction", default="", help="用户明确选择的 P1 方向标题关键字")
    parser.add_argument("--base", default="http://127.0.0.1:4180")
    parser.add_argument("--max-new-verification-claims", type=int, default=MAX_VERIFICATION_CLAIMS,
                        help="本次恢复允许重新核验的声明上限；默认保持产品门禁")
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
        if args.selected_direction:
            state["selected_direction"] = args.selected_direction
    elif not args.task_ids or not args.task_token:
        parser.error("请提供 --state-file，或同时提供 task_ids 和 --task-token")
    results = []
    for task_id in args.task_ids:
        try:
            results.append({"ok": True, **resume(
                args.base, task_id, args.task_token,
                state.get("selected_direction", "") if state_path else "",
                args.max_new_verification_claims,
            )})
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
