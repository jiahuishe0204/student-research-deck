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
        self.assertEqual(advance(queue, job, wrapped({"final_report": {}}), root=Path(".")), "completed")
        self.assertEqual(queue.completed, ["TASK-1"])


if __name__ == "__main__":
    unittest.main()
