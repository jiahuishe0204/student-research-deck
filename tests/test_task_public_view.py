import unittest

from task_public_view import delivery_view, progress_view


class TaskPublicViewTests(unittest.TestCase):
    def task(self, status="active", artifacts=None):
        return {"topic": "慢性植入神经接口", "tier": "fast", "status": status,
                "current_stage": "P4", "updated_at": "2026-10-15T00:00:00+00:00",
                "artifacts": artifacts or {}, "events": [{"payload": {"private": "internal"}}]}

    def test_progress_uses_real_saved_stage_without_internal_payload(self):
        view = progress_view(self.task())
        self.assertEqual(view["title"], "整理证据")
        self.assertFalse(view["delivery_available"])
        self.assertNotIn("events", view)
        self.assertNotIn("private", str(view))

    def test_delivery_requires_completed_final_report_and_ppt(self):
        final = {"final_delivery": {"data": {"final_report": {"title": "报告", "markdown": "# 报告"},
                                              "final_ppt": {"deck_title": "汇报", "pages": [{"title": "第一页"}]},
                                              "change_log": [{"internal": True}]}}}
        with self.assertRaisesRegex(ValueError, "尚未完成"):
            delivery_view(self.task(artifacts=final))
        view = delivery_view(self.task("completed", final))
        self.assertEqual(view["ppt"]["pages"][0]["title"], "第一页")
        self.assertNotIn("change_log", view)


if __name__ == "__main__":
    unittest.main()
