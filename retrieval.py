"""Public literature API adapters and deterministic source normalization."""

import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

USER_AGENT = "research-delivery-local-mvp/0.2"


def fetch_json(base, params, timeout=30):
    url = base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def fetch_bytes(base, params, timeout=30):
    url = base + "?" + urllib.parse.urlencode(params)
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_url_bytes(url, timeout=30):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def fetch_patsnap_json(path, api_key, payload=None, params=None, timeout=30):
    """Call an allow-listed Patsnap Open Platform endpoint."""
    base = "https://connect.patsnap.com"
    if not path.startswith("/synapse/"):
        raise ValueError("unsupported Patsnap API path")
    url = base + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    headers = {"User-Agent": USER_AGENT, "Authorization": "Bearer " + api_key, "Accept": "application/json"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("status"):
        raise RuntimeError("Patsnap API error %s" % result.get("error_code", "unknown"))
    return result.get("data")


def _localized_text(items, field):
    items = items if isinstance(items, list) else []
    for preferred in ("EN", "CN"):
        for item in items:
            if isinstance(item, dict) and item.get("lang") == preferred and item.get(field):
                return str(item[field]).strip()
    for item in items:
        if isinstance(item, dict) and item.get(field):
            return str(item[field]).strip()
    return ""


def search_patsnap_literature(query, limit=5, api_key=None, detail_cache=None):
    """Search Patsnap B011 and normalize B030 details into the shared source contract."""
    api_key = (api_key if api_key is not None else os.environ.get("PATSNAP_API_KEY", "")).strip()
    if not api_key:
        return []
    search = fetch_patsnap_json("/synapse/paper/search", api_key, {
        "offset": 0, "limit": min(max(int(limit), 1), 20),
        "keyword": {"value": [query], "condition": "OR"},
        "sort": [{"sort_field": "score", "sort_order": "desc"}],
    }) or {}
    records = []
    detail_cache = {} if detail_cache is None else detail_cache
    for item in search.get("items", [])[:limit]:
        paper_id = str(item.get("paper_id") or "").strip()
        if not paper_id:
            continue
        if paper_id not in detail_cache:
            detail_cache[paper_id] = fetch_patsnap_json("/synapse/paper/detail", api_key, params={"paper_id": paper_id}) or {}
        detail = detail_cache[paper_id]
        doi = str(detail.get("doi") or "").strip()
        publication_date = str(detail.get("publication_date") or detail.get("epub_date") or "")
        records.append({
            "source": "Patsnap", "source_id": "PATSNAP:PAPER:" + paper_id,
            "patsnap_paper_id": paper_id, "pmid": "", "doi": doi,
            "title": _localized_text(detail.get("paper_title"), "title") or _localized_text(item.get("paper_title"), "title"),
            "abstract": _localized_text(detail.get("paper_abstract"), "abst"),
            "authors": [str(name).strip() for name in detail.get("author", []) if str(name).strip()][:6],
            "journal": str(detail.get("journal") or "").strip(), "year": publication_date[:4],
            "volume": "", "issue": "", "pages": "",
            "url": ("https://doi.org/" + urllib.parse.quote(doi, safe="/")) if doi else "https://synapse.patsnap.com/",
            "access": "abstract" if detail.get("paper_abstract") else "metadata",
            "patsnap_entities": {key: detail.get(key, []) for key in ("drug", "target", "disease", "organization")},
        })
    return records


def text_of(node):
    return "" if node is None else "".join(node.itertext()).strip()


def search_pubmed(query, limit=5):
    common = {"db": "pubmed", "tool": "research_delivery_mvp"}
    email = os.environ.get("RESEARCH_CONTACT_EMAIL", "").strip()
    api_key = os.environ.get("NCBI_API_KEY", "").strip()
    if email:
        common["email"] = email
    if api_key:
        common["api_key"] = api_key
    search = fetch_json(
        "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi",
        {**common, "term": query, "retmax": limit, "retmode": "json", "sort": "relevance"},
    )
    ids = search.get("esearchresult", {}).get("idlist", [])
    if not ids:
        return []
    root = ET.fromstring(
        fetch_bytes(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi",
            {**common, "id": ",".join(ids), "retmode": "xml"},
        )
    )
    records = []
    for article in root.findall(".//PubmedArticle"):
        citation = article.find("MedlineCitation")
        data = citation.find("Article") if citation is not None else None
        if data is None:
            continue
        pmid = text_of(citation.find("PMID"))
        doi = ""
        for identifier in article.findall("./PubmedData/ArticleIdList/ArticleId"):
            if identifier.attrib.get("IdType") == "doi":
                doi = text_of(identifier)
        authors = []
        for author in data.findall(".//Author")[:6]:
            name = " ".join(filter(None, [text_of(author.find("ForeName")), text_of(author.find("LastName"))]))
            if name:
                authors.append(name)
        abstract = " ".join(text_of(item) for item in data.findall(".//AbstractText"))
        publication_types = [text_of(item) for item in data.findall(".//PublicationType") if text_of(item)]
        year = text_of(data.find(".//PubDate/Year")) or text_of(data.find(".//ArticleDate/Year"))
        records.append({
            "source": "PubMed", "source_id": "PMID:" + pmid, "pmid": pmid, "doi": doi,
            "title": text_of(data.find("ArticleTitle")), "abstract": abstract,
            "authors": authors, "journal": text_of(data.find("Journal/Title")), "year": year,
            "volume": text_of(data.find("Journal/JournalIssue/Volume")), "issue": text_of(data.find("Journal/JournalIssue/Issue")),
            "pages": text_of(data.find("Pagination/MedlinePgn")),
            "publication_types": publication_types,
            "url": "https://pubmed.ncbi.nlm.nih.gov/%s/" % pmid, "access": "abstract",
        })
    return records


def search_europe_pmc(query, limit=5):
    data = fetch_json(
        "https://www.ebi.ac.uk/europepmc/webservices/rest/search",
        {"query": query, "format": "json", "resultType": "core", "pageSize": limit},
    )
    records = []
    for item in data.get("resultList", {}).get("result", []):
        source = item.get("source", "")
        ext_id = item.get("id", "")
        pmid = item.get("pmid", "")
        doi = item.get("doi", "")
        pmcid = item.get("pmcid", "")
        records.append({
            "source": "Europe PMC", "source_id": "%s:%s" % (source, ext_id), "pmid": pmid, "doi": doi,
            "title": item.get("title", ""), "abstract": item.get("abstractText", ""),
            "authors": [name.strip() for name in item.get("authorString", "").split(",") if name.strip()][:6],
            "journal": item.get("journalTitle", ""), "year": str(item.get("pubYear", "")),
            "volume": item.get("journalVolume", ""), "issue": item.get("issue", ""), "pages": item.get("pageInfo", ""),
            "url": "https://europepmc.org/article/%s/%s" % (source, ext_id),
            "publication_types": item.get("pubTypeList", {}).get("pubType", []),
            "pmcid": pmcid, "access": "full_text" if item.get("inEPMC") == "Y" and pmcid else "abstract",
        })
    return records


def hydrate_europe_pmc_full_text(record, text_limit=24000, figure_limit=12):
    """Fetch open full text only for a selected Europe PMC source and retain figure locators."""
    if record.get("source") != "Europe PMC" or not record.get("pmcid"):
        return dict(record)
    hydrated = dict(record)
    pmcid = str(record["pmcid"]).strip()
    url = "https://www.ebi.ac.uk/europepmc/webservices/rest/%s/fullTextXML" % urllib.parse.quote(pmcid)
    try:
        root = ET.fromstring(fetch_url_bytes(url))
    except Exception as exc:
        hydrated["full_text_error"] = type(exc).__name__
        return hydrated
    body = root.find(".//body")
    full_text = re.sub(r"\s+", " ", text_of(body)).strip()
    if full_text:
        hydrated["full_text"] = full_text[:text_limit]
        hydrated["access"] = "full_text"
    figures = []
    for index, figure in enumerate(root.findall(".//fig")[:figure_limit], 1):
        figure_id = figure.attrib.get("id") or "fig-%d" % index
        label = text_of(figure.find("label")) or figure_id
        caption = re.sub(r"\s+", " ", text_of(figure.find("caption"))).strip()
        figures.append({
            "figure_id": "%s:%s" % (record.get("source_id", pmcid), figure_id),
            "label": label, "caption": caption,
            "locator": "%s, %s" % (pmcid, label),
            "article_figure_url": "https://europepmc.org/articles/%s/figure/%s" % (pmcid, figure_id),
            "reuse_status": "unknown",
        })
    hydrated["figure_candidates"] = figures
    return hydrated


def hydrate_frontiers_full_text(record, text_limit=24000, figure_limit=12):
    """Read a Frontiers JATS XML by DOI; never infer image reuse rights."""
    doi = str(record.get("doi") or "").strip().lower()
    if not doi.startswith("10.3389/"):
        return dict(record)
    hydrated = dict(record)
    try:
        request = urllib.request.Request(
            "https://doi.org/" + urllib.parse.quote(doi, safe="/"),
            headers={"User-Agent": USER_AGENT}, method="HEAD",
        )
        with urllib.request.urlopen(request, timeout=20) as response:
            landing_url = response.geturl()
        parsed = urllib.parse.urlsplit(landing_url)
        if parsed.scheme != "https" or parsed.hostname not in ("frontiersin.org", "www.frontiersin.org") or not parsed.path.endswith("/full"):
            return hydrated
        xml_url = urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path[:-5] + "/xml", "", ""))
        root = ET.fromstring(fetch_url_bytes(xml_url))
    except Exception as exc:
        hydrated["full_text_error"] = type(exc).__name__
        return hydrated
    body = root.find(".//body")
    full_text = re.sub(r"\s+", " ", text_of(body)).strip()
    if not full_text:
        return hydrated
    hydrated["full_text"] = full_text[:text_limit]
    hydrated["access"] = "full_text"
    hydrated["source"] = "Frontiers"
    hydrated["url"] = landing_url
    hydrated["also_found_in"] = list(dict.fromkeys((record.get("also_found_in") or []) + ["Frontiers"]))
    figures = []
    for index, figure in enumerate(root.findall(".//fig")[:figure_limit], 1):
        figure_id = figure.attrib.get("id") or "fig-%d" % index
        label = text_of(figure.find("label")) or figure_id
        figures.append({
            "figure_id": "%s:%s" % (record.get("source_id") or doi, figure_id),
            "label": label,
            "caption": re.sub(r"\s+", " ", text_of(figure.find("caption"))).strip(),
            "locator": "%s, %s" % (doi, label),
            "article_figure_url": landing_url + "#" + urllib.parse.quote(figure_id, safe=""),
            "reuse_status": "unknown",
        })
    hydrated["figure_candidates"] = figures
    return hydrated


