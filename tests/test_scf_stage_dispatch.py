import unittest

from scf_stage_dispatch import dispatch_stage


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


if __name__ == "__main__":
    unittest.main()
