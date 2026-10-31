"""Shared deterministic retrieval/screening orchestration for research tasks."""

from __future__ import annotations

import os

from retrieval import search_all, search_patsnap_literature
from research_sources import (
    assess_source_quality,
    enrich_kept_open_full_text,
    merge_search_results,
    plan_patsnap_queries,
    plan_search_queries,
)


def search_and_screen_sources(
    workflow,
    *,
    topic,
    plan,
    tier="fast",
    supplement=True,
    candidate_records=None,
    previous_queries=(),
    patent_client=None,
    environ=None,
    search_fn=None,
    patsnap_search_fn=None,
):
    """Run planned retrieval, source screening, enrichment, and quality gates.

    The function has no HTTP or task-store dependencies, so local HTTP and
    background SCF execution can share exactly the same research rules. Network
    providers and environment are injectable for deterministic offline tests.
    """
    if not isinstance(topic, str) or not 2 <= len(topic.strip()) <= 500:
        raise ValueError("检索主题无效")
    if not isinstance(plan, dict) or not plan:
        raise ValueError("检索规划无效")
    if tier not in ("fast", "deep"):
        raise ValueError("检索版本无效")
    if not isinstance(previous_queries, (list, tuple)) or any(not isinstance(item, str) for item in previous_queries):
        raise ValueError("已有检索式必须是字符串列表")

    search_fn = search_fn or search_all
    patsnap_search_fn = patsnap_search_fn or search_patsnap_literature
    environ = os.environ if environ is None else environ
    topic = topic.strip()

    results = []
    if candidate_records is not None:
        if not isinstance(candidate_records, list) or any(not isinstance(item, dict) for item in candidate_records):
            raise ValueError("候选来源必须是对象列表")
        sources = {"query": "planned", "queries": list(previous_queries or []),
                   "records": candidate_records, "errors": []}
    else:
        queries = plan_search_queries(plan, topic)
        for index, query in enumerate(queries):
            results.append(search_fn(
                query,
                per_source=4 if tier == "deep" else 3,
                patent_client=patent_client if index == 0 else None,
                include_patsnap=False,
            ))

    if candidate_records is None and environ.get("PATSNAP_API_KEY", "").strip():
        detail_cache = {}
        for query in plan_patsnap_queries(plan, topic):
            try:
                results.append({
                    "query": "Patsnap: " + query,
                    "records": patsnap_search_fn(query, 2, detail_cache=detail_cache),
                    "errors": [],
                })
            except Exception as exc:
                results.append({
                    "query": "Patsnap: " + query,
                    "records": [],
                    "errors": [{"source": "Patsnap", "error": type(exc).__name__}],
                })

    if candidate_records is None:
        sources = merge_search_results(results, 24 if tier == "deep" else 12)
    candidates = sources["records"]
    if candidates:
        screening, usage = workflow.screen_sources(topic, plan, candidates, tier)
    else:
        # Empty retrieval is a real evidence insufficiency outcome, not a
        # worker/runtime exception. Keep it structured so later stages can
        # report the limitation and the entitlement policy can distinguish it
        # from a technical failure.
        screening = {
            "screening_version": "P3-batched-1.0",
            "topic": topic,
            "decisions": [],
            "summary": {"candidate_count": 0, "keep_count": 0, "reserve_count": 0,
                        "drop_count": 0, "open_issues": ["未检索到可筛选来源"]},
        }
        usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0, "attempts": 0}
    candidates, enrichment = enrich_kept_open_full_text(candidates, screening) if tier == "deep" else (
        candidates, {"lookups": 0, "enriched_source_ids": [], "errors": []}
    )
    quality = assess_source_quality(plan, candidates, screening, tier)
    search_update = None

    if tier == "deep" and supplement and not quality["passed"]:
        known_queries = set(previous_queries or [])
        extra_queries = [query for query in plan_search_queries(plan, topic, supplement=True, limit=3)
                         if query not in known_queries][:2]
        extra_results = [search_fn(query, per_source=4, include_patsnap=False) for query in extra_queries]
        if environ.get("PATSNAP_API_KEY", "").strip():
            for query in plan_patsnap_queries(plan, topic, supplement=True, limit=1):
                try:
                    extra_results.append({
                        "query": "Patsnap: " + query,
                        "records": patsnap_search_fn(query, 1),
                        "errors": [],
                    })
                except Exception as exc:
                    extra_results.append({
                        "query": "Patsnap: " + query,
                        "records": [],
                        "errors": [{"source": "Patsnap", "error": type(exc).__name__}],
                    })
        search_update = merge_search_results(
            [{"query": "previous", "records": candidates, "errors": []}] + extra_results,
            30,
        )
        updated = search_update["records"]
        if {item["source_id"] for item in updated} != {item["source_id"] for item in candidates}:
            candidates = updated
            screening, additional_usage = workflow.screen_sources(topic, plan, candidates, tier)
            candidates, additional_enrichment = enrich_kept_open_full_text(candidates, screening)
            enrichment["lookups"] += additional_enrichment["lookups"]
            enrichment["publisher_lookups"] = enrichment.get("publisher_lookups", 0) + additional_enrichment.get("publisher_lookups", 0)
            enrichment["enriched_source_ids"].extend(additional_enrichment["enriched_source_ids"])
            enrichment["errors"].extend(additional_enrichment["errors"])
            for key in ("prompt_tokens", "completion_tokens", "total_tokens", "attempts"):
                usage[key] = usage.get(key, 0) + additional_usage.get(key, 0)
            quality = assess_source_quality(plan, candidates, screening, tier)

    screening["quality_gate"] = quality
    screening["full_text_enrichment"] = enrichment
    sources["records"] = candidates
    if search_update:
        search_update["topic"] = topic
        search_update["records"] = candidates
        sources = search_update
    return {"sources": sources, "screening": screening, "usage": usage,
            "supplemental_search": search_update is not None}


__all__ = ["search_and_screen_sources"]
