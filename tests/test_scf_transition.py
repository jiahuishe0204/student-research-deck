import json
import unittest

from scf_transition import P8_BATCH_SIZE, plan_next_stage
from scf_queue_contracts import queue_job_key


class Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def execute(self, sql, params):
        self.connection.queries.append((sql, params))
        if "SELECT job_key,result FROM research_task_jobs" in sql:
            self.rows = [
                (queue_job_key(params[1], work_item_id, 1), result)
                for work_item_id, result in self.connection.stages.get(params[1], [])
            ]
        elif "SELECT 1 FROM research_task_jobs" in sql:
            self.rows = [(1,)] if self.connection.outstanding.get(params[1], False) else []
        else:
            raise AssertionError("planner issued unexpected SQL: " + sql)

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class Connection:
    def __init__(self, stages=None, outstanding=None):
        self.stages = stages or {}
        self.outstanding = outstanding or {}
        self.queries = []

    def cursor(self):
        return Cursor(self)


def envelope(data):
    return {"data": data, "usage": {"total_tokens": 0}}


class ScfTransitionTests(unittest.TestCase):
    def test_p2_to_p3_preserves_context(self):
        plan, intent = {"questions": []}, {"normalized_topic": "研究主题"}
        job = {"task_id": "T1", "stage": "P2", "payload": {"topic": "研究主题", "intent": intent, "tier": "fast"}}
        jobs = plan_next_stage(Connection(), job, envelope(plan))
        self.assertEqual(jobs[0]["stage"], "P3")
        self.assertEqual(jobs[0]["payload"], {"topic": "研究主题", "intent": intent, "plan": plan, "tier": "fast"})

    def test_p3_fans_out_only_kept_sources(self):
        data = {"sources": [{"source_id": "SRC-1"}, {"source_id": "SRC-2"}], "screening": {"decisions": [
            {"source_id": "SRC-1", "status": "keep", "question_ids": ["Q1"]},
            {"source_id": "SRC-2", "status": "drop", "question_ids": []}]}}
        job = {"task_id": "T1", "stage": "P3", "payload": {"topic": "主题", "intent": {"i": 1}, "plan": {"p": 1}, "tier": "fast"}}
        jobs = plan_next_stage(Connection(), job, envelope(data))
        self.assertEqual([item["work_item_id"] for item in jobs], ["source:SRC-1"])
        self.assertEqual(jobs[0]["payload"]["intent"], {"i": 1})

    def test_zero_kept_sources_becomes_truthful_partial_delivery_job(self):
        job = {"task_id": "T1", "stage": "P3", "payload": {"topic": "研究主题", "tier": "fast"}}
        jobs = plan_next_stage(Connection(), job, envelope({"sources": [], "screening": {"decisions": [], "summary": {"candidate_count": 0, "open_issues": []}}}))
        self.assertEqual(jobs[0]["stage"], "P9")
        self.assertEqual(jobs[0]["work_item_id"], "publish")
        self.assertEqual(jobs[0]["payload"]["completion_status"], "partial")
        self.assertIn("不对研究问题作实质性科学结论", jobs[0]["payload"]["final_delivery"]["final_report"]["markdown"])

    def test_p4_barrier_waits_for_all_sources_and_aggregates_evidence(self):
        p3 = envelope({"sources": [{"source_id": "S1", "title": "A"}], "screening": {"decisions": []}})
        prior = ("source:S0", json.dumps(envelope({"evidence_records": [{"evidence_id": "E0", "source_id": "S1"}], "figure_records": []})))
        stages = {"P3": [("main", json.dumps(p3))], "P4": [prior]}
        job = {"task_id": "T1", "stage": "P4", "work_item_id": "source:S1", "payload": {"intent": {"i": 1}, "plan": {"p": 1}, "tier": "fast"}}
        result = envelope({"evidence_records": [{"evidence_id": "E1", "source_id": "S1"}], "figure_records": []})
        self.assertEqual(plan_next_stage(Connection(stages, {"P4": True}), job, result), [])
        jobs = plan_next_stage(Connection(stages), job, result)
        self.assertEqual(jobs[0]["stage"], "P5")
        self.assertEqual({item["evidence_id"] for item in jobs[0]["payload"]["evidence"]}, {"E0", "E1"})

    def test_p7_splits_claims_into_stable_p8_work_items(self):
        claims = {"claim_set_version": "1", "claims": [{"claim_id": "CLM-%04d" % i} for i in range(1, P8_BATCH_SIZE + 2)], "extraction_notes": []}
        job = {"task_id": "T1", "stage": "P7", "payload": {"tier": "fast"}}
        p3 = envelope({"sources": [], "screening": {"decisions": []}})
        jobs = plan_next_stage(Connection({"P3": [("main", json.dumps(p3))]}), job, envelope(claims))
        self.assertEqual([item["work_item_id"] for item in jobs], ["batch:0001", "batch:0002"])
        self.assertEqual([len(item["payload"]["claims"]["claims"]) for item in jobs], [P8_BATCH_SIZE, 1])

    def test_last_p8_batch_merges_and_checks_complete_coverage(self):
        p7 = envelope({"claims": [{"claim_id": "C1"}, {"claim_id": "C2"}]})
        p3 = envelope({"sources": [{"source_id": "S1"}], "screening": {"decisions": []}})
        p4 = envelope({"evidence_records": [{"evidence_id": "E1", "source_id": "S1"}], "figure_records": []})
        stages = {
            "P7": [("main", json.dumps(p7))], "P5": [("main", json.dumps(envelope({"report_markdown": "R"})))],
            "P6": [("main", json.dumps(envelope({"pages": [{"page_id": "SL-01"}]})))],
            "P3": [("main", json.dumps(p3))], "P4": [("source:S1", json.dumps(p4))],
            "P8": [("batch:0001", json.dumps(envelope({"results": [{"claim_id": "C1", "support_status": "supported"}]})))],
        }
        job = {"task_id": "T1", "stage": "P8", "work_item_id": "batch:0002", "payload": {"tier": "fast"}}
        result = envelope({"results": [{"claim_id": "C2", "support_status": "cannot_determine"}]})
        self.assertEqual(plan_next_stage(Connection(stages, {"P8": True}), job, result), [])
        jobs = plan_next_stage(Connection(stages), job, result)
        self.assertEqual(jobs[0]["stage"], "P9")
        self.assertEqual([item["claim_id"] for item in jobs[0]["payload"]["verification"]["results"]], ["C1", "C2"])
        self.assertEqual(jobs[0]["payload"]["verification"]["summary"]["supported"], 1)


if __name__ == "__main__":
    unittest.main()
