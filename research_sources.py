"""Shared retrieval planning and source-quality rules for every delivery path."""

import os
import re

from retrieval import (hydrate_frontiers_full_text, merge_source_records, search_all,
                       search_europe_pmc, search_patsnap_literature)


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


def plan_patsnap_queries(plan, fallback, *, supplement=False, limit=2):
    """Build short natural-language queries for Patsnap, not PubMed syntax."""
    concepts = plan.get("search_concepts", {}) if isinstance(plan, dict) else {}
    if not isinstance(concepts, dict):
        concepts = {}
    explicit = _phrases(concepts.get("patsnap_terms", []))
    if not explicit:
        core = _phrases(concepts.get("core_terms", []))
        details = []
        for key, value in concepts.items():
            if key not in ("core_terms", "patsnap_terms"):
                details.extend(_phrases(value))
        explicit = core[:2] + details[:1]
    if supplement and len(explicit) > 1:
        explicit = explicit[1:]
    return list(dict.fromkeys(explicit))[:limit] or [str(fallback).strip()]


def merge_search_results(results, limit=30):
    """Merge duplicate representations conservatively and retain source provenance."""
    merged = merge_source_records([record for result in results for record in result.get("records", [])])
    return {
        "query": " | ".join(item.get("query", "") for item in results),
        "queries": [item.get("query", "") for item in results],
        "records": merged[:limit],
        "errors": [error for item in results for error in item.get("errors", [])],
    }


def screen_sources_with_quality(workflow, topic, plan, candidates, tier="fast", queries=None):
    """Run the same screening, enrichment and supplement policy in local and cloud paths."""
    output, usage = workflow.screen_sources(topic, plan, candidates, tier)
    candidates, enrichment = (enrich_kept_open_full_text(candidates, output)
                              if tier == "deep" else
                              (candidates, {"lookups": 0, "enriched_source_ids": [], "errors": []}))
    quality = assess_source_quality(plan, candidates, output, tier)
    search_update = None
    if tier == "deep" and not quality["passed"]:
        previous_queries = set(queries or [])
        extra_queries = [item for item in plan_search_queries(plan, topic, supplement=True, limit=3)
                         if item not in previous_queries][:2]
        if extra_queries:
            extra_results = [search_all(item, per_source=4, include_patsnap=False)
                             for item in extra_queries]
            if os.environ.get("PATSNAP_API_KEY", "").strip():
                for patsnap_query in plan_patsnap_queries(plan, topic, supplement=True, limit=1):
                    try:
                        extra_results.append({"query": "Patsnap: " + patsnap_query,
                                              "records": search_patsnap_literature(patsnap_query, 1),
                                              "errors": []})
                    except Exception as exc:
                        extra_results.append({"query": "Patsnap: " + patsnap_query, "records": [],
                                              "errors": [{"source": "Patsnap", "error": type(exc).__name__}]})
            search_update = merge_search_results(
                [{"query": "previous", "records": candidates, "errors": []}] + extra_results, 30)
            updated = search_update["records"]
            if {item["source_id"] for item in updated} != {item["source_id"] for item in candidates}:
                candidates = updated
                output, additional_usage = workflow.screen_sources(topic, plan, candidates, tier)
                candidates, additional_enrichment = enrich_kept_open_full_text(candidates, output)
                enrichment["lookups"] += additional_enrichment["lookups"]
                enrichment["publisher_lookups"] = enrichment.get("publisher_lookups", 0) + additional_enrichment.get("publisher_lookups", 0)
                enrichment["enriched_source_ids"].extend(additional_enrichment["enriched_source_ids"])
                enrichment["errors"].extend(additional_enrichment["errors"])
                for key in ("prompt_tokens", "completion_tokens", "total_tokens", "attempts"):
                    usage[key] = usage.get(key, 0) + additional_usage.get(key, 0)
                quality = assess_source_quality(plan, candidates, output, tier)
    output["quality_gate"] = quality
    output["full_text_enrichment"] = enrichment
    if search_update:
        search_update["topic"] = topic
        search_update["records"] = candidates
    return output, usage, candidates, search_update


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
