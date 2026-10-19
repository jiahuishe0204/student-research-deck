import unittest
from unittest.mock import patch

from delivery_scf_entrypoint import main_handler


class DeliveryScfEntrypointTests(unittest.TestCase):
    @patch("delivery_scf_entrypoint.execute_one",return_value={"status":"idle"})
    @patch("delivery_scf_entrypoint.recover_expired_email_leases",return_value=[])
    def test_outbox_timer_quarantines_ambiguous_leases_first(self,recover,execute):
        deps={"connection":object(),"vault":object(),"mailer":object()}
        result=main_handler({"action":"outbox"},dependencies=deps)
        self.assertEqual(result["quarantined_count"],0)
        self.assertEqual(result["status"],"idle")

    @patch("delivery_scf_entrypoint.run_retention_cycle",return_value={"reminders_due":0,"expired":2,"failures":[],"expired_challenges_cleared":0})
    def test_retention_timer(self,run):
        result=main_handler({"action":"retention"},dependencies={"repository":object(),"lifecycle":object()})
        self.assertEqual(result["expired"],2)


if __name__ == "__main__": unittest.main()
