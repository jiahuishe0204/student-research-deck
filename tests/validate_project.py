import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

required = [
    "README.md",
    "docs/产品与使用场景.md",
    "docs/智能工作流与模型路由.md",
    "docs/流量投放与运营.md",
    "config/model-routing.json",
    "web/index.html",
    "web/styles.css",
    "web/app.js",
]

for relative in required:
    path = ROOT / relative
    assert path.exists() and path.stat().st_size > 0, f"missing: {relative}"

routing = json.loads((ROOT / "config/model-routing.json").read_text())
assert routing["strategy"] == "critical_nodes_upgrade"
assert routing["tiers"]["fast"]["intent_and_plan"] == "reasoning_high"
assert routing["tiers"]["deep"]["research_planning"] == "reasoning_high"

home = (ROOT / "web/index.html").read_text()
for phrase in ["PPT逐页内容", "演讲者注释", "快速版", "深入版"]:
    assert phrase in home, f"homepage missing promise: {phrase}"

print("project validation passed")
