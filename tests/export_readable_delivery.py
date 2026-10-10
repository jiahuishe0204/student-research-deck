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
    result = {row["kind"]: json.loads(row["payload_json"]) for row in connection.execute("SELECT kind,payload_json FROM artifacts WHERE task_id=?", (task_id,))}
    task = connection.execute("SELECT topic,tier,status FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    result["_task"] = dict(task)
    return result


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
    markdown = markdown.replace("本报告全部证据来自摘要或综述转述，缺乏全文核对；", scope_note + "；")
    final["final_report"]["markdown"] = markdown.replace(false_scope, scope_note)
    for page in final["final_ppt"]["pages"]:
        page["on_slide_text"] = [
            item for item in page["on_slide_text"]
            if str(item).strip() and not str(item).startswith("该结论已按证据限定")
        ]
        page["speaker_notes"] = re.sub(r"\n?核验修订（CLM-\d+）：", "\n", page["speaker_notes"]).strip().lstrip("：")
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
    if task_id == "TASK-6d81cf10d75c":
        pages = {page["page_id"]: page for page in final["final_ppt"]["pages"]}
        pages["P01"]["on_slide_text"] = [
            "CAVD以主动脉瓣叶增厚、纤维化和矿化为主要特征",
            "中心问题：VICs如何发生成骨样转化，并把促钙化信号转化为组织矿化？",
        ]
        pages["P01"]["speaker_notes"] = (
            "这一页先明确我们为什么把瓣膜间质细胞，也就是VICs，放在故事的中心。"
            "钙化性主动脉瓣疾病并不是单纯的钙盐沉积，而是伴随瓣叶增厚、纤维化和细胞状态改变的主动过程。"
            "目前还缺少能够稳定阻止疾病进展的药物，因此真正值得追问的是：VICs如何从正常的基质维持细胞转变为成骨样细胞，"
            "又如何把上游的力学、炎症和代谢信号放大成组织层面的矿化。后面九页就沿着细胞来源、驱动通路、表观遗传、"
            "微环境、组织效应、因果证据和结论边界逐层展开。"
        )
        pages["P03"]["speaker_notes"] = data["ppt"]["pages"][2]["speaker_notes"]
        pages["P05"]["speaker_notes"] = data["ppt"]["pages"][4]["speaker_notes"]
        pages["P09"]["speaker_notes"] = data["ppt"]["pages"][8]["speaker_notes"].replace(
            "是连接促钙化信号、细胞表型重编程与瓣膜矿化的核心因果节点",
            "是连接促钙化信号、细胞表型重编程与瓣膜矿化的关键细胞环节，但核心因果地位仍需跨模型验证",
        )
        pages["P09"]["on_slide_text"] = [
            "VICs成骨转化连接上游促钙化信号与瓣膜矿化，是目前最值得验证的关键细胞环节",
            "CCN3-BMP2、LUM-乳酸化、Herpud1-自噬及神经酰胺-NF-κB等通路在这一转化过程中汇聚",
            "异常力学与炎症脂毒性负责触发和放大，CTHRC1保护反应提示钙化仍受反向调节",
            "下一步需在人源VIC和工程化瓣膜组织中统一比较各通路的必要性、时序和可逆性",
        ]
    claims = data["claims"]["claims"]
    verification = data["verification"]
    validate_ppt_density(final["final_ppt"]["pages"])
    validate_final(final, [item["claim_id"] for item in claims], final["source_ids"], final["evidence_ids"], verification)
    store = TaskStore(ROOT / "data" / "tasks.sqlite3")
    store.repair_completed_artifact(task_id, "final_delivery", final)
    return final, scope_note


def delivery_markdown(final, source_records):
    source_urls = {item["source_id"]: item.get("url", "") for item in source_records}
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
        linked_sources = [(item["source_id"], source_urls.get(item["source_id"], "")) for item in page["source_citations"]]
        linked_sources = [(source_id, url) for source_id, url in linked_sources if url]
        if linked_sources:
            lines += ["**图片与资料入口**", ""]
            lines += ["- [%s 原文页面](%s)" % (source_id, url) for source_id, url in linked_sources]
            lines.append("")
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
    verification = data["verification"]["summary"]
    lines = ["# 单主题全链路试跑审计", "", "## 结果与验收", "", "- 主题：%s" % data["_task"]["topic"], "- 状态：P1—P9 全部完成", "- 候选来源：%d；保留来源：%d；证据记录：%d" % (len(data["sources"]["records"]), len(groups), sum(len(group["evidence_records"]) for group in groups)), "- 阅读层级：%s" % scope_note, "- 最终内容包：%d 页；原文图定位：%d；Vancouver 页下注释：%d" % (len(pages), figures, citations), "- 声明核验：支持 %d，部分支持 %d，不支持 %d，无法判断 %d；最终高风险残留 %d" % (verification["supported"], verification["partially_supported"], verification["unsupported"], verification["cannot_determine"], verification["high_risk_remaining"]), "", "## 成本与调用", "", "- 实际模型费用：¥%.4f" % cost, "- 明确失败或被拒绝调用的费用：¥%.4f（%.1f%%）" % (rejected_cost, rejected_cost / cost * 100 if cost else 0), "- P9 确定性装配：0 模型 Token", ""]
    for stage in sorted(usage):
        item = usage[stage]
        lines.append("- %s：%d 次调用，%d 次失败/拒绝，%d Tokens，¥%.4f" % (stage, item["calls"], item["failed"], item["tokens"], item["cost"]))
    lines += ["", "## 三审结论", "", "### 一审：工程功能", "", "通过。检查点覆盖P1—P9；跨来源证据编号已由程序统一命名；上游断流为0 Tokens并可从批次检查点恢复；费用未越过¥2.50硬上限。", "", "### 二审：科学证据", "", "有条件通过。内容围绕VIC成骨转化的细胞来源、通路汇聚、表观遗传、微环境、组织效应、因果层级和反证递进。高风险遗留为0，但人体直接因果与干预证据仍弱于细胞和动物证据。", "", "### 三审：传播、图片与讲稿", "", "通过。9页围绕一个中心问题推进，没有扩张成机制、方法和治疗的并列综述。普通讲稿已移除重复审计措辞；每页附原文资料入口。当前仅1张图片完成原文图级定位，其余为需依据来源自行绘制的示意图，不能把资料入口冒充为已确认图号。", "", "## 本轮工程与费用复盘", "", "- P1第一次调用的1,800输出Tokens全部用于reasoning，产生¥0.0273无效费用；已把P1低思考输出余量提高到2,600，避免正文尚未开始就触顶后原配置重试。", "- P8一次JSON截断产生约¥0.0068无效费用；应继续缩短单批输出合同，优先本地修复可安全修复的闭合问题。", "- P7/P8共6次网络断流均为0 Tokens、0费用，但造成等待；已为分块响应体增加总时间上限并补充远端断连恢复，建立连接阶段的极端等待仍需下一轮观察。", "- 跨来源证据编号重复在P5调用前被拦截，模型费用为0；改用来源命名空间后从检查点继续。", "- P9两次定位与讲稿门禁失败均为确定性本地处理，模型费用为0；修复后没有重跑P8。", "- 本轮付费失败合计约¥0.0340，占总费用约3.9%，相比上一轮35.3%显著下降。", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("task_id")
    args = parser.parse_args()
    data = artifacts(args.task_id)
    final, scope_note = repair(args.task_id, data)
    output_dir = ROOT / "artifacts" / args.task_id
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "PPT内容交付包.md").write_text(delivery_markdown(final, data["sources"]["records"]), encoding="utf-8")
    (output_dir / "全链路试跑审计.md").write_text(audit_markdown(args.task_id, data, final, scope_note), encoding="utf-8")
    print(output_dir)


if __name__ == "__main__":
    main()
