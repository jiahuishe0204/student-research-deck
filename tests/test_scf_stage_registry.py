import unittest

from scf_stage_registry import STAGE_REGISTRY, get_stage_spec


class StageRegistryTests(unittest.TestCase):
    def test_has_all_nine_stages(self):
        self.assertEqual([item.stage for item in STAGE_REGISTRY], [f"P{i}" for i in range(1, 10)])

    def test_p8_is_batched_and_p9_is_deterministic(self):
        self.assertEqual(get_stage_spec("p8").recovery, "batch")
        self.assertEqual(get_stage_spec("P9").recovery, "deterministic")

    def test_unknown_stage_fails_closed(self):
        with self.assertRaises(ValueError):
            get_stage_spec("P10")


if __name__ == "__main__":
    unittest.main()
