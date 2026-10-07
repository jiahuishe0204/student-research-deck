import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

required = [
    "README.md",
    "docs/产品与使用场景.md",
    "docs/智能工作流与模型路由.md",
    "docs/流量投放与运营.md",
    "config/model-routing.json",
    "model_routing.py",
    "model_client.py",
    "workflow_validation.py",
    "workflow_service.py",
    "server.py",
    "retrieval.py",
    "web/index.html",
    "web/mvp.css",
    "web/styles.css",
    "web/app.js",
]

for relative in required:
    path = ROOT / relative
    assert path.exists() and path.stat().st_size > 0, f"missing: {relative}"

routing = json.loads((ROOT / "config/model-routing.json").read_text())
assert routing["strategy"] == "critical_nodes_upgrade"
assert routing["tiers"]["fast"]["intent_detection"]["model"] == "deepseek-flash"
assert routing["tiers"]["fast"]["intent_detection"]["thinking"] == "disabled"
assert routing["tiers"]["deep"]["research_planning"]["model"] == "deepseek-v4-pro"
assert routing["pricing_snapshot"]["deepseek-v4-pro"]["output"]["peak"] == 27.0
server_source = (ROOT / "server.py").read_text()
assert '"deepseek-flash"' not in server_source, "server should obtain model IDs from model-routing.json"
assert '"deepseek-v4-pro"' not in server_source, "server should obtain model IDs from model-routing.json"

home = (ROOT / "web/index.html").read_text()
normalized_home = home.replace(" ", "")
for phrase in ["PPT逐页内容", "演讲者注释", "快速版", "深入版"]:
    assert phrase in normalized_home, f"homepage missing promise: {phrase}"
for removed_field in ['id="occasion"', 'id="duration"']:
    assert removed_field not in home, f"homepage should not require: {removed_field}"
assert "追问一个问题" in home
app = (ROOT / "web/app.js").read_text()
assert "/api/intent" in app
assert "/api/plan" in app
assert "/api/search" in app
assert "tier:currentTier" in app, "frontend must preserve the selected tier across later stages"

print("project validation passed")
