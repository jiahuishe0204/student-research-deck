import unittest

from quality_benchmark import score_ppt_density, score_verification


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
