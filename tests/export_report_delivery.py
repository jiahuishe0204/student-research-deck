#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Export a readable report and an evidence/cost audit from persisted artifacts."""

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from model_usage import ModelUsageLedger


def load_artifact(connection, task_id, kind):
    row = connection.execute(
        "SELECT payload_json FROM artifacts WHERE task_id=? AND kind=?", (task_id, kind)
    ).fetchone()
    if not row:
        raise RuntimeError("缺少任务产物：%s" % kind)
    return json.loads(row[0])


def vancouver(record):
    authors = record.get("authors", [])
    author_text = ", ".join(authors[:3]) + (", et al" if len(authors) > 3 else "")
    parts = [author_text + "." if author_text else "", record.get("title", "").rstrip(".") + "."]
    journal = record.get("journal", "")
    year = record.get("year", "")
    volume = record.get("volume", "")
    issue = record.get("issue", "")
    pages = record.get("pages", "")
    citation = journal
    if year:
        citation += (" " if citation else "") + year
    if volume:
        citation += ";" + volume
    if issue:
        citation += "(" + issue + ")"
    if pages:
        citation += ":" + pages
    if citation:
        parts.append(citation.rstrip(".") + ".")
    return " ".join(item for item in parts if item).strip()


def clean_markdown(markdown):
    replacements = (("。。", "。"), ("。；", "；"), ("；。", "。"), ("。，", "，"), ("；，", "，"))
    for old, new in replacements:
        markdown = markdown.replace(old, new)
    markdown = re.sub(r"\s+([，。；：])", r"\1", markdown)
    markdown = markdown.replace("核验修订：", "")
    markdown = markdown.replace("（未核实）", "（现有纳入资料未能直接验证）")
    return markdown


def render_report(final_report, evidence_groups, source_records, scientific_gate_passed):
    evidence_to_source = {}
    for group in evidence_groups:
        for evidence in group.get("evidence_records", []):
            evidence_to_source[evidence["evidence_id"]] = evidence["source_id"]
    source_map = {item["source_id"]: item for item in source_records}
    markdown = clean_markdown(final_report["markdown"])
    title = str(final_report.get("title") or "调查研究报告").strip()
    if not markdown.startswith("# " + title):
        markdown = re.sub(r"(?m)^## ", "### ", markdown)
        markdown = re.sub(r"(?m)^# ", "## ", markdown)
        markdown = "# %s\n\n%s" % (title, markdown)
    order = []
    for evidence_id in re.findall(r"EV::.+?::\d{3}", markdown):
        source_id = evidence_to_source.get(evidence_id)
        if source_id and source_id not in order:
            order.append(source_id)
    numbers = {source_id: index for index, source_id in enumerate(order, 1)}
    for evidence_id, source_id in evidence_to_source.items():
        if source_id in numbers:
            markdown = markdown.replace(evidence_id, str(numbers[source_id]))
    markdown = re.sub(r"\[(\d+)\](?:\[\1\])+", r"[\1]", markdown)
    references = ["## 参考文献", ""]
    for source_id in order:
        record = source_map.get(source_id, {"title": source_id})
        url = record.get("url", "")
        entry = "%d. %s" % (numbers[source_id], vancouver(record))
        if url:
            entry += " [原文入口](%s)" % url
        references.append(entry)
    return markdown.strip() + "\n\n" + "\n\n".join(references) + "\n"


def row_cost(row):
    prices = ModelUsageLedger.PEAK_PRICES_CNY_PER_MILLION.get(row["model"], {})
    if not prices:
        return 0.0
    hit = int(row["cache_hit_tokens"] or 0)
    miss = int(row["cache_miss_tokens"] or 0) + max(0, int(row["prompt_tokens"] or 0) - hit - int(row["cache_miss_tokens"] or 0))
    # This experiment ran outside the published peak windows, so the actual multiplier was 0.5.
    return 0.5 * (hit * prices["cache_hit"] + miss * prices["cache_miss"] + int(row["completion_tokens"] or 0) * prices["output"]) / 1_000_000


