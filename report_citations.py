"""Deterministic, source-backed citations for the customer report."""

import re


EVIDENCE_CITATION = re.compile(r"\[(EV::[^\]\s]+::\d{3})\]")
INTERNAL_OUTLINE_MARKER = re.compile(r"（M[1-9]\d*）")
ADJACENT_SAME_CITATION = re.compile(r"(\[\d+\]\(https://[^)]+\))\1+")
FULL_STOP_CITATIONS_COMMA = re.compile(r"。(\[\d+\]\(https://[^)]+\)(?:\[\d+\]\(https://[^)]+\))*)，")
REUSE_LABELS = {
    "allowed": "来源标注可复用（仍须核对具体许可）",
    "citation_only": "仅建议引用原文链接",
    "permission_required": "嵌入前需取得许可",
    "unknown": "许可未核实，仅提供原文链接",
}


def render_linked_report(markdown, evidence_records, source_records, figure_recommendations=None, figure_records=None):
    """Replace internal evidence IDs with clickable source citations.

    This runs only after verification has edited the report. The model never
    assigns source numbers or invents bibliography entries.
    """
    evidence_by_id = {item.get("evidence_id"): item for item in evidence_records}
    source_by_id = {item.get("source_id"): item for item in source_records}
    numbered = {}

    def replace(match):
        evidence_id = match.group(1)
        evidence = evidence_by_id.get(evidence_id)
        if not evidence:
            raise ValueError("报告引用了未保存的证据 " + evidence_id)
        source_id = evidence.get("source_id")
        source = source_by_id.get(source_id)
        if not source or not str(source.get("url") or "").startswith("https://"):
            raise ValueError("报告证据缺少可点击的来源网址 " + str(source_id))
        if source_id not in numbered:
            numbered[source_id] = len(numbered) + 1
        return "[%d](%s)" % (numbered[source_id], source["url"])

    if re.search(r"(?m)^#{1,3}\s*参考文献\s*$", markdown):
        raise ValueError("模型草稿自带参考文献表，无法安全生成确定性列表")
    rendered = EVIDENCE_CITATION.sub(replace, str(markdown or ""))
    # Planning markers are not customer citations. Keep scientific terms such
    # as macrophage M2 polarization, which lack these exact parentheses.
    rendered = INTERNAL_OUTLINE_MARKER.sub("", rendered)
    rendered = ADJACENT_SAME_CITATION.sub(r"\1", rendered)
    # A revised sentence may end before its citations while the next clause
    # retains the old comma. Remove only that orphan comma, not scientific text.
    rendered = FULL_STOP_CITATIONS_COMMA.sub(r"。\1", rendered)
    if "EV::" in rendered:
        raise ValueError("报告中仍有未转换的内部证据编号")
    if not numbered:
        raise ValueError("报告没有可核验的证据脚注")

    figure_lines = []
    figure_by_id = {item.get("figure_id"): item for item in (figure_records or [])}
    seen_figures = set()
    for recommendation in figure_recommendations or []:
        figure_id = recommendation.get("figure_id")
        figure = figure_by_id.get(figure_id)
        if not figure or figure.get("reuse_status") != recommendation.get("reuse_status"):
            raise ValueError("报告推荐了未核验或许可状态不一致的原文图片")
        if figure_id in seen_figures:
            continue
        seen_figures.add(figure_id)
        authoritative_url = str(figure.get("article_figure_url") or "").strip()
        url_match = re.search(r"https://[^\s|;)，]+", str(figure.get("locator") or ""))
        figure_url = authoritative_url or (url_match.group(0) if url_match else "")
        if not figure_url.startswith("https://"):
            raise ValueError("报告推荐图片缺少原文图页链接")
        purpose = str(recommendation.get("purpose") or "辅助说明").strip().rstrip("。.!！")
        figure_lines.append("- %s：%s。[查看原文图页](%s)；网址：%s；复用状态：%s。" % (
            recommendation.get("placement", "相关章节"), purpose,
            figure_url, figure_url, REUSE_LABELS.get(figure["reuse_status"], REUSE_LABELS["unknown"]),
        ))
    if figure_lines:
        rendered = rendered.rstrip() + "\n\n## 推荐配图\n\n" + "\n".join(figure_lines)

    references = []
    for source_id, number in sorted(numbered.items(), key=lambda item: item[1]):
        source = source_by_id[source_id]
        authors = [str(item).strip().rstrip(".") for item in (source.get("authors") or []) if str(item).strip()]
        author_text = ", ".join(authors[:6]) + (", et al." if len(authors) > 6 else ".") if authors else "Author unavailable."
        title = str(source.get("title") or "Untitled").strip().rstrip(".") + "."
        journal = str(source.get("journal") or source.get("source") or "Source unavailable").strip().rstrip(".") + "."
        year = str(source.get("year") or "n.d.").strip()
        volume = str(source.get("volume") or "").strip()
        issue = str(source.get("issue") or "").strip()
        pages = str(source.get("pages") or "").strip()
        locator = year + (";" + volume if volume else "") + ("(" + issue + ")" if issue else "") + (":" + pages if pages else "") + "."
        references.append("[%d] %s %s %s %s %s" % (number, author_text, title, journal, locator, source["url"]))
    return rendered.rstrip() + "\n\n## 参考文献\n\n" + "\n".join(references) + "\n"
