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
        for term in ("不得检索", "不得检索", "主问题", "展开维度"):
            self.assertIn(term, p1)
        for term in ("研究原型", "不得预写答案", "研究设计", "报告目录原样复制", "快速版减少"):
            self.assertIn(term, p2)


if __name__ == "__main__":
    unittest.main()
