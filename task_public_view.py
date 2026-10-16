"""Small, customer-facing projections of a saved local task.

These projections do not grant access: callers must authorize task ownership first.
"""

STAGE_LABELS = {
    "P1": "确认题目", "P2": "规划研究", "P3": "筛选来源",
    "P4": "整理证据", "P5": "撰写报告", "P6": "组织汇报",
    "P7": "抽取待核验主张", "P8": "核验主张", "P9": "装配交付",
}


def progress_view(task):
    status = task["status"]
    stage = task.get("current_stage")
    if status == "completed":
        title, next_action = "交付已完成", "阅读报告与 PPT 逐页内容。"
    elif status == "failed":
        title, next_action = "任务未完成", "查看失败说明；技术失败不得消耗首次免费资格。"
    elif status == "cancelled":
        title, next_action = "任务已暂停", "确认后可从已保存阶段继续。"
    else:
        title, next_action = STAGE_LABELS.get(stage, "正在处理"), "稍后刷新任务页查看实际进度。"
    return {
        "status": status,
        "stage": stage,
        "title": title,
        "next_action": next_action,
        "updated_at": task["updated_at"],
        "delivery_available": status == "completed" and bool(task.get("artifacts", {}).get("final_delivery")),
    }


def delivery_view(task):
    if task["status"] != "completed":
        raise ValueError("任务尚未完成，不能展示正式交付")
    final = task.get("artifacts", {}).get("final_delivery", {}).get("data")
    if not isinstance(final, dict):
        raise ValueError("最终交付尚未保存")
    report = final.get("final_report") or {}
    ppt = final.get("final_ppt") or {}
    if not isinstance(report, dict) or not isinstance(report.get("markdown"), str) or not report["markdown"].strip():
        raise ValueError("最终报告不可用")
    if not isinstance(ppt, dict) or not isinstance(ppt.get("pages"), list) or not ppt["pages"]:
        raise ValueError("PPT 逐页内容不可用")
    return {
        "topic": task["topic"],
        "tier": task["tier"],
        "report": {"title": report.get("title") or task["topic"], "markdown": report["markdown"]},
        "ppt": {"title": ppt.get("deck_title") or task["topic"], "pages": ppt["pages"]},
        "open_issues": final.get("open_issues") or [],
    }
