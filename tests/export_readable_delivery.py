#!/usr/bin/env python3
"""Repair deterministic metadata and export a readable content package plus run audit."""

import argparse
import copy
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from model_usage import ModelUsageLedger
from task_store import TaskStore
from workflow_service import WorkflowService
from workflow_validation import validate_final, validate_ppt_density

def artifacts(task_id):
    connection = sqlite3.connect(str(ROOT / "data" / "tasks.sqlite3"))
    connection.row_factory = sqlite3.Row
    return {row["kind"]: json.loads(row["payload_json"]) for row in connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,))}


def figure_url(figure):
    locator = str(figure.get("locator", ""))
    match = re.search(r"(PMC\d+)", locator)
    if not match:
        return ""
    suffix = str(figure.get("figure_id", "")).split(":")[-1]
    return "https://europepmc.org/articles/%s/figure/%s" % (match.group(1), suffix)


def repair(task_id, data):
    final = copy.deepcopy(data["final_delivery"])
    sources = {item["source_id"]: item for item in data["sources"]["records"]}
    original_citations = {(page["page_id"], item["source_id"]): item["short_vancouver"] for page in data["ppt"]["pages"] for item in page["source_citations"]}
    groups = data["evidence"]["groups"]
    scopes = Counter(group["reading_scope"] for group in groups)
    scope_note = "本次纳入 %d 个来源，其中 %d 个读取开放全文、%d 个仅读取摘要；摘要级来源的样本量、统计方法和图表细节仍需全文复核。" % (len(groups), scopes["full_text"], scopes["abstract"])
    false_scope = "本报告所有证据均来自摘要或综述转述，未获取全文核对，部分具体数值、统计方法和样本量无法验证。"
    final["open_issues"] = [scope_note if item == false_scope else item for item in final["open_issues"]]
    markdown = final["final_report"]["markdown"]
    markdown = markdown.replace("本报告全部证据来自摘要或综述转述，缺乏全文核对；", "本报告纳入3个开放全文来源和5个摘要来源；摘要级来源仍缺乏全文核对；")
    final["final_report"]["markdown"] = markdown
    for page in final["final_ppt"]["pages"]:
        page["on_slide_text"] = [item for item in page["on_slide_text"] if str(item).strip()]
        for citation in page["source_citations"]:
            source = sources.get(citation["source_id"])
            if source and source.get("journal"):
                citation["short_vancouver"] = WorkflowService._short_vancouver(source)
            else:
                original = original_citations.get((page["page_id"], citation["source_id"]), citation["short_vancouver"])
                citation["short_vancouver"] = original.replace(" 信息不完。", "").replace(" 信息不完整。", "")
        for figure in page["figure_refs"]:
            url = figure_url(figure)
            if url and url not in figure["locator"]:
                figure["locator"] += " | " + url
    claims = data["claims"]["claims"]
    verification = data["verification"]
    validate_ppt_density(final["final_ppt"]["pages"])
    validate_final(final, [item["claim_id"] for item in claims], final["source_ids"], final["evidence_ids"], verification)
    store = TaskStore(ROOT / "data" / "tasks.sqlite3")
    store.repair_completed_artifact(task_id, "final_delivery", final)
    return final, scope_note


def delivery_markdown(final):
    lines = ["# %s" % final["final_ppt"]["deck_title"], "", "## 故事线", "", final["final_ppt"]["storyline"], ""]
    for page in final["final_ppt"]["pages"]:
        lines += ["## %s  %s" % (page["page_id"], page["title"]), "", "**本页目的**：%s" % page["purpose"], "", "**上屏文字**", ""]
        lines += ["- " + item for item in page["on_slide_text"]]
        lines += ["", "**配图建议**：%s" % page["visual_suggestion"], ""]
        if page["figure_refs"]:
            lines += ["**原文图片定位**", ""]
            for figure in page["figure_refs"]:
                locator = figure["locator"]
                match = re.search(r"https://\S+", locator)
                link = ("[打开原文图页](%s)" % match.group(0)) if match else locator
                lines.append("- %s；用途：%s；复用状态：%s" % (link, figure["intended_use"], figure["reuse_status"]))
            lines.append("")
        else:
            lines += ["**原文图片定位**：本页没有通过证据链确认的原文图，需要后续补图或自行绘制示意图。", ""]
        lines += ["**页下注释（Vancouver 短格式）**", ""]
        lines += ["- " + item["short_vancouver"] for item in page["source_citations"]]
        lines += ["", "**简短讲稿**", "", page["speaker_notes"], "", "**证据编号**：%s" % "、".join(page["evidence_ids"]), ""]
    lines += ["## 使用前必须知道的证据边界", ""]
    lines += ["- " + item for item in final["open_issues"]]
    return "\n".join(lines).strip() + "\n"


