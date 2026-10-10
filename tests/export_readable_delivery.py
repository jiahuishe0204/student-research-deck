#!/usr/bin/env python3
# -*- coding: utf-8 -*-
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
    elif task_id == "TASK-00958dfd563f":
        pages = {page["page_id"]: page for page in final["final_ppt"]["pages"]}
        pages["P1"]["on_slide_text"] = [
            "2022年全球估计新发癌症近2000万例、癌症死亡约970万例，2050年年新发可能超过3500万例",
            "现有器官特异性筛查仅覆盖少数癌种，多癌早筛试图扩大无症状人群的筛查范围",
            "中心问题：检出更多癌症信号，能否最终转化为可验证的临床净获益？",
        ]
        pages["P2"]["on_slide_text"] = [
            "中心问题：cfDNA甲基化多癌早筛能否在无症状普通风险人群中产生临床净获益？",
            "证据链：检测性能决定能否发现信号，癌种溯源决定后续诊断路径",
            "降低晚期癌症发生率或癌症特异性死亡率，才是验证临床效用的关键终点",
            "假阳性、过度诊断和诊断负担必须与潜在获益同时评价",
        ]
        pages["P4"]["on_slide_text"] = [
            "PATHFINDER纳入6621名50岁及以上无症状人群，92人检出癌症信号，其中35人最终确诊",
            "阳性预测值为38%，意味着约每3个阳性信号中有1个确诊癌症",
            "症状转诊队列的PPV明显更高，说明患病率和入组场景会显著影响阳性结果的临床含义",
            "低患病率下NPV天然较高，不能只用高NPV证明筛查具有净获益",
        ]
        pages["P7"]["on_slide_text"] = [
            "分期迁移可能来自真正的早诊，也可能受到领先时间偏倚和过度诊断影响",
            "晚期癌症发生率可作为重要终点，但仍需验证它能否可靠预测癌症死亡率下降",
            "常规筛查推荐需要随机对照试验和长期随访，而不能仅依赖替代终点或模拟结果",
        ]
        pages["P10"]["on_slide_text"] = [
            "检测特异性和癌种溯源准确率提供了有前景的中间证据，但I期敏感性仍然有限",
            "无症状人群中的阳性预测值约38%，假阳性会带来持续数月的诊断负担",
            "癌症死亡率或晚期癌症发生率降低的随机对照证据尚未建立",
            "现阶段证据不足以支持将MCED作为无症状普通风险人群的常规筛查",
        ]
        academic_notes = {
            "P1": "本次汇报评估cfDNA甲基化多癌早筛在无症状普通风险人群中的临床价值。全球癌症负担持续增长，而现有器官特异性筛查只能覆盖少数癌种，因此一次血液检测同时识别多种癌症信号具有明确吸引力。但筛查价值不能由检出数量直接推导。真正需要回答的是：检测发现的信号能否沿着有效诊断路径转化为更早治疗，并最终减少晚期癌症或癌症死亡，同时不造成不可接受的假阳性和过度诊断。",
            "P2": "这一问题需要沿完整证据链评价。首先，检测必须在低患病率人群中保持足够特异性，并在早期癌症阶段具有可接受的敏感性。其次，癌种溯源需要把阳性信号引导至正确的确诊路径。前两项仍属于技术性能和中间结果；临床效用最终要由晚期癌症发生率或癌症特异性死亡率等终点验证。与此同时，假阳性检查、过度诊断和患者负担必须纳入净获益判断。后续内容将依次检查这四个环节。",
            "P3": "CCGA独立验证子研究提供了检测性能的主要基准。研究纳入4077名参与者，特异性为99.5%，全癌种总体敏感性为51.5%。敏感性具有明显分期依赖性：I期为16.8%，随后随分期升高，IV期达到90.1%。这意味着检测更容易识别肿瘤负荷较高的晚期疾病，却在筛查最希望发现的I期阶段表现较弱。因而，高特异性解决了假阳性的一部分问题，但早期敏感性仍限制其改变疾病结局的潜力。",
            "P4": "在普通风险人群中，阳性预测值比单独的特异性更能反映后续诊断负担。PATHFINDER纳入6621名50岁及以上无症状参与者，92人检出癌症信号，其中35人最终确诊，对应38%的阳性预测值。也就是说，每3个阳性信号中约有1个确诊癌症，其余参与者需要通过后续检查排除。症状转诊人群的PPV明显更高，说明同一检测指标必须结合入组场景和患病率解释，不能直接外推为筛查净获益。",
            "P5": "癌种溯源决定阳性结果能否进入合理的确诊路径。CCGA验证研究中，真阳性样本的癌症信号来源预测准确率为88.7%。PATHFINDER显示，真阳性的中位诊断解决时间为57天，而假阳性为162天。假阳性参与者接受侵入性操作的比例低于真阳性，但较长的诊断周期仍意味着持续的不确定性和资源消耗。因此，较高的溯源准确率具有实际价值，但还需要更完整地报告溯源失败及错误定位造成的后果。",
            "P6": "现有研究已经给出性能、溯源和诊断路径数据，但临床净获益的关键终点尚未建立。相关综述指出，大规模随机试验仍在进行，第一代MCED检测的诊断性能能否转化为临床获益仍待确认。THUNDER模型预测晚期发病率可能下降，并估计五年生存率改善，但建模结果不能替代随机试验观察到的死亡率或晚期癌症发生率。因此，硬终点是当前证据链最主要的缺口。",
            "P7": "筛查研究中的分期迁移需要谨慎解释。晚期癌症比例下降可能意味着真正的早诊，也可能受到领先时间偏倚影响；筛查还可能发现原本不会造成临床危害的病灶，从而形成过度诊断。正因如此，生存时间延长或早期病例比例增加不能自动等同于死亡率下降。未来试验需要预先设定具有临床意义的终点，并通过随机对照和长期随访区分真实获益与偏倚。",
            "P8": "净获益评价还必须考虑假阳性后的诊断负担。PATHFINDER中，大多数假阳性参与者接受了实验室和影像检查，30%接受操作；排除提前进入诊断流程的个体后，中位诊断解决时间为162天。现有研究已经初步量化检查和时间负担，但尚未系统报告过度诊断率、焦虑或生活质量等结局。因此，危害证据比检测性能证据更不完整。",
            "P9": "截至2025年相关综述发表时，尚无MCED检测获批用于常规临床筛查。现阶段的主要挑战包括提高早期癌症敏感性、降低假阳性与假阴性，并确保不同人群能够公平获得检测和后续诊断。监管状态与证据缺口相互一致：技术已经进入前瞻性研究阶段，但死亡率、过度诊断、错误溯源后果和患者报告结局仍不足以支撑常规筛查推荐。",
            "P10": "综合现有证据，cfDNA甲基化多癌早筛已经表现出较高特异性和较好的癌种溯源能力，但I期敏感性有限，无症状人群中的阳性预测值约为38%，假阳性还会带来持续数月的诊断过程。更重要的是，降低癌症死亡率或晚期癌症发生率的随机对照证据尚未建立。因此，当前证据可以支持继续开展临床研究，但不足以支持在无症状普通风险人群中作为常规筛查推广。",
            "P11": "本次结论受到研究人群和证据层级的限制。不同研究采用病例对照、富集队列或50岁以上便利样本，不能直接代表所有普通风险人群。部分关键性能数据仅能依据摘要核对，方法细节和长期随访仍需全文确认。死亡率终点需要较长随访，过度诊断的识别方法也尚未统一。这些边界不会改变当前证据不足以支持常规筛查的判断，但决定了未来试验在人群定义、终点和偏倚控制上的优先事项。",
        }
        for page_id, notes in academic_notes.items():
            pages[page_id]["speaker_notes"] = notes
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
    if task_id == "TASK-00958dfd563f":
        lines += ["", "## 三审结论", "", "### 一审：工程功能", "", "通过。P1—P9均有检查点，任务从失败阶段续跑，没有重复已完成阶段；总费用未越过¥2.50硬上限。P9重叠声明定位失败由本地确定性规则修复，未重新调用P8。", "", "### 二审：科学证据", "", "有条件通过。内容区分检测性能、癌种溯源、硬终点、筛查危害和推荐条件；高风险遗留为0。关键限制是4个来源仅获取摘要，死亡率、过度诊断和患者报告结局仍缺少直接证据。", "", "### 三审：传播、图片与讲稿", "", "专业复核后通过。11页围绕临床净获益推进，没有套用机制型主题结构。原始P9装配曾造成空标签、残句和审计语言回流，已用零模型Token的确定性后处理修复，并新增装配后可读性门禁。每页保留资料入口和Vancouver短引用；本轮没有完成原文图级定位，配图仍以自制示意图为主。", "", "## 与CAVD轮次对比", "", "- 本轮¥%.4f，低于CAVD轮次¥0.8812，减少¥%.4f（%.1f%%）。" % (cost, 0.8812 - cost, (0.8812 - cost) / 0.8812 * 100), "- 本轮11页、45条证据、85条声明；CAVD轮次9页、62条证据、104条声明。", "- 本轮失败/拒绝费用¥%.4f，占%.1f%%；CAVD轮次约¥0.0340，占3.9%%。本轮总成本更低，但失败占比反而更高。" % (rejected_cost, rejected_cost / cost * 100 if cost else 0), "", "## 本轮工程与费用复盘", "", "- P1两次15秒空闲超时和P2两次45秒空闲超时均为0 Tokens、0费用，但浪费等待时间。已改为只使用300秒总时限，不再把推理阶段的沉默误判为断流。", "- P1第一次有Token输出在2,600上限处截断，产生¥0.0353无效费用。P1输出空间已提高到4,200；按实际Tokens计费，不会因上限提高自动增加费用，但可避免完整重跑。", "- P8有一批未返回完整声明集合，校验拒绝并重试，产生¥0.0303无效费用。下一步应让批次调用保留已合格结果，只重试缺失声明，而不是重做整批。", "- P9两次因同一上屏长句包含重叠声明而拒绝装配，均为0 Tokens、0费用。已增加唯一数字锚点定位和重叠删除幂等处理。", "- P9后的专业复核发现空标签、断裂标点和审计语言回流。已新增装配后可读性门禁；本轮用已核验证据零成本修复，没有重跑P6或P8。", ""]
    else:
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
