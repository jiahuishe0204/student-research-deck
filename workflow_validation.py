"""Deterministic cross-stage validation for P1-P9 workflow outputs."""

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
)
LIMITATION_PAGE_TERMS = ("局限", "争议", "研究空白", "证据边界", "不足与展望")


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


def validate_presentation_voice(pages):
    """Keep internal audit language out of ordinary student-facing speaker notes."""
    ordinary_pages = []
    flagged_pages = []
    for page in pages:
        title = str(page.get("title", ""))
        purpose = str(page.get("purpose", ""))
        if any(term in title or term in purpose for term in LIMITATION_PAGE_TERMS):
            continue
        ordinary_pages.append(page)
        notes = str(page.get("speaker_notes", ""))
        hits = sum(notes.count(term) for term in AUDIT_LANGUAGE)
        if hits > 1:
            raise ContractError("PPT 普通页面讲稿反复使用证据审计措辞，应改为可直接讲述的汇报语言")
        if hits:
            flagged_pages.append(page.get("page_id"))
    if ordinary_pages and len(flagged_pages) / len(ordinary_pages) > 0.2:
        raise ContractError("PPT 讲稿中过多普通页面暴露内部证据审计语言，应集中到局限页")
    return pages


def validate_intent(value):
    required = {"domain", "normalized_topic", "scope_hint", "tier", "assumptions", "need_clarification", "clarification_question", "confirmation_text"}
    if not isinstance(value, dict) or set(value) != required:
        raise ValueError("意图识别返回字段不完整")
    if not isinstance(value["need_clarification"], bool):
        raise ValueError("澄清状态无效")
    if value["need_clarification"] and not isinstance(value["clarification_question"], str):
        raise ValueError("需要澄清时必须返回一个问题")
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


def validate_report(value, evidence_ids):
    validate_stage_output("P5", value)
    if not set(value["used_evidence_ids"]).issubset(set(evidence_ids)):
        raise ContractError("P5 使用了不存在的 evidence_id")
    return value


def validate_ppt(value, evidence_ids, figure_ids, source_ids=None):
    validate_stage_output("P6", value)
    allowed_evidence = set(evidence_ids)
    allowed_figures = set(figure_ids)
    allowed_sources = set(source_ids or [])
    for page in value["pages"]:
        if not set(page["evidence_ids"]).issubset(allowed_evidence):
            raise ContractError("P6 页面使用了不存在的 evidence_id")
        for figure in page["figure_refs"]:
            if figure["figure_id"] not in allowed_figures:
                raise ContractError("P6 页面使用了不存在的 figure_id")
        if allowed_sources and not {item["source_id"] for item in page["source_citations"]}.issubset(allowed_sources):
            raise ContractError("P6 页面使用了不存在的 source_id")
    validate_ppt_density(value["pages"])
    validate_presentation_voice(value["pages"])
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
