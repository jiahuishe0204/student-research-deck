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
        self.assertEqual(calls[0][5:], ("high", validator, 99, 3, 12))

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

        self.assertEqual(calls, ["report", "ppt_pages_1_3", "ppt_pages_4_4"])
        self.assertEqual([item["claim_id"] for item in output["claims"]], ["CLM-0001", "CLM-0002", "CLM-0003"])
        self.assertEqual(usage["total_tokens"], 6)
        self.assertEqual(metadata["batches"], 3)

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
        base = {"atomic_claim": "same claim", "cited_evidence_ids": ["EV-1"], "risk_level": "high"}
        claims = {"claim_set_version": "1", "claims": [{**base, "claim_id": "CL-1"}, {**base, "claim_id": "CL-2"}]}
        output, usage, metadata = service.verify_claims(claims, [{"evidence_id": "EV-1"}], [{"source_id": "SRC-1"}], "fast")

        self.assertEqual(len(calls), 1)
        self.assertEqual([item["claim_id"] for item in output["results"]], ["CL-1", "CL-2"])
        self.assertEqual(usage["total_tokens"], 5)
        self.assertEqual(metadata["unique_claims"], 1)
        self.assertEqual(metadata["claims"], 2)
        self.assertEqual(metadata["reason"], "high_risk_upgrade")


if __name__ == "__main__":
    unittest.main()