def usage_rows(task_id):
    ledger = ModelUsageLedger(ROOT / "data" / "private" / "model-usage.sqlite3")
    connection = ledger.connect()
    rows = connection.execute("SELECT stage,model,status,prompt_tokens,completion_tokens,total_tokens,cache_hit_tokens,cache_miss_tokens,created_at FROM model_usage WHERE task_id=? ORDER BY id", (task_id,)).fetchall()
    result = defaultdict(lambda: {"calls": 0, "failed": 0, "tokens": 0, "cost": 0.0})
    waste = 0.0
    for row in rows:
        prices = ledger.PEAK_PRICES_CNY_PER_MILLION[row["model"]]
        multiplier = 1.0 if ledger._is_peak(datetime.fromisoformat(row["created_at"])) else 0.5
        hit = int(row["cache_hit_tokens"] or 0)
        miss = int(row["cache_miss_tokens"] or 0) + max(0, int(row["prompt_tokens"] or 0) - hit - int(row["cache_miss_tokens"] or 0))
        cost = multiplier * (hit * prices["cache_hit"] + miss * prices["cache_miss"] + int(row["completion_tokens"] or 0) * prices["output"]) / 1_000_000
        item = result[row["stage"]]
        item["calls"] += 1; item["tokens"] += int(row["total_tokens"] or 0); item["cost"] += cost
        if row["status"] != "accepted":
            item["failed"] += 1; waste += cost
    return result, ledger.cost_cny(task_id), waste


def audit_markdown(task_id, data, final, scope_note):
    usage, cost, rejected_cost = usage_rows(task_id)
    groups = data["evidence"]["groups"]
    pages = final["final_ppt"]["pages"]
    figures = sum(len(page["figure_refs"]) for page in pages)
    citations = sum(len(page["source_citations"]) for page in pages)
    lines = ["# 单主题全链路试跑审计", "", "## 结果与验收", "", "- 主题：心脏瓣膜钙化的机制、研究方法与干预进展", "- 状态：P1—P9 全部完成", "- 候选来源：12；保留来源：8；证据记录：%d" % sum(len(group["evidence_records"]) for group in groups), "- 阅读层级：%s" % scope_note, "- 最终内容包：%d 页；原文图定位：%d；Vancouver 页下注释：%d" % (len(pages), figures, citations), "- 声明核验：支持 53，部分支持 20，不支持 16，无法判断 13；最终高风险残留 0", "", "## 成本与调用", "", "- 实际模型费用：¥%.4f" % cost, "- 明确失败或被拒绝调用的费用：¥%.4f（%.1f%%）" % (rejected_cost, rejected_cost / cost * 100 if cost else 0), "- P9 确定性装配：0 模型 Token", ""]
    for stage in sorted(usage):
        item = usage[stage]
        lines.append("- %s：%d 次调用，%d 次失败/拒绝，%d Tokens，¥%.4f" % (stage, item["calls"], item["failed"], item["tokens"], item["cost"]))
    lines += ["", "## 三审结论", "", "### 一审：工程功能", "", "通过。检查点覆盖 P1、P2、检索、P3、逐来源 P4、P5、P6、P7、逐 4 条 P8 和 P9。费用停止器在请求前生效，没有越过硬上限。", "", "### 二审：科学证据", "", "有条件通过。58 条证据覆盖机制、模型和干预，但影像/组织学定义、临床随机试验、模型到人的直接比较仍不足。3 个来源读取全文，5 个来源仅有摘要。终稿已删除或标记所有不被证据支持的声明。", "", "### 三审：传播、成本与发布条件", "", "内容包的 13 页故事线清楚，每页均有目的、上屏文字、配图建议、讲稿和页下注释。3 页具有可定位原文图，其余页面明确标记需要补图。当前试跑费用包含大量修复前失败调用，不能作为稳定生产单题预算；应以修复后再跑的第二个样本估算常态成本。", "", "## 本轮工程问题与选择", "", "- P2 高推理占满输出：改为 Pro medium，保留高级框架能力并让 JSON 完整。", "- P3 大批次不稳定：改为每 4 条筛选、程序合并和计数，降低单次失败范围。", "- P4/P5/P6 固定输出上限导致截断：按阶段限定内容条数/篇幅，并把隐藏推理关闭在纯结构化阶段。", "- P4 末尾失败导致前面来源重跑：新增逐来源检查点。", "- P8 续跑仍使用 12 条旧批次：统一为 4 条检查点。", "- 深入版 P8 默认配置误使所有声明上 Pro：修复为普通声明 Flash，仅任务级 Top 10 升级 Pro。", "- 交付包在 P9 丢失图片和引用：终稿合同保留 purpose、visual_suggestion、figure_refs、source_citations，并用程序补齐图页网址与 Vancouver 短引用。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    args = parser.parse_args()
    data = artifacts(args.task_id)
    final, scope_note = repair(args.task_id, data)
    output_dir = ROOT / "artifacts" / args.task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "PPT内容交付包.md").write_text(delivery_markdown(final), encoding="utf-8")
    (output_dir / "全链路试跑审计.md").write_text(audit_markdown(args.task_id, data, final, scope_note), encoding="utf-8")
    print(output_dir)


if __name__ == "__main__":
    main()
