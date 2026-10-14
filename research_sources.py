"""Shared retrieval planning and source-quality rules for every delivery path."""

import re

from retrieval import hydrate_frontiers_full_text, normalized_key, search_europe_pmc


def _phrases(value):
    if isinstance(value, str):
        text = value.strip().replace('"', "")
        return [text] if 3 <= len(text) <= 100 and re.search(r"[A-Za-z]{3}", text) else []
    if isinstance(value, list):
        return [phrase for item in value for phrase in _phrases(item)]
    return []


def plan_search_queries(plan, fallback, *, supplement=False, limit=6):
    """Give each story group a search chance; keep a shared topic anchor."""
    groups = plan.get("search_concepts", {}) if isinstance(plan, dict) else {}
    if not isinstance(groups, dict):
        groups = {}
    core = _phrases(groups.get("core_terms", []))
    queries = []
    if len(core) >= 2:
        anchor = " AND ".join('"%s"' % term for term in core[:3])
        if not supplement:
            queries.append(anchor)
        for name, terms in groups.items():
            if name == "core_terms":
                continue
            phrases = _phrases(terms)
            if phrases:
                detail = phrases[1] if supplement and len(phrases) > 1 else phrases[0]
                queries.append('"%s" AND "%s" AND (%s)' % (core[0], core[1], detail))
    else:
        for terms in groups.values():
            phrases = _phrases(terms)
            if phrases:
                queries.append(phrases[1] if supplement and len(phrases) > 1 else phrases[0])
    return list(dict.fromkeys(queries))[:limit] or [fallback]


def merge_search_results(results, limit=30):
    """Merge by DOI/PMID/title and preserve the richest open-access locator."""
    records = {}
    aliases = {}
    for result in results:
        for record in result.get("records", []):
            title_key = "title:" + re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(record.get("title") or "").lower())
            identifiers = [value for value in (
                "doi:" + str(record.get("doi") or "").lower().strip() if record.get("doi") else "",
                "pmid:" + str(record.get("pmid") or "").strip() if record.get("pmid") else "",
                title_key if len(title_key) > 12 else "",
            ) if value]
            key = normalized_key(record)
            for identifier in identifiers:
                candidate_key = aliases.get(identifier)
                if candidate_key is None:
                    continue
                candidate = records[candidate_key]
                if record.get("doi") and candidate.get("doi") and str(record["doi"]).lower() != str(candidate["doi"]).lower():
                    continue
                if record.get("pmid") and candidate.get("pmid") and str(record["pmid"]) != str(candidate["pmid"]):
                    continue
                key = candidate_key
                break
            if key not in records:
                records[key] = dict(record)
                records[key]["also_found_in"] = list(record.get("also_found_in") or [record.get("source", "unknown")])
                for value in identifiers:
                    aliases[value] = key
                continue
            current = records[key]
            for value in identifiers:
                if value not in aliases:
                    aliases[value] = key
            current["also_found_in"] = list(dict.fromkeys(current["also_found_in"] + (record.get("also_found_in") or [record.get("source", "unknown")])))
            for field in ("abstract", "title", "authors", "journal", "publication_types", "pmcid", "pmid", "doi", "volume", "issue", "pages"):
                existing = current.get(field)
                incoming = record.get(field)
                if incoming and (not existing or field == "abstract" and len(str(incoming)) > len(str(existing))):
                    current[field] = incoming
            if record.get("pmcid") and record.get("access") == "full_text":
                current["source"] = "Europe PMC"
                current["access"] = "full_text"
                current["url"] = record.get("url") or current.get("url")
    return {
        "query": " | ".join(item.get("query", "") for item in results),
        "queries": [item.get("query", "") for item in results],
        "records": list(records.values())[:limit],
        "errors": [error for item in results for error in item.get("errors", [])],
    }


def _primary(record):
    types = " ".join(record.get("publication_types") or []).lower()
    title = str(record.get("title") or "").lower()
    if re.search(r"\breview\b|meta.analysis|perspective|editorial|commentary|news", types + " " + title):
        return False
    if not (record.get("abstract") or record.get("full_text")):
        return False
    return bool(re.search(r"clinical trial|randomized|cohort|case.control|observational|research article|journal article", types))


