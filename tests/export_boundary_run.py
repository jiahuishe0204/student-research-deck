"""Export a fresh run without editorial changes; keep draft and final comparable."""
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.export_readable_delivery import delivery_markdown
from model_usage import ModelUsageLedger
from workflow_validation import presentation_boundary_issues
from workflow_service import WorkflowService
from report_citations import render_linked_report


def diagnose(task_id):
    """Save rejected intermediate output for debugging, never as a delivery."""
    with sqlite3.connect(f"file:{ROOT / 'data/tasks.sqlite3'}?mode=ro", uri=True) as db:
        data = {kind: json.loads(value) for kind, value in db.execute(
            "SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,))}
    evidence = [e for group in data["evidence"]["groups"] for e in group["evidence_records"]]
    figures = [f for group in data["evidence"]["groups"] for f in group["figure_records"]]
    def no_model(*args, **kwargs):
        raise AssertionError("Diagnosis must not call a model")
    intermediate, _ = WorkflowService("", None, "", {}, model_client=no_model).assemble_final_deterministic(
        data["verification"], data["report"], data["ppt"], data["claims"]["claims"],
        [s["source_id"] for s in data["sources"]["records"]], [e["evidence_id"] for e in evidence])
    try:
        render_linked_report(intermediate["final_report"]["markdown"], evidence,
                             data["sources"]["records"], data["report"]["figure_recommendations"], figures)
        citation_error = None
    except ValueError as exc:
        citation_error = str(exc)
    out = ROOT / "artifacts" / "fresh-boundary-run" / task_id
    out.mkdir(parents=True, exist_ok=True)
    for name, value in {"draft-ppt": data["ppt"], "claims": data["claims"],
                        "verification": data["verification"], "REJECTED-intermediate": intermediate}.items():
        (out / f"{name}.json").write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {"task_id": task_id, "status": "failed_acceptance_not_deliverable", "editorial_input": False,
               "scope": "Fresh P1-P8 completed with repairs/resumes; public P9 rejected",
               "citation_error": citation_error,
               "cost_cny_estimated": ModelUsageLedger(ROOT / "data/private/model-usage.sqlite3").cost_cny(task_id),
               "pages": len(data["ppt"]["pages"]), "claims": len(data["claims"]["claims"]),
               "verification_summary": data["verification"]["summary"],
               "pattern_hits_in_intermediate": {p["page_id"]: presentation_boundary_issues(p) for p in intermediate["final_ppt"]["pages"] if presentation_boundary_issues(p)},
               "manual_review_finding": "SL-06 CLM-0077 removed from bullets but paraphrased Au/CSC/CIC comparison survives in notes; pattern checks miss it."}
    (out / "FAILED-run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


def export(task_id):
    with sqlite3.connect(f"file:{ROOT / 'data/tasks.sqlite3'}?mode=ro", uri=True) as db:
        data = {kind: json.loads(value) for kind, value in db.execute(
            "SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,))}
    final = data["final_delivery"]
    out = ROOT / "artifacts" / "fresh-boundary-run" / task_id
    out.mkdir(parents=True, exist_ok=True)
    sources = data["sources"]["records"]
    (out / "PPT自动终稿.md").write_text(delivery_markdown(final, sources), encoding="utf-8")
    (out / "调研报告自动终稿.md").write_text(final["final_report"]["markdown"], encoding="utf-8")
    for name in ("ppt", "claims", "verification", "final_delivery"):
        (out / f"{name}.json").write_text(json.dumps(data[name], ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = ModelUsageLedger(ROOT / "data/private/model-usage.sqlite3")
    summary = {
        "task_id": task_id, "editorial_input": False,
        "scope": "fresh P1-P9 run; no earlier task content reused",
        "cost_cny_estimated": ledger.cost_cny(task_id),
        "model_usage": ledger.summary(task_id),
        "draft_pages": len(data["ppt"]["pages"]),
        "final_pages": len(final["final_ppt"]["pages"]),
        "draft_boundary_hits": {p["page_id"]: presentation_boundary_issues(p) for p in data["ppt"]["pages"] if presentation_boundary_issues(p)},
        "final_boundary_hits": {p["page_id"]: presentation_boundary_issues(p) for p in final["final_ppt"]["pages"] if presentation_boundary_issues(p)},
        "verification_summary": data["verification"]["summary"],
        "verification_note": final["verification_note"],
        "limitation": "Pattern checks do not prove semantic correctness; independent reading still required.",
    }
    (out / "run-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    (diagnose if "--diagnose" in sys.argv else export)(sys.argv[1])
