import unittest
from http import HTTPStatus
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import server
import retrieval


class ValidationTests(unittest.TestCase):
    def test_runtime_fingerprint_changes_when_validator_changes(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "prompts").mkdir()
            (root / "config" / "prompt-stages.json").write_text('{"global_prompt":"prompts/system.md","stages":[]}', encoding="utf-8")
            (root / "prompts" / "system.md").write_text("system", encoding="utf-8")
            for name in ("server.py", "workflow_service.py", "workflow_validation.py", "patsnap_mcp.py"):
                (root / name).write_text(name, encoding="utf-8")
            before = server.runtime_fingerprint(root)
            (root / "workflow_validation.py").write_text("changed", encoding="utf-8")
            self.assertNotEqual(before, server.runtime_fingerprint(root))

    def test_explicit_patsnap_mcp_provider_uses_only_mcp_key(self):
        client = server.create_patent_client(environ={
            "PATENT_PROVIDER": "patsnap_mcp_cn",
            "PATSNAP_MCP_API_KEY": "mcp-secret",
            "PATSNAP_API_KEY": "literature-secret",
        })
        self.assertIsInstance(client, server.PatsnapMCPClient)
        self.assertEqual(client.api_key, "mcp-secret")

    def test_explicit_patsnap_mcp_provider_fails_closed_without_mcp_key(self):
        with self.assertRaisesRegex(RuntimeError, "PATSNAP_MCP_API_KEY"):
            server.create_patent_client(environ={
                "PATENT_PROVIDER": "patsnap_mcp_cn",
                "PATSNAP_API_KEY": "literature-secret",
            })

    def test_epo_remains_an_explicit_rollback_provider(self):
        fallback = object()
        with patch.object(server.EPOClient, "from_environment", return_value=fallback):
            client = server.create_patent_client(environ={"PATENT_PROVIDER": "epo_ops"})
        self.assertIs(client, fallback)

    def test_delivery_endpoint_checks_task_access_before_reading(self):
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/tasks/TASK-test/delivery"
        handler.headers = {"X-Task-Token": "wrong"}
        reads = []
        handler.server = SimpleNamespace(task_store=SimpleNamespace(get_task=lambda task_id: reads.append(task_id)))
        handler.require_task_access = lambda task_id: (_ for _ in ()).throw(PermissionError("任务访问凭据无效"))
        replies = []
        handler.send_json = lambda status, value: replies.append((status, value))
        handler.do_GET()
        self.assertEqual(replies[0][0], 403)
        self.assertEqual(reads, [])

    def test_progress_endpoint_omits_saved_artifacts(self):
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/tasks/TASK-test/progress"
        handler.headers = {"X-Task-Token": "owner"}
        saved = {"status": "active", "current_stage": "P3", "updated_at": "now", "artifacts": {"secret": {"data": "private"}}}
        handler.server = SimpleNamespace(task_store=SimpleNamespace(get_task=lambda task_id: saved))
        handler.require_task_access = lambda task_id: task_id
        replies = []
        handler.send_json = lambda status, value: replies.append((status, value))
        handler.do_GET()
        self.assertEqual(replies[0][0], 200)
        self.assertNotIn("artifacts", replies[0][1]["data"])

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
            "topic_breadth": "focused",
            "direction_options": [],
            "need_clarification": False,
            "clarification_question": None,
            "confirmation_text": "将梳理主要技术路线",
        }
        self.assertEqual(server.validate_intent(value), value)

    def test_broad_intent_requires_clickable_directions(self):
        value = {
            "domain": "life_science", "normalized_topic": "心脏瓣膜钙化", "scope_hint": "需选择焦点",
            "tier": "deep", "assumptions": [], "topic_breadth": "broad",
            "direction_options": [
                {"direction_id": "D1", "title": "钙化机制", "focus": "重点梳理细胞与分子机制"},
                {"direction_id": "D2", "title": "干预策略", "focus": "重点梳理药物与材料干预"},
            ],
            "need_clarification": True, "clarification_question": "请选择一个本次最想展开的方向", "confirmation_text": None,
        }
        self.assertEqual(server.validate_intent(value), value)
        value["direction_options"] = value["direction_options"][:1]
        with self.assertRaisesRegex(ValueError, "2—4"):
            server.validate_intent(value)

    def test_plan_requires_saved_user_direction_and_ignores_forged_intent(self):
        saved = {
            "domain": "life_science", "normalized_topic": "导电水凝胶在神经电刺激调控中的应用",
            "scope_hint": "范围宽", "tier": "deep", "assumptions": [], "topic_breadth": "broad",
            "direction_options": [
                {"direction_id": "D1", "title": "神经损伤修复", "focus": "分析修复研究"},
                {"direction_id": "D2", "title": "慢性植入界面", "focus": "分析长期稳定性"},
            ],
            "need_clarification": True, "clarification_question": "请选择方向", "confirmation_text": None,
        }
        task = {"topic": saved["normalized_topic"], "tier": "deep", "artifacts": {"intent": {"data": saved}}}
        body = {"topic": task["topic"], "tier": "deep", "clarification": saved["scope_hint"],
                "intent": {**saved, "topic_breadth": "focused", "need_clarification": False}}
        with self.assertRaisesRegex(ValueError, "用户选择"):
            server.resolve_plan_request(task, body)
        with self.assertRaisesRegex(ValueError, "用户选择"):
            server.resolve_plan_request(task, {**body, "direction_id": "unknown"})
        topic, tier, clarification, intent = server.resolve_plan_request(task, {**body, "direction_id": "D2"})
        self.assertEqual((topic, tier), (task["topic"], "deep"))
        self.assertEqual(clarification, "慢性植入界面：分析长期稳定性")
        self.assertIs(intent, saved)

    def test_plan_requires_persisted_intent_even_if_request_forges_one(self):
        task = {"topic": "心脏瓣膜钙化", "tier": "deep", "artifacts": {}}
        with self.assertRaisesRegex(ValueError, "先完成并保存"):
            server.resolve_plan_request(task, {"topic": "心脏瓣膜钙化", "tier": "deep", "intent": {"topic_breadth": "focused"}})

    def test_plan_api_rejects_unselected_broad_topic_before_model_call(self):
        intent = {
            "domain": "life_science", "normalized_topic": "导电水凝胶在神经电刺激调控中的应用",
            "scope_hint": "范围宽", "tier": "deep", "assumptions": [], "topic_breadth": "broad",
            "direction_options": [
                {"direction_id": "D1", "title": "神经损伤修复", "focus": "分析修复研究"},
                {"direction_id": "D2", "title": "慢性植入界面", "focus": "分析长期稳定性"},
            ], "need_clarification": True, "clarification_question": "请选择方向", "confirmation_text": None,
        }
        calls = []
        task = {"topic": intent["normalized_topic"], "tier": "deep", "artifacts": {"intent": {"data": intent}}}
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/plan"
        handler.client_address = ("127.0.0.1", 1000)
        handler.server = SimpleNamespace(
            api_key="configured", rate_limiter=SimpleNamespace(allow=lambda key: True),
            task_store=SimpleNamespace(get_task=lambda task_id: task),
            workflow=SimpleNamespace(set_task_context=lambda task_id: None, create_plan=lambda *args: calls.append(args)),
        )
        handler.read_json = lambda: {"topic": task["topic"], "tier": "deep", "clarification": "范围宽"}
        handler.require_task_access = lambda: "TASK-test"
        responses = []
        handler.send_json = lambda status, value: responses.append((status, value))
        handler.do_POST()
        self.assertEqual(responses[0][0], 400)
        self.assertIn("用户选择", responses[0][1]["error"])
        self.assertEqual(calls, [])

    def test_intent_normalizes_single_assumption_without_paid_retry(self):
        value = {
            "domain": "life_science", "normalized_topic": "导电水凝胶", "scope_hint": "聚焦周围神经",
            "tier": "deep", "assumptions": "默认讨论周围神经",
            "topic_breadth": "focused", "direction_options": [], "need_clarification": False,
            "clarification_question": None, "confirmation_text": "按该主题继续",
        }
        normalized = server.validate_intent(value)
        self.assertEqual(normalized["assumptions"], ["默认讨论周围神经"])

    def test_intent_normalizes_empty_assumption_without_paid_retry(self):
        value = {
            "domain": "life_science", "normalized_topic": "导电水凝胶", "scope_hint": "聚焦周围神经",
            "tier": "deep", "assumptions": "   ",
            "topic_breadth": "focused", "direction_options": [], "need_clarification": False,
            "clarification_question": None, "confirmation_text": "按该主题继续",
        }
        normalized = server.validate_intent(value)
        self.assertEqual(normalized["assumptions"], [])

    def test_intent_rejects_extra_field(self):
        with self.assertRaises(ValueError):
            server.validate_intent({"unexpected": True})

    def test_preauth_intent_fails_closed_without_shared_daily_budget(self):
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/intent"
        handler.client_address = ("127.0.0.1", 1000)
        task_writes = []
        model_calls = []
        handler.server = SimpleNamespace(
            api_key="configured",
            rate_limiter=SimpleNamespace(allow=lambda key: True),
            workflow=SimpleNamespace(
                daily_budget_ledger=None,
                set_task_context=lambda task_id: model_calls.append(("context", task_id)),
                create_intent=lambda *args: model_calls.append(("intent", args)),
            ),
            task_store=SimpleNamespace(create_task=lambda *args: task_writes.append(args)),
        )
        handler.read_json = lambda: {"topic": "3D生物打印类器官心脏瓣膜", "tier": "fast"}
        replies = []
        handler.send_json = lambda status, value: replies.append((status, value))
        handler.do_POST()
        self.assertEqual(replies[0][0], 503)
        self.assertIn("每日预算尚未接入", replies[0][1]["error"])
        self.assertEqual(task_writes, [])
        self.assertEqual(model_calls, [])

    def test_preauth_intent_with_budget_never_creates_persistent_task(self):
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/intent"
        handler.client_address = ("127.0.0.1", 1000)
        task_writes = []
        calls = []
        output = {"normalized_topic": "主题"}
        handler.server = SimpleNamespace(
            api_key="configured",
            rate_limiter=SimpleNamespace(allow=lambda key: True),
            workflow=SimpleNamespace(
                daily_budget_ledger=object(),
                set_task_context=lambda task_id: calls.append(("context", task_id)),
                create_intent=lambda topic, tier: (calls.append(("intent", topic, tier)) or output, {"total_tokens": 3}),
            ),
            task_store=SimpleNamespace(create_task=lambda *args: task_writes.append(args)),
        )
        handler.read_json = lambda: {"topic": "主题", "tier": "fast"}
        replies = []
        handler.send_json = lambda status, value: replies.append((status, value))
        handler.do_POST()
        self.assertEqual(replies[0], (HTTPStatus.OK, {"data": output, "usage": {"total_tokens": 3}}))
        self.assertEqual(calls, [("context", "anonymous-intent"), ("intent", "主题", "fast")])
        self.assertEqual(task_writes, [])

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
        value = {"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","navigation_title":"Title","purpose":"purpose","on_slide_text":[],"visual_suggestion":"none","speaker_notes":"notes","evidence_ids":["EV-1"],"figure_refs":[{"figure_id":"FIG-2","source_id":"SRC-1","locator":"figure 1","intended_use":"show","reuse_status":"unknown"}],"source_citations":[]}]}
        with self.assertRaises(ValueError):
            server.validate_ppt(value, ["EV-1"], ["FIG-1"])

    def test_ppt_rejects_overlong_slide_text(self):
        value = {"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","navigation_title":"Title","purpose":"purpose","on_slide_text":["字" * 141],"visual_suggestion":"none","speaker_notes":"notes","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]}
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
        value = {"delivery_version":"1.0","evidence_version":"1.0","final_report":{"title":"title","markdown":"body","used_evidence_ids":["EV-1"]},"final_ppt":{"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","navigation_title":"Title","purpose":"","on_slide_text":[],"visual_suggestion":"","speaker_notes":"","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]},"verification_note":"checked","open_issues":[],"source_ids":["SRC-1"],"evidence_ids":["EV-1"],"change_log":[{"claim_id":"CL-1","action":"kept","reason":"wrong"}]}
        verification = {"results": [{"claim_id": "CL-1", "action": "remove"}]}
        with self.assertRaisesRegex(ValueError, "未落实"):
            server.validate_final(value, ["CL-1"], ["SRC-1"], ["EV-1"], verification)

    def test_final_rejects_broken_sentence_after_deterministic_edit(self):
        value = {"delivery_version":"1.0","evidence_version":"1.0","final_report":{"title":"title","markdown":"疗效改善，但。","used_evidence_ids":["EV-1"]},"final_ppt":{"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","navigation_title":"Title","purpose":"","on_slide_text":[],"visual_suggestion":"","speaker_notes":"","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]},"verification_note":"checked","open_issues":[],"source_ids":["SRC-1"],"evidence_ids":["EV-1"],"change_log":[]}
        with self.assertRaisesRegex(ValueError, "断裂标点"):
            server.validate_final(value, [], ["SRC-1"], ["EV-1"])

    def test_final_rejects_internal_audit_labels_in_customer_report(self):
        value = {"delivery_version":"1.0","evidence_version":"1.0","final_report":{"title":"title","markdown":"结果见 evidence_contexts（未核实）","used_evidence_ids":["EV-1"]},"final_ppt":{"deck_title":"deck","storyline":"story","pages":[{"page_id":"SL-1","title":"title","navigation_title":"Title","purpose":"","on_slide_text":[],"visual_suggestion":"","speaker_notes":"","evidence_ids":["EV-1"],"figure_refs":[],"source_citations":[]}]},"verification_note":"checked","open_issues":[],"source_ids":["SRC-1"],"evidence_ids":["EV-1"],"change_log":[]}
        with self.assertRaisesRegex(ValueError, "内部审计字段"):
            server.validate_final(value, [], ["SRC-1"], ["EV-1"])

    def test_workflow_service_is_separate_from_http_handler(self):
        self.assertFalse(hasattr(server, "deepseek_json"))
        self.assertTrue(hasattr(server, "WorkflowService"))

    def test_browser_product_path_inherits_shared_plan_and_final_assembly(self):
        script = (server.ROOT / "web" / "app.js").read_text(encoding="utf-8")
        self.assertIn("request('/api/search',{topic:currentTopic,plan:currentPlan,tier:currentTier})", script)
        self.assertNotIn("buildSearchQuery(", script)
        self.assertIn("claims:claimsResponse.data.claims", script)
        self.assertIn("renderPptPages(finalDelivery.final_ppt)", script)
        self.assertIn("renderLinkedReportMarkdown(finalDelivery.final_report.markdown)", script)

    def test_public_evidence_api_blocks_bad_source_mix_before_model_call(self):
        calls = []
        records = [{"source_id": "S1", "abstract": "text", "access": "abstract", "publication_types": ["Clinical Trial"]}]
        artifacts = {
            "plan": {"data": {"questions": [{"question_id": "Q1"}]}},
            "sources": {"data": {"records": records}},
            "screening": {"data": {"decisions": [{"source_id": "S1", "status": "keep", "question_ids": ["Q1"]}]}},
        }
        workflow = SimpleNamespace(set_task_context=lambda task_id: None,
                                   extract_evidence=lambda *args: calls.append(args))
        handler = object.__new__(server.AppHandler)
        handler.path = "/api/evidence"
        handler.client_address = ("127.0.0.1", 1000)
        handler.server = SimpleNamespace(api_key="configured", rate_limiter=SimpleNamespace(allow=lambda key: True),
                                         task_store=SimpleNamespace(get_task=lambda task_id: {"artifacts": artifacts}), workflow=workflow)
        handler.read_json = lambda: {"tier": "deep", "source_record": records[0], "question_ids": ["Q1"]}
        handler.require_task_access = lambda: "TASK-test"
        responses = []
        handler.send_json = lambda status, value: responses.append((status, value))
        handler.do_POST()
        self.assertEqual(responses[0][0], 400)
        self.assertIn("来源质量门禁未通过", responses[0][1]["error"])
        self.assertEqual(calls, [])

    def test_report_rejects_unmapped_numeric_citations(self):
        report = {"report_version": "1", "report_title": "报告", "report_markdown": "## 摘要\n研究表明有效[9]。", "used_evidence_ids": ["EV::S1::001"], "figure_recommendations": [], "status": "draft", "open_issues": []}
        with self.assertRaisesRegex(ValueError, "数字脚注"):
            server.validate_report(report, ["EV::S1::001"], "deep")

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
