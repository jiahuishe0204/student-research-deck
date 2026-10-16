import copy
import unittest

from ppt_boundary_repair import repair_verified_pages
from workflow_service import WorkflowService


class AutomaticBoundaryRepairTests(unittest.TestCase):
    def sample(self):
        page = {"page_id": "P1", "title": "实验结果", "purpose": "说明测量结果",
                "on_slide_text": ["电压降低，电荷注入效率优于Pt"],
                "speaker_notes": "该结果表明电荷注入效率优于Pt。",
                "visual_suggestion": "效率优势图", "evidence_ids": ["EV-1"],
                "figure_refs": [], "source_citations": []}
        claim = {"claim_id": "C1", "location_type": "ppt_slide", "section_or_page_id": "P1",
                 "original_text": page["on_slide_text"][0], "atomic_claim": page["on_slide_text"][0],
                 "claim_type": "comparison", "cited_evidence_ids": ["EV-1"], "risk_level": "high"}
        result = {"claim_id": "C1", "action": "revise", "support_status": "partially_supported",
                  "revised_claim": "固定电流、n=1条件下电压降低，不等同于电荷注入效率的直接比较。",
                  "valid_evidence_ids": ["EV-1"], "explanation": "测量指标不能外推"}
        return page, claim, result

    def test_public_p9_automatically_rebuilds_notes_after_slide_revision(self):
        page, claim, result = self.sample()
        service = WorkflowService("", None, "", {}, model_client=lambda *a, **k: self.fail("must not call model"))
        output, usage = service.assemble_final_deterministic(
            {"results": [result]}, {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"]},
            {"deck_title": "汇报", "storyline": "研究结果", "pages": [page]},
            [claim], ["SRC-1"], ["EV-1"]
        )
        fixed = output["final_ppt"]["pages"][0]
        self.assertEqual(fixed["speaker_notes"], result["revised_claim"])
        self.assertNotIn("效率优于", str(fixed))
        self.assertEqual(usage["total_tokens"], 0)
        self.assertIn("自动重建", output["verification_note"])

    def test_title_and_truncated_bullet_rebuilt_from_accepted_claim_not_original_notes(self):
        page, claim, result = self.sample()
        page.update(title="器件优于传统电极", on_slide_text=["测量值更高，但摘要未说明比较条件。", "配方影响形貌，"], speaker_notes="批次一致性已经证实。")
        claim["original_text"] = "配方影响形貌"
        result.update(action="keep", support_status="supported", revised_claim=None)
        other = copy.deepcopy(page)
        other.update(page_id="P2", title="研究背景", on_slide_text=["背景"], speaker_notes="背景。")
        fixed, repairs = repair_verified_pages([page, other], [claim], {"results": [result]})
        self.assertEqual(fixed[0]["on_slide_text"], ["配方影响形貌"])
        self.assertEqual(fixed[0]["speaker_notes"], "配方影响形貌。")
        self.assertNotIn("批次一致性", str(fixed[0]))
        self.assertNotIn("优于", fixed[0]["title"])
        self.assertEqual(fixed[1], other)
        self.assertEqual(len(repairs), 1)

    def test_missing_valid_citation_does_not_turn_into_automatic_fact(self):
        page, claim, result = self.sample()
        page["on_slide_text"] = [result["revised_claim"]]
        result["valid_evidence_ids"] = ["WRONG"]
        with self.assertRaisesRegex(ValueError, "原引用"):
            repair_verified_pages([page], [claim], {"results": [result]})

    def test_removed_and_unknown_claims_are_absent_from_rebuilt_page(self):
        page, claim, result = self.sample()
        page["on_slide_text"] = [result["revised_claim"]]
        removed = dict(claim, claim_id="C2", original_text="材料已能治愈疾病")
        unknown = dict(claim, claim_id="C3", original_text="长期安全已确定")
        fixed, _ = repair_verified_pages([page], [claim, removed, unknown], {"results": [result,
            {"claim_id": "C2", "action": "remove", "support_status": "unsupported"},
            {"claim_id": "C3", "action": "mark_unverified", "support_status": "cannot_determine"}]})
        self.assertNotIn("治愈", str(fixed))
        self.assertNotIn("安全已确定", str(fixed))
