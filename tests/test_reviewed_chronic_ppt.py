"""Regression checks for the human-reviewed, customer-readable chronic PPT sample."""

import re
import unittest
from pathlib import Path

from workflow_validation import validate_presentation_voice


SAMPLE = Path(__file__).resolve().parents[1] / "docs" / "验证稿-慢性植入神经接口-PPT内容包.md"


def reviewed_pages():
    markdown = SAMPLE.read_text(encoding="utf-8")
    pages = []
    for match in re.finditer(r"(?ms)^## 第 (\d+) 页｜([^\n]+)\n(.*?)(?=^## 第 |\Z)", markdown):
        body = match.group(3)
        bullets = re.findall(r"(?m)^- (.+)$", body.split("配图建议：", 1)[0])
        notes = body.split("讲稿：", 1)[1].split("来源：", 1)[0].strip()
        pages.append({"page_id": match.group(1), "title": match.group(2),
                      "purpose": "科学修订稿", "on_slide_text": bullets, "speaker_notes": notes})
    return pages


class ReviewedChronicPptTests(unittest.TestCase):
    def test_complete_reviewed_deck_passes_customer_readability_gate(self):
        pages = reviewed_pages()
        self.assertEqual(len(pages), 12)
        self.assertEqual(validate_presentation_voice(pages), pages)

    def test_review_keeps_three_evidence_boundaries_across_fields(self):
        pages = {page["page_id"]: page for page in reviewed_pages()}
        self.assertIn("单项研究", pages["9"]["title"])
        self.assertNotIn("优于商用金属电极", pages["9"]["title"])
        self.assertIn("比较条件、样本量和统计方法", " ".join(pages["9"]["on_slide_text"]))
        self.assertIn("不能据此断定", pages["10"]["speaker_notes"])
        self.assertNotIn("表明其电荷注入效率优于", pages["10"]["speaker_notes"])
        self.assertIn("不能直接证明批次间", " ".join(pages["11"]["on_slide_text"]))
        self.assertFalse(any(item.endswith(("，", "、")) for item in pages["11"]["on_slide_text"]))


if __name__ == "__main__":
    unittest.main()
