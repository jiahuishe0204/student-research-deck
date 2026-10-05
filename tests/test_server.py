import unittest

import server
import retrieval


class ValidationTests(unittest.TestCase):
    def test_valid_intent(self):
        value = {
            "domain": "life_science",
            "normalized_topic": "CRISPR分子诊断",
            "scope_hint": "聚焦主要技术路线",
            "tier": "fast",
            "assumptions": [],
            "need_clarification": False,
            "clarification_question": None,
            "confirmation_text": "将梳理主要技术路线",
        }
        self.assertEqual(server.validate_intent(value), value)

    def test_intent_rejects_extra_field(self):
        with self.assertRaises(ValueError):
            server.validate_intent({"unexpected": True})

    def test_plan_question_count(self):
        value = {
            "research_scope": "scope",
            "exclusions": [],
            "questions": [{"question_id": str(i), "question": "q", "evidence_needs": []} for i in range(3)],
            "search_concepts": {},
            "source_plan": [],
            "selection_criteria": [],
            "stop_conditions": [],
            "report_outline": [],
            "ppt_story_arc": [],
            "risks": [],
        }
        self.assertEqual(server.validate_plan(value), value)
        value["questions"] = value["questions"][:2]
        with self.assertRaises(ValueError):
            server.validate_plan(value)

    def test_source_keys_prefer_doi_then_pmid(self):
        self.assertEqual(retrieval.normalized_key({"doi": "10.1/ABC", "pmid": "123"}), "doi:10.1/abc")
        self.assertEqual(retrieval.normalized_key({"doi": "", "pmid": "123"}), "pmid:123")

    def test_plan_rejects_object_source_plan(self):
        value = {
            "research_scope": "scope", "exclusions": [],
            "questions": [{"question_id": str(i), "question": "q", "evidence_needs": []} for i in range(3)],
            "search_concepts": {}, "source_plan": {"sources": []}, "selection_criteria": [],
            "stop_conditions": [], "report_outline": [], "ppt_story_arc": [], "risks": [],
        }
        with self.assertRaises(ValueError):
            server.validate_plan(value)

    def test_screen_rejects_invented_source(self):
        value = {
            "screening_version": "1.0", "topic": "topic",
            "decisions": [{"source_id": "SRC-2", "status": "keep", "question_ids": ["Q1"], "intended_uses": ["overview"], "reason": "relevant", "priority": "high", "relevance_score": 0.9, "evidence_type": "systematic_review", "flags": []}],
            "summary": {"candidate_count": 1, "keep_count": 1, "reserve_count": 0, "drop_count": 0, "open_issues": []},
        }
        with self.assertRaises(ValueError):
            server.validate_screen(value, ["SRC-1"])

    def test_evidence_rejects_cross_source_record(self):
        value = {
            "evidence_version": "1.0", "source_id": "SRC-1", "extraction_status": "extracted", "reading_scope": "abstract",
            "evidence_records": [{"evidence_id": "EV-1", "source_id": "SRC-2", "question_ids": ["Q1"], "fact": "fact", "excerpt": "text", "locator": "abstract", "evidence_type": "comparison", "conditions": [], "limitations": []}],
            "figure_records": [], "no_extractable_reason": None,
        }
        with self.assertRaises(ValueError):
            server.validate_evidence(value, "SRC-1")

    def test_evidence_cannot_claim_full_text_from_abstract(self):
        value = {
            "evidence_version": "1.0", "source_id": "SRC-1", "extraction_status": "extracted", "reading_scope": "full_text",
            "evidence_records": [], "figure_records": [], "no_extractable_reason": None,
        }
        with self.assertRaises(ValueError):
            server.validate_evidence(value, "SRC-1", "abstract")

    def test_report_rejects_unknown_evidence(self):
        value = {"report_version":"1.0","report_title":"title","report_markdown":"body","used_evidence_ids":["EV-2"],"figure_recommendations":[],"status":"draft","open_issues":[]}
        with self.assertRaises(ValueError):
            server.validate_report(value, ["EV-1"])

    def test_ppt_rejects_unknown_figure(self):
        value = {"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","purpose":"purpose","on_slide_text":[],"visual_suggestion":"none","speaker_notes":"notes","evidence_ids":["EV-1"],"figure_refs":[{"figure_id":"FIG-2","source_id":"SRC-1","locator":"figure 1","intended_use":"show","reuse_status":"unknown"}]}]}
        with self.assertRaises(ValueError):
            server.validate_ppt(value, ["EV-1"], ["FIG-1"])

    def test_claims_reject_unknown_evidence(self):
        value = {"claim_set_version":"1.0","claims":[{"claim_id":"CL-1","location_type":"report_section","section_or_page_id":"s1","original_text":"text","atomic_claim":"claim","claim_type":"other","cited_evidence_ids":["EV-2"],"risk_level":"low"}],"extraction_notes":[]}
        with self.assertRaises(ValueError):
            server.validate_claims(value, ["EV-1"])

    def test_unsupported_claim_must_be_removed(self):
        value = {"verification_version":"1.0","results":[{"claim_id":"CL-1","source_identity":{"matched":True,"source_ids":["SRC-1"]},"support_status":"unsupported","issue_codes":["evidence_missing"],"explanation":"not supported","action":"keep","revised_claim":None,"valid_evidence_ids":[]}],"summary":{"supported":0,"partially_supported":0,"unsupported":1,"cannot_determine":0,"high_risk_remaining":0}}
        with self.assertRaises(ValueError):
            server.validate_verification(value, ["CL-1"], ["EV-1"])


if __name__ == "__main__":
    unittest.main()
