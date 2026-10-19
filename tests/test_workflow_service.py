import unittest
import json
import tempfile
from pathlib import Path

from workflow_service import WorkflowService


class FakeRouter:
    def for_stage(self, stage, tier, upgrade=False):
        return {"model": "%s-%s" % (stage, tier), "effort": "high" if upgrade else "none", "upgraded": upgrade}


class WorkflowServiceTests(unittest.TestCase):
    def test_deep_report_has_stage_specific_output_room(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P5": "report"})
        limits = []

        def generate(stage, tier, payload, validator=None, **options):
            limits.append(options["max_tokens"])
            body = ("执行摘要\n摘要。\n研究范围与资料方法\n范围与方法。\n正文\n"
                    + ("结果与限制[EV::SRC-1::001]。" * 300)
                    + "\n综合结论\n结论。\n局限与后续研究\n局限。")
            value = {"report_version": "1", "report_title": "t", "report_markdown": body,
                     "used_evidence_ids": ["EV::SRC-1::001"], "figure_recommendations": [],
                     "status": "draft", "open_issues": []}
            return validator(value), {"total_tokens": 1}, {}

        service.generate = generate
        evidence = [{"evidence_id": "EV::SRC-1::001"}]
        service.create_report({}, {}, evidence, "fast")
        service.create_report({}, {}, evidence, "deep")
        self.assertEqual(limits, [5000, 10000])

    def test_full_text_evidence_has_room_for_complete_captions(self):
        service = WorkflowService("", FakeRouter(), "system", {"P4": "evidence"})
        limits = []
        def generate(stage, tier, payload, validator, **options):
            limits.append(options["max_tokens"])
            return {"evidence_records": [], "figure_records": []}, {}, {}
        service.generate = generate
        for full_text in ("", "Full article with multi-panel figure captions"):
            service.extract_evidence({"source_id": "S1", "abstract": "Abstract", "full_text": full_text}, ["Q1"])
        self.assertEqual(limits, [4500, 8000])

    def test_screen_sources_batches_and_applies_global_keep_limit(self):
        calls = []

        def client(*args):
            payload = args[4]
            calls.append(payload)
            decisions = [{"source_id": item["source_id"], "status": "keep", "question_ids": ["Q1"], "intended_uses": ["overview"], "reason": "relevant", "priority": "high", "relevance_score": 0.9, "evidence_type": "systematic_review", "flags": []} for item in payload["candidate_sources"]]
            return {"screening_version": "1.0", "topic": payload["topic"], "decisions": decisions, "summary": {"candidate_count": 0, "keep_count": 0, "reserve_count": 0, "drop_count": 0, "open_issues": []}}, {"total_tokens": 10}

        service = WorkflowService("secret", FakeRouter(), "system", {"P3": "screen"}, client)
        candidates = [{"source_id": "SRC-%d" % index, "source": "PubMed", "title": "t", "abstract": "a", "year": "2024", "access": "abstract", "url": "u"} for index in range(9)]
        plan = {"research_scope": "scope", "questions": [], "source_plan": [], "selection_criteria": []}

        output, usage = service.screen_sources("topic", plan, candidates, "fast")

        self.assertEqual(len(calls), 3)
        self.assertEqual(output["summary"]["candidate_count"], 9)
        self.assertEqual(output["summary"]["keep_count"], 4)
        self.assertEqual(output["summary"]["reserve_count"], 5)
        self.assertEqual(usage["total_tokens"], 30)

    def test_screen_sources_drops_harmless_notes_without_retry(self):
        calls = []

        def client(*args):
            calls.append(args)
            source = args[4]["candidate_sources"][0]
            return {
                "screening_version":"1", "topic":"topic", "screening_notes":"解释文字",
                "decisions":[{"source_id":source["source_id"], "status":"keep", "question_ids":["Q1"], "intended_uses":["overview"], "reason":"relevant", "priority":"high", "relevance_score":0.9, "evidence_type":"cohort", "flags":[], "title":"echoed but unused"}],
                "summary":{"candidate_count":1, "keep_count":1, "reserve_count":0, "drop_count":0, "open_issues":[]},
            }, {"total_tokens":10}

        service = WorkflowService("secret", FakeRouter(), "system", {"P3":"screen"}, client)
        candidates = [{"source_id":"SRC-1", "source":"PubMed", "title":"t", "abstract":"a", "year":"2024", "access":"abstract", "url":"u"}]
        plan = {"research_scope":"scope", "questions":[], "source_plan":[], "selection_criteria":[]}
        output, _ = service.screen_sources("topic", plan, candidates, "deep")

        self.assertEqual(len(calls), 1)
        self.assertEqual(output["summary"]["keep_count"], 1)
        self.assertNotIn("title", output["decisions"][0])

    def test_generate_binds_prompt_route_and_client_options(self):
        calls = []

        def client(*args):
            calls.append(args)
            return {"ok": True}, {"total_tokens": 7}

        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"}, client)
        validator = lambda value: value
        output, usage, route = service.generate(
            "P8", "fast", {"claim": 1}, validator,
            upgrade=True, max_tokens=99, max_attempts=3, request_timeout=12,
        )

        self.assertEqual(output, {"ok": True})
        self.assertEqual(usage["total_tokens"], 7)
        self.assertTrue(route["upgraded"])
        self.assertEqual(calls[0][:5], ("secret", "P8-fast", "system", "verify", {"claim": 1}))
        self.assertEqual(calls[0][5:10], ("high", validator, 99, 3, 12))
        self.assertEqual(len(calls[0]), 12)

    def test_missing_prompt_is_rejected_before_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {}, lambda *args: None)
        with self.assertRaisesRegex(ValueError, "缺少提示词"):
            service.generate("P1", "fast", {})

    def test_cached_output_failing_new_validator_is_regenerated(self):
        calls = []
        def client(*args):
            calls.append(True)
            return ({"ok": False} if len(calls) == 1 else {"ok": True}), {"total_tokens": 1}
        with tempfile.TemporaryDirectory() as directory:
            service = WorkflowService("secret", FakeRouter(), "system", {"P5": "report"}, client, response_cache_dir=directory)
            service.set_task_context("TASK-test")
            service.generate("P5", "fast", {"same": "input"}, lambda value: value)
            def stricter(value):
                if not value["ok"]:
                    raise ValueError("旧缓存未满足新规则")
                return value
            output, _, _ = service.generate("P5", "fast", {"same": "input"}, stricter)
        self.assertTrue(output["ok"])
        self.assertEqual(len(calls), 2)

    def test_project_factory_loads_registered_prompts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "config").mkdir()
            (root / "prompts").mkdir()
            (root / "prompts" / "system.md").write_text("system", encoding="utf-8")
            (root / "prompts" / "p1.md").write_text("intent", encoding="utf-8")
            registry = {"global_prompt": "prompts/system.md", "stages": [{"id": "P1", "prompt": "prompts/p1.md"}]}
            (root / "config" / "prompt-stages.json").write_text(json.dumps(registry), encoding="utf-8")

            service = WorkflowService.from_project("secret", FakeRouter(), root, lambda *args: ({}, {}))

        self.assertEqual(service.system_prompt, "system")
        self.assertEqual(service.stage_prompts, {"P1": "intent"})

    def test_plan_payload_includes_epo_and_preserves_clarification(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P2A": "architecture", "P2B": "blueprint"})
        captured = {}
        stages = []

        def generate(stage, tier, payload, validator=None, **options):
            stages.append(stage)
            captured[stage] = payload
            if stage == "P2A":
                return {
                    "research_scope": "scope", "exclusions": [], "overall_story": "story",
                    "modules": [{
                        "module_id": "M%d" % i, "working_title": "t", "content_purpose": "p",
                        "main_content": "c", "why_it_comes_here": "w", "connection_to_next": None,
                    } for i in range(3)], "risks": [],
                }, {"total_tokens": 2}, {}
            return {
                "research_scope": "scope", "exclusions": [],
                "questions": [{"question_id": str(i), "question": "q", "evidence_needs": []} for i in range(3)],
                "search_concepts": {}, "source_plan": [], "selection_criteria": [], "stop_conditions": [],
                "report_outline": [], "ppt_story_arc": [], "risks": [],
            }, {"total_tokens": 3}, {}

        service.generate = generate
        intent = {"domain": "life_science", "normalized_topic": "主题", "scope_hint": "按疾病定义、机制、研究方法和干预证据展开", "tier": "deep", "assumptions": [], "topic_breadth": "focused", "direction_options": [], "need_clarification": False, "clarification_question": None, "confirmation_text": "确认"}
        service.create_plan("主题", "只看临床", "deep", intent)

        self.assertEqual(stages, ["P2A", "P2B"])
        self.assertIn("EPO OPS", captured["P2B"]["available_sources"])
        self.assertIn("只看临床", captured["P2A"]["intent"]["normalized_topic"])
        self.assertIn("疾病定义", captured["P2A"]["intent"]["scope_hint"])
        self.assertEqual(captured["P2B"]["runtime_config"]["source_limit"], 19)
        self.assertEqual(captured["P2A"]["output_contract"]["type"], "object")
        self.assertIn("questions", captured["P2B"]["output_contract"]["required"])
        self.assertEqual(captured["P2B"]["research_architecture"]["overall_story"], "story")

    def test_ppt_payload_inherits_topic_specific_plan(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P6": "ppt"})
        captured = {}

        def generate(stage, tier, payload, validator=None, **options):
            captured.update(payload)
            return {"deck_title": "deck", "storyline": "story", "pages": []}, {"total_tokens": 1}, {}

        service.generate = generate
        plan = {"ppt_story_arc": ["定义瓣膜钙化", "机制与研究模型", "干预证据阶段"]}
        service.create_ppt({}, {}, [{"evidence_id": "EV-1"}], [], {}, "deep", plan)

        self.assertEqual(captured["plan"], plan)
        self.assertEqual(captured["presentation_limits"]["page_characters_max"], 400)

    def test_ppt_can_only_receive_evidence_cited_in_validated_report(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P6": "ppt"})
        captured = {}

        def generate(stage, tier, payload, validator=None, **options):
            captured.update(payload)
            return {"deck_title": "deck", "storyline": "story", "pages": []}, {"total_tokens": 1}, {}

        service.generate = generate
        evidence = [{"evidence_id": "EV::SRC-1::001"}, {"evidence_id": "EV::SRC-2::001"}]
        report = {"report_markdown": "结果支持[EV::SRC-1::001]。"}
        service.create_ppt({}, report, evidence, [], {}, "fast")
        self.assertEqual(captured["allowed_evidence_ids"], ["EV::SRC-1::001"])
        self.assertEqual(captured["evidence_records"], [evidence[0]])

    def test_ppt_revises_only_after_specific_evidence_id_validation_feedback(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P6": "ppt"})
        payloads = []

        def generate(stage, tier, payload, validator=None, **options):
            payloads.append(payload)
            evidence_id = "EV::INVALID::001" if len(payloads) == 1 else "EV::SRC-1::001"
            page = {"page_id": "SL-01", "title": "界面结论", "purpose": "解释机制",
                    "on_slide_text": ["结论有证据支持"], "visual_suggestion": "机制示意图",
                    "speaker_notes": "该结果仍需结合具体条件解释。", "evidence_ids": [evidence_id],
                    "figure_refs": [], "source_citations": []}
            return validator({"deck_title": "deck", "storyline": "story", "pages": [page]}), {"total_tokens": 1}, {}

        service.generate = generate
        evidence = [{"evidence_id": "EV::SRC-1::001"}]
        report = {"report_markdown": "结论[EV::SRC-1::001]。"}
        service.create_ppt({}, report, evidence, [], {}, "fast")
        self.assertEqual(len(payloads), 2)
        self.assertIn("validation_feedback", payloads[1])
        self.assertIn("EV::INVALID::001", payloads[1]["validation_feedback"])

    def test_long_deep_ppt_uses_two_bounded_arc_batches_and_unique_page_ids(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P6": "ppt"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            batch = payload["page_batch"]
            calls.append((batch["index"], [item["module_id"] for item in batch["assigned_arc"]], options["max_tokens"]))
            page = {"page_id": "SL-01", "title": "界面结论", "purpose": "解释界面机制",
                    "on_slide_text": ["导电水凝胶改善电极界面"], "visual_suggestion": "材料结构示意图",
                    "speaker_notes": "材料界面性能需要结合具体实验评价。", "evidence_ids": ["EV-1"],
                    "figure_refs": [], "source_citations": []}
            return (validator({"deck_title": "deck", "storyline": "story", "pages": [page]}),
                    {"prompt_tokens": 10, "completion_tokens": 20, "total_tokens": 30, "attempts": 1}, {})

        service.generate = generate
        arc = [{"module_id": "M%d" % index, "narrative": "part"} for index in range(1, 7)]
        output, usage = service.create_ppt({}, {"report_markdown": "文" * 7001},
                                           [{"evidence_id": "EV-1"}], [], {}, "deep", {"ppt_story_arc": arc})
        self.assertEqual(calls, [(1, ["M1", "M2", "M3"], 7000), (2, ["M4", "M5", "M6"], 7000)])
        self.assertEqual([page["page_id"] for page in output["pages"]], ["SL-01", "SL-02"])
        self.assertEqual(usage["total_tokens"], 60)

    def test_metadata_only_evidence_skips_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P4": "evidence"})
        service.generate = lambda *args, **kwargs: self.fail("metadata-only source must not call model")
        output, usage = service.extract_evidence(
            {"source_id": "EPO:EP.1.A1", "source": "EPO OPS", "abstract": "", "access": "patent_bibliographic_metadata"},
            ["Q1"], "fast",
        )
        self.assertEqual(output["extraction_status"], "no_extractable_evidence")
        self.assertEqual(usage["total_tokens"], 0)

    def test_figure_provenance_overrides_model_claim_of_reuse_permission(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P4": "evidence"})
        source = {"source_id": "SRC-1", "source": "Europe PMC", "abstract": "Study result", "access": "full_text",
                  "figure_candidates": [{"figure_id": "SRC-1:fig1", "label": "Figure 1", "caption": "Original caption: (a) response, (b) control",
                                         "article_figure_url": "https://europepmc.org/articles/PMC123/figure/fig1", "reuse_status": "unknown"}]}
        model_output = {"evidence_version": "1", "source_id": "SRC-1", "extraction_status": "extracted", "reading_scope": "abstract",
                        "evidence_records": [], "figure_records": [{"figure_id": "SRC-1:fig1", "source_id": "SRC-1", "caption": "Observed response",
                        "locator": "PMC123, Figure 1", "supported_claims": ["response"], "reuse_status": "allowed"}], "no_extractable_reason": None}
        service.generate = lambda stage, tier, payload, validator, **kwargs: (validator(model_output), {"total_tokens": 1}, {})

        output, _ = service.extract_evidence(source, ["Q1"], "fast")

        figure = output["figure_records"][0]
        self.assertEqual(figure["caption"], "Original caption: (a) response, (b) control")
        self.assertEqual(figure["reuse_status"], "unknown")
        self.assertEqual(figure["article_figure_url"], "https://europepmc.org/articles/PMC123/figure/fig1")
        self.assertEqual(figure["label"], "Figure 1")

    def test_ppt_figure_reference_inherits_saved_source_and_permission(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P6": "ppt"})
        figure = {"figure_id": "SRC-1:fig1", "source_id": "SRC-1", "locator": "PMC123, Figure 1 | https://example.org/fig1", "reuse_status": "unknown"}
        page = {"page_id": "P1", "title": "Study", "purpose": "Explain", "on_slide_text": ["Evidence-based result"],
                "visual_suggestion": "Figure 1", "speaker_notes": "The source reports this result.", "evidence_ids": ["EV-1"],
                "figure_refs": [{"figure_id": "SRC-1:fig1", "source_id": "WRONG", "locator": "invented", "intended_use": "Show result", "reuse_status": "allowed"}],
                "source_citations": []}
        service.generate = lambda *args, **kwargs: ({"deck_title": "Deck", "storyline": "Story", "pages": [page]}, {"total_tokens": 1}, {})

        output, _ = service.create_ppt({}, {}, [{"evidence_id": "EV-1"}], [figure], {}, "fast")

        reference = output["pages"][0]["figure_refs"][0]
        self.assertEqual(reference["source_id"], "SRC-1")
        self.assertEqual(reference["locator"], figure["locator"])
        self.assertEqual(reference["reuse_status"], "unknown")

    def test_evidence_ids_are_namespaced_by_source(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P4": "evidence"})

        def generate(stage, tier, payload, validator=None, **options):
            output = {
                "evidence_version": "1", "source_id": "SRC-1", "extraction_status": "extracted",
                "reading_scope": "abstract", "figure_records": [], "no_extractable_reason": None,
                "evidence_records": [{
                    "evidence_id": "EV-001", "source_id": "SRC-1", "question_ids": ["Q1"],
                    "fact": "fact", "excerpt": "quote", "locator": "abstract",
                    "evidence_type": "observation", "conditions": [], "limitations": [],
                }],
            }
            return validator(output), {"total_tokens": 1}, {}

        service.generate = generate
        output, _ = service.extract_evidence(
            {"source_id": "SRC-1", "source": "PubMed", "abstract": "text", "access": "abstract"},
            ["Q1"], "fast",
        )
        self.assertEqual(output["evidence_records"][0]["evidence_id"], "EV::SRC-1::001")

    def test_service_rejects_duplicate_evidence_before_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P5": "report"})
        service.generate = lambda *args, **kwargs: self.fail("invalid input must not call model")
        evidence = [{"evidence_id": "EV-1"}, {"evidence_id": "EV-1"}]
        with self.assertRaisesRegex(ValueError, "重复"):
            service.create_report({}, {}, evidence, "fast")

    def test_report_rejects_unknown_citation_instead_of_silently_deleting_support(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P5": "report"})

        def generate(stage, tier, payload, validator=None, **options):
            body = "# 摘要\n摘要。\n# 研究范围\n范围。\n# 资料方法\n方法。\n# 正文\n" + ("有证据的叙述[EV::SRC-1::001]与待核验叙述[EV::SRC-X::999]。" * 100) + "\n# 结论\n结论。\n# 局限\n局限。"
            value = {
                "report_version": "1", "report_title": "t", "report_markdown": body,
                "used_evidence_ids": ["EV::SRC-1::001", "EV::SRC-X::999"], "figure_recommendations": [],
                "status": "draft", "open_issues": [],
            }
            return validator(value), {"total_tokens": 1}, {}

        service.generate = generate
        with self.assertRaisesRegex(ValueError, "不存在的 evidence_id"):
            service.create_report({}, {}, [{"evidence_id": "EV::SRC-1::001"}], "fast")

    def test_extract_claims_batches_pages_and_renumbers_claims(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P7": "claims"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            calls.append(payload["batch_label"])
            claim = {
                "claim_id": "temporary", "location_type": "report_section", "section_or_page_id": "S1",
                "original_text": "text", "atomic_claim": "claim", "claim_type": "other",
                "cited_evidence_ids": ["EV-1"], "risk_level": "low",
            }
            return {"claim_set_version": "1", "claims": [claim], "extraction_notes": []}, {"total_tokens": 2}, {}

        service.generate = generate
        ppt = {"deck_title": "deck", "storyline": "story", "pages": [{"page_id": str(index)} for index in range(4)]}
        output, usage, metadata = service.extract_claims({}, ppt, ["EV-1"], "fast")

        self.assertEqual(calls, ["report", "ppt_page_1", "ppt_page_2", "ppt_page_3", "ppt_page_4"])
        self.assertEqual([item["claim_id"] for item in output["claims"]], ["CLM-0001", "CLM-0002", "CLM-0003", "CLM-0004", "CLM-0005"])
        self.assertEqual(usage["total_tokens"], 10)
        self.assertEqual(metadata["batches"], 5)

    def test_extract_claims_chunks_long_report_before_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P7": "claims"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            calls.append((payload["batch_label"], len(payload["report"].get("report_markdown", ""))))
            claim = {
                "claim_id": "temporary", "location_type": "report_section", "section_or_page_id": "S1",
                "original_text": "text", "atomic_claim": "claim " + str(len(calls)), "claim_type": "other",
                "cited_evidence_ids": ["EV-1"], "risk_level": "low",
            }
            return {"claim_set_version": "1", "claims": [claim], "extraction_notes": []}, {"total_tokens": 1}, {}

        service.generate = generate
        report = {"report_markdown": ("paragraph\n" * 1200)}
        service.extract_claims(report, {"pages": []}, ["EV-1"], "fast")

        self.assertGreater(len(calls), 1)
        self.assertTrue(all(size <= 1200 for _, size in calls))
        self.assertTrue(all(label.startswith("report_part_") for label, _ in calls))

    def test_extract_claims_filters_unknown_evidence_without_paid_retry(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P7": "claims"})

        def generate(stage, tier, payload, validator=None, **options):
            claim = {
                "claim_id": "temporary", "location_type": "report_section", "section_or_page_id": "S1",
                "original_text": "text", "atomic_claim": "claim", "claim_type": "other",
                "cited_evidence_ids": ["EV-1", "EV-HALLUCINATED"], "risk_level": "low",
            }
            output = {"claim_set_version": "1", "claims": [claim], "extraction_notes": []}
            return validator(output), {"total_tokens": 2}, {}

        service.generate = generate
        output, _, _ = service.extract_claims({"report_markdown": "text"}, {"pages": []}, ["EV-1"], "fast")

        self.assertEqual(output["claims"][0]["cited_evidence_ids"], ["EV-1"])
        self.assertIn("EV-HALLUCINATED", output["extraction_notes"][0])

    def test_verify_claims_deduplicates_then_expands_results(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            batch = payload["claims"]["claims"]
            calls.append(batch)
            result = {
                "claim_id": batch[0]["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"], "explanation": "supported",
                "action": "keep", "revised_claim": None, "valid_evidence_ids": ["EV-1"],
            }
            route = {"model": "strong", "upgraded": options["upgrade"]}
            return {"results": [result]}, {"total_tokens": 5}, route

        service.generate = generate
        base = {"atomic_claim": "same claim", "cited_evidence_ids": ["EV-1"], "risk_level": "high", "claim_type": "efficacy"}
        claims = {"claim_set_version": "1", "claims": [{**base, "claim_id": "CL-1"}, {**base, "claim_id": "CL-2"}]}
        output, usage, metadata = service.verify_claims(claims, [{"evidence_id": "EV-1"}], [{"source_id": "SRC-1"}], "fast")

        self.assertEqual(len(calls), 1)
        self.assertEqual([item["claim_id"] for item in output["results"]], ["CL-1", "CL-2"])
        self.assertEqual(usage["total_tokens"], 5)
        self.assertEqual(metadata["unique_claims"], 1)
        self.assertEqual(metadata["claims"], 2)
        self.assertEqual(metadata["reason"], "risk_split")
        self.assertEqual(metadata["high_risk_claims"], 1)
        self.assertEqual(metadata["standard_claims"], 0)

    def test_verify_claims_routes_standard_and_high_risk_separately(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            batch = payload["claims"]["claims"]
            calls.append((options["upgrade"], [item["claim_id"] for item in batch]))
            results = [{
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"], "explanation": "supported",
                "action": "keep", "revised_claim": None, "valid_evidence_ids": ["EV-1"],
            } for item in batch]
            return {"results": results}, {"total_tokens": 5}, {"model": "pro" if options["upgrade"] else "flash", "upgraded": options["upgrade"]}

        service.generate = generate
        claims = {"claim_set_version": "1", "claims": [
            {"claim_id": "CL-1", "atomic_claim": "背景事实", "cited_evidence_ids": ["EV-1"], "risk_level": "low", "claim_type": "other"},
            {"claim_id": "CL-2", "atomic_claim": "疗效事实", "cited_evidence_ids": ["EV-1"], "risk_level": "medium", "claim_type": "efficacy"},
        ]}

        output, usage, metadata = service.verify_claims(claims, [{"evidence_id": "EV-1"}], [{"source_id": "SRC-1"}], "fast")

        self.assertEqual(calls, [(False, ["CL-1"]), (True, ["CL-2"])])
        self.assertEqual([item["claim_id"] for item in output["results"]], ["CL-1", "CL-2"])
        self.assertEqual(metadata["models"], ["flash", "pro"])
        self.assertEqual(metadata["standard_claims"], 1)
        self.assertEqual(metadata["high_risk_claims"], 1)
        self.assertEqual(usage["total_tokens"], 10)

    def test_verify_claims_normalizes_invalid_actions_without_paid_retry(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})

        def generate(stage, tier, payload, validator=None, **options):
            item = payload["claims"]["claims"][0]
            result = {
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "unsupported", "issue_codes": ["scope_overreach"], "explanation": "not supported",
                "action": "keep", "revised_claim": "should not survive", "valid_evidence_ids": ["EV-1", "EV-X"],
            }
            return validator({"results": [result]}), {"total_tokens": 5}, {"model": "flash", "upgraded": False}

        service.generate = generate
        claims = {"claim_set_version": "1", "claims": [{
            "claim_id": "CL-1", "atomic_claim": "claim", "cited_evidence_ids": ["EV-1"],
            "risk_level": "low", "claim_type": "other",
        }]}
        output, _, _ = service.verify_claims(
            claims, [{"evidence_id": "EV-1", "source_id": "SRC-1"}], [{"source_id": "SRC-1"}], "fast"
        )

        result = output["results"][0]
        self.assertEqual(result["action"], "remove")
        self.assertIsNone(result["revised_claim"])
        self.assertEqual(result["valid_evidence_ids"], ["EV-1"])

    def test_final_assembly_falls_back_to_atomic_claim_when_original_text_drifted(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {
            "claim_id": "CL-1", "location_type": "report_section", "section_or_page_id": "body",
            "original_text": "震荡剪切应力使炎症基因升高", "atomic_claim": "振荡剪切应力使炎症基因升高。",
        }
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "体外实验中，振荡剪切应力使炎症基因升高。", "explanation": "补充条件",
        }]}
        report = {"report_title": "t", "report_markdown": "研究显示振荡剪切应力使炎症基因升高[EV-1]。源头摘要提及 M2 极化，但未提供对应 evidence_id 的独立证据条目。", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "P1", "title": "title", "purpose": "", "on_slide_text": ["text"],
            "visual_suggestion": "", "speaker_notes": "", "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}

        output, _ = service.assemble_final_deterministic(
            verification, report, ppt, [claim], ["SRC-1"], ["EV-1"], "1"
        )

        self.assertIn("体外实验中", output["final_report"]["markdown"])
        self.assertIn("M2 极化，但这一细节尚缺独立证据支持", output["final_report"]["markdown"])
        self.assertNotIn("evidence_id", output["final_report"]["markdown"])

    def test_final_assembly_routes_exact_open_issue_claim_to_open_issues(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {
            "claim_id": "CL-OPEN", "location_type": "report_section", "section_or_page_id": "open_issues",
            "original_text": "需要前瞻性验证。", "atomic_claim": "需要前瞻性验证。",
        }
        verification = {"results": [{
            "claim_id": "CL-OPEN", "support_status": "cannot_determine", "action": "mark_unverified",
            "revised_claim": None, "explanation": "证据缺失",
        }]}
        report = {"report_title": "t", "report_markdown": "正文", "used_evidence_ids": [], "open_issues": ["需要前瞻性验证。"]}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "P1", "title": "t", "purpose": "p", "on_slide_text": [],
            "visual_suggestion": "", "speaker_notes": "", "evidence_ids": [],
            "figure_refs": [], "source_citations": [],
        }]}

        output, _ = service.assemble_final_deterministic(
            verification, report, ppt, [claim], [], [], "1"
        )

        self.assertTrue(any(item.startswith("尚待核实：") for item in output["open_issues"]))
        self.assertEqual(len(output["open_issues"]), 1)

    def test_final_assembly_does_not_overflow_notes_with_verification_append(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {
            "claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1",
            "original_text": "原结论", "atomic_claim": "原结论",
        }
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "修订" * 100, "explanation": "补充条件",
        }]}
        report = {"report_title": "t", "report_markdown": "report", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "P1", "title": "title", "purpose": "", "on_slide_text": ["原结论"],
            "visual_suggestion": "", "speaker_notes": "讲稿" * 300, "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}
        output, _ = service.assemble_final_deterministic(
            verification, report, ppt, [claim], ["SRC-1"], ["EV-1"], "1"
        )
        page = output["final_ppt"]["pages"][0]
        self.assertLessEqual(len(page["speaker_notes"]), 800)
        self.assertEqual(page["on_slide_text"], [])

    def test_final_assembly_does_not_duplicate_shared_note_revision(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{"claim_id": claim_id, "location_type": "ppt_speaker_note", "section_or_page_id": "P1",
                   "original_text": "原句。", "atomic_claim": "原句。", "cited_evidence_ids": ["EV-1"]}
                  for claim_id in ("CL-1", "CL-2")]
        verification = {"results": [{"claim_id": claim_id, "support_status": "partially_supported", "action": "revise",
                                     "revised_claim": "修订句。", "valid_evidence_ids": ["EV-1"], "explanation": "限定范围"}
                                    for claim_id in ("CL-1", "CL-2")]}
        report = {"report_title": "t", "report_markdown": "report", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "P1", "title": "t", "purpose": "p", "on_slide_text": [],
            "visual_suggestion": "", "speaker_notes": "原句。", "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}
        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, [], ["EV-1"], "1")
        self.assertEqual(output["final_ppt"]["pages"][0]["speaker_notes"], "修订句。")

    def test_final_assembly_moves_verified_revision_to_supplement_when_page_is_full(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {"claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "SL-01",
                 "original_text": "原结论", "atomic_claim": "原结论", "cited_evidence_ids": ["EV-1"]}
        verification = {"results": [{"claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
                                     "revised_claim": "经核验的适用条件" * 20, "valid_evidence_ids": ["EV-1"], "explanation": "限定范围"}]}
        report = {"report_title": "t", "report_markdown": "report", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "SL-01", "title": "t", "purpose": "p", "on_slide_text": ["原结论"],
            "visual_suggestion": "", "speaker_notes": "背景说明" * 190, "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}
        output, _ = service.assemble_final_deterministic(verification, report, ppt, [claim], ["SRC-1"], ["EV-1"], "1")
        self.assertEqual(len(output["final_ppt"]["pages"]), 2)
        supplemental = output["final_ppt"]["pages"][1]
        self.assertIn("经核验的适用条件", supplemental["speaker_notes"])
        self.assertEqual(supplemental["evidence_ids"], ["EV-1"])

    def test_final_assembly_moves_overflowing_note_revision_without_deleting_original_notes(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        original = "原始临床数据描述。"
        claim = {"claim_id": "CL-1", "location_type": "ppt_speaker_note", "section_or_page_id": "SL-01",
                 "original_text": original, "atomic_claim": original, "cited_evidence_ids": ["EV-1"]}
        revision = "核验后应保留的完整适用条件與统计限定。" * 5
        verification = {"results": [{"claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
                                     "revised_claim": revision, "valid_evidence_ids": ["EV-1"], "explanation": "補充限定"}]}
        report = {"report_title": "t", "report_markdown": "report", "used_evidence_ids": ["EV-1"], "open_issues": []}
        notes = "背景。" * 255 + original
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "SL-01", "title": "t", "purpose": "p", "on_slide_text": ["可靠要点"],
            "visual_suggestion": "", "speaker_notes": notes, "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}
        output, _ = service.assemble_final_deterministic(verification, report, ppt, [claim], ["SRC-1"], ["EV-1"], "1")
        self.assertEqual(output["final_ppt"]["pages"][0]["speaker_notes"], notes)
        self.assertEqual(len(output["final_ppt"]["pages"]), 2)
        self.assertEqual(output["final_ppt"]["pages"][1]["speaker_notes"], revision)

    def test_final_assembly_removes_unverified_claim_from_ordinary_spoken_notes(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {
            "claim_id": "CL-1", "location_type": "ppt_speaker_note", "section_or_page_id": "P1",
            "original_text": "尚未得到验证的结论", "atomic_claim": "尚未得到验证的结论",
        }
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "cannot_determine", "action": "mark_unverified",
            "revised_claim": None, "explanation": "证据缺失",
        }]}
        report = {"report_title": "t", "report_markdown": "report", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "d", "storyline": "s", "pages": [{
            "page_id": "P1", "title": "核心机制", "purpose": "解释机制", "on_slide_text": ["可靠结论"],
            "visual_suggestion": "", "speaker_notes": "先讲可靠发现。尚未得到验证的结论。然后进入下一页。",
            "evidence_ids": ["EV-1"], "figure_refs": [], "source_citations": [],
        }]}
        output, _ = service.assemble_final_deterministic(
            verification, report, ppt, [claim], ["SRC-1"], ["EV-1"], "1"
        )
        notes = output["final_ppt"]["pages"][0]["speaker_notes"]
        self.assertNotIn("未核实", notes)
        self.assertNotIn("尚未得到验证的结论", notes)

    def test_verify_claims_uses_dynamic_batches_and_only_cited_evidence(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            batch = payload["claims"]["claims"]
            calls.append({
                "claims": [item["claim_id"] for item in batch],
                "evidence": [item["evidence_id"] for item in payload["evidence_records"]],
                "sources": [item["source_id"] for item in payload["source_records"]],
                "max_tokens": options["max_tokens"],
            })
            results = [{
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"], "explanation": "supported",
                "action": "keep", "revised_claim": None, "valid_evidence_ids": item["cited_evidence_ids"],
            } for item in batch]
            return {"results": results}, {"total_tokens": 1}, {"model": "flash", "upgraded": False}

        service.generate = generate
        claims = {"claim_set_version": "1", "claims": [{
            "claim_id": "CL-%d" % index, "atomic_claim": "背景事实%d" % index,
            "cited_evidence_ids": ["EV-1"], "risk_level": "low", "claim_type": "other",
        } for index in range(1, 10)]}
        evidence = [
            {"evidence_id": "EV-1", "source_id": "SRC-1", "fact": "used"},
            {"evidence_id": "EV-2", "source_id": "SRC-2", "fact": "must not be sent"},
        ]
        sources = [{"source_id": "SRC-1"}, {"source_id": "SRC-2"}]

        output, _, metadata = service.verify_claims(claims, evidence, sources, "fast")

        self.assertEqual([len(item["claims"]) for item in calls], [8, 1])
        self.assertTrue(all(item["evidence"] == ["EV-1"] for item in calls))
        self.assertTrue(all(item["sources"] == ["SRC-1"] for item in calls))
        self.assertLess(calls[1]["max_tokens"], calls[0]["max_tokens"])
        self.assertEqual(len(output["results"]), 9)
        self.assertEqual(metadata["batches"], 2)

    def test_verify_claims_merges_safe_near_duplicates_before_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})
        calls = []

        def generate(stage, tier, payload, validator=None, **options):
            batch = payload["claims"]["claims"]
            calls.append([item["claim_id"] for item in batch])
            results = [{
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"], "explanation": "supported",
                "action": "keep", "revised_claim": None, "valid_evidence_ids": ["EV-1"],
            } for item in batch]
            return validator({"results": results}), {"total_tokens": 1}, {"model": "flash", "upgraded": False}

        service.generate = generate
        common = {"cited_evidence_ids": ["EV-1"], "risk_level": "medium", "claim_type": "efficacy"}
        claims = {"claim_set_version": "1", "claims": [
            dict(common, claim_id="CL-1", atomic_claim="CT041的ORR为38.8%"),
            dict(common, claim_id="CL-2", atomic_claim="CT041的ORR为38.8%。"),
        ]}
        output, _, metadata = service.verify_claims(
            claims, [{"evidence_id": "EV-1", "source_id": "SRC-1"}], [{"source_id": "SRC-1"}], "deep"
        )

        self.assertEqual(calls, [["CL-1"]])
        self.assertEqual([item["claim_id"] for item in output["results"]], ["CL-1", "CL-2"])
        self.assertEqual(metadata["unique_claims"], 1)

    def test_high_risk_verification_includes_sibling_evidence_from_same_source(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})
        seen = {}

        def generate(stage, tier, payload, validator=None, **options):
            seen["evidence"] = [item["evidence_id"] for item in payload["evidence_records"]]
            item = payload["claims"]["claims"][0]
            result = {"claim_id":item["claim_id"],"source_identity":{"matched":True,"source_ids":["SRC-1"]},"support_status":"supported","issue_codes":["none"],"explanation":"supported","action":"keep","revised_claim":None,"valid_evidence_ids":["EV-2"]}
            return {"results":[result]}, {"total_tokens":1}, {"model":"pro","upgraded":True}

        service.generate = generate
        claims = {"claim_set_version":"1","claims":[{"claim_id":"CL-1","atomic_claim":"疗效","cited_evidence_ids":["EV-1"],"risk_level":"high","claim_type":"efficacy"}]}
        evidence = [{"evidence_id":"EV-1","source_id":"SRC-1"},{"evidence_id":"EV-2","source_id":"SRC-1"},{"evidence_id":"EV-3","source_id":"SRC-2"}]
        service.verify_claims(claims, evidence, [{"source_id":"SRC-1"},{"source_id":"SRC-2"}], "fast")

        self.assertEqual(set(seen["evidence"]), {"EV-1", "EV-2"})

    def test_verification_fails_closed_when_only_sibling_evidence_supports_claim(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})

        def generate(stage, tier, payload, validator=None, **options):
            item = payload["claims"]["claims"][0]
            result = {
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"],
                "explanation": "同源 EV-2 支持该事实", "action": "revise",
                "revised_claim": "修订后的事实", "valid_evidence_ids": ["EV-2"],
            }
            return {"results": [result]}, {"total_tokens": 1}, {"model": "flash", "upgraded": True}

        service.generate = generate
        claims = {"claim_set_version": "1", "claims": [{
            "claim_id": "CL-1", "atomic_claim": "高风险结论", "cited_evidence_ids": ["EV-1"],
            "risk_level": "high", "claim_type": "efficacy",
        }]}
        evidence = [{"evidence_id": "EV-1", "source_id": "SRC-1"}, {"evidence_id": "EV-2", "source_id": "SRC-1"}]

        output, _, _ = service.verify_claims(claims, evidence, [{"source_id": "SRC-1"}], "fast")
        result = output["results"][0]

        self.assertEqual(result["support_status"], "unsupported")
        self.assertEqual(result["action"], "remove")
        self.assertEqual(result["valid_evidence_ids"], [])
        self.assertEqual(result["issue_codes"], ["source_mismatch", "citation_missing"])

    def test_verification_marks_claim_without_current_citation_unverified(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P8": "verify"})

        def generate(stage, tier, payload, validator=None, **options):
            item = payload["claims"]["claims"][0]
            result = {
                "claim_id": item["claim_id"], "source_identity": {"matched": True, "source_ids": ["SRC-1"]},
                "support_status": "supported", "issue_codes": ["none"], "explanation": "其他证据支持",
                "action": "keep", "revised_claim": None, "valid_evidence_ids": ["EV-1"],
            }
            return {"results": [result]}, {"total_tokens": 1}, {"model": "flash", "upgraded": False}

        service.generate = generate
        claims = {"claim_set_version": "1", "claims": [{
            "claim_id": "CL-1", "atomic_claim": "没有引用的结论", "cited_evidence_ids": [],
            "risk_level": "low", "claim_type": "other",
        }]}

        output, _, _ = service.verify_claims(claims, [{"evidence_id": "EV-1", "source_id": "SRC-1"}], [{"source_id": "SRC-1"}], "fast")
        result = output["results"][0]

        self.assertEqual(result["support_status"], "cannot_determine")
        self.assertEqual(result["action"], "mark_unverified")
        self.assertEqual(result["valid_evidence_ids"], [])

    def test_deterministic_final_applies_revision_without_model_tokens(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "report_section", "section_or_page_id": "S1",
            "original_text": "能够治愈疾病。", "atomic_claim": "能够治愈疾病", "claim_type": "efficacy",
            "cited_evidence_ids": ["EV-1"], "risk_level": "high",
        }]
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "研究观察到潜在改善。", "explanation": "证据仅支持相关性",
        }]}
        report = {"report_title": "报告", "report_markdown": "结果显示能够治愈疾病。", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{"page_id": "P1", "title": "结论", "on_slide_text": ["谨慎解释"], "speaker_notes": "", "evidence_ids": ["EV-1"]}]}

        output, usage = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        self.assertIn("研究观察到潜在改善", output["final_report"]["markdown"])
        self.assertNotIn("能够治愈", output["final_report"]["markdown"])
        self.assertEqual(output["change_log"][0]["action"], "revised")
        self.assertEqual(usage["total_tokens"], 0)

    def test_deterministic_final_repairs_unique_alias_and_punctuation_drift(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "report_section", "section_or_page_id": "摘要",
            "original_text": "CLDN18.2在胃癌中呈局限性表达而在正常组织中表达受限，使其成为CAR-T细胞疗法的候选靶点",
            "atomic_claim": "CLDN18.2在胃癌中呈局限性表达，而在正常组织中表达受限，使其成为CAR-T细胞疗法的候选靶点。",
            "claim_type": "mechanism", "cited_evidence_ids": ["EV-1"], "risk_level": "medium",
        }]
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "现有资料仅支持该靶点已进入早期临床评估。", "explanation": "机制证据不足",
        }]}
        report = {"report_title": "报告", "report_markdown": "Claudin18.2（CLDN18.2）在胃癌中呈局限性表达而在正常组织中表达受限，使其成为CAR-T细胞疗法的候选靶点。", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "结论", "purpose": "汇报", "on_slide_text": ["证据结论"],
            "visual_suggestion": "", "speaker_notes": "", "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        self.assertIn("仅支持该靶点已进入早期临床评估", output["final_report"]["markdown"])
        self.assertNotIn("局限性表达", output["final_report"]["markdown"])

    def test_deterministic_final_preserves_visuals_and_citations(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{"claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1", "original_text": "证据结论", "atomic_claim": "证据结论", "claim_type": "other", "cited_evidence_ids": ["EV-1"], "risk_level": "low"}]
        verification = {"results": [{"claim_id": "CL-1", "support_status": "supported", "action": "keep", "revised_claim": None, "explanation": "证据一致"}]}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        figure = {"figure_id": "FIG-1", "source_id": "SRC-1", "locator": "Fig. 2", "intended_use": "解释机制", "reuse_status": "citation_only"}
        citation = {"source_id": "SRC-1", "short_vancouver": "Smith J, et al. Example J. 2024;1:1-2."}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{"page_id": "P1", "title": "结论", "purpose": "解释机制", "on_slide_text": ["证据结论"], "visual_suggestion": "使用 Fig. 2", "speaker_notes": "", "evidence_ids": ["EV-1"], "figure_refs": [figure], "source_citations": [citation]}]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])
        page = output["final_ppt"]["pages"][0]

        self.assertEqual(page["figure_refs"], [figure])
        self.assertEqual(page["source_citations"], [citation])
        self.assertEqual(page["visual_suggestion"], "使用 Fig. 2")

    def test_deterministic_final_locates_slide_claim_after_label_prefix(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1",
            "original_text": "突破：无标记大片段整合平台", "atomic_claim": "已建立无标记整合平台",
            "claim_type": "research_stage", "cited_evidence_ids": ["EV-1"], "risk_level": "medium",
        }]
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "在指定宿主中开发了无标记整合平台。", "explanation": "需要限定宿主",
        }]}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "突破", "on_slide_text": ["突破：定向酶工程；无标记大片段整合平台；共定位"],
            "speaker_notes": "", "evidence_ids": ["EV-1"],
        }]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        slide = output["final_ppt"]["pages"][0]["on_slide_text"][0]
        self.assertIn("在指定宿主中开发", slide)
        self.assertNotIn("无标记大片段整合平台", slide)

    def test_deterministic_final_recovers_mislabeled_slide_field(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "ppt_speaker_note", "section_or_page_id": "P1",
            "original_text": "优化 NADPH 与血红素", "atomic_claim": "优化供应",
            "claim_type": "mechanism", "cited_evidence_ids": ["EV-1"], "risk_level": "high",
        }]
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "增强 NADPH 与血红素供应", "explanation": "未直接测量",
        }]}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "结论", "on_slide_text": ["过表达相关基因，优化 NADPH 与血红素"],
            "speaker_notes": "谨慎解释", "evidence_ids": ["EV-1"],
        }]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        self.assertIn("增强 NADPH 与血红素供应", output["final_ppt"]["pages"][0]["on_slide_text"][0])

    def test_deterministic_final_promotes_verified_visual_note_to_slide(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1",
            "original_text": "底部标注摘要级证据", "atomic_claim": "证据为摘要级",
            "claim_type": "other", "cited_evidence_ids": ["EV-1"], "risk_level": "medium",
        }]
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": "多数证据为摘要级且统计信息不完整", "explanation": "需要限定范围",
        }]}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "结论", "purpose": "总结", "on_slide_text": ["案例"],
            "visual_suggestion": "三栏卡片，底部标注摘要级证据", "speaker_notes": "谨慎解释", "evidence_ids": ["EV-1"],
        }]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        self.assertIn("多数证据为摘要级", output["final_ppt"]["pages"][0]["on_slide_text"][-1])

    def test_deterministic_final_moves_long_slide_revision_to_notes(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [{
            "claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1",
            "original_text": "原结论", "atomic_claim": "原结论", "claim_type": "efficacy",
            "cited_evidence_ids": ["EV-1"], "risk_level": "high",
        }]
        long_revision = "在指定研究对象、剂量、观察时间和实验条件下观察到有限改善，不能外推至其他人群或解释为已经证明临床疗效。" * 4
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "partially_supported", "action": "revise",
            "revised_claim": long_revision, "explanation": "需要完整限定",
        }]}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "结论", "on_slide_text": ["原结论"],
            "speaker_notes": "", "evidence_ids": ["EV-1"],
        }]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])
        page = output["final_ppt"]["pages"][0]

        self.assertEqual(page["on_slide_text"], [])
        self.assertIn(long_revision, page["speaker_notes"])

    def test_deterministic_final_removes_unique_long_bullet_containing_numeric_claim(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claim = {
            "claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1",
            "original_text": "结直肠癌IV期5年相对生存率降至约15%。",
            "atomic_claim": "结直肠癌IV期5年相对生存率降至约15%。",
        }
        verification = {"results": [{
            "claim_id": "CL-1", "support_status": "unsupported", "action": "remove",
            "explanation": "引用错配", "revised_claim": None, "valid_evidence_ids": [],
        }], "summary": {"supported": 0, "partially_supported": 0, "unsupported": 1, "cannot_determine": 0, "high_risk_remaining": 0}}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "早筛", "purpose": "说明背景",
            "on_slide_text": ["结直肠癌等癌种分期与预后相关（I期5年相对生存率接近90%，IV期降至约15%）。", "另一条结论"],
            "visual_suggestion": "示意图", "speaker_notes": "讲稿", "evidence_ids": ["EV-1"],
            "figure_refs": [], "source_citations": [],
        }]}

        output, usage = service.assemble_final_deterministic(verification, report, ppt, [claim], ["SRC-1"], ["EV-1"])

        self.assertEqual(output["final_ppt"]["pages"][0]["on_slide_text"], ["另一条结论"])
        self.assertEqual(usage["total_tokens"], 0)

    def test_deterministic_final_treats_overlapping_removals_as_idempotent(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        claims = [
            {"claim_id": "CL-1", "location_type": "ppt_slide", "section_or_page_id": "P1", "original_text": "结直肠癌等癌种分期与预后相关（I期5年相对生存率接近90%，IV期降至约15%）。", "atomic_claim": "结直肠癌I期5年相对生存率接近90%。"},
            {"claim_id": "CL-2", "location_type": "ppt_slide", "section_or_page_id": "P1", "original_text": "结直肠癌IV期5年相对生存率降至约15%。", "atomic_claim": "结直肠癌IV期5年相对生存率降至约15%。"},
        ]
        results = [{"claim_id": item["claim_id"], "support_status": "unsupported", "action": "remove", "explanation": "引用错配", "revised_claim": None, "valid_evidence_ids": []} for item in claims]
        verification = {"results": results, "summary": {"supported": 0, "partially_supported": 0, "unsupported": 2, "cannot_determine": 0, "high_risk_remaining": 0}}
        report = {"report_title": "报告", "report_markdown": "正文", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{"page_id": "P1", "title": "早筛", "purpose": "背景", "on_slide_text": [claims[0]["original_text"], "另一条结论"], "visual_suggestion": "示意图", "speaker_notes": "讲稿", "evidence_ids": ["EV-1"], "figure_refs": [], "source_citations": []}]}

        output, _ = service.assemble_final_deterministic(verification, report, ppt, claims, ["SRC-1"], ["EV-1"])

        self.assertEqual(output["final_ppt"]["pages"][0]["on_slide_text"], ["另一条结论"])
        self.assertEqual([item["action"] for item in output["change_log"]], ["removed", "removed"])

    def test_deterministic_final_cleans_punctuation_left_by_report_removal(self):
        service = WorkflowService("secret", FakeRouter(), "system", {})
        report = {"report_title": "报告", "report_markdown": "此外，，因此仍需验证。。下一步。，继续研究。", "used_evidence_ids": ["EV-1"], "open_issues": []}
        ppt = {"deck_title": "汇报", "storyline": "证据", "pages": [{
            "page_id": "P1", "title": "研究结论", "purpose": "说明后续验证", "on_slide_text": ["现有研究提出值得进一步检验的方向"],
            "visual_suggestion": "研究流程图", "speaker_notes": "现有研究给出一些线索，后续仍需独立验证。",
            "evidence_ids": ["EV-1"], "figure_refs": [], "source_citations": [],
        }]}
        verification = {"results": [], "summary": {"supported": 0, "partially_supported": 0, "unsupported": 0, "cannot_determine": 0, "high_risk_remaining": 0}}

        output, usage = service.assemble_final_deterministic(verification, report, ppt, [], ["SRC-1"], ["EV-1"])

        self.assertEqual(output["final_report"]["markdown"], "因此仍需验证。下一步。继续研究。")
        self.assertEqual(usage["total_tokens"], 0)


if __name__ == "__main__":
    unittest.main()
