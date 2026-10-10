import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ResearchFramingTests(unittest.TestCase):
    def test_benchmark_covers_four_distinct_research_archetypes(self):
        benchmark = json.loads((ROOT / "tests/fixtures/research-framing-benchmark.json").read_text(encoding="utf-8"))
        cases = benchmark["cases"]
        self.assertEqual(len(cases), 4)
        self.assertEqual(len({item["id"] for item in cases}), 4)
        self.assertTrue(all(len(item["required_dimensions"]) >= 7 for item in cases))
        self.assertTrue(all(item["forbidden_template_terms"] for item in cases))

    def test_prompts_define_capability_boundaries_and_dynamic_structure(self):
        p1 = (ROOT / "prompts/P1-intent.md").read_text(encoding="utf-8")
        p2 = (ROOT / "prompts/P2-plan.md").read_text(encoding="utf-8")
        for term in ("不得检索", "中心问题", "聚焦工作标题", "排除说明"):
            self.assertIn(term, p1)
        for term in ("研究原型", "不得预写答案", "研究设计", "聚焦工作标题", "核心判断", "相邻方向", "快速版减少"):
            self.assertIn(term, p2)

    def test_ppt_prompt_separates_spoken_story_from_internal_audit(self):
        p6 = (ROOT / "prompts/P6-ppt.md").read_text(encoding="utf-8")
        for term in ("现场可以直接说出口", "学术答辩稿", "不是聊天式解说", "准确术语", "代表性数据", "集中放在专门页面", "不得为了流畅而虚构"):
            self.assertIn(term, p6)
        for casual_phrase in ("这一页想说明", "我们先看", "那这些", "刚才讲了", "这一页告诉我们"):
            self.assertIn(casual_phrase, p6)


if __name__ == "__main__":
    unittest.main()
