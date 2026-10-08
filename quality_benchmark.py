"""Deterministic scoring for the fixed model-quality and PPT-density benchmark."""


def score_verification(results, gold, allowed_evidence_ids):
    by_id = {item["claim_id"]: item for item in results}
    structure_ok = set(by_id) == set(gold)
    status_exact = action_exact = issue_hits = evidence_hits = wording_hits = 0
    critical_errors, hallucinated = [], []
    details = {}
    for claim_id, expected in gold.items():
        actual = by_id.get(claim_id, {})
        status_ok = actual.get("support_status") == expected["support_status"]
        action_ok = actual.get("action") == expected["action"]
        issue_ok = expected["required_issue"] in actual.get("issue_codes", [])
        valid = set(actual.get("valid_evidence_ids", []))
        required = set(expected.get("required_evidence", []))
        forbidden = tuple(expected.get("forbidden_evidence_prefixes", []))
        evidence_ok = required.issubset(valid) and not any(item.startswith(forbidden) for item in valid) if forbidden else required.issubset(valid)
        if not required:
            evidence_ok = evidence_ok and not valid
        unknown = sorted(valid - set(allowed_evidence_ids))
        hallucinated.extend((claim_id, item) for item in unknown)
        wording = (actual.get("explanation", "") + " " + (actual.get("revised_claim") or ""))
        wording_ok = all(term in wording for term in expected.get("required_terms", []))
        status_exact += status_ok; action_exact += action_ok; issue_hits += issue_ok; evidence_hits += evidence_ok; wording_hits += wording_ok
        if expected["support_status"] in ("unsupported", "cannot_determine") and (actual.get("support_status") == "supported" or actual.get("action") == "keep"):
            critical_errors.append(claim_id)
        details[claim_id] = {"status":status_ok,"action":action_ok,"issue":issue_ok,"evidence":evidence_ok,"wording":wording_ok}
    score = status_exact * 3 + action_exact * 2 + issue_hits + evidence_hits * 2 + wording_hits + (10 if structure_ok else 0)
    return {"score":score,"structure_ok":structure_ok,"status_exact":status_exact,"action_exact":action_exact,"issue_hits":issue_hits,"evidence_hits":evidence_hits,"wording_hits":wording_hits,"critical_errors":critical_errors,"hallucinated_evidence":hallucinated,"details":details}


def score_ppt_density(pages, limits):
    page_results, total = [], 0
    for page in pages:
        bullets = page.get("on_slide_text", [])
        characters = sum(len(item) for item in bullets)
        total += characters
        failures = []
        if characters > limits["page_characters_max"]: failures.append("page_characters")
        if len(bullets) > limits["bullets_max"]: failures.append("bullet_count")
        if any(len(item) > limits["bullet_characters_max"] for item in bullets): failures.append("bullet_length")
        if len(page.get("speaker_notes", "")) > limits["speaker_notes_max"]: failures.append("speaker_notes")
        page_results.append({"page_id":page.get("page_id"),"characters":characters,"bullets":len(bullets),"failures":failures})
    average = total / len(pages) if pages else 0
    return {"average_characters":round(average,1),"average_pass":average <= limits["deck_average_max"],"failed_pages":[item for item in page_results if item["failures"]],"pages":page_results}