def search_crossref(query, limit=5):
    params = {"query.bibliographic": query, "rows": limit, "select": "DOI,title,author,published,container-title,abstract,URL,type"}
    email = os.environ.get("RESEARCH_CONTACT_EMAIL", "").strip()
    if email:
        params["mailto"] = email
    data = fetch_json("https://api.crossref.org/works", params)
    records = []
    for item in data.get("message", {}).get("items", []):
        parts = item.get("published", {}).get("date-parts", [[]])
        year = str(parts[0][0]) if parts and parts[0] else ""
        authors = [" ".join(filter(None, [a.get("given", ""), a.get("family", "")])).strip() for a in item.get("author", [])[:6]]
        abstract = re.sub(r"<[^>]+>", " ", item.get("abstract", ""))
        doi = item.get("DOI", "")
        records.append({
            "source": "Crossref", "source_id": "DOI:" + doi, "pmid": "", "doi": doi,
            "title": (item.get("title") or [""])[0], "abstract": re.sub(r"\s+", " ", abstract).strip(),
            "authors": authors, "journal": (item.get("container-title") or [""])[0], "year": year,
            "volume": item.get("volume", ""), "issue": item.get("issue", ""), "pages": item.get("page", ""),
            "url": item.get("URL", ""), "access": "metadata",
        })
    return records


