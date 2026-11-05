import unittest

from scf_stage_dispatch import dispatch_queued_stage, dispatch_stage


class FakeWorkflow:
    def create_intent(self, topic, tier):
        return {"topic": topic, "tier": tier}


class StageDispatchTests(unittest.TestCase):
    def test_routes_p1_explicitly(self):
        result = dispatch_stage(FakeWorkflow(), "P1", {"topic": "细胞", "tier": "fast"})
        self.assertEqual(result["topic"], "细胞")

    def test_rejects_missing_inputs(self):
        with self.assertRaises(ValueError):
            dispatch_stage(FakeWorkflow(), "P1", {"tier": "fast"})

    def test_rejects_missing_workflow_method(self):
        with self.assertRaises(AttributeError):
            dispatch_stage(FakeWorkflow(), "P2", {"topic": "细胞", "intent": {}, "tier": "fast"})

    def test_queued_p3_requires_explicit_retrieval_injection(self):
        with self.assertRaisesRegex(RuntimeError, "未显式配置"):
            dispatch_queued_stage(
                FakeWorkflow(), "P3", {"topic": "细胞", "plan": {}, "tier": "fast"}
            )

    def test_queued_p3_returns_sources_screening_usage_and_metadata(self):
        calls = []

        def pipeline(workflow, **kwargs):
            calls.append((workflow, kwargs))
            return {
                "sources": {"records": [{"source_id": "PMID:1"}], "queries": ["q1", "q2"]},
                "screening": {"decisions": []},
                "usage": {"total_tokens": 11},
                "supplemental_search": True,
            }

        workflow = FakeWorkflow()
        result = dispatch_queued_stage(
            workflow,
            "P3",
            {"topic": "细胞", "plan": {"questions": []}, "tier": "fast"},
            research_pipeline_fn=pipeline,
            research_pipeline_options={"environ": {}},
        )
        self.assertEqual(calls, [(workflow, {
            "topic": "细胞", "plan": {"questions": []}, "tier": "fast", "environ": {},
        })])
        self.assertEqual(result, (
            {"sources": [{"source_id": "PMID:1"}], "screening": {"decisions": []},
             "supplemental_search": True},
            {"total_tokens": 11},
            {"retrieval_query_count": 2},
        ))

    def test_queued_p3_rejects_missing_plan_before_external_dependency(self):
        pipeline = lambda *args, **kwargs: self.fail("pipeline must not run")
        with self.assertRaisesRegex(ValueError, "plan"):
            dispatch_queued_stage(
                FakeWorkflow(), "P3", {"topic": "细胞", "tier": "fast"},
                research_pipeline_fn=pipeline,
            )

    def test_p9_publish_requires_explicit_private_delivery_publisher(self):
        payload = {"action": "publish", "task_id": "TASK-12345678"}
        with self.assertRaisesRegex(RuntimeError, "发布器未配置"):
            dispatch_queued_stage(FakeWorkflow(), "P9", payload)

    def test_p9_publish_calls_only_the_injected_publisher(self):
        calls = []
        result = dispatch_queued_stage(
            FakeWorkflow(), "P9", {"action": "publish", "task_id": "TASK-12345678"},
            delivery_publisher_fn=lambda payload: calls.append(payload) or {"status": "published"},
        )
        self.assertEqual(calls, [{"action": "publish", "task_id": "TASK-12345678"}])
        self.assertEqual(result[0], {"status": "published"})
        self.assertEqual(result[1]["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
