import unittest

from preauth_intent_ticket import issue_intent_ticket, verify_intent_ticket


SECRET = "test-signing-secret-longer-than-thirty-two-characters"
INTENT = {
    "domain": "生命科学", "normalized_topic": "CRISPR 检测", "scope_hint": "诊断机制",
    "tier": "fast", "assumptions": [], "topic_breadth": "focused",
    "direction_options": [], "need_clarification": False,
    "clarification_question": "", "confirmation_text": "研究诊断机制",
}


class IntentTicketTests(unittest.TestCase):
    def test_signed_ticket_round_trip(self):
        ticket = issue_intent_ticket("CRISPR 检测", "fast", INTENT, SECRET, now=1000)
        self.assertEqual(verify_intent_ticket(ticket, SECRET, now=1001), {
            "topic": "CRISPR 检测", "tier": "fast", "intent": INTENT,
        })

    def test_tamper_expiry_and_oversize_fail_closed(self):
        ticket = issue_intent_ticket("CRISPR 检测", "fast", INTENT, SECRET, now=1000)
        for candidate, now in (("x" + ticket, 1001), (ticket, 4601), (ticket, 999),
                               ("x" * 32769, 1001), (None, 1001)):
            with self.subTest(candidate=str(candidate)[:12], now=now):
                with self.assertRaises(ValueError):
                    verify_intent_ticket(candidate, SECRET, now=now)

    def test_short_signing_secret_fails(self):
        with self.assertRaises(RuntimeError):
            issue_intent_ticket("CRISPR 检测", "fast", INTENT, "short")


if __name__ == "__main__": unittest.main()
