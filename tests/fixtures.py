"""FICTIONAL fixture data shaped like Semantic Scholar / arXiv responses.

Used only by the test-suite (and the screenshot harness) because tests must not
depend on live APIs. None of these people or papers are real.
"""
import json

import httpx

PAPERS = [
    {"paperId": "p1", "title": "Symptom extraction from clinical notes with rule-guided transformers",
     "abstract": "We extract symptoms from clinical notes by combining spaCy rule-based NLP pipelines with a fine-tuned BERT model, reporting precision and recall on de-identified notes.",
     "year": 2025, "venue": "Journal of Fictional Biomedical Informatics", "url": "https://example.org/p1", "citationCount": 14,
     "authors": [{"authorId": "a1", "name": "Avery Fixture"}, {"authorId": "a2", "name": "Morgan Placeholder"}]},
    {"paperId": "p2", "title": "Evaluating clinical NLP pipelines under distribution shift",
     "abstract": "A study of named entity recognition in clinical text across hospitals, measuring how pipelines degrade and how to recalibrate them.",
     "year": 2024, "venue": "Fictional NLP Workshop", "url": "https://example.org/p2", "citationCount": 6,
     "authors": [{"authorId": "a1", "name": "Avery Fixture"}]},
    {"paperId": "p3", "title": "Retinal vessel segmentation with lightweight U-Nets",
     "abstract": "We propose a compact deep learning model for retinal image segmentation using computer vision techniques.",
     "year": 2023, "venue": "Fictional Vision Conference", "url": "https://example.org/p3", "citationCount": 30,
     "authors": [{"authorId": "a3", "name": "Jordan Sample"}]},
    {"paperId": "p4", "title": "Dashboards for hospital operations analytics",
     "abstract": "Tableau dashboards and SQL data pipelines for monitoring hospital operations.",
     "year": 2022, "venue": "Fictional Analytics Symposium", "url": "https://example.org/p4", "citationCount": 3,
     "authors": [{"authorId": "a2", "name": "Morgan Placeholder"}, {"authorId": "a4", "name": "Casey Elsewhere"}]},
]
AUTHORS = {
    "a1": {"authorId": "a1", "name": "Avery Fixture", "affiliations": ["Arizona State University"], "paperCount": 42, "citationCount": 900, "hIndex": 15, "url": "https://example.org/a1"},
    "a2": {"authorId": "a2", "name": "Morgan Placeholder", "affiliations": [], "paperCount": 20, "citationCount": 300, "hIndex": 9, "url": "https://example.org/a2"},
    "a3": {"authorId": "a3", "name": "Jordan Sample", "affiliations": ["Arizona State University"], "paperCount": 61, "citationCount": 2100, "hIndex": 22, "url": "https://example.org/a3"},
    "a4": {"authorId": "a4", "name": "Casey Elsewhere", "affiliations": ["Another University"], "paperCount": 12, "citationCount": 80, "hIndex": 5, "url": "https://example.org/a4"},
}
ARXIV_XML = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry><id>http://arxiv.org/abs/2501.00001v1</id><published>2025-01-05T00:00:00Z</published>
    <title>Fixture paper on clinical text mining</title><summary>Fictional abstract about NLP for clinical notes.</summary>
    <author><name>Riley Fixture</name></author></entry>
</feed>"""


def handler(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    if request.url.host == "export.arxiv.org":
        return httpx.Response(200, text=ARXIV_XML)
    if path.endswith("/paper/search"):
        return httpx.Response(200, json={"total": len(PAPERS), "offset": 0, "data": PAPERS})
    if path.endswith("/author/search"):
        q = request.url.params.get("query", "").lower()
        hits = [a for a in AUTHORS.values() if any(w in a["name"].lower() for w in q.split())]
        return httpx.Response(200, json={"total": len(hits), "offset": 0, "data": hits})
    if path.endswith("/author/batch"):
        ids = json.loads(request.content)["ids"]
        return httpx.Response(200, json=[AUTHORS.get(i) for i in ids])
    if "/author/" in path and path.endswith("/papers"):
        aid = path.split("/author/")[1].split("/")[0]
        return httpx.Response(200, json={"offset": 0, "data": [p for p in PAPERS if any(a["authorId"] == aid for a in p["authors"])]})
    if "/author/" in path:
        aid = path.rsplit("/", 1)[1]
        return httpx.Response(200, json=AUTHORS[aid]) if aid in AUTHORS else httpx.Response(404)
    return httpx.Response(404)


def rate_limited(_request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": "0"})
