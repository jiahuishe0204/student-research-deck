import copy
import json
import unittest
from pathlib import Path

from contracts import ContractError, load_contract, validate_stage_output

ROOT = Path(__file__).resolve().parents[1]


SAMPLES = {
    "P3": {"screening_version":"1.0","topic":"CRISPR诊断","decisions":[{"source_id":"SRC-1","status":"keep","question_ids":["Q1"],"intended_uses":["技术路线"],"reason":"直接回答研究问题","priority":"high","relevance_score":0.9,"evidence_type":"systematic_review","flags":[]}],"summary":{"candidate_count":1,"keep_count":1,"reserve_count":0,"drop_count":0,"open_issues":[]}},
    "P4": {"evidence_version":"1.0","source_id":"SRC-1","extraction_status":"extracted","reading_scope":"abstract","evidence_records":[{"evidence_id":"EV-1","source_id":"SRC-1","question_ids":["Q1"],"fact":"研究比较了两种检测路线","excerpt":"Two routes were compared.","locator":"abstract/results","evidence_type":"comparison","conditions":["体外样本"],"limitations":["仅摘要"]}],"figure_records":[],"no_extractable_reason":None},
    "P5": {"report_version":"1.0","report_title":"CRISPR诊断调研","report_markdown":"# CRISPR诊断调研\n\n正文。","used_evidence_ids":["EV-1"],"figure_recommendations":[],"status":"draft","open_issues":[]},
    "P6": {"deck_title":"CRISPR诊断","storyline":"问题—路线—比较—结论","pages":[{"page_id":"SL-1","navigation_title":"诊断路线","title":"技术路线","purpose":"解释路线","on_slide_text":["路线A"],"visual_suggestion":"流程图","speaker_notes":"依据EV-1说明。","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[{"source_id":"SRC-1","short_vancouver":"Smith J, et al. Example J. 2024;1:1-2."}]}]},
    "P7": {"claim_set_version":"1.0","claims":[{"claim_id":"CL-1","location_type":"report_section","section_or_page_id":"技术路线","original_text":"两种路线被比较。","atomic_claim":"研究比较了两种路线。","claim_type":"comparison","cited_evidence_ids":["EV-1"],"risk_level":"medium"}],"extraction_notes":[]},
    "P8": {"verification_version":"1.0","results":[{"claim_id":"CL-1","source_identity":{"matched":True,"source_ids":["SRC-1"]},"support_status":"supported","issue_codes":["none"],"explanation":"对象和比较关系一致","action":"keep","revised_claim":None,"valid_evidence_ids":["EV-1"]}],"summary":{"supported":1,"partially_supported":0,"unsupported":0,"cannot_determine":0,"high_risk_remaining":0}},
    "P9": {"delivery_version":"1.0","evidence_version":"1.0","final_report":{"title":"CRISPR诊断调研","markdown":"# 终稿","used_evidence_ids":["EV-1"]},"final_ppt":{"deck_title":"CRISPR诊断","storyline":"问题—路线—结论","pages":[{"page_id":"SL-1","navigation_title":"诊断路线","title":"技术路线","purpose":"解释路线","on_slide_text":["两种路线"],"visual_suggestion":"流程图","speaker_notes":"研究比较了两种路线。","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[{"source_id":"SRC-1","short_vancouver":"Smith J, et al. Example J. 2024;1:1-2."}]}]},"verification_note":"全部声明已核验。","open_issues":[],"source_ids":["SRC-1"],"evidence_ids":["EV-1"],"change_log":[{"claim_id":"CL-1","action":"kept","reason":"证据充分"}]}
}


class ContractTests(unittest.TestCase):
    def test_p3_to_p9_have_dedicated_contracts(self):
        registry = json.loads((ROOT / "config/prompt-stages.json").read_text(encoding="utf-8"))
        for entry in registry["stages"][2:]:
            self.assertNotEqual(entry["output_schema"], "schemas/generic-object.schema.json")
            self.assertTrue((ROOT / entry["output_schema"]).exists())

    def test_success_examples_are_accepted(self):
        for stage, sample in SAMPLES.items():
            with self.subTest(stage=stage):
                self.assertEqual(validate_stage_output(stage, sample), sample)

    def test_missing_required_field_is_rejected(self):
        for stage, sample in SAMPLES.items():
            broken = copy.deepcopy(sample)
            del broken[next(iter(load_contract(stage)["required"]))]
            with self.subTest(stage=stage), self.assertRaises(ContractError):
                validate_stage_output(stage, broken)

    def test_unknown_field_is_rejected(self):
        for stage, sample in SAMPLES.items():
            broken = copy.deepcopy(sample)
            broken["invented_field"] = True
            with self.subTest(stage=stage), self.assertRaises(ContractError):
                validate_stage_output(stage, broken)

    def test_invalid_enum_is_rejected(self):
        broken = copy.deepcopy(SAMPLES["P8"])
        broken["results"][0]["support_status"] = "probably_supported"
        with self.assertRaises(ContractError):
            validate_stage_output("P8", broken)


if __name__ == "__main__":
    unittest.main()
