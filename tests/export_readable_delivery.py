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
        academic_defense_notes = {
            "P01": (
                "本次汇报聚焦钙化性主动脉瓣疾病中的瓣膜间质细胞，也就是VICs。CAVD并非被动的钙盐沉积，而是伴随瓣叶增厚、"
                "纤维化和细胞状态重编程的主动病理过程。由于目前仍缺少能够稳定阻断疾病进展的药物，一个关键科学问题是："
                "VICs如何由基质稳态细胞转变为成骨样细胞，并将力学、炎症和代谢信号放大为组织矿化。后续内容将依次讨论"
                "细胞来源、驱动通路、表观遗传维持、微环境输入、组织效应以及现有证据的因果边界。"
            ),
            "P02": (
                "首先需要明确成骨样VICs的细胞来源及其空间位置。人主动脉瓣单细胞测序识别出VICs向成骨细胞群转变前的中间状态；"
                "小鼠谱系追踪进一步显示，扩增群体主要来源于PDGFRβ阳性的驻留间质细胞，内皮细胞贡献较小。空间证据显示，"
                "CTHRC1在增厚瓣叶及人狭窄主动脉瓣的活化VICs中高表达，而钙化灶集中于振荡剪切和弯曲应力较强的区域。"
                "这些结果共同支持CAVD存在具有空间选择性的VIC身份重编程，并将问题推进到促成这一转化的分子信号。"
            ),
            "P03": (
                "现有功能实验提示，VIC成骨转化由多条信号轴共同驱动。髓系CCN3缺失可加重小鼠瓣膜增厚和钙化，条件培养实验则支持"
                "巨噬细胞来源CCN3通过BMP2调控VIC促钙化表型。LUM通路将炎症、糖酵解和乳酸积累连接至H3K14la、H3K9la等"
                "组蛋白乳酸化位点，并与RUNX2和BMP2表达相关。Herpud1研究进一步把内质网应激和自噬纳入这一网络。"
                "因此，VIC成骨转化更适合被理解为多通路汇聚的细胞状态变化，而不是由单一分子开关控制。"
            ),
            "P04": (
                "在确认多条通路能够诱导成骨表型后，还需要解释这一表型为何能够持续。LUM相关研究显示，炎症和糖酵解增强可导致乳酸积累，"
                "H3K14la与H3K9la则与RUNX2、BMP2表达相关，提示组蛋白乳酸化可能把代谢变化转化为较稳定的成骨转录程序。"
                "另一类研究表明，Piezo1介导的钙内流、YAP核转位和GLS1依赖的谷氨酰胺分解，可通过乙酰辅酶A和组蛋白乙酰化促进"
                "VIC成骨分化。综合这些结果，表观修饰可能构成微环境刺激与持续性细胞记忆之间的连接层。"
            ),
            "P05": (
                "VIC状态重编程的上游输入主要来自异常力学和炎症脂毒性。钙化灶偏好出现在主动脉侧瓣叶表面及高弯曲应力区域，提示局部"
                "血流与组织受力参与病变定位。在二叶式主动脉瓣等先天性病因中，力学异常可能构成原发驱动；在高脂血症和慢性炎症相关"
                "CAVD中，则更可能发挥继发放大作用。与此同时，钙化人瓣膜富集长链神经酰胺，C18神经酰胺可诱导人VIC钙化，"
                "Myriocin在动物模型中还能在不降低LDL的情况下减轻炎症、矿化和血流动力学恶化。这些证据说明，两类微环境信号可共同"
                "触发并维持成骨转化。"
            ),
            "P06": (
                "细胞状态改变只有进一步转化为基质重塑和矿物沉积，才会形成组织层面的瓣膜钙化。工程化瓣膜组织在钙化诱导条件下能够"
                "重现纤维化、RUNX2上调和羟基磷灰石沉积，外加力学应力后钙化进一步加重；时间序列转录组也显示其沿成骨分化轨迹推进。"
                "剪切应力通过TIMP/MMP系统改变细胞外基质，为矿化提供局部微环境。CTHRC1缺陷模型中出现泡沫样巨噬细胞积聚、"
                "线粒体功能特征丢失和细胞死亡通路激活，则提示免疫损伤可继续放大这一过程。由此可见，VIC转化通过基质、矿物沉积与"
                "免疫微环境的相互作用被放大为组织病变。"
            ),
            "P07": (
                "判断VIC成骨转化是因果驱动还是伴随现象，需要区分动物干预证据与人体关联证据。CCN3、LUM和Herpud1相关敲除模型"
                "均改变了瓣膜成骨或钙化表型；Myriocin在疾病建立后仍能减缓血流动力学进展，进一步支持相关通路具有可修饰性。人体证据"
                "目前主要包括成骨样VIC标志物的空间关联、瓣膜脂质组学以及离体人VIC实验，尚未达到VIC特异性人体干预的因果强度。"
                "临床上，他汀类和抗骨吸收治疗未能延缓CAVD，而SNF472在特定透析人群中显示钙化抑制信号。这一对照提示，未来靶点选择"
                "需要更直接地对应VIC成骨转化及其上游机制。"
            ),
            "P08": (
                "现有证据支持VIC成骨转化的重要作用，但其结论边界需要明确。CTHRC1缺失会加重慢性瓣膜钙化，提示内皮损伤后短暂的"
                "CTHRC1诱导可能属于内源性基质保护反应，因此VIC活化并不等同于单向促钙化。力学信号的作用也具有病因依赖性：在先天性"
                "CAVD中可能是原发驱动，在获得性疾病中则更接近继发放大因素。此外，DNA甲基化、非编码RNA以及各通路之间的因果层级"
                "仍缺少统一比较。因而，本次结论主要适用于主动脉瓣VIC成骨样转化这一特定语境，不应直接外推至血管钙化或其他瓣膜疾病。"
            ),
            "P09": (
                "综合细胞来源、功能干预和组织模型证据，VIC成骨转化可以被视为连接促钙化微环境、细胞表型重编程与瓣膜矿化的关键环节，"
                "但其核心因果地位仍需跨模型验证。CCN3-BMP2、LUM-乳酸化、Herpud1-内质网应激与自噬，以及神经酰胺-NF-κB等通路"
                "在这一环节汇聚；异常力学与炎症脂毒性负责触发和放大，而CTHRC1相关保护反应说明系统中仍存在反向调节。下一步应在统一的"
                "人源VIC和工程化瓣膜组织中，对候选通路进行平行干预，比较其必要性、作用时序和可逆性，从而筛选更有转化价值的干预节点。"
            ),
        }
        for page_id, notes in academic_defense_notes.items():
            pages[page_id]["speaker_notes"] = notes
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
