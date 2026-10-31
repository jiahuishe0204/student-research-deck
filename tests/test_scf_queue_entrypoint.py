import unittest
from unittest.mock import patch

import scf_queue_entrypoint


class ScfQueueEntrypointTests(unittest.TestCase):
    def test_parallel_entrypoint_claims_queue_and_uses_durable_transition_planner(self):
        connection = object()
        workflow = object()
        dispatcher = object()
        captured = {}

        def execute(connection_arg, workflow_arg, planner, **kwargs):
            captured.update(connection=connection_arg, workflow=workflow_arg, planner=planner, **kwargs)
            job = {"task_id": "T1", "stage": "P2", "payload": {"topic": "主题", "intent": {}, "tier": "fast"}}
            result = {"data": {"questions": []}, "usage": {}}
            return planner(job, result)

        with patch.object(scf_queue_entrypoint, "execute_queued_stage", side_effect=execute), \
             patch.object(scf_queue_entrypoint, "plan_next_stage", return_value=[{"stage": "P3"}]) as planner:
            result = scf_queue_entrypoint.process_one_queued_stage(connection, workflow, dispatcher, lease_seconds=600)

        self.assertEqual(result, [{"stage": "P3"}])
        self.assertIs(captured["connection"], connection)
        self.assertIs(captured["workflow"], workflow)
        self.assertIs(captured["stage_dispatcher"], dispatcher)
        self.assertEqual(captured["lease_seconds"], 600)
        planner.assert_called_once_with(connection, {
            "task_id": "T1", "stage": "P2", "payload": {"topic": "主题", "intent": {}, "tier": "fast"},
        }, {"data": {"questions": []}, "usage": {}})


if __name__ == "__main__":
    unittest.main()
