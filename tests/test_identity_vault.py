import unittest

from identity_vault import IdentityVault, normalize_email


class Repository:
    def __init__(self): self.record = None
    def encrypted_email_for_user(self, user_id): return self.record
    def encrypted_challenge(self, challenge_id): return self.record


class IdentityVaultTests(unittest.TestCase):
    def test_round_trip_binds_ciphertext_to_user(self):
        repository = Repository(); vault = IdentityVault("s" * 32, repository)
        encrypted = vault.encrypt("u1", " User@Example.COM ")
        self.assertNotIn(b"user@example.com", encrypted)
        repository.record = {"email_ciphertext": encrypted, "email_key_version": 1}
        self.assertEqual(vault.recipient_for_user("u1"), "user@example.com")
        with self.assertRaises(Exception): vault.decrypt("u2", encrypted)

    def test_hash_is_stable_but_keyed(self):
        first = IdentityVault("a" * 32, Repository())
        second = IdentityVault("b" * 32, Repository())
        self.assertEqual(first.email_hash("A@EXAMPLE.com"), first.email_hash("a@example.com"))
        self.assertNotEqual(first.email_hash("a@example.com"), second.email_hash("a@example.com"))

    def test_rejects_invalid_address_and_short_key(self):
        with self.assertRaises(ValueError): normalize_email("not-an-email")
        with self.assertRaises(ValueError): IdentityVault("short", Repository())

    def test_otp_material_is_encrypted_outside_outbox(self):
        repository=Repository(); vault=IdentityVault("s"*32,repository); challenge="c1"
        repository.record={"email_ciphertext":vault.encrypt_challenge_value(challenge,"u@example.com","email"),
                           "code_ciphertext":vault.encrypt_challenge_value(challenge,"123456","code")}
        self.assertEqual(vault.otp_material_for_challenge(challenge),
                         {"recipient":"u@example.com","code":"123456"})


if __name__ == "__main__": unittest.main()
