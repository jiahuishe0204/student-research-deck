"""Tencent SES and COS adapters for private customer delivery.

Imports are lazy so offline tests and the public demo never require cloud SDKs.
Callers remain responsible for task ownership checks before requesting a URL.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass


ALLOWED_KINDS = frozenset({"otp", "completed", "expiry"})
CONTENT_TYPES = frozenset({"application/pdf", "text/markdown; charset=utf-8", "application/json"})


def private_object_key(task_id, artifact_id, extension):
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", str(task_id)):
        raise ValueError("任务标识无效")
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,80}", str(artifact_id)):
        raise ValueError("产物标识无效")
    if not re.fullmatch(r"[a-z0-9]{1,8}", str(extension)):
        raise ValueError("文件扩展名无效")
    return "deliveries/%s/%s.%s" % (task_id, artifact_id, extension)


@dataclass(frozen=True)
class StoredArtifact:
    key: str
    sha256: str
    size_bytes: int
    etag: str


class TencentSesMailer:
    def __init__(self, client, from_address, template_ids):
        self.client = client
        self.from_address = from_address
        self.template_ids = dict(template_ids)

    @classmethod
    def from_config(cls, config):  # pragma: no cover - exercised in cloud smoke test
        from tencentcloud.common import credential
        from tencentcloud.ses.v20201002 import ses_client
        cred = credential.Credential(config.ses_secret_id, config.ses_secret_key)
        return cls(ses_client.SesClient(cred, config.ses_region), config.email_from, {
            "otp": config.ses_template_otp,
            "completed": config.ses_template_completed,
            "expiry": config.ses_template_expiry,
        })

    def send_template(self, kind, destination, variables):
        if kind not in ALLOWED_KINDS or kind not in self.template_ids:
            raise ValueError("邮件模板类型无效")
        if not isinstance(destination, str) or len(destination) > 254 or "@" not in destination:
            raise ValueError("收件地址无效")
        safe = {str(key): str(value) for key, value in dict(variables).items()}
        if any(len(value) > 500 for value in safe.values()):
            raise ValueError("邮件模板变量过长")
        try:
            from tencentcloud.ses.v20201002 import models
            request = models.SendEmailRequest()
            request.FromEmailAddress = self.from_address
            request.Destination = [destination]
            template = models.Template()
            template.TemplateID = int(self.template_ids[kind])
            template.TemplateData = json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
            request.Template = template
            response = self.client.SendEmail(request)
            return {"message_id": str(response.MessageId), "request_id": str(response.RequestId)}
        except ImportError:
            # Test clients accept a neutral payload and never see cloud secrets.
            response = self.client.send_email({
                "from": self.from_address, "destination": destination,
                "template_id": int(self.template_ids[kind]), "variables": safe,
            })
            return {"message_id": str(response["message_id"]), "request_id": str(response["request_id"])}


class TencentCosArtifactStore:
    def __init__(self, client, bucket):
        self.client = client
        self.bucket = bucket

    @classmethod
    def from_config(cls, config):  # pragma: no cover - exercised in cloud smoke test
        from qcloud_cos import CosConfig, CosS3Client
        cos_config = CosConfig(Region=config.cos_region, SecretId=config.cos_secret_id,
                               SecretKey=config.cos_secret_key, Scheme="https")
        return cls(CosS3Client(cos_config), config.cos_bucket)

    def upload(self, key, body, content_type):
        if not key.startswith("deliveries/") or ".." in key:
            raise ValueError("对象键无效")
        if content_type not in CONTENT_TYPES:
            raise ValueError("交付文件类型无效")
        payload = body.encode("utf-8") if isinstance(body, str) else bytes(body)
        if not payload or len(payload) > 50 * 1024 * 1024:
            raise ValueError("交付文件大小无效")
        digest = hashlib.sha256(payload).hexdigest()
        response = self.client.put_object(
            Bucket=self.bucket, Key=key, Body=payload, ContentType=content_type,
            ServerSideEncryption="AES256", Metadata={"sha256": digest},
        )
        return StoredArtifact(key, digest, len(payload), str(response.get("ETag", "")).strip('"'))

    def signed_download(self, key, filename, expires_seconds=600):
        if not key.startswith("deliveries/") or ".." in key:
            raise ValueError("对象键无效")
        if not 30 <= int(expires_seconds) <= 600:
            raise ValueError("下载链接有效期必须为30—600秒")
        safe_name = re.sub(r"[^0-9A-Za-z._-]+", "_", str(filename))[:100] or "delivery"
        return self.client.get_presigned_download_url(
            Bucket=self.bucket, Key=key,
            Params={"response-content-disposition": 'attachment; filename="%s"' % safe_name},
            Expired=int(expires_seconds),
        )

    def signed_download_before(self, key, filename, expires_at, now):
        remaining = int((expires_at - now).total_seconds())
        if remaining < 30:
            raise PermissionError("交付文件已到期或即将到期")
        return self.signed_download(key, filename, min(600, remaining))

    def delete(self, key):
        if not key.startswith("deliveries/") or ".." in key:
            raise ValueError("对象键无效")
        self.client.delete_object(Bucket=self.bucket, Key=key)


__all__ = ["StoredArtifact", "TencentSesMailer", "TencentCosArtifactStore", "private_object_key"]