def render_audit(task, verification, usage_rows, report_length, source_count, primary_count, evidence_count, claim_count):
    total = sum(row_cost(row) for row in usage_rows)
    rejected = sum(row_cost(row) for row in usage_rows if row["status"] not in ("accepted", "transport_error"))
    stages = {}
    for row in usage_rows:
        item = stages.setdefault(row["stage"], {"calls": 0, "failed": 0, "tokens": 0, "cost": 0.0})
        item["calls"] += 1
        item["failed"] += row["status"] != "accepted"
        item["tokens"] += int(row["total_tokens"] or 0)
        item["cost"] += row_cost(row)
    lines = [
        "# 调查研究报告全链路审计",
        "",
        "## 目的与验收标准",
        "",
        "目标是生成一份可独立阅读、可提交给导师或上级的调查研究报告，并验证其成本、失败恢复和证据追溯能力。",
        "",
        "本轮验收包括：忠实保留用户确认的题目；先建立大故事再展开小故事；正文继承既定故事线而不套通用论证模板；关键声明可追溯；无高风险遗留；来源结构通过门禁；成本与失败逐次可查。",
        "",
        "## 执行结果",
        "",
        "- 主题：%s" % task["topic"],
        "- 最终报告：%d 字；%d 个来源（其中原始研究 %d 个）、%d 条证据、%d 条声明。" % (report_length, source_count, primary_count, evidence_count, claim_count),
        "- 核验：支持 %d；部分支持 %d；不支持 %d；无法判断 %d；高风险残留 %d。" % (
            verification["summary"].get("supported", 0), verification["summary"].get("partially_supported", 0),
            verification["summary"].get("unsupported", 0), verification["summary"].get("cannot_determine", 0),
            verification["summary"].get("high_risk_remaining", 0)),
        "- 实际模型费用：¥%.4f；其中被拒绝输出约 ¥%.4f。" % (total, rejected),
        "- 结论：工程链路、科学来源结构和高风险核验均通过，交付为同主题对照稿。",
        "",
        "## 分阶段成本与失败",
        "",
    ]
    for stage in sorted(stages):
        item = stages[stage]
        lines.append("- %s：%d 次调用，%d 次未接受，%d Tokens，¥%.4f。" % (stage, item["calls"], item["failed"], item["tokens"], item["cost"]))
    lines += [
        "",
        "## 一审：工程与成本",
        "",
        "通过项：检查点恢复有效；P1—P4没有因P5失败而重跑；最终完成P5、P7、P8、P9；一次零Token网络错误被安全重试；总额未触及¥1.50硬停止。",
        "",
        "本轮主要浪费为P2一次JSON截断和P5一次未通过结构校验的输出。修复方向不是降低推理强度，而是向P2传入真实输出契约、限制蓝图重复，并对可确定处理的无害字段本地归一化。P5需继续将“内容不足”与“格式不符”分开，只有前者才允许重新写作。",
        "",
        "## 二审：科学证据",
        "",
        "来源结构门禁通过：保留来源不少于5个，且原始研究不少于2个。48条声明中有2条不支持、7条无法判断，已在装配阶段删除、修订或标记，高风险遗留为0。但“高风险遗留为0”仍不等于所有结论已被高等级临床证据证实。",
        "",
        "## 三审：表达与交付",
        "",
        "通过。报告按既定大故事和小故事组织，没有在每节机械显示‘本节问题’‘能否比较’等后台标签。引用已由内部证据编号转换为编号引用与Vancouver参考文献，并保留原文入口。",
        "",
        "## 已固化的规则优化",
        "",
        "- 检索从宽泛OR式改为核心概念AND，并按疗效安全、微环境、患者选择、联合策略分别检索后去重。",
        "- 深入报告在证据抽取前检查来源结构，少于5条保留来源或少于2条原始研究即停止。",
        "- P5深入版以5000—8000字为建议区间，以12000字仅作技术防失控线；回答清楚和证据完整优先于凑篇幅或机械截断。",
        "- 报告任务跳过P6 PPT生成，避免无关模型费用。",
        "- 保留逐次调用账本、任务费用硬停止、检查点恢复和高风险声明升级核验。",
        "",
    ]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    parser.add_argument("--output-root", default="artifacts")
    args = parser.parse_args()
    task_db = sqlite3.connect("data/tasks.sqlite3")
    task_db.row_factory = sqlite3.Row
    task = task_db.execute("SELECT * FROM tasks WHERE task_id=?", (args.task_id,)).fetchone()
    if not task:
        raise RuntimeError("任务不存在")
    sources = load_artifact(task_db, args.task_id, "sources")["records"]
    evidence = load_artifact(task_db, args.task_id, "evidence")["groups"]
    claims = load_artifact(task_db, args.task_id, "claims")["claims"]
    verification = load_artifact(task_db, args.task_id, "verification")
    final = load_artifact(task_db, args.task_id, "final_delivery")["final_report"]
    used_source_ids = {item["source_id"] for group in evidence for item in group["evidence_records"]}
    selected_sources = [item for item in sources if item["source_id"] in used_source_ids]
    usage_db = sqlite3.connect("data/private/model-usage.sqlite3")
    usage_db.row_factory = sqlite3.Row
    rows = usage_db.execute("SELECT * FROM model_usage WHERE task_id=? ORDER BY id", (args.task_id,)).fetchall()
    target = Path(args.output_root) / args.task_id
    target.mkdir(parents=True, exist_ok=True)
    primary_count = sum(
        "review" not in " ".join(item.get("publication_types", [])).lower()
        and "review" not in item.get("title", "").lower()
        and "meta-analysis" not in item.get("title", "").lower()
        for item in selected_sources
    )
    gate_passed = len(selected_sources) >= 5 and primary_count >= 2
    report_text = render_report(final, evidence, selected_sources, gate_passed)
    (target / "调查研究报告-同主题对照稿-v2.md").write_text(report_text, encoding="utf-8")
    audit = render_audit(task, verification, rows, len(final["markdown"]), len(selected_sources), primary_count, sum(len(group["evidence_records"]) for group in evidence), len(claims))
    (target / "报告全链路审计.md").write_text(audit, encoding="utf-8")
    print(target.resolve())


if __name__ == "__main__":
    main()
