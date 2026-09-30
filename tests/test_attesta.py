import os
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ["ATTESTA_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
os.environ.pop("ATTESTA_PROVIDER", None)

from fastapi.testclient import TestClient  # noqa: E402

import backend.main as main  # noqa: E402
from backend.engine import llm  # noqa: E402
from backend.engine.requirements import extract_requirements  # noqa: E402
from backend.engine.resume import parse_resume  # noqa: E402
from backend.engine.scholar import ScholarClient, ScholarError  # noqa: E402
from backend.engine.skills import extract_skills, skill_groups  # noqa: E402
from backend.engine.text import split_sentences  # noqa: E402
from backend.engine.verifier import build_sources, verify_text  # noqa: E402
from tests import fixtures  # noqa: E402

SAMPLE_RESUME = (ROOT / "samples" / "sample_resume.txt").read_text()
SAMPLE_JOB = (ROOT / "samples" / "sample_job.txt").read_text()
client = TestClient(main.app)
mock_scholar = lambda: ScholarClient(transport=httpx.MockTransport(fixtures.handler), use_cache=False)  # noqa: E731


@pytest.fixture(autouse=True)
def _mock_scholar(monkeypatch):
    monkeypatch.setattr(main, "scholar", mock_scholar)


@pytest.fixture
def profile():
    return client.post("/api/profile/sample").json()


# ------------------------------------------------------------------ engine units
def test_skill_extraction_and_groups():
    assert extract_skills("Built REST APIs in Flask; C++ and C#") == ["REST APIs", "Flask", "C++", "C#"]
    assert skill_groups("Python or R, and SQL") == [["Python", "R"], ["SQL"]]
    assert "R" not in extract_skills("Read the report")


def test_sentence_split_keeps_abbreviations_and_citations():
    s = split_sentences("I am an M.S. student [E1]. I built X. [E2] Dr. Lee works on e.g. vision.")
    assert s == ["I am an M.S. student [E1].", "I built X. [E2]", "Dr. Lee works on e.g. vision."]


def test_resume_parser_sections_and_demonstrated():
    ev = parse_resume(SAMPLE_RESUME)["evidence"]
    secs = {e["section"] for e in ev}
    assert {"Education", "Experience", "Projects", "Skills", "Certifications"} <= secs
    tableau = next(e for e in ev if "Tableau dashboard" in e["text"])
    assert tableau["demonstrated"] and "Tableau" in tableau["skills"] and tableau["context"].startswith("Data Analyst Intern")
    assert not next(e for e in ev if e["section"] == "Skills")["demonstrated"]


def test_requirement_kinds():
    reqs = extract_requirements(SAMPLE_JOB)
    kinds = {r["text"][:25]: r["kind"] for r in reqs}
    assert kinds["Working knowledge of SQL"] == "required"
    assert kinds["Familiarity with Power BI"] == "preferred"
    assert kinds["Currently enrolled as a s"] == "eligibility"
    assert not any("equal opportunity" in r["text"] for r in reqs)


# ------------------------------------------------------------------ verifier
def _sources():
    ev = parse_resume(SAMPLE_RESUME)["evidence"]
    paper = {"title": "Retinal vessel segmentation with U-Nets", "abstract": "Deep learning for retinal images.",
             "year": 2024, "venue": "Conf", "authors": [{"name": "Jane Doe"}]}
    return ev, build_sources(ev, [paper])


@pytest.mark.parametrize("sentence,status", [
    ("I built an NLP pipeline with spaCy to extract symptoms from 500 synthetic clinical notes [E10].", "attested"),
    ("I have deployed models on Kubernetes [E13].", "unsupported"),          # invented skill
    ("I improved accuracy by 35% [E12].", "unsupported"),                    # invented number
    ("I have extensive PyTorch experience.", "unsupported"),                 # no citation
    ("I worked at Google on search [E4].", "unsupported"),                   # invented employer
    ("I have deep learning experience [P1].", "unsupported"),                # self-claim cited to a paper
    ("I tutored students in Python [E99].", "unsupported"),                  # fake citation
    ("I also built a Tableau dashboard [E4].", "warn"),                      # real but mis-cited
    ("I have not yet worked with medical imaging.", "gap"),
    ("Would you be open to a short meeting?", "neutral"),
])
def test_verifier_statuses(sentence, status):
    _, src = _sources()
    r = verify_text(sentence, src, {"Jane Doe"})
    assert r["sentences"][0]["status"] == status, r["sentences"][0]["reasons"]


# ------------------------------------------------------------------ API: ledger / fit / drafts
def test_profile_crud(profile):
    assert len(profile["evidence"]) > 10 and profile["display"] == "Riley Chen"
    ev = [{k: e[k] for k in ("id", "section", "context", "text")} for e in profile["evidence"]][:3]
    ev.append({"section": "Projects", "context": "Demo", "text": "Built a FastAPI service with PostgreSQL"})
    p = client.put("/api/profile", json={"name": "Riley", "evidence": ev}).json()
    assert [e["id"] for e in p["evidence"]] == ["E1", "E2", "E3", "E4"]
    assert "PostgreSQL" in p["evidence"][3]["skills"]


def test_upload_rejects_bad_type():
    r = client.post("/api/profile/upload", files={"file": ("x.exe", b"MZ", "application/octet-stream")})
    assert r.status_code == 400


def test_fit_and_drafts_are_fully_attested(profile):
    fit = client.post("/api/fit", json={"posting": SAMPLE_JOB, "org": "Library Data Services"}).json()
    rep = fit["report"]
    assert 60 <= rep["score"] <= 100 and rep["recommendation"].startswith("APPLY")
    levels = {m["text"][:25]: m["level"] for m in rep["matches"]}
    assert levels["Familiarity with Power BI"] == "No Evidence"
    assert levels["Working knowledge of SQL"] == "Strong"
    for kind in ("cover_letter", "resume_bullets"):
        d = client.post("/api/drafts", json={"kind": kind}).json()
        assert d["verification"]["summary"]["unsupported"] == 0, d["struck"]
        assert d["engine"] == "offline"


def test_llm_output_is_verified_and_struck(profile, monkeypatch):
    client.post("/api/fit", json={"posting": SAMPLE_JOB})
    fake = ("Dear Hiring Committee,\n\nI cleaned and merged 3 years of sales data in pandas and SQL [E4]. "
            "I led a team of 12 engineers at Microsoft [E4]. I am an expert in Kubernetes.\n\nSincerely,\nRiley Chen")
    calls = []
    monkeypatch.setattr(main, "settings", lambda: {"provider": "anthropic", "api_key": "x", "model": ""})
    monkeypatch.setattr(llm, "complete", lambda *a, **k: calls.append(1) or fake)
    d = client.post("/api/drafts", json={"kind": "cover_letter"}).json()
    assert len(calls) == 2  # draft + one repair round
    assert d["verification"]["summary"]["unsupported"] == 0
    assert len(d["struck"]) == 2 and "Microsoft" not in d["text"] and "Kubernetes" not in d["text"]


def test_llm_failure_falls_back_offline(profile, monkeypatch):
    client.post("/api/fit", json={"posting": SAMPLE_JOB})
    monkeypatch.setattr(main, "settings", lambda: {"provider": "openai", "api_key": "", "model": ""})
    d = client.post("/api/drafts", json={"kind": "cover_letter"}).json()
    assert d["engine"] == "offline" and "offline writer" in d["note"]


def test_verify_endpoint_flags_user_edits(profile):
    r = client.post("/api/verify", json={"text": "I built dashboards in Power BI [E5]."}).json()
    assert r["sentences"][0]["status"] == "unsupported"


# ------------------------------------------------------------------ API: research (mocked)
def test_topic_ranking_filters_affiliation(profile):
    r = client.post("/api/research/topic", json={"topic": "clinical NLP symptom extraction", "affiliation": "Arizona State"}).json()
    names = [x["name"] for x in r["researchers"]]
    assert names[0] == "Avery Fixture" and "Casey Elsewhere" not in names and "Morgan Placeholder" not in names
    r2 = client.post("/api/research/topic", json={"topic": "clinical NLP", "affiliation": "Arizona State", "include_unknown": True}).json()
    assert "Morgan Placeholder" in [x["name"] for x in r2["researchers"]]


def test_author_search_and_outreach_draft(profile):
    authors = client.get("/api/research/authors", params={"q": "Avery"}).json()["authors"]
    assert authors[0]["authorId"] == "a1"
    res = client.get("/api/research/authors/a1/papers", params={"topic": "clinical NLP"}).json()
    titles = [p["title"] for p in res["papers"]]
    assert len(titles) == 2 and all("clinical" in t.lower() for t in titles) and res["sharedGround"]
    d = client.post("/api/drafts", json={"kind": "outreach_email", "papers": res["papers"][:2],
                                         "professor": "Avery Fixture", "interest": "clinical NLP"}).json()
    assert d["verification"]["summary"]["unsupported"] == 0, d["struck"]
    assert titles[0] in d["text"] and "[P1]" in d["text"]


def test_scholar_rate_limit_is_reported():
    c = ScholarClient(transport=httpx.MockTransport(fixtures.rate_limited), use_cache=False, sleep=lambda s: None)
    with pytest.raises(ScholarError, match="Rate limited"):
        c.search_authors("anyone")


def test_arxiv_parsing():
    c = ScholarClient(transport=httpx.MockTransport(fixtures.handler), use_cache=False)
    p = c.search_arxiv("clinical text")[0]
    assert p["title"] == "Fixture paper on clinical text mining" and p["year"] == 2025


# ------------------------------------------------------------------ API: pipeline / settings
def test_pipeline_crud():
    item = client.post("/api/pipeline", json={"kind": "job", "title": "Data Assistant", "fit_score": 80}).json()
    assert item["status"] == "researching"
    upd = client.patch(f"/api/pipeline/{item['id']}", json={"status": "applied", "follow_up": "2026-10-10"}).json()
    assert upd["status"] == "applied"
    assert client.patch(f"/api/pipeline/{item['id']}", json={"status": "bogus"}).status_code == 400
    assert client.delete(f"/api/pipeline/{item['id']}").json()["ok"]


def test_settings_masks_key():
    s = client.put("/api/settings", json={"provider": "anthropic", "api_key": "sk-secret-1234"}).json()
    assert s["api_key"].endswith("1234") and "secret" not in s["api_key"]
    s = client.put("/api/settings", json={"provider": "anthropic", "api_key": None}).json()
    assert s["api_key"].endswith("1234")  # kept
    client.put("/api/settings", json={"provider": "offline"})
