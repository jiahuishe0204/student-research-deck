"""Offline regression for console event shape; no cloud/model calls."""

import json
from pathlib import Path
import unittest
from unittest.mock import Mock

from scf_handler import WorkerEventError, validate_worker_event
from scf_stage_dispatch import dispatch_stage


class ConsoleEventTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parent / "fixtures" / "scf_p2_smoke.json"
        self.event = json.loads(path.read_text(encoding="utf-8"))

    def test_fixture_routes_exact_arguments_to_p2(self):
        event = validate_worker_event(self.event)
        workflow = Mock()
        dispatch_stage(workflow, event["stage"], event["payload"])
        p = event["payload"]
        workflow.create_plan.assert_called_once_with(p["topic"], "", "fast", p["intent"])

    def test_hello_world_template_is_not_a_worker_event(self):
        with self.assertRaisesRegex(WorkerEventError, "task_id"):
            validate_worker_event({"key1": "test value 1", "key2": "test value 2"})

    def test_lost_underscore_is_rejected(self):
        self.event["taskid"] = self.event.pop("task_id")
        with self.assertRaisesRegex(WorkerEventError, "task_id"):
            validate_worker_event(self.event)

    def test_nested_event_is_not_implicitly_unwrapped(self):
        with self.assertRaisesRegex(WorkerEventError, "task_id"):
            validate_worker_event({"body": self.event})

    def test_serialized_string_is_not_a_json_object(self):
        with self.assertRaisesRegex(WorkerEventError, "JSON 对象"):
            validate_worker_event(json.dumps(self.event))

    def test_missing_p2_input_does_not_call_model(self):
        del self.event["payload"]["intent"]
        workflow = Mock()
        with self.assertRaisesRegex(ValueError, "intent"):
            dispatch_stage(workflow, "P2", self.event["payload"])
        workflow.create_plan.assert_not_called()

    def test_p4_routes_exact_arguments_to_evidence_extraction(self):
        payload = {
            "source_record": {"source_id": "SRC-30889382", "abstract": "abstract text"},
            "question_ids": ["Q3"],
            "tier": "fast",
        }
        workflow = Mock()
        dispatch_stage(workflow, "P4", payload)
        workflow.extract_evidence.assert_called_once_with(
            payload["source_record"], payload["question_ids"], "fast"
        )

    def test_missing_p4_question_ids_does_not_call_model(self):
        payload = {"source_record": {"source_id": "SRC-30889382"}, "tier": "fast"}
        workflow = Mock()
        with self.assertRaisesRegex(ValueError, "question_ids"):
            dispatch_stage(workflow, "P4", payload)
        workflow.extract_evidence.assert_not_called()


if __name__ == "__main__":
    unittest.main()