def normalized_key(record):
    doi = normalize_doi(record.get("doi"))
    if doi:
        return "doi:" + doi
    pmid = re.sub(r"\D", "", str(record.get("pmid") or ""))
    if pmid:
        return "pmid:" + pmid
    trial_id = normalize_trial_id(record)
    if trial_id:
        return "trial:" + trial_id
    family = str(record.get("patent_family_id") or record.get("family_id") or "").strip().upper()
    if family:
        return "patent-family:" + family
    source_id = str(record.get("source_id") or "").strip()
    if source_id:
        return "record:" + source_id
    title = normalize_title(record.get("title"))
    return "title:" + title if title else "record:unknown"


def normalize_doi(value):
    doi = str(value or "").strip().lower()
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi\s*:\s*)", "", doi)
    return doi.rstrip(" .;,)")


def normalize_title(value):
    return re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(value or "").lower())


def normalize_trial_id(record):
    candidates = [record.get("trial_id"), record.get("nct_id"), record.get("registry_id")]
    for value in candidates:
        match = re.search(r"NCT\s*\d{8}", str(value or ""), re.I)
        if match:
            return match.group(0).replace(" ", "").upper()
    return ""


def classify_source(record):
    """Classify source material without changing its scientific evidence strength."""
    source = str(record.get("source") or "").lower()
    kind = str(record.get("source_type") or record.get("record_type") or "").lower()
    if "patent" in source or "patent" in kind or record.get("patent_id"):
        return "patent"
    if "trial" in source or "clinical_trial" in kind or normalize_trial_id(record):
        return "clinical_trial_registry"
    if any(word in source for word in ("regulatory", "fda", "ema", "official", "guideline")) or kind in ("regulatory", "guideline"):
        return "regulatory_or_guideline"
    if any(word in source for word in ("news", "company", "press")) or kind in ("company_disclosure", "news"):
        return "company_or_news"
    if source in ("patsnap", "pubmed", "europe pmc", "crossref", "frontiers") or record.get("doi") or record.get("pmid"):
        return "scientific_literature"
    return "other"


