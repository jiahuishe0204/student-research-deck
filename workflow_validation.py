"""Deterministic cross-stage validation for P1-P9 workflow outputs."""

import re

from contracts import ContractError, validate_stage_output


PPT_DENSITY_LIMITS = {
    "page_characters_max": 400,
    "bullet_characters_max": 140,
    "bullets_max": 7,
    "speaker_notes_max": 800,
}

AUDIT_LANGUAGE = (
    "证据不足", "未核实", "开放问题", "无法确认", "无法核查",
    "摘要未提供", "需要进一步查证", "需进一步核实", "没有查到", "没查到",
    "所引证据未直接", "本次可获取证据",
)
LIMITATION_PAGE_TERMS = ("局限", "争议", "研究空白", "证据边界", "不足与展望")
CASUAL_SPEAKER_LANGUAGE = (
    "这一页想说明", "我们先看", "那这些", "刚才讲了", "刚才的",
    "这一页告诉我们", "大家可以看到", "下面来看", "简单来说", "说白了",
)
COMPARISON_LIMITS = (
    "未说明比较条件", "未提供比较条件", "比较条件未说明",
    "样本量未说明", "统计方法未说明", "比较条件、样本量",
)
EFFICACY_OVERCLAIM = re.compile(r"(?:电荷注入)?效率优于|刺激效率优于")
NEGATED_SUPERIORITY = re.compile(r"(?:不等同于|不能|无法|尚不足以|并非|不意味着)[^。；\n]{0,35}优于")
LIMITED_EFFICIENCY = re.compile(r"(?:不等同于|不能|无法|尚不足以|并非|不意味着)[^。；\n]{0,35}(?:电荷注入效率|刺激效率)")


def presentation_boundary_issues(page):
    """Shared repair triggers and final delivery gates must agree."""
    bullets = page.get("on_slide_text", [])
    notes = page.get("speaker_notes", "")
    title = page.get("title", "")
    issues = []
    if any(str(item).rstrip().endswith(("，", "、")) for item in bullets):
        issues.append("unfinished_bullet")
    limited = any(LIMITED_EFFICIENCY.search(item) or (NEGATED_SUPERIORITY.search(item) and "效率" in item) for item in bullets)
    if limited and any(EFFICACY_OVERCLAIM.search(sentence) and not NEGATED_SUPERIORITY.search(sentence) for sentence in re.split(r"[。；\n]", notes)):
        issues.append("conflicting_comparison")
    if "优于" in title and any(term in "\n".join(bullets + [notes]) for term in COMPARISON_LIMITS) and not any(term in title for term in ("该研究", "摘要报告", "在体外", "在离体")):
        issues.append("unbounded_comparison_title")
    return issues


def validate_ppt_density(pages):
    for page in pages:
        bullets = page.get("on_slide_text", [])
        characters = sum(len(str(item)) for item in bullets)
        if characters > PPT_DENSITY_LIMITS["page_characters_max"]:
            raise ContractError("PPT 页面出现极端文字堆积，超过 400 字")
        if len(bullets) > PPT_DENSITY_LIMITS["bullets_max"]:
            raise ContractError("PPT 单页要点超过 7 条，缺少信息层级")
        if any(len(str(item)) > PPT_DENSITY_LIMITS["bullet_characters_max"] for item in bullets):
            raise ContractError("PPT 单条上屏文字超过 140 字，已经接近正文段落")
        if len(str(page.get("speaker_notes", ""))) > PPT_DENSITY_LIMITS["speaker_notes_max"]:
            raise ContractError("PPT 单页备注超过 800 字，应拆分讲解任务")
    return pages


