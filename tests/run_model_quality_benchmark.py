#!/usr/bin/env python3
"""Run the fixed ten-claim Flash/Pro/mixed quality benchmark."""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from model_usage import ModelUsageLedger
from quality_benchmark import score_ppt_density, score_verification
from server import load_dotenv
from workflow_service import WorkflowService


class BenchmarkRouter:
    def __init__(self, scheme):
        self.scheme = scheme

    def for_stage(self, stage, tier="fast", upgrade=False):
        if self.scheme == "flash":
            model, effort = "deepseek-flash", "none"
        elif self.scheme == "pro_low":
            model, effort = "deepseek-v4-pro", "low"
        else:
            model, effort = ("deepseek-v4-pro", "low") if upgrade else ("deepseek-flash", "none")
        return {"model":model,"effort":effort,"capability":"high_risk_verification","upgraded":upgrade}


def artifact(connection, task_id, kind):
    row = connection.execute("SELECT payload_json FROM artifacts WHERE task_id=? AND kind=?", (task_id, kind)).fetchone()
    return json.loads(row[0])


def main():
    benchmark = json.loads((ROOT / "tests/fixtures/model-quality-benchmark.json").read_text(encoding="utf-8"))
    connection = sqlite3.connect(str(ROOT / "data/tasks.sqlite3"))
    task_id = benchmark["baseline_task_id"]
    all_claims = artifact(connection, task_id, "claims")["claims"]
    claims_by_id = {item["claim_id"]: item for item in all_claims}
    claims = {"claim_set_version":"quality-benchmark-1.0","claims":[claims_by_id[item] for item in benchmark["claim_ids"]],"extraction_notes":[]}
    evidence_artifact = artifact(connection, task_id, "evidence")
    evidence = [item for group in evidence_artifact["groups"] for item in group["evidence_records"]]
    evidence_ids = {item["evidence_id"] for item in evidence}
    sources_artifact = artifact(connection, task_id, "sources")
    source_ids = {item["source_id"] for item in evidence}
    sources = [item for item in sources_artifact["records"] if item["source_id"] in source_ids]

    load_dotenv(ROOT.parent / ".env")
    api_key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("未配置 DeepSeek API 密钥")
    ledger = ModelUsageLedger(ROOT / "data/private/model-usage.sqlite3")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results = {"run_id":run_id,"schemes":{},"ppt_density":{}}
    for scheme in ("flash", "pro_low", "mixed"):
        ledger_id = "BENCH-%s-%s" % (run_id, scheme)
        service = WorkflowService.from_project(api_key, BenchmarkRouter(scheme), ROOT, usage_ledger=ledger, model_limits={
            "task_max_cost_cny": 0.15, "task_max_total_tokens": 90000,
            "pro_max_calls": 8, "pro_max_output_tokens": 24000, "pro_max_total_tokens": 70000,
        })
        service.set_task_context(ledger_id)
        try:
            output, usage, metadata = service.verify_claims(claims, evidence, sources, "fast")
            score = score_verification(output["results"], benchmark["gold"], evidence_ids)
            acceptance = benchmark["acceptance"]
            passed = (
                score["score"] >= acceptance["minimum_score"]
                and score["status_exact"] >= acceptance["minimum_status_exact"]
                and score["action_exact"] >= acceptance["minimum_action_exact"]
                and len(score["critical_errors"]) <= acceptance["maximum_critical_errors"]
                and len(score["hallucinated_evidence"]) <= acceptance["maximum_hallucinated_evidence"]
            )
            results["schemes"][scheme] = {"completed":True,"passed":passed,"score":score,"usage":usage,"metadata":metadata,"cost_cny":ledger.cost_cny(ledger_id),"output":output}
        except Exception as exc:
            results["schemes"][scheme] = {"completed":False,"passed":False,"error":type(exc).__name__ + ": " + str(exc),"cost_cny":ledger.cost_cny(ledger_id),"usage_summary":ledger.summary(ledger_id)}
        private_path = ROOT / "data/private" / ("model-quality-benchmark-%s.json" % run_id)
        private_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
        os.chmod(private_path, 0o600)

    for name, compared_task in (("baseline", task_id), ("optimized", "TASK-c3ec0391d47e")):
        final = artifact(connection, compared_task, "final_delivery")
        results["ppt_density"][name] = score_ppt_density(final["final_ppt"]["pages"], benchmark["ppt_density"])
    results["total_cost_cny"] = sum(item["cost_cny"] for item in results["schemes"].values())
    private_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print("MODEL_QUALITY_BENCHMARK=" + json.dumps({**results, "schemes": {key:{k:v for k,v in value.items() if k != "output"} for key,value in results["schemes"].items()}}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
