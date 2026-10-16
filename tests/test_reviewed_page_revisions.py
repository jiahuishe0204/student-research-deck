import unittest
from unittest.mock import patch

from reviewed_page_revisions import apply_reviewed_page_revisions


class ReviewedPageRevisionTests(unittest.TestCase):
    def setUp(self):
        self.delivery = {"final_ppt": {"pages": [{"page_id": "P1", "title": "旧标题", "on_slide_text": ["旧要点"],
                                                  "visual_suggestion": "旧图", "speaker_notes": "旧讲稿"}]},
                         "source_ids": ["S1"], "evidence_ids": ["E1"]}
        self.claims = [{"claim_id": "C1", "section_or_page_id": "P1"}]
        self.verification = {"results": [{"claim_id": "C1"}]}

    def test_exact_reviewed_edit_changes_only_target_and_revalidates(self):
        edit = {"page_id": "P1", "field": "title", "old": "旧标题", "new": "有条件的结论",
                "claim_ids": ["C1"], "reason": "核验结果要求限定范围"}
        with patch("reviewed_page_revisions.validate_final") as validate:
            result = apply_reviewed_page_revisions(self.delivery, [edit], self.claims, self.verification)
        self.assertEqual(result["final_ppt"]["pages"][0]["title"], "有条件的结论")
        self.assertEqual(self.delivery["final_ppt"]["pages"][0]["title"], "旧标题")
        validate.assert_called_once()

    def test_stale_text_or_unverified_claim_cannot_be_applied(self):
        edit = {"page_id": "P1", "field": "title", "old": "并非旧标题", "new": "新标题",
                "claim_ids": ["C1"], "reason": "审稿"}
        with self.assertRaisesRegex(ValueError, "原文不唯一或已发生变化"):
            apply_reviewed_page_revisions(self.delivery, [edit], self.claims, self.verification)
        edit["old"] = "旧标题"
        edit["claim_ids"] = ["C2"]
        with self.assertRaisesRegex(ValueError, "已核验的声明"):
            apply_reviewed_page_revisions(self.delivery, [edit], self.claims, self.verification)


if __name__ == "__main__":
    unittest.main()
