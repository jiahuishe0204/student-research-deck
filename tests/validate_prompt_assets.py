import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
registry = json.loads((ROOT / "config/prompt-stages.json").read_text())
stage_ids = [s["id"] for s in registry["stages"]]
assert stage_ids == ["P1", "P2", "P2A", "P2B", "P3", "P4", "P5", "P6", "P7", "P8", "P9"]
assert {f"P{i}" for i in range(1, 10)} <= set(stage_ids)
assert (ROOT / registry["global_prompt"]).exists()

for stage in registry["stages"]:
    assert (ROOT / stage["prompt"]).exists(), stage["prompt"]
    schema = json.loads((ROOT / stage["output_schema"]).read_text())
    assert schema["type"] == "object"

system = (ROOT / registry["global_prompt"]).read_text()
for number in range(1, 15):
    assert f"【{number}." in system, f"global prompt missing section {number}"

cases = json.loads((ROOT / "tests/fixtures/prompt-cases.json").read_text())["cases"]
assert len(cases) >= 10
assert {c["stage"] for c in cases} >= {"P1", "P2", "P5", "P6", "P8"}
assert any("figure" in c["id"] for c in cases)
print("prompt asset validation passed")
