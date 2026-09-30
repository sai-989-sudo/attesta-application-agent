"""Research-mode data: Semantic Scholar Graph API (primary) and arXiv (fallback).

Only real API results are ever shown — nothing here generates or guesses papers.
Responses are cached in SQLite for 24 h to respect the public rate limits.
"""
from __future__ import annotations

import datetime as dt
import math
import time
import xml.etree.ElementTree as ET

import httpx

from .. import db
from .matcher import similarity_matrix
from .text import truncate

S2 = "https://api.semanticscholar.org/graph/v1"
ARXIV = "https://export.arxiv.org/api/query"
PAPER_FIELDS = "title,abstract,year,venue,url,citationCount,externalIds,authors"
AUTHOR_FIELDS = "name,affiliations,paperCount,citationCount,hIndex,url"
CACHE_AGE = 24 * 3600


class ScholarError(RuntimeError):
    pass


class ScholarClient:
    def __init__(self, api_key: str | None = None, transport: httpx.BaseTransport | None = None,
                 use_cache: bool = True, sleep=time.sleep):
        headers = {"User-Agent": "Attesta/1.0 (student research-match tool)"}
        if api_key:
            headers["x-api-key"] = api_key
        self.http = httpx.Client(timeout=20, headers=headers, transport=transport, follow_redirects=True)
        self.use_cache = use_cache
        self.sleep = sleep

    # ------------------------------------------------------------ transport
    def _get(self, url: str, params: dict | None = None, method: str = "GET", json_body=None, parse="json"):
        key = f"{method} {url} {sorted((params or {}).items())} {json_body}"
        if self.use_cache and (hit := db.cache_get(key, CACHE_AGE)) is not None:
            return hit
        last = None
        for attempt in range(3):
            try:
                r = self.http.request(method, url, params=params, json=json_body)
            except httpx.HTTPError as e:
                last = f"Network error: {e.__class__.__name__}"
                self.sleep(1.5 * (attempt + 1))
                continue
            if r.status_code == 429:
                last = "Rate limited by the API — wait a minute or add a free Semantic Scholar API key in Settings."
                self.sleep(float(r.headers.get("Retry-After", 2 ** attempt)))
                continue
            if r.status_code == 404:
                raise ScholarError("Not found.")
            if r.status_code >= 400:
                raise ScholarError(f"API error {r.status_code}.")
            data = r.json() if parse == "json" else r.text
            if self.use_cache:
                db.cache_put(key, data)
            return data
        raise ScholarError(last or "Request failed.")

    # ------------------------------------------------------------ Semantic Scholar
    def search_authors(self, name: str, limit: int = 10) -> list[dict]:
        data = self._get(f"{S2}/author/search", {"query": name, "fields": AUTHOR_FIELDS, "limit": limit})
        return [_author(a) for a in data.get("data", [])]

    def author(self, author_id: str) -> dict:
        return _author(self._get(f"{S2}/author/{author_id}", {"fields": AUTHOR_FIELDS}))

    def author_papers(self, author_id: str, limit: int = 100) -> list[dict]:
        data = self._get(f"{S2}/author/{author_id}/papers", {"fields": PAPER_FIELDS, "limit": limit})
        papers = [_paper(p, "Semantic Scholar") for p in data.get("data", []) if p.get("title")]
        return sorted(papers, key=lambda p: (p["year"] or 0, p["citations"] or 0), reverse=True)

    def authors_batch(self, ids: list[str]) -> dict[str, dict]:
        if not ids:
            return {}
        data = self._get(f"{S2}/author/batch", {"fields": AUTHOR_FIELDS}, method="POST", json_body={"ids": ids[:500]})
        return {a["authorId"]: _author(a) for a in data if a}

    def search_papers(self, query: str, limit: int = 100, since_years: int = 6) -> list[dict]:
        year_from = dt.date.today().year - since_years
        data = self._get(f"{S2}/paper/search", {"query": query, "fields": PAPER_FIELDS, "limit": limit,
                                                 "year": f"{year_from}-"})
        return [_paper(p, "Semantic Scholar") for p in data.get("data", []) if p.get("title")]

    # ------------------------------------------------------------ arXiv fallback
    def search_arxiv(self, query: str, limit: int = 60) -> list[dict]:
        terms = " AND ".join(f'all:"{w}"' if " " in w else f"all:{w}" for w in query.split()[:6])
        xml = self._get(ARXIV, {"search_query": terms, "start": 0, "max_results": limit, "sortBy": "relevance"}, parse="text")
        ns = {"a": "http://www.w3.org/2005/Atom"}
        root = ET.fromstring(xml)
        out = []
        for e in root.findall("a:entry", ns):
            title = " ".join((e.findtext("a:title", "", ns) or "").split())
            if not title:
                continue
            pub = e.findtext("a:published", "", ns) or ""
            out.append({
                "paperId": "arxiv:" + (e.findtext("a:id", "", ns) or "").rsplit("/", 1)[-1],
                "title": title,
                "abstract": " ".join((e.findtext("a:summary", "", ns) or "").split()),
                "year": int(pub[:4]) if pub[:4].isdigit() else None,
                "venue": "arXiv", "url": e.findtext("a:id", "", ns), "citations": None,
                "authors": [{"authorId": None, "name": a.findtext("a:name", "", ns)} for a in e.findall("a:author", ns)],
                "source": "arXiv",
            })
        return out