def classify_publication_level(record):
    publication_types = record.get("publication_types", [])
    if isinstance(publication_types, str):
        publication_types = [publication_types]
    text = " ".join([str(item) for item in publication_types] + [str(record.get("title") or "")]).lower()
    if "preprint" in text or "pre-print" in text:
        return "preprint"
    if re.search(r"\breview\b|meta.analysis|systematic review|perspective|editorial|commentary", text):
        return "secondary"
    if re.search(r"clinical trial|randomized controlled trial|observational study|case reports|comparative study|research article|journal article", text):
        return "primary"
    if record.get("source_type") == "scientific_literature" or classify_source(record) == "scientific_literature":
        return "primary_or_secondary_unclassified"
    return "not_applicable"


def _title_records_compatible(first, second):
    title_a, title_b = normalize_title(first.get("title")), normalize_title(second.get("title"))
    if not title_a or title_a != title_b:
        return False
    for field in ("doi", "pmid"):
        a = normalize_doi(first.get(field)) if field == "doi" else re.sub(r"\D", "", str(first.get(field) or ""))
        b = normalize_doi(second.get(field)) if field == "doi" else re.sub(r"\D", "", str(second.get(field) or ""))
        if a and b and a != b:
            return False
    year_a, year_b = str(first.get("year") or "")[:4], str(second.get("year") or "")[:4]
    if year_a.isdigit() and year_b.isdigit() and abs(int(year_a) - int(year_b)) > 1:
        return False
    authors_a = first.get("authors", [])
    authors_b = second.get("authors", [])
    authors_a = [authors_a] if isinstance(authors_a, str) else authors_a
    authors_b = [authors_b] if isinstance(authors_b, str) else authors_b
    authors_a = {re.sub(r"[^a-z0-9]+", "", str(name).lower()) for name in authors_a if name}
    authors_b = {re.sub(r"[^a-z0-9]+", "", str(name).lower()) for name in authors_b if name}
    return not authors_a or not authors_b or bool(authors_a & authors_b)


_SOURCE_PREFERENCE = {
    "Europe PMC": 70, "Frontiers": 65, "PubMed": 60, "Patsnap": 55, "Crossref": 30,
}


def merge_source_records(records):
    """Deduplicate representations of one work, preserving their provenance and best readable record."""
    groups, aliases = [], {}
    for original in records:
        record = dict(original)
        record["doi"] = normalize_doi(record.get("doi"))
        record["canonical_identity"] = normalized_key(record)
        record["source_type"] = classify_source(record)
        record["publication_level"] = classify_publication_level(record)
        record["reading_scope"] = {"full_text": "full_text", "abstract": "abstract"}.get(record.get("access"), "metadata_only")
        record.setdefault("retrieved_at", datetime.now(timezone.utc).isoformat(timespec="seconds"))
        if record["source_type"] in ("scientific_literature", "clinical_trial_registry"):
            record["intended_uses"] = list(record.get("intended_uses") or (["literature_discovery", "scientific_evidence_review"] if record["source_type"] == "scientific_literature" else ["trial_status"] ))
        identifiers = []
        for key, value in (("doi", record.get("doi")), ("pmid", re.sub(r"\D", "", str(record.get("pmid") or ""))), ("trial", normalize_trial_id(record)), ("family", str(record.get("patent_family_id") or record.get("family_id") or "").strip().upper())):
            if value:
                identifiers.append(key + ":" + value)
        if not identifiers and record.get("source_id"):
            identifiers.append("record:" + str(record["source_id"]))
        matches = {aliases[item] for item in identifiers if item in aliases}
        if not matches and record.get("title"):
            matches = {index for index, group in enumerate(groups) if _title_records_compatible(group["record"], record)}
        if len(matches) > 1:
            # Merge alias-linked buckets only when all present persistent IDs agree.
            indexes = sorted(matches)
            base = indexes[0]
            for other in reversed(indexes[1:]):
                if not _title_records_compatible(groups[base]["record"], groups[other]["record"]):
                    continue
                groups[base] = _merge_record_group(groups[base], groups[other])
                groups.pop(other)
                aliases = {key: (base if value == other else value - 1 if value > other else value) for key, value in aliases.items()}
            matches = {base}
        if matches:
            index = next(iter(matches))
            groups[index] = _merge_record_group(groups[index], {"record": record, "provenance": _record_provenance(record)})
        else:
            provenance = _record_provenance(record)
            groups.append({"record": record, "provenance": provenance})
            index = len(groups) - 1
        for identifier in identifiers:
            aliases[identifier] = index
    output = []
    for group in groups:
        record = group["record"]
        record["source_records"] = _dedupe_provenance(group["provenance"])
        record["also_found_in"] = list(dict.fromkeys(item["source"] for item in record["source_records"] if item.get("source")))
        record["independence_group"] = record["canonical_identity"]
        output.append(record)
    return output


