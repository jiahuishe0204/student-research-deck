import unittest

from contracts import ContractError
from quality_benchmark import score_ppt_density, score_verification
from workflow_validation import validate_presentation_voice, validate_report


class QualityBenchmarkTests(unittest.TestCase):
    def test_verification_score_flags_false_acceptance_and_unknown_evidence(self):
        gold = {"C1":{"support_status":"unsupported","action":"remove","required_issue":"source_mismatch","required_evidence":[],"required_terms":["不支持"]}}
        results = [{"claim_id":"C1","support_status":"supported","action":"keep","issue_codes":["none"],"valid_evidence_ids":["EV-X"],"explanation":"支持","revised_claim":None}]
        score = score_verification(results, gold, {"EV-1"})
        self.assertEqual(score["score"], 10)
        self.assertEqual(score["critical_errors"], ["C1"])
        self.assertEqual(score["hallucinated_evidence"], [("C1", "EV-X")])

    def test_ppt_density_reports_page_and_average_failures(self):
        pages = [{"page_id":"P1","on_slide_text":["字" * 90, "字" * 140],"speaker_notes":""}]
        result = score_ppt_density(pages, {"deck_average_max":180,"page_characters_max":220,"bullet_characters_max":80,"bullets_max":5,"speaker_notes_max":350})
        self.assertFalse(result["average_pass"])
        self.assertEqual(result["failed_pages"][0]["failures"], ["page_characters", "bullet_length"])

    def test_spoken_notes_reject_repeated_audit_language_on_ordinary_page(self):
        pages = [{"page_id":"P1","title":"核心机制","purpose":"解释机制","speaker_notes":"这条证据不足，另一条也未核实。"}]
        with self.assertRaises(ContractError):
            validate_presentation_voice(pages)

    def test_spoken_notes_allow_caveats_on_dedicated_limitations_page(self):
        pages = [{"page_id":"P9","title":"研究局限与下一步","purpose":"说明证据边界","speaker_notes":"部分证据不足，临床效果仍未核实。"}]
        self.assertEqual(validate_presentation_voice(pages), pages)

    def test_spoken_notes_reject_chatty_scaffolding_across_deck(self):
        pages = [
            {"page_id":"P1","title":"细胞来源","purpose":"解释来源","speaker_notes":"有了中心问题，我们先看细胞来源。"},
            {"page_id":"P2","title":"驱动机制","purpose":"解释机制","speaker_notes":"刚才讲了来源，下面讨论驱动机制。"},
        ]
        with self.assertRaises(ContractError):
            validate_presentation_voice(pages)

    def test_spoken_notes_allow_academic_defense_register(self):
        pages = [{
            "page_id":"P1", "title":"细胞来源", "purpose":"解释来源",
            "speaker_notes":"首先需要明确成骨样VICs的细胞来源。单细胞测序识别出过渡状态，谱系追踪进一步支持其主要来自驻留间质细胞。",
        }]
        self.assertEqual(validate_presentation_voice(pages), pages)

    def test_post_verification_readability_rejects_dangling_label_and_broken_punctuation(self):
        with self.assertRaises(ContractError):
            validate_presentation_voice([{"page_id":"P1","title":"结论","purpose":"总结","on_slide_text":["关键判断："],"speaker_notes":"结论。"}])
        with self.assertRaises(ContractError):
            validate_presentation_voice([{"page_id":"P1","title":"结论","purpose":"总结","on_slide_text":["有效结论"],"speaker_notes":"证据支持该判断。；仍需随访。。"}])

    def test_deep_report_requires_complete_sections_and_bounded_length(self):
        markdown = "# 报告\n## 执行摘要\n结论。\n## 研究问题与范围\n问题。\n## 方法与证据基础\n方法。\n## 主要发现\n" + ("研究结果支持这一判断[EV::SRC-1::001]。" * 150) + "\n## 综合结论\n结论。\n## 局限与下一步\n局限。"
        value = {"report_version":"1","report_title":"报告","report_markdown":markdown,"used_evidence_ids":["EV::SRC-1::001"],"figure_recommendations":[],"status":"draft","open_issues":[]}
        self.assertEqual(validate_report(value, ["EV::SRC-1::001"], "deep"), value)

    def test_deep_report_rejects_overlong_or_incomplete_delivery(self):
        value = {"report_version":"1","report_title":"报告","report_markdown":"正文" * 4000,"used_evidence_ids":[],"figure_recommendations":[],"status":"draft","open_issues":[]}
        with self.assertRaises(ContractError):
            validate_report(value, [], "deep")
