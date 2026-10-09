import unittest
from io import BytesIO
from unittest.mock import patch

import server
import retrieval


class ValidationTests(unittest.TestCase):
    def test_rate_limiter_blocks_after_configured_limit(self):
        limiter = server.RateLimiter(limit=2, window_seconds=60)
        self.assertTrue(limiter.allow("same-task"))
        self.assertTrue(limiter.allow("same-task"))
        self.assertFalse(limiter.allow("same-task"))

    def test_rate_limiter_removes_expired_keys(self):
        now = [0]
        limiter = server.RateLimiter(limit=2, window_seconds=10, clock=lambda: now[0])
        self.assertTrue(limiter.allow("old"))
        now[0] = 11
        self.assertTrue(limiter.allow("new"))
        self.assertNotIn("old", limiter.events)

    def test_request_path_ignores_query_string(self):
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/search?trace=1"
        self.assertEqual(handler.request_path(), "/api/search")

    def test_read_json_rejects_non_object(self):
        handler = object.__new__(server.AppHandler)
        handler.headers = {"Content-Length": "2"}
        handler.rfile = BytesIO(b"[]")
        with self.assertRaisesRegex(ValueError, "JSON 对象"):
            handler.read_json()

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

    def test_search_all_includes_epo_records_when_configured(self):
        class FakeEPO:
            def search(self, query, limit):
                self.query = query
                return [{"source": "EPO OPS", "source_id": "EPO:EP.1.A1", "patent_id": "EP.1.A1", "pmid": "", "doi": "", "title": "Patent", "abstract": "", "authors": [], "journal": "", "year": "", "url": "https://example.invalid", "access": "patent_bibliographic_metadata"}]
        epo = FakeEPO()
        original = (retrieval.search_pubmed, retrieval.search_europe_pmc, retrieval.search_crossref)
        retrieval.search_pubmed = retrieval.search_europe_pmc = retrieval.search_crossref = lambda query, limit: []
        try:
            output = retrieval.search_all('"CRISPR diagnostics" OR "Cas12 detection"', per_source=4, epo_client=epo, epo_query="CRISPR diagnostics Cas12 detection")
        finally:
            retrieval.search_pubmed, retrieval.search_europe_pmc, retrieval.search_crossref = original
        self.assertEqual(output["records"][0]["source_id"], "EPO:EP.1.A1")
        self.assertEqual(epo.query, "CRISPR diagnostics Cas12 detection")

    def test_europe_pmc_full_text_keeps_figure_locator(self):
        xml = b'<article><body><sec><p>Full text result.</p><fig id="F1"><label>Fig. 1</label><caption><p>Valve calcification pathway.</p></caption></fig></sec></body></article>'
        record = {"source": "Europe PMC", "source_id": "PMC:123", "pmcid": "PMC123", "access": "full_text"}
        with patch("retrieval.fetch_url_bytes", return_value=xml):
            hydrated = retrieval.hydrate_europe_pmc_full_text(record)
        self.assertIn("Full text result", hydrated["full_text"])
        self.assertEqual(hydrated["figure_candidates"][0]["locator"], "PMC123, Fig. 1")
        self.assertIn("/figure/F1", hydrated["figure_candidates"][0]["article_figure_url"])

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

    def test_screen_recomputes_summary_without_model_retry(self):
        value = {
            "screening_version": "1.0", "topic": "topic",
            "decisions": [{"source_id": "SRC-1", "status": "keep", "question_ids": ["Q1"], "intended_uses": ["overview"], "reason": "relevant", "priority": "high", "relevance_score": 0.9, "evidence_type": "systematic_review", "flags": []}],
            "summary": {"candidate_count": 99, "keep_count": 0, "reserve_count": 7, "drop_count": 4, "open_issues": []},
        }
        result = server.validate_screen(value, ["SRC-1"], keep_max=1)
        self.assertEqual(result["summary"]["candidate_count"], 1)
        self.assertEqual(result["summary"]["keep_count"], 1)
        self.assertEqual(result["summary"]["reserve_count"], 0)

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
        value = {"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","purpose":"purpose","on_slide_text":[],"visual_suggestion":"none","speaker_notes":"notes","evidence_ids":["EV-1"],"figure_refs":[{"figure_id":"FIG-2","source_id":"SRC-1","locator":"figure 1","intended_use":"show","reuse_status":"unknown"}],"source_citations":[]}]}
        with self.assertRaises(ValueError):
            server.validate_ppt(value, ["EV-1"], ["FIG-1"])

    def test_ppt_rejects_overlong_slide_text(self):
        value = {"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","purpose":"purpose","on_slide_text":["字" * 141],"visual_suggestion":"none","speaker_notes":"notes","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]}
        with self.assertRaisesRegex(Exception, "单条上屏文字"):
            server.validate_ppt(value, ["EV-1"], [])

    def test_claims_reject_unknown_evidence(self):
        value = {"claim_set_version":"1.0","claims":[{"claim_id":"CL-1","location_type":"report_section","section_or_page_id":"s1","original_text":"text","atomic_claim":"claim","claim_type":"other","cited_evidence_ids":["EV-2"],"risk_level":"low"}],"extraction_notes":[]}
        with self.assertRaises(ValueError):
            server.validate_claims(value, ["EV-1"])

    def test_unsupported_claim_must_be_removed(self):
        value = {"verification_version":"1.0","results":[{"claim_id":"CL-1","source_identity":{"matched":True,"source_ids":["SRC-1"]},"support_status":"unsupported","issue_codes":["evidence_missing"],"explanation":"not supported","action":"keep","revised_claim":None,"valid_evidence_ids":[]}],"summary":{"supported":0,"partially_supported":0,"unsupported":1,"cannot_determine":0,"high_risk_remaining":0}}
        with self.assertRaises(ValueError):
            server.validate_verification(value, ["CL-1"], ["EV-1"])

    def test_partial_support_requires_real_revision(self):
        value = {"verification_version":"1.0","results":[{"claim_id":"CL-1","source_identity":{"matched":True,"source_ids":["SRC-1"]},"support_status":"partially_supported","issue_codes":["tone_overstatement"],"explanation":"too strong","action":"revise","revised_claim":"原句","valid_evidence_ids":["EV-1"]}],"summary":{"supported":0,"partially_supported":1,"unsupported":0,"cannot_determine":0,"high_risk_remaining":0}}
        claims = [{"claim_id":"CL-1","atomic_claim":"原句"}]
        with self.assertRaises(ValueError):
            server.validate_verification(value, ["CL-1"], ["EV-1"], claims)

    def test_final_change_log_must_apply_verification_actions(self):
        value = {"delivery_version":"1.0","evidence_version":"1.0","final_report":{"title":"title","markdown":"body","used_evidence_ids":["EV-1"]},"final_ppt":{"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","purpose":"","on_slide_text":[],"visual_suggestion":"","speaker_notes":"","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]},"verification_note":"checked","open_issues":[],"source_ids":["SRC-1"],"evidence_ids":["EV-1"],"change_log":[{"claim_id":"CL-1","action":"kept","reason":"wrong"}]}
        verification = {"results": [{"claim_id": "CL-1", "action": "remove"}]}
        with self.assertRaisesRegex(ValueError, "未落实"):
            server.validate_final(value, ["CL-1"], ["SRC-1"], ["EV-1"], verification)

    def test_workflow_service_is_separate_from_http_handler(self):
        self.assertFalse(hasattr(server, "deepseek_json"))
        self.assertTrue(hasattr(server, "WorkflowService"))

    def test_http_handler_does_not_build_stage_contracts_or_generate_directly(self):
        source = (server.ROOT / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("load_contract(", source)
        self.assertNotIn("workflow.generate(", source)

    def test_usage_endpoint_is_task_scoped(self):
        source = (server.ROOT / "server.py").read_text(encoding="utf-8")
        usage_branch = source.index('parts[3] == "usage"')
        access_check = source.rfind("self.require_task_access(task_id)", 0, usage_branch)
        self.assertGreater(access_check, source.index("def do_GET"))


if __name__ == "__main__":
    unittest.main()
