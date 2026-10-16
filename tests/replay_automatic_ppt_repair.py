#!/usr/bin/env python3
"""Replay original P1-P8 artifacts through public P9, with no editorial input."""

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from workflow_service import WorkflowService
from tests.export_readable_delivery import delivery_markdown


def replay(task_id="TASK-9247d22f42ff"):
    with sqlite3.connect("file:%s?mode=ro" % (ROOT / "data/tasks.sqlite3"), uri=True) as connection:
        data = {kind: json.loads(payload) for kind, payload in connection.execute(
            "SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,))}
    evidence = [item for group in data["evidence"]["groups"] for item in group["evidence_records"]]
    figures = [item for group in data["evidence"]["groups"] for item in group["figure_records"]]
    before = data["final_delivery"]
    def no_model(*args, **kwargs):
        raise AssertionError("离线自动修复不得调用模型")
    service = WorkflowService("", None, "", {}, model_client=no_model)
    final, usage = service.assemble_final_deterministic(
        data["verification"], data["report"], data["ppt"], data["claims"]["claims"],
        before["source_ids"], before["evidence_ids"], evidence_records=evidence,
        source_records=data["sources"]["records"], figure_records=figures,
    )
    old_pages = {page["page_id"]: page for page in before["final_ppt"]["pages"]}
    changed = [page["page_id"] for page in final["final_ppt"]["pages"] if old_pages.get(page["page_id"]) != page]
    if task_id == "TASK-9247d22f42ff":
        assert changed == ["SL-09", "SL-10", "SL-11"], changed
        pages = {page["page_id"]: page for page in final["final_ppt"]["pages"]}
        assert "优于" not in pages["SL-09"]["title"]
        assert "效率优于" not in pages["SL-10"]["speaker_notes"]
        assert "不等同于" in pages["SL-10"]["speaker_notes"]
        assert not any(item.endswith(("，", "、")) for item in pages["SL-11"]["on_slide_text"])
        assert "批次间一致性" not in pages["SL-11"]["speaker_notes"]
    assert usage["total_tokens"] == 0
    output_dir = ROOT / "artifacts" / "automatic-boundary-replay" / task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "PPT自动修复内容包.md").write_text(delivery_markdown(final, data["sources"]["records"]), encoding="utf-8")
    summary = {"task_id": task_id, "input": "saved report/ppt/claims/verification/evidence/sources",
               "editorial_input": False, "pages": len(final["final_ppt"]["pages"]),
               "changed_pages": changed, "usage": usage, "validation": "full P9 passed",
               "verification_note": final["verification_note"]}
    (output_dir / "replay.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    replay(sys.argv[1] if len(sys.argv) > 1 else "TASK-9247d22f42ff")
