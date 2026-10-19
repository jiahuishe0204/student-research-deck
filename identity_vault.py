"""Encrypted email identity storage for the trusted control plane."""

from __future__ import annotations

import hashlib
import hmac
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


KEY_VERSION = 1


def normalize_email(email):
    value = str(email).strip().casefold()
    local, separator, domain = value.rpartition("@")
    if not separator or not local or not domain or len(value) > 254:
        raise ValueError("邮箱格式无效")
    return value


class IdentityVault:
    """Hash for lookup and AES-GCM encrypt for late-bound delivery."""

    def __init__(self, secret, repository):
        raw = str(secret).encode("utf-8")
        if len(raw) < 32:
            raise ValueError("身份密钥至少需要 32 字节")
        self._hash_key = hmac.new(raw, b"email-lookup-v1", hashlib.sha256).digest()
        self._cipher = AESGCM(hmac.new(raw, b"email-encryption-v1", hashlib.sha256).digest())
        self._repository = repository

    def email_hash(self, email):
        normalized = normalize_email(email).encode("utf-8")
        return hmac.new(self._hash_key, normalized, hashlib.sha256).hexdigest()

    def encrypt(self, user_id, email):
        nonce = os.urandom(12)
        plaintext = normalize_email(email).encode("utf-8")
        aad = ("user:" + str(user_id) + ":v1").encode("utf-8")
        return nonce + self._cipher.encrypt(nonce, plaintext, aad)

    def encrypt_challenge_value(self, challenge_id, value, purpose):
        nonce = os.urandom(12)
        aad = ("challenge:" + str(challenge_id) + ":" + purpose + ":v1").encode("utf-8")
        return nonce + self._cipher.encrypt(nonce, str(value).encode("utf-8"), aad)

    def decrypt_challenge_value(self, challenge_id, ciphertext, purpose):
        nonce, body = bytes(ciphertext[:12]), bytes(ciphertext[12:])
        aad = ("challenge:" + str(challenge_id) + ":" + purpose + ":v1").encode("utf-8")
        return self._cipher.decrypt(nonce, body, aad).decode("utf-8")

    def decrypt(self, user_id, ciphertext, key_version=KEY_VERSION):
        if key_version != KEY_VERSION or len(ciphertext) < 29:
            raise ValueError("不支持的身份密文")
        nonce, body = bytes(ciphertext[:12]), bytes(ciphertext[12:])
        aad = ("user:" + str(user_id) + ":v1").encode("utf-8")
        return self._cipher.decrypt(nonce, body, aad).decode("utf-8")

    def recipient_for_user(self, user_id):
        record = self._repository.encrypted_email_for_user(user_id)
        if not record:
            raise LookupError("用户身份不存在")
        return self.decrypt(user_id, record["email_ciphertext"], record["email_key_version"])

    def otp_material_for_challenge(self, challenge_id):
        record = self._repository.encrypted_challenge(challenge_id)
        if not record:
            raise LookupError("验证码挑战不存在或已失效")
        return {
            "recipient": self.decrypt_challenge_value(challenge_id, record["email_ciphertext"], "email"),
            "code": self.decrypt_challenge_value(challenge_id, record["code_ciphertext"], "code"),
        }


__all__ = ["IdentityVault", "KEY_VERSION", "normalize_email"]