def validate_presentation_voice(pages, check_claim_boundaries=True):
    """Keep audit language and chatty scaffolding out of academic-defense notes."""
    ordinary_pages = []
    flagged_pages = []
    casual_hits = []
    for page in pages:
        title = str(page.get("title", ""))
        purpose = str(page.get("purpose", ""))
        is_limitation_page = any(term in title or term in purpose for term in LIMITATION_PAGE_TERMS)
        if not is_limitation_page:
            ordinary_pages.append(page)
        notes = str(page.get("speaker_notes", ""))
        bullets = [str(item).strip() for item in page.get("on_slide_text", [])]
        if any((len(item) < 20 and item.endswith(("：", ":"))) for item in bullets):
            raise ContractError("PPT 核验装配后留下空标签或残句，应在交付前清理")
        boundary_issues = presentation_boundary_issues(page)
        if "unfinished_bullet" in boundary_issues:
            raise ContractError("PPT 上屏要点以逗号或顿号结尾，疑似截断残句")
        combined = "\n".join(bullets + [notes])
        if any(pattern in combined for pattern in ("。。", "。；", "；。", ".。")):
            raise ContractError("PPT 核验装配后出现断裂标点，应在交付前清理")
        if not is_limitation_page:
            hits = sum(notes.count(term) for term in AUDIT_LANGUAGE)
            if hits > 1:
                raise ContractError("PPT 普通页面讲稿反复使用证据审计措辞，应改为可直接讲述的汇报语言")
            if hits:
                flagged_pages.append(page.get("page_id"))
            if any(term in notes for term in CASUAL_SPEAKER_LANGUAGE):
                casual_hits.append(page.get("page_id"))
        if check_claim_boundaries:
            # Check the same comparison, not unrelated results on the page.
            # For example, an n=1 ex-vivo result must not invalidate a
            # separate, better supported impedance comparison.
            if "conflicting_comparison" in boundary_issues:
                raise ContractError("同一PPT页的讲稿与要点对效率比较给出相反结论")
            if "unbounded_comparison_title" in boundary_issues:
                raise ContractError("PPT 标题把比较条件未明的单项结果写成无条件优于")
    if ordinary_pages and len(flagged_pages) / len(ordinary_pages) > 0.2:
        raise ContractError("PPT 讲稿中过多普通页面暴露内部证据审计语言，应集中到局限页")
    if len(casual_hits) > 1:
        raise ContractError("PPT 讲稿中过多页面使用聊天式串词，应改为专业的学术答辩表达")
    return pages


