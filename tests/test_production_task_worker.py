import unittest

from production_task_worker import execute_next_job


class Queue:
    def __init__(self, job):
        self.job = job
        self.finished = []

    def claim_transition(self):
        return None

    def claim_next(self):
        return self.job

    def finish(self, job, **values):
        self.finished.append((job, values))
        return True


class Workflow:
    def __init__(self):
        self.task_id = None

    def set_task_context(self, task_id):
        self.task_id = task_id

    def create_intent(self, topic, tier):
        return {"topic": topic, "tier": tier}


class ProductionTaskWorkerTests(unittest.TestCase):
    def test_empty_queue_is_safe(self):
        self.assertEqual(execute_next_job(Queue(None), Workflow()),
                         {"accepted": False, "reason": "empty"})

    def test_claimed_stage_saves_result(self):
        job = {"job_id": "j1", "task_id": "TASK-1", "stage": "P1", "attempt": 1,
               "payload": {"topic": "CRISPR", "tier": "fast"}, "lease_token": "lease"}
        queue, workflow = Queue(job), Workflow()
        result = execute_next_job(queue, workflow, advance_job=lambda *args, **kwargs: "awaiting_clarification")
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(workflow.task_id, "TASK-1")
        self.assertEqual(queue.finished[0][1]["result"]["data"]["topic"], "CRISPR")
        self.assertEqual(result["next"], "transition_pending")

    def test_failure_is_requeued_without_payload_or_secret_in_error(self):
        class BrokenWorkflow(Workflow):
            def create_intent(self, topic, tier):
                raise RuntimeError("sensitive detail")
        job = {"job_id": "j1", "task_id": "TASK-1", "stage": "P1", "attempt": 1,
               "payload": {"topic": "CRISPR", "tier": "fast"}, "lease_token": "lease"}
        queue = Queue(job)
        with self.assertRaises(RuntimeError):
            execute_next_job(queue, BrokenWorkflow(), advance_job=lambda *args, **kwargs: None)
        self.assertEqual(queue.finished[0][1], {"error_code": "RuntimeError", "retry_delay_seconds": 60})

    def test_third_failure_is_terminal(self):
        class BrokenWorkflow(Workflow):
            def create_intent(self, topic, tier):
                raise RuntimeError("failed")
        job = {"job_id": "j1", "task_id": "TASK-1", "stage": "P1", "attempt": 3,
               "payload": {"topic": "CRISPR", "tier": "fast"}, "lease_token": "lease"}
        queue = Queue(job)
        with self.assertRaises(RuntimeError):
            execute_next_job(queue, BrokenWorkflow(), advance_job=lambda *args, **kwargs: None)
        self.assertEqual(queue.finished[0][1], {"error_code": "RuntimeError", "retry_delay_seconds": None})

    def test_transition_is_retried_without_rerunning_model(self):
        transition = {"job_id": "j1", "task_id": "TASK-1", "stage": "P2", "attempt": 1,
                      "payload": {}, "result": {"data": {"plan": True}},
                      "transition_attempt": 1, "lease_token": "transition-lease"}
        class TransitionQueue(Queue):
            def claim_transition(self): return transition
            def claim_next(self): raise AssertionError("model job must not be claimed")
            def finish_transition(self, job, **values): self.transition_finished=(job,values); return True
        queue = TransitionQueue(None)
        result = execute_next_job(queue, Workflow(),
                                  advance_job=lambda *args, **kwargs: "P3")
        self.assertEqual(result["status"], "advanced")
        self.assertEqual(result["next"], "P3")
        self.assertEqual(queue.transition_finished[1], {})

    def test_p9_transition_builds_publisher_lazily(self):
        transition = {"job_id": "j9", "task_id": "TASK-1", "stage": "P9", "attempt": 1,
                      "payload": {}, "result": {"data": {"final_report": {}}},
                      "transition_attempt": 1, "lease_token": "transition-lease"}
        class TransitionQueue(Queue):
            def claim_transition(self): return transition
            def finish_transition(self, job, **values): return True
        publishers = []
        def factory():
            publishers.append(True)
            return lambda *args: None
        def advance_p9(queue, job, result, **values):
            self.assertTrue(callable(values["publisher"]))
            return "completed"
        result = execute_next_job(TransitionQueue(None), Workflow(), advance_job=advance_p9,
                                  publisher_factory=factory)
        self.assertEqual(result["next"], "completed")
        self.assertEqual(publishers, [True])


if __name__ == "__main__":
    unittest.main()
