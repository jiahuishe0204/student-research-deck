#!/usr/bin/env python3
"""Export a completed live-regression task into a read-only static web case."""
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tests.export_readable_delivery import delivery_markdown, report_reference_style

TASK_ID = "TASK-fc65f4495743"


def main():
    db_path = ROOT / "data" / "tasks.sqlite3"
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    task = connection.execute("SELECT topic,status FROM tasks WHERE task_id=?", (TASK_ID,)).fetchone()
    if not task or task["status"] != "completed":
        raise SystemExit("Refusing to export: task missing or not completed")
    artifacts = {row["kind"]: json.loads(row["payload_json"]) for row in connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=?", (TASK_ID,))}
    connection.close()
    final = artifacts["final_delivery"]
    source_pages = {page["page_id"]: page for page in artifacts["ppt"]["pages"]}
    for page in final["final_ppt"]["pages"]:
        source = source_pages.get(page["page_id"])
        if not source or source.get("title") != page.get("title"):
            raise SystemExit("Refusing to export: navigation title cannot be safely reconciled with final title for %s" % page.get("page_id"))
        page["navigation_title"] = source["navigation_title"]
    report = report_reference_style(final["final_report"]["markdown"], artifacts["sources"]["records"])
    slides = delivery_markdown(final, artifacts["sources"]["records"])
    slides = re.sub(r"（引用证据应改为EV::[^）]+）", "", slides)
    if "EV::" in report or "EV::" in slides:
        raise SystemExit("Refusing to export: internal evidence identifiers remain in customer-visible text")
    out = ROOT / "web"
    (out / "single-cell-delivery-data.js").write_text(
        "window.DELIVERY_SAMPLE=" + json.dumps({"report": report, "slides": slides}, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    (out / "single-cell-report.md").write_text(report.rstrip() + "\n", encoding="utf-8")
    (out / "single-cell-ppt-content.md").write_text(slides, encoding="utf-8")
    print("Exported completed task %s (%s)" % (TASK_ID, task["topic"]))


if __name__ == "__main__":
    main()