def validate_intent(value):
    required = {"domain", "normalized_topic", "scope_hint", "tier", "assumptions", "topic_breadth", "direction_options", "need_clarification", "clarification_question", "confirmation_text"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("意图识别返回字段不完整")
    if isinstance(value["assumptions"], str):
        value = dict(value)
        normalized_assumption = value["assumptions"].strip()
        value["assumptions"] = [normalized_assumption] if normalized_assumption else []
    if not isinstance(value["assumptions"], list) or any(not isinstance(item, str) for item in value["assumptions"]):
        raise ValueError("意图假设必须为字符串数组")
    if not isinstance(value["need_clarification"], bool):
        raise ValueError("澄清状态无效")
    if value["need_clarification"] and not isinstance(value["clarification_question"], str):
        raise ValueError("需要澄清时必须返回一个问题")
    breadth = value["topic_breadth"]
    if breadth not in {"focused", "broad", "ambiguous", "out_of_scope"}:
        raise ValueError("主题范围判断无效")
    options = value["direction_options"]
    if not isinstance(options, list):
        raise ValueError("研究方向选项必须为数组")
    if breadth == "broad" and (not value["need_clarification"] or not 2 <= len(options) <= 4):
        raise ValueError("宽泛主题必须返回2—4个方向并等待用户选择")
    if breadth != "broad" and options:
        raise ValueError("只有宽泛主题可以返回研究方向卡片")
    option_keys = {"direction_id", "title", "focus"}
    if any(not isinstance(item, dict) or set(item) != option_keys or not all(isinstance(item[key], str) and item[key].strip() for key in option_keys) for item in options):
        raise ValueError("研究方向卡片字段无效")
    if len({item["direction_id"] for item in options}) != len(options):
        raise ValueError("研究方向编号不能重复")
    return value


def validate_plan(value):
    required = {"research_scope", "exclusions", "questions", "search_concepts", "source_plan", "selection_criteria", "stop_conditions", "report_outline", "ppt_story_arc", "risks"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("调研规划返回字段不完整")
    array_fields = ("exclusions", "source_plan", "selection_criteria", "stop_conditions", "report_outline", "ppt_story_arc", "risks")
    if any(not isinstance(value.get(field), list) for field in array_fields):
        raise ValueError("调研规划数组字段类型无效")
    if not isinstance(value.get("search_concepts"), dict):
        raise ValueError("检索概念必须为对象")
    if not 3 <= len(value.get("questions", [])) <= 6:
        raise ValueError("调研问题数量必须为 3—6 个")
    question_keys = {"question_id", "question", "evidence_needs"}
    if any(not isinstance(item, dict) or set(item) != question_keys or not isinstance(item["evidence_needs"], list) for item in value["questions"]):
        raise ValueError("调研问题字段结构无效")
    return value


def validate_screen(value, candidate_ids, keep_max=None):
    validate_stage_output("P3", value)
    decisions = value["decisions"]
    returned_ids = [item["source_id"] for item in decisions]
    if len(returned_ids) != len(set(returned_ids)):
        raise ContractError("P3 返回了重复 source_id")
    if set(returned_ids) != set(candidate_ids):
        raise ContractError("P3 必须且只能判断本次全部候选资料")
    counts = {status: sum(item["status"] == status for item in decisions) for status in ("keep", "reserve", "drop")}
    summary = value["summary"]
    summary["candidate_count"] = len(candidate_ids)
    for status, count in counts.items():
        summary[status + "_count"] = count
    if keep_max is not None and counts["keep"] > keep_max:
        raise ContractError("P3 保留数量超过本版本预算")
    return value


def validate_evidence(value, source_id, source_access=None, allowed_figure_ids=None, evidence_max=None, figure_max=None):
    validate_stage_output("P4", value)
    if value["source_id"] != source_id:
        raise ContractError("P4 source_id 与输入不一致")
    if any(item["source_id"] != source_id for item in value["evidence_records"]):
        raise ContractError("P4 证据引用了其他来源")
    if any(item["source_id"] != source_id for item in value["figure_records"]):
        raise ContractError("P4 图片引用了其他来源")
    if allowed_figure_ids is not None and not {item["figure_id"] for item in value["figure_records"]}.issubset(set(allowed_figure_ids)):
        raise ContractError("P4 图片不在原文候选列表中")
    if evidence_max is not None and len(value["evidence_records"]) > evidence_max:
        raise ContractError("P4 证据条目超过上限")
    if figure_max is not None and len(value["figure_records"]) > figure_max:
        raise ContractError("P4 图片条目超过上限")
    if source_access != "full_text" and value["reading_scope"] == "full_text":
        raise ContractError("P4 未获得全文时不能标记为全文阅读")
    return value


def validate_report(value, evidence_ids, tier="deep"):
    validate_stage_output("P5", value)
    if not set(value["used_evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P5 使用了不存在的 evidence_id")
    markdown = str(value.get("report_markdown", ""))
    # Figure labels are not evidence IDs. Catch malformed model-made citations
    # such as [EV::PMID:12345678::Fig2] here, before the report reaches P9.
    malformed_citations = [
        candidate for candidate in re.findall(r"\[EV::[^\]\s]*\]", markdown)
        if not re.fullmatch(r"\[EV::[^\]\s]+::\d{3}\]", candidate)
    ]
    if malformed_citations:
        raise ContractError("P5 将图号或其他标记误作证据编号：" + "、".join(malformed_citations[:3]))
    if re.search(r"\[\d+\]", markdown):
        raise ContractError("P5 草稿使用了无法对应证据的数字脚注；必须先引用输入中的 EV 编号")
    cited = set(re.findall(r"EV::.+?::\d{3}", markdown))
    if tier == "deep" and value.get("status") == "draft" and not cited:
        raise ContractError("P5 深入报告没有逐项证据引用，不能进入后续交付")
    # The lower bound guards against a disguised outline.  The upper bound is
    # only a technical runaway guard: report depth must not be cut merely to
    # satisfy the former 8,000-character product target.
    limits = {"fast": (2000, 8000), "deep": (4000, 12000)}
    minimum, maximum = limits.get(tier, limits["deep"])
    if len(markdown) > maximum:
        raise ContractError("P5 调研报告超过版本字数上限：%d/%d" % (len(markdown), maximum))
    if value.get("status") == "draft" and len(markdown) < minimum:
        raise ContractError("P5 调研报告未达到完整交付的最低篇幅：%d/%d" % (len(markdown), minimum))
    required_sections = (("执行摘要", "摘要"), ("研究范围", "研究问题与范围", "问题界定", "研究目的"), ("方法", "证据基础", "资料基础"), ("综合结论", "结论"), ("局限", "证据边界"))
    missing_sections = [alternatives[0] for alternatives in required_sections if not any(term in markdown for term in alternatives)]
    if missing_sections:
        raise ContractError("P5 调研报告缺少摘要、范围方法、结论或局限部分：" + "、".join(missing_sections))
    if not cited.issubset(set(evidence_ids)):
        raise ContractError("P5 正文使用了不存在的 evidence_id：" + "、".join(sorted(cited - set(evidence_ids)))[:200])
    return value


def validate_ppt(value, evidence_ids, figure_ids, source_ids=None):
    validate_stage_output("P6", value)
    allowed_evidence = set(evidence_ids)
    allowed_figures = set(figure_ids)
    allowed_sources = set(source_ids or [])
    for page in value["pages"]:
        invalid_evidence = sorted(set(page["evidence_ids"]) - allowed_evidence)
        if invalid_evidence:
            safe_ids = [re.sub(r"[^A-Za-z0-9:_-]", "", item)[:120] for item in invalid_evidence[:8]]
            raise ContractError("P6 页面使用了不存在的 evidence_id：" + ", ".join(safe_ids))
        for figure in page["figure_refs"]:
            if figure["figure_id"] not in allowed_figures:
                raise ContractError("P6 页面使用了不存在的 figure_id")
        if allowed_sources and not {item["source_id"] for item in page["source_citations"]}.issubset(allowed_sources):
            raise ContractError("P6 页面使用了不存在的 source_id")
    validate_ppt_density(value["pages"])
    validate_presentation_voice(value["pages"], check_claim_boundaries=False)
    return value


def validate_claims(value, evidence_ids):
    validate_stage_output("P7", value)
    claim_ids = [item["claim_id"] for item in value["claims"]]
    if len(claim_ids) != len(set(claim_ids)):
        raise ContractError("P7 claim_id 重复")
    if any(not set(item["cited_evidence_ids"]).issubset(set(evidence_ids)) for item in value["claims"]):
        raise ContractError("P7 声明使用了不存在的 evidence_id")
    return value


def validate_verification(value, claim_ids, evidence_ids, claim_items=None):
    validate_stage_output("P8", value)
    result_ids = [item["claim_id"] for item in value["results"]]
    if set(result_ids) != set(claim_ids) or len(result_ids) != len(set(result_ids)):
        raise ContractError("P8 必须且只能核验本次全部声明")
    if any(not set(item["valid_evidence_ids"]).issubset(set(evidence_ids)) for item in value["results"]):
        raise ContractError("P8 使用了不存在的 evidence_id")
    claims_by_id = {item["claim_id"]: item for item in (claim_items or [])}
    for item in value["results"]:
        if item["support_status"] == "unsupported" and item["action"] != "remove":
            raise ContractError("P8 不支持的声明必须删除")
        if item["support_status"] == "partially_supported":
            original = claims_by_id.get(item["claim_id"], {}).get("atomic_claim", "").strip()
            revised = (item["revised_claim"] or "").strip()
            if item["action"] != "revise" or not revised or (original and revised == original):
                raise ContractError("P8 部分支持的声明必须产生实质性降级修订")
        if item["support_status"] == "cannot_determine" and item["action"] not in ("remove", "mark_unverified"):
            raise ContractError("P8 无法判断的声明必须删除或标未核实")
    return value


def validate_final(value, claim_ids, source_ids, evidence_ids, verification=None):
    validate_stage_output("P9", value)
    if not set(value["source_ids"]).issubset(set(source_ids)) or not set(value["evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P9 输出引用了输入之外的来源或证据")
    if not set(value["final_report"]["used_evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P9 报告使用了不存在的 evidence_id")
    if any(not set(page["evidence_ids"]).issubset(set(evidence_ids)) for page in value["final_ppt"]["pages"]):
        raise ContractError("P9 PPT 使用了不存在的 evidence_id")
    validate_ppt_density(value["final_ppt"]["pages"])
    validate_presentation_voice(value["final_ppt"]["pages"])
    delivery_text = "\n".join([value["final_report"]["markdown"]] + [
        "\n".join([page.get("speaker_notes", "")] + page.get("on_slide_text", []))
        for page in value["final_ppt"]["pages"]
    ])
    if any(fragment in delivery_text for fragment in ("，，", "，但。", "，而。", "，因此。", "；。", "。。", "。，", "，。")):
        raise ContractError("P9 核验修订留下断裂标点或空转折，不能交付")
    report_text = value["final_report"]["markdown"]
    if any(fragment in report_text for fragment in ("evidence_id", "source_id", "evidence_contexts", "（未核实）")):
        raise ContractError("P9 客户报告泄露内部审计字段或未核实标签，不能交付")
    reference_headings = re.findall(r"(?m)^#{1,3}\s*参考文献\s*$", value["final_report"]["markdown"])
    if len(reference_headings) > 1:
        raise ContractError("P9 报告重复生成参考文献标题，不能交付")
    if any(item["claim_id"] not in set(claim_ids) for item in value["change_log"]):
        raise ContractError("P9 变更记录使用了不存在的 claim_id")
    if verification is not None:
        expected = {"keep": "kept", "revise": "revised", "remove": "removed", "mark_unverified": "marked_unverified"}
        decisions = {item["claim_id"]: expected[item["action"]] for item in verification.get("results", [])}
        changes = {item["claim_id"]: item["action"] for item in value["change_log"]}
        if len(changes) != len(value["change_log"]) or set(changes) != set(decisions):
            raise ContractError("P9 必须为每条核验声明保留且仅保留一条变更记录")
        if any(changes[claim_id] != action for claim_id, action in decisions.items()):
            raise ContractError("P9 变更动作未落实 P8 核验结论")
    return value