def assess_source_quality(plan, records, screening, tier="deep"):
    by_id = {item.get("source_id"): item for item in records}
    kept = [by_id[item["source_id"]] for item in screening.get("decisions", [])
            if item.get("status") == "keep" and item.get("source_id") in by_id]
    usable_ids = {item["source_id"] for item in kept if item.get("abstract") or item.get("full_text")}
    primary = [item for item in kept if item["source_id"] in usable_ids and _primary(item)]
    full_text = [item for item in kept if item["source_id"] in usable_ids and item.get("access") == "full_text"]
    question_ids = {item.get("question_id") for item in plan.get("questions", []) if isinstance(item, dict)}
    covered = {qid for item in screening.get("decisions", []) if item.get("status") == "keep" and item.get("source_id") in usable_ids
               for qid in item.get("question_ids", [])}
    gaps = sorted(question_ids - covered)
    problems = []
    if not usable_ids:
        problems.append("没有可读取摘要或全文的保留来源")
    if tier == "deep":
        if len(usable_ids) < 5:
            problems.append("深入版有效来源少于5条")
        if len(primary) < 2:
            problems.append("深入版可识别的原始研究少于2条")
        if not full_text:
            problems.append("深入版没有可读取的开放全文，无法可靠定位原文图片")
        if gaps:
            problems.append("研究问题缺少可读取来源：" + "、".join(gaps))
    return {"passed": not problems, "usable_source_ids": sorted(usable_ids),
            "usable_count": len(usable_ids), "primary_count": len(primary), "full_text_count": len(full_text),
            "uncovered_question_ids": gaps, "problems": problems}


def assess_evidence_quality(plan, evidence_records, tier="deep"):
    question_ids = {item.get("question_id") for item in plan.get("questions", []) if isinstance(item, dict)}
    covered = {qid for item in evidence_records for qid in item.get("question_ids", [])}
    gaps = sorted(question_ids - covered)
    problems = []
    if not evidence_records:
        problems.append("没有可提取证据")
    if tier == "deep" and gaps:
        problems.append("研究问题缺少直接提取证据：" + "、".join(gaps))
    return {"passed": not problems, "uncovered_question_ids": gaps, "problems": problems}


def enrich_kept_open_full_text(records, screening, max_lookups=8, max_publisher_lookups=4):
    """Resolve selected full text from Europe PMC or a supported publisher without a model call."""
    kept_ids = {item.get("source_id") for item in screening.get("decisions", []) if item.get("status") == "keep"}
    updated = [dict(item) for item in records]
    enriched = []
    errors = []
    lookups = 0
    publisher_lookups = 0
    for record in updated:
        pmid = str(record.get("pmid") or "").strip()
        if record.get("source_id") not in kept_ids or record.get("access") == "full_text":
            continue
        match = None
        if pmid and lookups < max_lookups:
            lookups += 1
            try:
                matches = search_europe_pmc("EXT_ID:%s AND SRC:MED" % pmid, 1)
                match = next((item for item in matches if str(item.get("pmid") or "") == pmid
                              and item.get("pmcid") and item.get("access") == "full_text"
                              and (not record.get("doi") or not item.get("doi") or str(record["doi"]).lower() == str(item["doi"]).lower())), None)
            except Exception as exc:
                errors.append({"source_id": record.get("source_id"), "error": type(exc).__name__})
        if match:
            for field in ("pmcid", "access", "url", "source"):
                record[field] = match[field]
            if len(str(match.get("abstract") or "")) > len(str(record.get("abstract") or "")):
                record["abstract"] = match["abstract"]
            record["also_found_in"] = list(dict.fromkeys((record.get("also_found_in") or []) + ["Europe PMC"]))
            enriched.append(record["source_id"])
            continue
        if str(record.get("doi") or "").lower().startswith("10.3389/") and publisher_lookups < max_publisher_lookups:
            publisher_lookups += 1
            publisher = hydrate_frontiers_full_text(record)
            if publisher.get("access") == "full_text" and publisher.get("full_text"):
                record.update(publisher)
                enriched.append(record["source_id"])
            elif publisher.get("full_text_error"):
                errors.append({"source_id": record.get("source_id"), "error": publisher["full_text_error"]})
    return updated, {"lookups": lookups, "publisher_lookups": publisher_lookups, "enriched_source_ids": enriched, "errors": errors}
