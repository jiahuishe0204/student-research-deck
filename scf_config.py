"""Environment-only configuration for the SCF worker."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ScfConfig:
    database_url: str
    deepseek_api_key: str
    task_max_total_tokens: int = 600000
    task_max_cost_cny: float = 3.0


def load_scf_config(environ=None) -> ScfConfig:
    values = os.environ if environ is None else environ
    database_url = str(values.get("DATABASE_URL", "")).strip()
    api_key = str(values.get("DEEPSEEK_API_KEY", "")).strip()
    missing = [name for name, value in (("DATABASE_URL", database_url), ("DEEPSEEK_API_KEY", api_key)) if not value]
    if missing:
        raise RuntimeError("SCF 缺少必要环境变量：" + ", ".join(missing))
    try:
        tokens = int(values.get("MODEL_TASK_MAX_TOTAL_TOKENS", "600000"))
        cost = float(values.get("MODEL_TASK_MAX_COST_CNY", "3"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("模型预算环境变量格式无效") from exc
    if tokens <= 0 or cost <= 0:
        raise RuntimeError("模型预算必须为正数")
    return ScfConfig(database_url, api_key, tokens, cost)


__all__ = ["ScfConfig", "load_scf_config"]
