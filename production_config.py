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
    email_provider_api_key: str
    email_from: str
    artifact_bucket: str
    public_origin: str
    task_max_total_tokens: int
    task_max_cost_cny: float


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
        email_provider_api_key=_required(values, "EMAIL_PROVIDER_API_KEY"),
        email_from=_required(values, "EMAIL_FROM"),
        artifact_bucket=_required(values, "ARTIFACT_BUCKET"),
        public_origin=_required(values, "PUBLIC_ORIGIN").rstrip("/"),
        task_max_total_tokens=int(_required(values, "MODEL_TASK_MAX_TOTAL_TOKENS")),
        task_max_cost_cny=float(_required(values, "MODEL_TASK_MAX_COST_CNY")),
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


def readiness(environ=None):
    values = os.environ if environ is None else environ
    names = (
        "DATABASE_URL", "DEEPSEEK_API_KEY", "IDENTITY_SECRET",
        "EMAIL_PROVIDER_API_KEY", "EMAIL_FROM", "ARTIFACT_BUCKET",
        "PUBLIC_ORIGIN", "MODEL_TASK_MAX_TOTAL_TOKENS",
        "MODEL_TASK_MAX_COST_CNY",
    )
    return {name: bool(str(values.get(name, "")).strip()) for name in names}


__all__ = ["ProductionConfig", "load_production_config", "readiness"]
