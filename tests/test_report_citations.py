import unittest

from report_citations import render_linked_report


class ReportCitationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [
            {"evidence_id": "EV::S1::001", "source_id": "S1"},
            {"evidence_id": "EV::S1::002", "source_id": "S1"},
        ]
        self.sources = [{"source_id": "S1", "authors": ["Li A", "Zhang B"], "title": "Trial title",
                         "journal": "J Clin Oncol", "year": "2026", "volume": "44", "pages": "1-9",
                         "url": "https://example.org/article"}]

    def test_evidence_ids_become_one_clickable_vancouver_reference(self):
        rendered = render_linked_report("研究发现一[EV::S1::001]，发现二[EV::S1::002]。", self.evidence, self.sources)
        self.assertEqual(rendered.count("[1](https://example.org/article)"), 2)
        self.assertIn("[1] Li A, Zhang B. Trial title. J Clin Oncol. 2026;44:1-9.", rendered)
        self.assertIn("## 参考文献", rendered)

    def test_missing_evidence_refuses_customer_delivery(self):
        with self.assertRaisesRegex(ValueError, "未保存的证据"):
            render_linked_report("错误引用[EV::S2::001]。", self.evidence, self.sources)

    def test_unverified_numeric_bibliography_refuses_conversion(self):
        with self.assertRaisesRegex(ValueError, "自带参考文献表"):
            render_linked_report("报告[EV::S1::001]\n## 参考文献\n[1] guessed", self.evidence, self.sources)

    def test_verified_figure_is_linked_with_reuse_status(self):
        rendered = render_linked_report(
            "研究发现[EV::S1::001]。", self.evidence, self.sources,
            [{"figure_id": "FIG::S1::001", "placement": "机制章节", "purpose": "展示通路", "reuse_status": "permission_required"}],
            [{"figure_id": "FIG::S1::001", "locator": "Fig 1 https://example.org/article/fig1", "reuse_status": "permission_required"}],
        )
        self.assertIn("## 推荐配图", rendered)
        self.assertIn("[查看原文 Figure 1](https://example.org/article/fig1)", rendered)
        self.assertIn("复用状态：嵌入前需取得许可", rendered)

    def test_figure_reuse_status_cannot_be_improved_by_model(self):
        with self.assertRaisesRegex(ValueError, "许可状态不一致"):
            render_linked_report(
                "研究发现[EV::S1::001]。", self.evidence, self.sources,
                [{"figure_id": "FIG::S1::001", "reuse_status": "allowed"}],
                [{"figure_id": "FIG::S1::001", "locator": "https://example.org/fig1", "reuse_status": "permission_required"}],
            )

    def test_figure_source_cannot_be_reassigned_by_model(self):
        with self.assertRaisesRegex(ValueError, "来源归属"):
            render_linked_report(
                "研究发现[EV::S1::001]。", self.evidence, self.sources,
                [{"figure_id": "FIG::S1::001", "source_id": "S2", "reuse_status": "unknown"}],
                [{"figure_id": "FIG::S1::001", "source_id": "S1", "article_figure_url": "https://example.org/fig1", "reuse_status": "unknown"}],
            )

    def test_figure_must_belong_to_a_saved_source(self):
        with self.assertRaisesRegex(ValueError, "未保存的来源"):
            render_linked_report(
                "研究发现[EV::S1::001]。", self.evidence, self.sources,
                [{"figure_id": "FIG::S2::001", "source_id": "S2", "reuse_status": "unknown"}],
                [{"figure_id": "FIG::S2::001", "source_id": "S2", "article_figure_url": "https://example.org/fig2", "reuse_status": "unknown"}],
            )

    def test_figure_uses_structured_url_and_deduplicates_same_image(self):
        recommendation = {"figure_id": "FIG::S1::001", "placement": "结果", "purpose": "解释数据", "reuse_status": "unknown"}
        rendered = render_linked_report(
            "研究发现[EV::S1::001]。", self.evidence, self.sources,
            [recommendation, recommendation],
            [{"figure_id": "FIG::S1::001", "locator": "PMC123, Fig 1", "article_figure_url": "https://example.org/fig1", "reuse_status": "unknown"}],
        )
        self.assertEqual(rendered.count("[查看原文 Figure 1](https://example.org/fig1)"), 1)

    def test_figure_purpose_with_terminal_stop_does_not_double_punctuate(self):
        rendered = render_linked_report(
            "研究发现[EV::S1::001]。", self.evidence, self.sources,
            [{"figure_id": "FIG::S1::001", "placement": "机制", "purpose": "展示研究设计。", "reuse_status": "unknown"}],
            [{"figure_id": "FIG::S1::001", "label": "Figure 1", "article_figure_url": "https://example.org/fig1", "reuse_status": "unknown"}],
        )
        self.assertIn("展示研究设计。[查看原文 Figure 1]", rendered)
        self.assertNotIn("。。", rendered)

    def test_internal_outline_markers_removed_but_biological_m2_kept(self):
        rendered = render_linked_report(
            "分析材料性质（M2），观察巨噬细胞向 M2 极化[EV::S1::001][EV::S1::002]。",
            self.evidence, self.sources,
        )
        self.assertNotIn("（M2）", rendered)
        self.assertIn("巨噬细胞向 M2 极化", rendered)
        self.assertEqual(rendered.count("[1](https://example.org/article)"), 1)

    def test_revised_sentence_does_not_leave_comma_after_footnote(self):
        rendered = render_linked_report(
            "第一项结论。[EV::S1::001]，第二项结论。[EV::S1::002]。",
            self.evidence, self.sources,
        )
        self.assertIn("第一项结论。[1](https://example.org/article)第二项结论。", rendered)
        self.assertNotIn(")]，", rendered)
