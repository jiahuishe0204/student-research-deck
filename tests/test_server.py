import unittest

import server


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

    def test_plan_rejects_object_source_plan(self):
        value = {
            "research_scope": "scope", "exclusions": [],
            "questions": [{"question_id": str(i), "question": "q", "evidence_needs": []} for i in range(3)],
            "search_concepts": {}, "source_plan": {"sources": []}, "selection_criteria": [],
            "stop_conditions": [], "report_outline": [], "ppt_story_arc": [], "risks": [],
        }
        with self.assertRaises(ValueError):
            server.validate_plan(value)


if __name__ == "__main__":
    unittest.main()
