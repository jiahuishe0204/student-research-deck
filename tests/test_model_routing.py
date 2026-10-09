import unittest

from model_routing import ModelRouter, ModelRoutingError


class ModelRouterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.router = ModelRouter.from_file()

    def test_fast_and_deep_planning_follow_config(self):
        self.assertEqual(self.router.for_stage("P1", "fast")["model"], "deepseek-v4-pro")
        self.assertEqual(self.router.for_stage("P1", "fast")["effort"], "low")
        self.assertEqual(self.router.for_stage("P2", "fast")["model"], "deepseek-v4-pro")
        self.assertEqual(self.router.for_stage("P2", "fast")["effort"], "low")
        self.assertEqual(self.router.for_stage("P2", "deep")["model"], "deepseek-v4-pro")
        self.assertEqual(self.router.for_stage("P2", "deep")["effort"], "medium")
        self.assertEqual(self.router.for_stage("P1", "deep")["model"], "deepseek-v4-pro")
        self.assertEqual(self.router.for_stage("P1", "deep")["effort"], "low")
        self.assertEqual(self.router.for_stage("P4", "deep")["effort"], "none")
        self.assertEqual(self.router.for_stage("P6", "deep")["effort"], "none")

    def test_high_risk_fast_verification_upgrades_with_bounded_effort(self):
        route = self.router.for_stage("P8", "fast", upgrade=True)
        self.assertEqual(route["model"], "deepseek-v4-pro")
        self.assertEqual(route["effort"], "low")
        self.assertTrue(route["upgraded"])

    def test_unknown_stage_or_tier_is_rejected(self):
        with self.assertRaises(ModelRoutingError):
            self.router.for_stage("P10", "fast")
        with self.assertRaises(ModelRoutingError):
            self.router.for_stage("P1", "premium")


if __name__ == "__main__":
    unittest.main()
