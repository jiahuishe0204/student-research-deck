"""Configuration-backed model selection for every workflow stage."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent
STAGE_CAPABILITIES = {
    "P1": "intent_detection",
    "P2": "research_planning",
    "P2A": "research_planning",
    "P2B": "planning_synthesis",
    "P3": "retrieval_screening",
    "P4": "content_generation",
    "P5": "content_generation",
    "P6": "ppt_storyboard",
    "P7": "content_generation",
    "P8": "high_risk_verification",
    "P9": "content_generation",
}


class ModelRoutingError(ValueError):
    pass


class ModelRouter:
    def __init__(self, config):
        self.config = config
        tiers = config.get("tiers")
        if not isinstance(tiers, dict) or not all(tier in tiers for tier in ("fast", "deep")):
            raise ModelRoutingError("模型路由缺少 fast/deep 配置")

    @classmethod
    def from_file(cls, path=None):
        target = Path(path) if path else ROOT / "config" / "model-routing.json"
        return cls(json.loads(target.read_text(encoding="utf-8")))

    def for_stage(self, stage, tier="fast", upgrade=False):
        if tier not in ("fast", "deep"):
            raise ModelRoutingError("未知产品版本: %s" % tier)
        capability = STAGE_CAPABILITIES.get(stage)
        if capability is None:
            raise ModelRoutingError("未知工作流阶段: %s" % stage)
        entry = self.config["tiers"][tier].get(capability)
        if not isinstance(entry, dict) or not entry.get("model"):
            raise ModelRoutingError("阶段 %s 缺少模型配置" % stage)

        selected = entry
        model = entry["model"]
        if upgrade:
            model = entry.get("upgrade_model") or self.config["tiers"]["deep"][capability]["model"]
            if entry.get("upgrade_reasoning_effort"):
                selected = {"thinking": "enabled", "reasoning_effort": entry["upgrade_reasoning_effort"]}
            elif model == self.config["tiers"]["deep"][capability]["model"]:
                selected = self.config["tiers"]["deep"][capability]

        thinking = selected.get("thinking", "disabled")
        effort = selected.get("reasoning_effort", "none") if thinking == "enabled" else "none"
        return {"model": model, "effort": effort, "capability": capability, "upgraded": bool(upgrade)}
