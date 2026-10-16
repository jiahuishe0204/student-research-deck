"""Apply explicit, evidence-linked page edits to a verified delivery."""

import copy

from workflow_validation import validate_final


REVISABLE_FIELDS = {"title", "visual_suggestion", "speaker_notes", "on_slide_text"}


def apply_reviewed_page_revisions(delivery, revisions, claims, verification):
    """Apply exact-match reviewer edits and recheck the whole delivery.

    This does not invent replacement language. Each edit must identify the
    affected P8 claim, its old text, the reviewer-approved new text, and why.
    """
    result = copy.deepcopy(delivery)
    pages = {page["page_id"]: page for page in result["final_ppt"]["pages"]}
    claim_by_id = {item["claim_id"]: item for item in claims}
    verified_ids = {item["claim_id"] for item in verification["results"]}
    if not revisions:
        raise ValueError("没有可应用的审稿修订")
    for revision in revisions:
        page_id = revision.get("page_id")
        field = revision.get("field")
        old = revision.get("old")
        new = revision.get("new")
        claim_ids = revision.get("claim_ids")
        if page_id not in pages or field not in REVISABLE_FIELDS or not isinstance(old, str) or not old or not isinstance(new, str) or not new or old == new or not str(revision.get("reason") or "").strip():
            raise ValueError("审稿修订缺少页码、精确原文、替换文案或审核理由")
        if not isinstance(claim_ids, list) or not claim_ids or any(
            claim_id not in verified_ids or claim_by_id.get(claim_id, {}).get("section_or_page_id") != page_id
            for claim_id in claim_ids
        ):
            raise ValueError("审稿修订没有关联到本页已核验的声明")
        page = pages[page_id]
        if field == "on_slide_text":
            if page[field].count(old) != 1:
                raise ValueError("上屏要点原文不唯一或已发生变化")
            page[field][page[field].index(old)] = new
        else:
            current = page[field]
            if current.count(old) != 1:
                raise ValueError("页面原文不唯一或已发生变化")
            page[field] = current.replace(old, new, 1)
    validate_final(result, list(claim_by_id), result["source_ids"], result["evidence_ids"], verification)
    return result
