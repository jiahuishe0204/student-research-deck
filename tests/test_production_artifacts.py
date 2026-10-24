import json
import unittest

from production_artifacts import build_final_artifacts, publish_final_artifacts


class Lifecycle:
    def __init__(self): self.calls = []
    def publish(self, **values): self.calls.append(values); return {"status": "published", **values}


class ProductionArtifactsTests(unittest.TestCase):
    def setUp(self):
        self.final = {"final_report": {"markdown": "# Report\nBody"},
                      "final_ppt": {"deck_title": "Deck", "storyline": "Story",
                                    "pages": [{"page_id": "SL-01", "title": "One"}]}}
        self.payload = {"source_records": [{"source_id": "S1"}],
                        "evidence_records": [{"evidence_id": "E1"}], "evidence_version": "1.0"}

    def test_builds_three_deterministic_private_artifacts(self):
        artifacts = build_final_artifacts("TASK-12345678", self.final, self.payload)
        self.assertEqual([item["kind"] for item in artifacts], ["report", "ppt_content", "references"])
        self.assertEqual([item["extension"] for item in artifacts], ["md", "json", "json"])
        self.assertTrue(artifacts[0]["body"].endswith("\n"))
        self.assertEqual(json.loads(artifacts[2]["body"])["sources"][0]["source_id"], "S1")

    def test_publishes_only_after_complete_p9_shape(self):
        lifecycle = Lifecycle()
        published = publish_final_artifacts(lifecycle, "TASK-12345678", self.final, self.payload)
        self.assertEqual(len(published), 3)
        self.assertEqual(len({item["artifact_id"] for item in lifecycle.calls}), 3)
        with self.assertRaises(ValueError):
            build_final_artifacts("TASK-12345678", {"final_report": {}}, self.payload)


if __name__ == "__main__":
    unittest.main()
