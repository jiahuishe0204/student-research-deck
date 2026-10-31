import json
import unittest

from scf_terminal_delivery import artifact_bodies, publish_final_delivery


class Store:
    def __init__(self):
        self.items = {}

    def upload(self, key, body, content_type):
        import hashlib
        raw = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        digest = hashlib.sha256(raw).hexdigest()
        self.items[key] = {"sha256": digest, "size_bytes": len(raw), "content_type": content_type,
                           "encryption": "AES256", "etag": "etag"}
        return type("Stored", (), {"sha256": digest, "size_bytes": len(raw), "etag": "etag"})()

    def stat(self, key):
        return self.items[key]

    def delete(self, key):
        self.items.pop(key, None)

    def stat_or_none(self, key):
        return self.items.get(key)


class Repository:
    def __init__(self):
        self.prepared = {}
        self.publish_calls = []

    def prepare_artifact(self, **values):
        self.prepared[values["kind"]] = values
        return {"status": "prepared"}

    def publish_artifact_and_complete(self, **values):
        self.publish_calls.append(values)
        status = "published" if len(self.publish_calls) == 3 else "uploaded"
        return {"status": status}


class ScfTerminalDeliveryTests(unittest.TestCase):
    def final_delivery(self):
        return {
            "final_report": {"title": "主题报告", "markdown": "# 报告\n内容", "used_evidence_ids": ["EV-1"]},
            "final_ppt": {"deck_title": "主题演示", "storyline": "故事线", "pages": [{"page_id": "SL-01"}]},
            "source_ids": ["SRC-1"], "evidence_ids": ["EV-1"], "open_issues": [],
        }

    def test_package_has_three_deterministic_private_artifact_bodies(self):
        bodies = artifact_bodies(self.final_delivery(), [{"source_id": "SRC-1", "title": "Study", "url": "https://example.org"}])
        self.assertEqual(set(bodies), {"report", "ppt_content", "references"})
        self.assertEqual(bodies["report"][0], "# 报告\n内容")
        refs = json.loads(bodies["references"][0])
        self.assertEqual(refs["source_ids"], ["SRC-1"])
        self.assertEqual(refs["sources"][0]["title"], "Study")

    def test_completion_waits_until_all_three_artifacts_are_verified(self):
        repository, store = Repository(), Store()
        result = publish_final_delivery(
            object(), {"task_id": "TASK-12345678", "completion_status": "partial",
                       "final_delivery": self.final_delivery(),
                       "source_records": [{"source_id": "SRC-1", "title": "Study"}]},
            repository=repository, artifact_store=store,
        )
        self.assertEqual(result, {"status": "published", "completion_status": "partial",
                                  "artifact_kinds": ["ppt_content", "references", "report"]})
        self.assertEqual(len(repository.publish_calls), 3)
        self.assertEqual([call["completion_status"] for call in repository.publish_calls], ["partial"] * 3)
        self.assertEqual(len(store.items), 3)

    def test_empty_report_or_deck_is_rejected_before_any_upload(self):
        bad = self.final_delivery()
        bad["final_ppt"]["pages"] = []
        with self.assertRaisesRegex(ValueError, "演示逐页内容为空"):
            artifact_bodies(bad, [])


if __name__ == "__main__":
    unittest.main()
