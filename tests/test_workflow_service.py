import unittest
import json
import tempfile
from pathlib import Path

from workflow_service import WorkflowService


class FakeRouter:
    def for_stage(self, stage, tier, upgrade=False):
        return {"model": "%s-%s" % (stage, tier), "effort": "high" if upgrade else "none", "upgraded": upgrade}


class WorkflowServiceTests(unittest.TestCase):
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
        service = WorkflowService("secret", FakeRouter(), "system", {"P2": "plan"})
        captured = {}

        def generate(stage, tier, payload, validator=None, **options):
            captured.update(payload)
            output = {
                "research_scope": "scope", "exclusions": [],
                "questions": [{"question_id": str(i), "question": "q", "evidence_needs": []} for i in range(3)],
                "search_concepts": {}, "source_plan": [], "selection_criteria": [], "stop_conditions": [],
                "report_outline": [], "ppt_story_arc": [], "risks": [],
            }
            return output, {"total_tokens": 1}, {}

        service.generate = generate
        service.create_plan("主题", "只看临床", "deep")

        self.assertIn("EPO OPS", captured["available_sources"])
        self.assertIn("只看临床", captured["intent"]["normalized_topic"])
        self.assertEqual(captured["runtime_config"]["source_limit"], 19)

    def test_metadata_only_evidence_skips_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P4": "evidence"})
        service.generate = lambda *args, **kwargs: self.fail("metadata-only source must not call model")
        output, usage = service.extract_evidence(
            {"source_id": "EPO:EP.1.A1", "source": "EPO OPS", "abstract": "", "access": "patent_bibliographic_metadata"},
            ["Q1"], "fast",
        )
        self.assertEqual(output["extraction_status"], "no_extractable_evidence")
        self.assertEqual(usage["total_tokens"], 0)

    def test_service_rejects_duplicate_evidence_before_model_call(self):
        service = WorkflowService("secret", FakeRouter(), "system", {"P5": "report"})
        service.generate = lambda *args, **kwargs: self.fail("invalid input must not call model")
        evidence = [{"evidence_id": "EV-1"}, {"evidence_id": "EV-1"}]
        with self.assertRaisesRegex(ValueError, "重复"):
            service.create_report({}, {}, evidence, "fast")

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


if __name__ == "__main__":
    unittest.main()
