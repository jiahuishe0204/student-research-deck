"""Fail-closed configuration for the unified production control plane.

The public demo does not load this module. EdgeOne/SCF production services must
read secrets from their server-side environment and expose only readiness
booleans through health checks.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from urllib.parse import urlparse


@dataclass(frozen=True)
class ProductionConfig:
    database_url: str
    deepseek_api_key: str
    identity_secret: str
    email_from: str
    public_origin: str
    task_max_total_tokens: int
    task_max_cost_cny: float
    ses_secret_id: str
    ses_secret_key: str
    cos_secret_id: str
    cos_secret_key: str
    ses_region: str
    ses_template_otp: int
    ses_template_completed: int
    ses_template_expiry: int
    cos_region: str
    cos_bucket: str


@dataclass(frozen=True)
class DeliveryCommonConfig:
    database_url: str
    identity_secret: str
    public_origin: str


@dataclass(frozen=True)
class SesConfig:
    email_from: str
    ses_secret_id: str
    ses_secret_key: str
    ses_region: str
    ses_template_otp: int
    ses_template_completed: int
    ses_template_expiry: int


@dataclass(frozen=True)
class CosConfig:
    cos_secret_id: str
    cos_secret_key: str
    cos_region: str
    cos_bucket: str


def _required(values, name):
    value = str(values.get(name, "")).strip()
    if not value:
        raise RuntimeError("生产环境缺少必要变量：" + name)
    return value


def load_production_config(environ=None):
    values = os.environ if environ is None else environ
    config = ProductionConfig(
        database_url=_required(values, "DATABASE_URL"),
        deepseek_api_key=_required(values, "DEEPSEEK_API_KEY"),
        identity_secret=_required(values, "IDENTITY_SECRET"),
        email_from=_required(values, "EMAIL_FROM"),
        public_origin=_required(values, "PUBLIC_ORIGIN").rstrip("/"),
        task_max_total_tokens=int(_required(values, "MODEL_TASK_MAX_TOTAL_TOKENS")),
        task_max_cost_cny=float(_required(values, "MODEL_TASK_MAX_COST_CNY")),
        ses_secret_id=_required(values, "SES_SECRET_ID"),
        ses_secret_key=_required(values, "SES_SECRET_KEY"),
        cos_secret_id=_required(values, "COS_SECRET_ID"),
        cos_secret_key=_required(values, "COS_SECRET_KEY"),
        ses_region=_required(values, "SES_REGION"),
        ses_template_otp=int(_required(values, "SES_TEMPLATE_OTP")),
        ses_template_completed=int(_required(values, "SES_TEMPLATE_COMPLETED")),
        ses_template_expiry=int(_required(values, "SES_TEMPLATE_EXPIRY")),
        cos_region=_required(values, "COS_REGION"),
        cos_bucket=_required(values, "COS_BUCKET"),
    )
    origin = urlparse(config.public_origin)
    if origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/"):
        raise RuntimeError("PUBLIC_ORIGIN 必须是无路径的 HTTPS 来源")
    if len(config.identity_secret) < 32:
        raise RuntimeError("IDENTITY_SECRET 至少需要 32 个字符")
    if "@" not in config.email_from:
        raise RuntimeError("EMAIL_FROM 格式无效")
    if config.task_max_total_tokens <= 0 or config.task_max_cost_cny <= 0:
        raise RuntimeError("生产模型预算必须为正数")
    return config


def load_delivery_common_config(environ=None):
    values = os.environ if environ is None else environ
    config = DeliveryCommonConfig(
        database_url=_required(values, "DATABASE_URL"),
        identity_secret=_required(values, "IDENTITY_SECRET"),
        public_origin=_required(values, "PUBLIC_ORIGIN").rstrip("/"),
    )
    origin = urlparse(config.public_origin)
    if origin.scheme != "https" or not origin.netloc or origin.path not in ("", "/"):
        raise RuntimeError("PUBLIC_ORIGIN 必须是无路径的 HTTPS 来源")
    if len(config.identity_secret) < 32:
        raise RuntimeError("IDENTITY_SECRET 至少需要 32 个字符")
    return config


def load_ses_config(environ=None):
    values = os.environ if environ is None else environ
    config = SesConfig(
        email_from=_required(values, "EMAIL_FROM"),
        ses_secret_id=_required(values, "SES_SECRET_ID"),
        ses_secret_key=_required(values, "SES_SECRET_KEY"),
        ses_region=_required(values, "SES_REGION"),
        ses_template_otp=int(_required(values, "SES_TEMPLATE_OTP")),
        ses_template_completed=int(_required(values, "SES_TEMPLATE_COMPLETED")),
        ses_template_expiry=int(_required(values, "SES_TEMPLATE_EXPIRY")),
    )
    if "@" not in config.email_from:
        raise RuntimeError("EMAIL_FROM 格式无效")
    return config


def load_cos_config(environ=None):
    values = os.environ if environ is None else environ
    return CosConfig(
        cos_secret_id=_required(values, "COS_SECRET_ID"),
        cos_secret_key=_required(values, "COS_SECRET_KEY"),
        cos_region=_required(values, "COS_REGION"),
        cos_bucket=_required(values, "COS_BUCKET"),
    )


def readiness(environ=None):
    values = os.environ if environ is None else environ
    names = (
        "DATABASE_URL", "DEEPSEEK_API_KEY", "IDENTITY_SECRET", "EMAIL_FROM",
        "PUBLIC_ORIGIN", "MODEL_TASK_MAX_TOTAL_TOKENS",
        "MODEL_TASK_MAX_COST_CNY",
        "SES_SECRET_ID", "SES_SECRET_KEY", "COS_SECRET_ID", "COS_SECRET_KEY", "SES_REGION",
        "SES_TEMPLATE_OTP", "SES_TEMPLATE_COMPLETED", "SES_TEMPLATE_EXPIRY",
        "COS_REGION", "COS_BUCKET",
    )
    return {name: bool(str(values.get(name, "")).strip()) for name in names}


__all__ = ["CosConfig", "DeliveryCommonConfig", "ProductionConfig", "SesConfig",
           "load_cos_config", "load_delivery_common_config", "load_production_config",
           "load_ses_config", "readiness"]