def _author(a: dict) -> dict:
    return {
        "authorId": a.get("authorId"), "name": a.get("name", ""),
        "affiliations": a.get("affiliations") or [], "paperCount": a.get("paperCount"),
        "citationCount": a.get("citationCount"), "hIndex": a.get("hIndex"), "url": a.get("url"),
    }


def _paper(p: dict, source: str) -> dict:
    return {
        "paperId": p.get("paperId"), "title": p.get("title", ""), "abstract": p.get("abstract") or "",
        "year": p.get("year"), "venue": p.get("venue") or "", "url": p.get("url") or "",
        "citations": p.get("citationCount"),
        "authors": [{"authorId": x.get("authorId"), "name": x.get("name", "")} for x in (p.get("authors") or [])],
        "source": source,
    }


# ------------------------------------------------------------------ ranking helpers
def _paper_text(p: dict) -> str:
    return f"{p['title']}. {p['abstract']}"


def shared_ground(papers: list[dict], evidence: list[dict], k: int = 3) -> list[dict]:
    """Evidence items most related to a set of papers (what the student can honestly connect to)."""
    if not papers or not evidence:
        return []
    sims = similarity_matrix([" ".join(_paper_text(p) for p in papers[:8])], evidence)[0]
    ranked = sorted(range(len(evidence)), key=lambda j: -sims[j])
    return [{"id": evidence[j]["id"], "text": evidence[j]["text"], "score": round(float(sims[j]), 3)}
            for j in ranked[:k] if sims[j] > 0.02]


def score_papers(papers: list[dict], query: str, evidence: list[dict]) -> list[dict]:
    """Attach topic relevance and overlap with the student's evidence to each paper."""
    if not papers:
        return []
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
    texts = [_paper_text(p) for p in papers]
    profile = " ".join(f"{e['context']} {e['text']}" for e in evidence)
    vec = TfidfVectorizer(stop_words="english", ngram_range=(1, 2), sublinear_tf=True).fit(texts + [query, profile])
    P = vec.transform(texts)
    topic = cosine_similarity(vec.transform([query]), P)[0] if query else [0.0] * len(papers)
    prof = cosine_similarity(vec.transform([profile]), P)[0] if profile.strip() else [0.0] * len(papers)
    this_year = dt.date.today().year
    for p, t, o in zip(papers, topic, prof):
        age = this_year - (p["year"] or this_year - 10)
        p["relevance"] = round(float(t), 3)
        p["overlap"] = round(float(o), 3)
        p["recency"] = round(math.exp(-max(age, 0) / 4), 3)
        p["snippet"] = truncate(p["abstract"], 260)
    return papers


def rank_researchers(client: ScholarClient, topic: str, evidence: list[dict], affiliation: str = "",
                     include_unknown: bool = False, top: int = 12) -> dict:
    source, note = "Semantic Scholar", ""
    try:
        papers = client.search_papers(topic)
    except ScholarError as e:
        papers, source = [], "arXiv"
        note = f"Semantic Scholar unavailable ({e}); showing arXiv results (no affiliations available)."
    if not papers:
        try:
            papers = client.search_arxiv(topic)
            source = "arXiv"
        except ScholarError as e:
            raise ScholarError(f"No results from Semantic Scholar or arXiv: {e}")
    papers = score_papers(papers, topic, evidence)

    agg: dict[str, dict] = {}
    for p in papers:
        for a in p["authors"][:12]:
            key = a["authorId"] or a["name"]
            if not key:
                continue
            r = agg.setdefault(key, {"authorId": a["authorId"], "name": a["name"], "papers": []})
            r["papers"].append(p)
    for r in agg.values():
        ps = sorted(r["papers"], key=lambda p: -(0.7 * p["relevance"] + 0.3 * p["overlap"]))
        best = ps[:3]
        r["papers"] = best
        r["score"] = round(sum(0.6 * p["relevance"] + 0.25 * p["overlap"] + 0.15 * p["recency"] for p in best) / 3
                           + 0.03 * math.log1p(len(ps)), 4)
        r["matchedPapers"] = len(ps)

    ranked = sorted(agg.values(), key=lambda r: -r["score"])
    if source == "Semantic Scholar":
        ids = [r["authorId"] for r in ranked[:80] if r["authorId"]]
        try:
            details = client.authors_batch(ids)
        except ScholarError:
            details, note = {}, "Could not load author affiliations (rate limit) — showing unfiltered results."
        for r in ranked:
            d = details.get(r["authorId"] or "", {})
            r.update({k: d.get(k) for k in ("affiliations", "hIndex", "paperCount", "url")})
    aff = affiliation.strip().lower()
    if aff and source == "Semantic Scholar" and not note.startswith("Could not"):
        def ok(r):
            affs = r.get("affiliations") or []
            if not affs:
                return include_unknown
            return any(aff in a.lower() for a in affs)
        ranked = [r for r in ranked if ok(r)]
    elif aff and source == "arXiv":
        note = (note + " " if note else "") + "Affiliation filter skipped: arXiv does not provide affiliations."

    results = ranked[:top]
    top_score = results[0]["score"] if results else 1
    for r in results:
        r["match"] = round(100 * r["score"] / top_score) if top_score else 0
        r["sharedGround"] = shared_ground(r["papers"], evidence, k=2)
    return {"source": source, "note": note.strip(), "papersScanned": len(papers), "researchers": results}
