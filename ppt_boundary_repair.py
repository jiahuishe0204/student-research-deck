"""Rebuild affected pages exclusively from their accepted P8 statements."""

import copy
from workflow_validation import presentation_boundary_issues, PPT_DENSITY_LIMITS


def repair_verified_pages(pages, claims, verification, evidence_records=None):
    """No inference or model call: the approved sentences are the only facts.

    Rebuild the entire affected page, so the old conclusion cannot survive in
    another field. If the accepted statements cannot fit, fail without deleting
    qualifiers or silently dropping facts.
    """
    result = copy.deepcopy(pages)
    verdicts = {item["claim_id"]: item for item in verification.get("results", [])}
    evidence_sources = {item["evidence_id"]: item.get("source_id") for item in (evidence_records or [])}
    repairs = []
    for page in result:
        issues = presentation_boundary_issues(page)
        if not issues:
            continue
        statements, used_ids, accepted_claims = [], [], []
        for claim in claims:
            if claim.get("section_or_page_id") != page["page_id"] or not claim.get("location_type", "").startswith("ppt_"):
                continue
            verdict = verdicts.get(claim["claim_id"], {})
            if verdict.get("action") == "keep" and verdict.get("support_status") == "supported":
                statement = claim["original_text"]
            elif verdict.get("action") == "revise" and verdict.get("support_status") == "partially_supported":
                statement = verdict.get("revised_claim") or ""
            else:
                continue
            statement = statement.strip()
            if not statement or statement.endswith(("，", "、", "：", ":")):
                raise ValueError("已核验句子仍不完整，不能自动修复页面 " + page["page_id"])
            cited = set(claim.get("cited_evidence_ids", []))
            valid = cited.intersection(verdict.get("valid_evidence_ids", []))
            if not valid:
                raise ValueError("自动修复缺少已核验的原引用 " + claim["claim_id"])
            if statement not in statements:
                statements.append(statement)
            used_ids.extend(sorted(valid))
            accepted_claims.append(claim["claim_id"])
        if not statements:
            raise ValueError("页面没有可用于自动修复的已核验结论 " + page["page_id"])
        notes = "\n".join(statement.rstrip("。") + "。" for statement in statements)
        if len(notes) > PPT_DENSITY_LIMITS["speaker_notes_max"]:
            raise ValueError("已核验内容超出单页讲稿容量，不能截断科学限定 " + page["page_id"])
        bullets = []
        for statement in statements:
            if len(statement) <= PPT_DENSITY_LIMITS["bullet_characters_max"] and len(bullets) < PPT_DENSITY_LIMITS["bullets_max"] and sum(map(len, bullets)) + len(statement) <= PPT_DENSITY_LIMITS["page_characters_max"]:
                bullets.append(statement)
        if not bullets:
            raise ValueError("已核验内容无法构成完整上屏要点 " + page["page_id"])
        page.update(title="研究结果与适用条件", purpose="呈现本页实验结果及其适用范围",
                    on_slide_text=bullets, speaker_notes=notes,
                    visual_suggestion="以文字卡片展示本页研究结果与实验条件；具体数据及限定见要点与讲稿。",
                    evidence_ids=list(dict.fromkeys(used_ids)))
        # Figure uses were written for the old conclusion. Keep bibliography,
        # but do not silently transfer that interpretation to a repaired page.
        page["figure_refs"] = []
        if evidence_sources:
            sources = {evidence_sources.get(item) for item in used_ids}
            page["source_citations"] = [item for item in page.get("source_citations", []) if item["source_id"] in sources]
        repairs.append({"page_id": page["page_id"], "issues": issues, "claim_ids": accepted_claims})
    return result, repairs
