import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from identity_store import LocalIdentityStore


class LocalIdentityStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = LocalIdentityStore(Path(self.temp.name) / "identity.sqlite3", b"local-test-secret-with-32-plus-bytes")
        self.now = datetime(2026, 10, 15, tzinfo=timezone.utc)

    def tearDown(self):
        self.temp.cleanup()

    def login(self, email="Student@Example.edu"):
        code, _ = self.store.issue_code(email, self.now)
        return self.store.verify_code(email, code, self.now + timedelta(seconds=1))

    def test_code_is_hashed_single_use_and_expires(self):
        code, _ = self.store.issue_code("Student@Example.edu", self.now)
        with self.store.connect() as db:
            row = db.execute("SELECT * FROM email_challenges").fetchone()
        self.assertNotEqual(row["code_hash"], code)
        self.assertNotIn("Student@Example.edu", str(dict(row)))
        token = self.store.verify_code("student@example.edu", code, self.now + timedelta(minutes=9))
        self.assertIsNotNone(self.store.session_email_hash(token, self.now + timedelta(minutes=9)))
        with self.assertRaisesRegex(ValueError, "无效"):
            self.store.verify_code("student@example.edu", code, self.now + timedelta(minutes=9))
        self.store.issue_code("student@example.edu", self.now + timedelta(minutes=11))
        with self.assertRaisesRegex(ValueError, "无效"):
            self.store.verify_code("student@example.edu", code, self.now + timedelta(minutes=22))

    def test_code_expires_at_exactly_ten_minutes(self):
        code, _ = self.store.issue_code("student@example.edu", self.now)
        with self.assertRaisesRegex(ValueError, "过期"):
            self.store.verify_code("student@example.edu", code, self.now + timedelta(minutes=10))

    def test_resend_attempt_limit_and_unsent_revocation(self):
        code, challenge_id = self.store.issue_code("student@example.edu", self.now)
        with self.assertRaisesRegex(ValueError, "60 秒"):
            self.store.issue_code("student@example.edu", self.now + timedelta(seconds=59))
        for _ in range(5):
            with self.assertRaisesRegex(ValueError, "无效"):
                self.store.verify_code("student@example.edu", "000000" if code != "000000" else "999999", self.now)
        with self.assertRaisesRegex(ValueError, "无效"):
            self.store.verify_code("student@example.edu", code, self.now)
        self.store.revoke_code("student@example.edu", challenge_id)
        with self.assertRaisesRegex(ValueError, "无效"):
            self.store.verify_code("student@example.edu", code, self.now)

    def test_free_entitlement_reserve_release_consume_and_no_reset_on_relogin(self):
        token = self.login()
        self.assertEqual(self.store.entitlement_state(token, self.now), "available")
        self.store.reserve_fast(token, "TASK-1", self.now)
        with self.assertRaisesRegex(ValueError, "预留"):
            self.store.reserve_fast(token, "TASK-2", self.now)
        self.assertEqual(self.store.settle_fast("TASK-1", "worker_timeout", self.now), "available")
        self.store.reserve_fast(token, "TASK-2", self.now)
        self.assertEqual(self.store.settle_fast("TASK-2", "partial", self.now), "consumed")
        self.store.issue_code("student@example.edu", self.now + timedelta(minutes=1))
        newer_code, _ = self.store.issue_code("student@example.edu", self.now + timedelta(minutes=2))
        second = self.store.verify_code("student@example.edu", newer_code, self.now + timedelta(minutes=2))
        self.assertEqual(self.store.entitlement_state(second, self.now + timedelta(minutes=2)), "consumed")
        with self.assertRaisesRegex(ValueError, "已使用"):
            self.store.reserve_fast(second, "TASK-3", self.now + timedelta(minutes=2))

    def test_concurrent_reservation_only_one_wins(self):
        token = self.login()
        def reserve(task_id):
            try:
                self.store.reserve_fast(token, task_id, self.now)
                return True
            except ValueError:
                return False
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(reserve, ("TASK-A", "TASK-B")))
        self.assertEqual(results.count(True), 1)
        self.assertEqual(results.count(False), 1)

    def test_session_revocation_and_expiry(self):
        token = self.login()
        self.store.revoke_session(token, self.now)
        with self.assertRaises(PermissionError):
            self.store.reserve_fast(token, "TASK-1", self.now)
        second, _ = self.store.issue_code("student@example.edu", self.now + timedelta(minutes=1))
        session = self.store.verify_code("student@example.edu", second, self.now + timedelta(minutes=1))
        self.assertIsNone(self.store.session_email_hash(session, self.now + timedelta(days=8)))

    def test_failed_send_revocation_does_not_delete_newer_code(self):
        with patch("identity_store.secrets.randbelow", side_effect=[111111, 222222]):
            _, older_id = self.store.issue_code("student@example.edu", self.now)
            newer, _ = self.store.issue_code("student@example.edu", self.now + timedelta(minutes=1))
        self.store.revoke_code("student@example.edu", older_id)
        token = self.store.verify_code("student@example.edu", newer, self.now + timedelta(minutes=1))
        self.assertTrue(self.store.session_email_hash(token, self.now + timedelta(minutes=1)))


if __name__ == "__main__":
    unittest.main()