def _record_provenance(record):
    existing = record.get("source_records")
    if isinstance(existing, list) and existing:
        return [dict(item) for item in existing if isinstance(item, dict)]
    return [{"source": record.get("source", "unknown"), "source_id": str(record.get("source_id") or ""),
             "url": record.get("url", ""), "access": record.get("access", "metadata"),
             "retrieved_at": record.get("retrieved_at", "")}]


def _dedupe_provenance(items):
    unique = {}
    for item in items:
        key = (item.get("source"), item.get("source_id"))
        if key not in unique or (item.get("access") == "full_text" and unique[key].get("access") != "full_text"):
            unique[key] = item
    return list(unique.values())


def _merge_record_group(current_group, incoming_group):
    current, incoming = current_group["record"], incoming_group["record"]
    provenance = current_group["provenance"] + incoming_group["provenance"]
    for item in incoming_group["provenance"]:
        if item not in provenance:
            provenance.append(item)
    # Keep one display/source identity, preferring an open full-text locator.
    current_rank = _SOURCE_PREFERENCE.get(current.get("source"), 0) + (100 if current.get("access") == "full_text" and current.get("pmcid") else 0)
    incoming_rank = _SOURCE_PREFERENCE.get(incoming.get("source"), 0) + (100 if incoming.get("access") == "full_text" and incoming.get("pmcid") else 0)
    if incoming_rank > current_rank:
        replacement = dict(incoming)
        replacement.update({key: value for key, value in current.items() if value not in (None, "", [], {}) and key not in replacement})
        current = replacement
    else:
        current = dict(current)
        for field, value in incoming.items():
            if field not in current or current[field] in (None, "", [], {}):
                current[field] = value
    for field in ("abstract", "full_text"):
        if len(str(incoming.get(field) or "")) > len(str(current.get(field) or "")):
            current[field] = incoming[field]
    current["source_records"] = provenance
    current["source_type"] = current_group["record"].get("source_type") or incoming.get("source_type")
    current["publication_level"] = current_group["record"].get("publication_level") or incoming.get("publication_level")
    current["canonical_identity"] = normalized_key(current)
    current["reading_scope"] = "full_text" if any(item.get("access") == "full_text" for item in provenance) else "abstract" if any(item.get("access") == "abstract" for item in provenance) else "metadata_only"
    current["retrieved_at"] = max([str(item.get("retrieved_at") or "") for item in provenance] or [""])
    entities = dict(current.get("patsnap_entities") or {})
    for key, value in (incoming.get("patsnap_entities") or {}).items():
        if value and not entities.get(key):
            entities[key] = value
    if entities:
        current["patsnap_entities"] = entities
    return {"record": current, "provenance": provenance}


def search_all(query, per_source=5, patent_client=None, patent_query=None,
               include_patsnap=True, patsnap_query=None, epo_client=None, epo_query=None):
    """Search literature plus one configured patent provider.

    ``epo_client``/``epo_query`` remain accepted for backward compatibility.
    """
    results, errors = [], []
    searchers = [("PubMed", search_pubmed), ("Europe PMC", search_europe_pmc), ("Crossref", search_crossref)]
    if include_patsnap and os.environ.get("PATSNAP_API_KEY", "").strip():
        searchers.append(("Patsnap", lambda _query, limit: search_patsnap_literature(patsnap_query or query, limit)))
    for name, searcher in searchers:
        try:
            results.extend(searcher(query, per_source))
        except Exception as exc:
            errors.append({"source": name, "error": type(exc).__name__})
    patent_client = patent_client or epo_client
    patent_query = patent_query or epo_query or query
    if patent_client is not None:
        try:
            results.extend(patent_client.search(patent_query, min(per_source, 3)))
        except Exception as exc:
            errors.append({"source": getattr(patent_client, "provider_name", "Patent provider"),
                           "error": type(exc).__name__})
    return {"query": query, "records": merge_source_records(results), "errors": errors}
