#!/usr/bin/env python3
"""Offline replay: apply the reviewed chronic PPT pages to saved P9 output."""

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from reviewed_page_revisions import apply_reviewed_page_revisions


TASK_ID = "TASK-9247d22f42ff"
CLAIM_IDS = {"SL-09": ["CLM-0092"], "SL-10": ["CLM-0097", "CLM-0099"],
             "SL-11": ["CLM-0104", "CLM-0105", "CLM-0106"]}


def saved_artifacts():
    connection = sqlite3.connect("file:%s?mode=ro" % (ROOT / "data/tasks.sqlite3"), uri=True)
    rows = connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=? AND kind IN ('final_delivery','claims','verification')", (TASK_ID,))
    return {kind: json.loads(payload) for kind, payload in rows}


def reviewed_pages():
    markdown = (ROOT / "docs/验证稿-慢性植入神经接口-PPT内容包.md").read_text(encoding="utf-8")
    pages = {}
    for match in re.finditer(r"(?ms)^## 第 (\d+) 页｜([^\n]+)\n(.*?)(?=^## 第 |\Z)", markdown):
        number = int(match.group(1))
        if number not in (9, 10, 11):
            continue
        body = match.group(3)
        page_id = "SL-%02d" % number
        pages[page_id] = {
            "title": match.group(2),
            "on_slide_text": re.findall(r"(?m)^- (.+)$", body.split("配图建议：", 1)[0]),
            "visual_suggestion": body.split("配图建议：", 1)[1].split("\n", 1)[0].strip(),
            "speaker_notes": body.split("讲稿：", 1)[1].split("来源：", 1)[0].strip(),
        }
    return pages


def replay():
    data = saved_artifacts()
    original = data["final_delivery"]
    by_id = {page["page_id"]: page for page in original["final_ppt"]["pages"]}
    revisions = []
    for page_id, reviewed in reviewed_pages().items():
        saved = by_id[page_id]
        for field in ("title", "visual_suggestion", "speaker_notes"):
            if saved[field] != reviewed[field]:
                revisions.append({"page_id": page_id, "field": field, "old": saved[field], "new": reviewed[field],
                                  "claim_ids": CLAIM_IDS[page_id], "reason": "依据本页 P8 核验和科学审稿修正跨字段表述"})
        if page_id == "SL-11":
            for old, new in zip(saved["on_slide_text"], reviewed["on_slide_text"]):
                if old != new:
                    revisions.append({"page_id": page_id, "field": "on_slide_text", "old": old, "new": new,
                                      "claim_ids": CLAIM_IDS[page_id], "reason": "补全残句并区分配方差异与批次一致性"})
    repaired = apply_reviewed_page_revisions(
        original, revisions, data["claims"]["claims"], data["verification"]
    )
    changed = [page_id for page_id in CLAIM_IDS if by_id[page_id] != next(
        page for page in repaired["final_ppt"]["pages"] if page["page_id"] == page_id
    )]
    print("validated pages=%d, reviewed edits=%d, changed=%s, model cost=¥0" % (
        len(repaired["final_ppt"]["pages"]), len(revisions), ",".join(changed)
    ))


if __name__ == "__main__":
    replay()
