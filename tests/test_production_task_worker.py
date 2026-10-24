import unittest

from production_task_worker import execute_next_job


class Queue:
    def __init__(self, job):
        self.job = job
        self.finished = []

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
        result = execute_next_job(queue, workflow)
        self.assertEqual(result["status"], "succeeded")
        self.assertEqual(workflow.task_id, "TASK-1")
        self.assertEqual(queue.finished[0][1]["result"]["topic"], "CRISPR")

    def test_failure_is_requeued_without_payload_or_secret_in_error(self):
        class BrokenWorkflow(Workflow):
            def create_intent(self, topic, tier):
                raise RuntimeError("sensitive detail")
        job = {"job_id": "j1", "task_id": "TASK-1", "stage": "P1", "attempt": 1,
               "payload": {"topic": "CRISPR", "tier": "fast"}, "lease_token": "lease"}
        queue = Queue(job)
        with self.assertRaises(RuntimeError):
            execute_next_job(queue, BrokenWorkflow())
        self.assertEqual(queue.finished[0][1], {"error_code": "RuntimeError", "retry_delay_seconds": 60})

    def test_third_failure_is_terminal(self):
        class BrokenWorkflow(Workflow):
            def create_intent(self, topic, tier):
                raise RuntimeError("failed")
        job = {"job_id": "j1", "task_id": "TASK-1", "stage": "P1", "attempt": 3,
               "payload": {"topic": "CRISPR", "tier": "fast"}, "lease_token": "lease"}
        queue = Queue(job)
        with self.assertRaises(RuntimeError):
            execute_next_job(queue, BrokenWorkflow())
        self.assertEqual(queue.finished[0][1], {"error_code": "RuntimeError", "retry_delay_seconds": None})


if __name__ == "__main__":
    unittest.main()
