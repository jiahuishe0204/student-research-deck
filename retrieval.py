"""Public literature API adapters and deterministic source normalization."""

import json
import os
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

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
        year = text_of(data.find(".//PubDate/Year")) or text_of(data.find(".//ArticleDate/Year"))
        records.append({
            "source": "PubMed", "source_id": "PMID:" + pmid, "pmid": pmid, "doi": doi,
            "title": text_of(data.find("ArticleTitle")), "abstract": abstract,
            "authors": authors, "journal": text_of(data.find("Journal/Title")), "year": year,
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
        records.append({
            "source": "Europe PMC", "source_id": "%s:%s" % (source, ext_id), "pmid": pmid, "doi": doi,
            "title": item.get("title", ""), "abstract": item.get("abstractText", ""),
            "authors": [name.strip() for name in item.get("authorString", "").split(",") if name.strip()][:6],
            "journal": item.get("journalTitle", ""), "year": str(item.get("pubYear", "")),
            "url": "https://europepmc.org/article/%s/%s" % (source, ext_id),
            "access": "full_text" if item.get("inEPMC") == "Y" else "abstract",
        })
    return records


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
            "url": item.get("URL", ""), "access": "metadata",
        })
    return records


def normalized_key(record):
    if record.get("doi"):
        return "doi:" + record["doi"].lower().strip()
    if record.get("pmid"):
        return "pmid:" + record["pmid"].strip()
    title = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", record.get("title", "").lower())
    return "title:" + title


def search_all(query, per_source=5, epo_client=None, epo_query=None):
    results, errors = [], []
    for name, searcher in (("PubMed", search_pubmed), ("Europe PMC", search_europe_pmc), ("Crossref", search_crossref)):
        try:
            results.extend(searcher(query, per_source))
        except Exception as exc:
            errors.append({"source": name, "error": type(exc).__name__})
    if epo_client is not None:
        try:
            results.extend(epo_client.search(epo_query or query, min(per_source, 3)))
        except Exception as exc:
            errors.append({"source": "EPO OPS", "error": type(exc).__name__})
    deduplicated = {}
    for record in results:
        key = normalized_key(record)
        if key not in deduplicated:
            record["also_found_in"] = [record["source"]]
            deduplicated[key] = record
        elif record["source"] not in deduplicated[key]["also_found_in"]:
            deduplicated[key]["also_found_in"].append(record["source"])
            if len(record.get("abstract", "")) > len(deduplicated[key].get("abstract", "")):
                deduplicated[key]["abstract"] = record["abstract"]
                deduplicated[key]["access"] = record["access"]
    return {"query": query, "records": list(deduplicated.values()), "errors": errors}
