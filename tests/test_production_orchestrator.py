import unittest
from pathlib import Path

from production_orchestrator import advance


def wrapped(data):
    return {"data": data, "usage": {"total_tokens": 1}}


class Queue:
    def __init__(self, jobs=None):
        self.jobs = jobs or {}
        self.enqueued = []
        self.completed = []

    def enqueue(self, **values):
        if any(item.get("task_id") == values.get("task_id") and item.get("job_key") == values.get("job_key")
               for item in self.enqueued):
            return False
        self.enqueued.append(values)
        return True

    def stage_jobs(self, *, task_id, stage):
        return self.jobs.get(stage, [])

    def complete_task(self, task_id):
        self.completed.append(task_id)
        return True


class ProductionOrchestratorTests(unittest.TestCase):
    def test_p1_waits_for_user_direction(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "stage": "P1", "payload": {}}
        self.assertEqual(advance(queue, job, wrapped({"need_clarification": True}), root=Path(".")),
                         "awaiting_clarification")
        self.assertEqual(queue.enqueued, [])

    def test_p2_enqueues_persisted_retrieval_job(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "stage": "P2", "payload": {
            "topic": "CRISPR", "tier": "fast", "intent": {"normalized_topic": "CRISPR"}}}
        self.assertEqual(advance(queue, job, wrapped({"questions": []}), root=Path(".")), "P3:retrieve")
        self.assertEqual(queue.enqueued[0]["stage"], "P3")
        self.assertEqual(queue.enqueued[0]["job_key"], "P3:retrieve")
        self.assertEqual(queue.enqueued[0]["payload"]["mode"], "retrieve")

    def test_persisted_retrieval_result_enqueues_screening_without_new_search(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "job_key": "P3:retrieve", "stage": "P3", "payload": {
            "mode": "retrieve", "topic": "CRISPR", "plan": {}, "tier": "fast", "intent": {}}}
        self.assertEqual(advance(queue, job, wrapped({"records": [{"source_id": "S1"}]}),
                                 root=Path(".")), "P3:screen")
        self.assertEqual(queue.enqueued[0]["payload"]["sources"][0]["source_id"], "S1")

    def test_p3_fans_out_only_kept_sources(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "job_key": "P3:screen", "stage": "P3", "payload": {
            "sources": [{"source_id": "S1"}, {"source_id": "S2"}], "tier": "fast"}}
        screening = {"decisions": [
            {"source_id": "S1", "status": "keep", "question_ids": ["Q1"]},
            {"source_id": "S2", "status": "drop", "question_ids": []},
        ]}
        self.assertEqual(advance(queue, job, wrapped(screening), root=Path(".")), "P4")
        self.assertEqual([item["job_key"] for item in queue.enqueued], ["P4:S1"])

    def test_p4_barrier_waits_until_every_extraction_succeeds(self):
        queue = Queue({"P4": [
            {"status": "succeeded", "result": wrapped({"evidence_records": [{"evidence_id": "E1"}]})},
            {"status": "running", "result": None},
        ]})
        job = {"task_id": "TASK-1", "stage": "P4", "payload": {}}
        self.assertEqual(advance(queue, job, wrapped({}), root=Path(".")), "P4")
        self.assertEqual(queue.enqueued, [])

    def test_last_p4_transition_uses_screen_job_and_enqueues_p5(self):
        queue = Queue({
            "P1": [{"job_key": "P1", "status": "succeeded", "result": wrapped({"intent": True})}],
            "P2": [{"job_key": "P2", "status": "succeeded", "result": wrapped({"plan": True})}],
            "P3": [
                {"job_key": "P3:retrieve", "status": "succeeded", "payload": {}, "result": wrapped({"records": []})},
                {"job_key": "P3:screen", "status": "succeeded",
                 "payload": {"sources": [{"source_id": "S1"}], "tier": "fast"},
                 "result": wrapped({"screening": {"decisions": []}, "sources": [{"source_id": "S1"}]})},
            ],
            "P4": [{"job_key": "P4:S1", "status": "succeeded",
                    "result": wrapped({"source_id": "S1", "reading_scope": "abstract_only",
                                       "evidence_records": [{"evidence_id": "E1", "source_id": "S1"}],
                                       "figure_records": []})}],
        })
        job = {"task_id": "TASK-1", "stage": "P4", "payload": {}}
        self.assertEqual(advance(queue, job, wrapped({}), root=Path(".")), "P5")
        self.assertEqual(queue.enqueued[0]["job_key"], "P5")
        self.assertEqual(queue.enqueued[0]["payload"]["sources"][0]["source_id"], "S1")

    def test_p9_marks_task_complete(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "stage": "P9", "payload": {}}
        calls = []
        self.assertEqual(advance(queue, job, wrapped({"final_report": {}}), root=Path("."),
                                 publisher=lambda *args: calls.append(args)), "completed")
        self.assertEqual(calls[0][0], "TASK-1")
        self.assertEqual(queue.completed, [])

    def test_p7_persists_small_p8_batches_with_full_claim_manifest(self):
        queue = Queue()
        claims = [{"claim_id": "C%03d" % index} for index in range(14)]
        payload = {"evidence": [{"evidence_id": "E1"}], "sources": [], "tier": "deep",
                   "report": {}, "ppt": {}, "figure_records": []}
        self.assertEqual(advance(queue, {"task_id": "TASK-1", "stage": "P7", "payload": payload},
                                 wrapped({"claims": claims, "claim_set_version": "v1"}), root=Path(".")),
                         "P8:4-batches")
        self.assertEqual(len(set(job["job_key"] for job in queue.enqueued)), 4)
        self.assertTrue(all(job["job_key"].startswith("P8:batch:") for job in queue.enqueued))
        self.assertEqual([len(job["payload"]["claims"]["claims"]) for job in queue.enqueued], [4, 4, 4, 2])
        self.assertEqual(len(queue.enqueued[1]["payload"]["all_claims"]["claims"]), 14)

    def test_p8_waits_for_all_batches_then_aggregates_exactly_once(self):
        full_claims = {"claims": [{"claim_id": "C1"}, {"claim_id": "C2"}]}
        payload = {"claims": {"claims": [{"claim_id": "C2"}]}, "all_claims": full_claims,
                   "report": {}, "ppt": {}, "evidence": [{"evidence_id": "E1", "source_id": "S1"}],
                   "sources": [{"source_id": "S1"}], "figure_records": [], "tier": "fast"}
        queue = Queue({"P8": [
            {"job_key": "P8:batch:0001", "status": "succeeded", "result": wrapped({"results": [
                {"claim_id": "C1", "support_status": "supported"}]})},
            {"job_key": "P8:batch:0002", "status": "pending", "result": None},
        ]})
        job = {"task_id": "TASK-1", "stage": "P8", "payload": payload}
        self.assertEqual(advance(queue, job, wrapped({"results": [{"claim_id": "C2", "support_status": "unsupported"}]}), root=Path(".")),
                         "P8:awaiting-batches")
        self.assertEqual(queue.enqueued, [])
        queue.jobs["P8"][1] = {"job_key": "P8:batch:0002", "status": "succeeded",
                               "result": wrapped({"results": [{"claim_id": "C2", "support_status": "unsupported"}]})}
        self.assertEqual(advance(queue, job, wrapped({}), root=Path(".")), "P9")
        self.assertEqual(len(queue.enqueued), 1)
        p9 = queue.enqueued[0]["payload"]
        self.assertEqual([item["claim_id"] for item in p9["verification"]["results"]], ["C1", "C2"])
        self.assertEqual(p9["claims"], full_claims["claims"])

    def test_end_to_end_p7_batches_persist_then_enqueue_one_p9(self):
        queue = Queue()
        claims = [{"claim_id": "C%02d" % i} for i in range(13)]
        common = {"evidence": [{"evidence_id": "E1", "source_id": "S1"}],
                  "sources": [{"source_id": "S1"}], "tier": "deep", "report": {},
                  "ppt": {}, "figure_records": []}
        p7_job = {"task_id": "TASK-E2E", "stage": "P7", "payload": common}
        self.assertEqual(advance(queue, p7_job, wrapped({"claims": claims}), root=Path(".")), "P8:4-batches")
        p8_jobs = list(queue.enqueued)
        persisted_p8 = [{**item, "status": "pending", "result": None} for item in p8_jobs]
        queue.jobs["P8"] = persisted_p8
        for index, queued in enumerate(persisted_p8):
            result = wrapped({"results": [{"claim_id": item["claim_id"], "support_status": "supported"}
                                          for item in queued["payload"]["claims"]["claims"]]})
            queued["status"] = "succeeded"
            queued["result"] = result
            status = advance(queue, {"task_id": "TASK-E2E", "stage": "P8", "payload": queued["payload"]},
                             result, root=Path("."))
            if index < len(p8_jobs) - 1:
                self.assertEqual(status, "P8:awaiting-batches")
        p9_jobs = [item for item in queue.enqueued if item["stage"] == "P9"]
        self.assertEqual(len(p9_jobs), 1)
        # A replayed transition is safe because the durable queue key is unique.
        final_job = persisted_p8[-1]
        advance(queue, {"task_id": "TASK-E2E", "stage": "P8", "payload": final_job["payload"]},
                final_job["result"], root=Path("."))
        self.assertEqual(len([item for item in queue.enqueued if item["stage"] == "P9"]), 1)

    def test_p9_never_completes_without_private_publisher(self):
        queue = Queue()
        job = {"task_id": "TASK-1", "stage": "P9", "payload": {}}
        with self.assertRaisesRegex(RuntimeError, "发布器"):
            advance(queue, job, wrapped({"final_report": {}}), root=Path("."))


if __name__ == "__main__":
    unittest.main()
