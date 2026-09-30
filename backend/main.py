"""Attesta API (FastAPI). Run from the project root:  python run.py"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db
from .engine import llm
from .engine.matcher import fit_report
from .engine.requirements import extract_requirements, guess_title
from .engine.resume import enrich, parse_resume, read_file, renumber
from .engine.skills import category
from .engine.scholar import ScholarClient, ScholarError, rank_researchers, score_papers, shared_ground
from .engine.verifier import build_sources, verify_text
from .engine.writer import display_name, generate

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
SAMPLES = ROOT / "samples"
MAX_UPLOAD = 5 * 1024 * 1024

app = FastAPI(title="Attesta", version="1.0.0", description="Evidence-grounded application agent for students")
db.init()


# ----------------------------------------------------------------- models
class TextIn(BaseModel):
    text: str = Field(min_length=20, max_length=60_000)


class EvidenceItem(BaseModel):
    id: str = ""
    section: str = "Experience"
    context: str = ""
    text: str = Field(min_length=3, max_length=600)


class ProfileIn(BaseModel):
    name: str = ""
    evidence: list[EvidenceItem]


class FitIn(BaseModel):
    posting: str = Field(min_length=40, max_length=40_000)
    title: str = ""
    org: str = ""


class TopicIn(BaseModel):
    topic: str = Field(min_length=3, max_length=200)
    affiliation: str = ""
    include_unknown: bool = False


class DraftIn(BaseModel):
    kind: Literal["cover_letter", "outreach_email", "resume_bullets"]
    title: str = ""
    org: str = ""
    professor: str = ""
    interest: str = ""
    papers: list[dict] = []


class VerifyIn(BaseModel):
    text: str = Field(max_length=30_000)
    papers: list[dict] = []
    allowed: list[str] = []


class PipelineIn(BaseModel):
    kind: Literal["job", "research"] = "job"
    title: str = Field(min_length=1, max_length=200)
    org: str = ""
    contact: str = ""
    status: str = "researching"
    fit_score: int | None = None
    follow_up: str = ""
    notes: str = ""
    link: str = ""


class PipelinePatch(BaseModel):
    title: str | None = None
    org: str | None = None
    contact: str | None = None
    status: str | None = None
    fit_score: int | None = None
    follow_up: str | None = None
    notes: str | None = None
    link: str | None = None


class SettingsIn(BaseModel):
    provider: Literal["offline", "anthropic", "openai", "ollama"] = "offline"
    model: str = ""
    api_key: str | None = None      # None = keep existing
    ollama_url: str = "http://localhost:11434"
    s2_api_key: str | None = None


# ----------------------------------------------------------------- helpers
def settings() -> dict:
    s = {"provider": "offline", "model": "", "api_key": "", "ollama_url": "http://localhost:11434", "s2_api_key": ""}
    s.update(db.get("settings", {}))
    # environment variables override stored values (handy for .env / deployment)
    prov = os.environ.get("ATTESTA_PROVIDER")
    if prov:
        s["provider"] = prov
    env_key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}.get(s["provider"])
    if env_key and os.environ.get(env_key):
        s["api_key"] = os.environ[env_key]
    if os.environ.get("S2_API_KEY"):
        s["s2_api_key"] = os.environ["S2_API_KEY"]
    return s


def mask(k: str) -> str:
    return "" if not k else ("•" * 8 + k[-4:])


def profile_or_400() -> dict:
    p = db.get("profile")
    if not p or not p.get("evidence"):
        raise HTTPException(400, "Add your resume in the Ledger first.")
    return p


def save_profile(parsed: dict, source: str) -> dict:
    prof = {"name": parsed.get("name", ""), "evidence": parsed["evidence"], "source": source, "updated": time.time()}
    db.put("profile", prof)
    return public_profile(prof)


def public_profile(p: dict | None) -> dict:
    if not p:
        return {"name": "", "evidence": [], "source": "", "updated": None, "display": "", "skills": []}
    skills: dict[str, dict] = {}
    for e in p["evidence"]:
        for sk in e["skills"] + e.get("context_skills", []):
            d = skills.setdefault(sk, {"name": sk, "category": category(sk), "demonstrated": False, "ids": []})
            d["demonstrated"] |= e["demonstrated"]
            if e["id"] not in d["ids"]:
                d["ids"].append(e["id"])
    return {**p, "display": display_name(p), "skills": sorted(skills.values(), key=lambda d: (not d["demonstrated"], d["name"].lower()))}


def scholar() -> ScholarClient:
    return ScholarClient(api_key=settings().get("s2_api_key") or None)


@app.exception_handler(ScholarError)
async def scholar_error(_, exc: ScholarError):
    return JSONResponse({"detail": str(exc)}, status_code=502)


# ----------------------------------------------------------------- profile / ledger
@app.get("/api/health")
def health():
    s = settings()
    return {"ok": True, "provider": s["provider"], "version": app.version}


@app.get("/api/profile")
def get_profile():
    return public_profile(db.get("profile"))


@app.post("/api/profile/upload")
async def upload_profile(file: UploadFile = File(...)):
    data = await file.read()
    if len(data) > MAX_UPLOAD:
        raise HTTPException(413, "File too large (max 5 MB).")
    try:
        text = read_file(file.filename or "", data)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception:
        raise HTTPException(400, "Could not read that file. Try exporting it as .docx or .txt.")
    parsed = parse_resume(text)
    if not parsed["evidence"]:
        raise HTTPException(422, "No evidence found — make sure the resume has section headings like EXPERIENCE or PROJECTS.")
    return save_profile(parsed, file.filename or "upload")


@app.post("/api/profile/text")
def profile_from_text(body: TextIn):
    parsed = parse_resume(body.text)
    if not parsed["evidence"]:
        raise HTTPException(422, "No evidence found — include section headings like EXPERIENCE, PROJECTS, SKILLS.")
    return save_profile(parsed, "pasted text")


@app.post("/api/profile/sample")
def profile_sample():
    return save_profile(parse_resume((SAMPLES / "sample_resume.txt").read_text()), "sample profile (fictional)")


@app.put("/api/profile")
def update_profile(body: ProfileIn):
    items = [enrich(i.model_dump()) for i in body.evidence if i.text.strip()]
    prof = db.get("profile") or {}
    prof.update({"name": body.name, "evidence": renumber(items), "updated": time.time()})
    prof.setdefault("source", "edited")
    db.put("profile", prof)
    return public_profile(prof)


@app.delete("/api/profile")
def clear_profile():
    db.put("profile", None)
    return {"ok": True}


# ----------------------------------------------------------------- job fit
@app.get("/api/samples/job")
def sample_job():
    return {"text": (SAMPLES / "sample_job.txt").read_text()}


@app.post("/api/fit")
def fit(body: FitIn):
    prof = profile_or_400()
    reqs = extract_requirements(body.posting)
    if not reqs:
        raise HTTPException(422, "Couldn't find requirements in that text. Paste the full posting, including qualifications.")
    title = body.title.strip() or guess_title(body.posting)
    report = fit_report(reqs, prof["evidence"])
    result = {"title": title, "org": body.org.strip(), "report": report, "created": time.time()}
    db.put("last_fit", result)
    return result


@app.get("/api/fit/last")
def last_fit():
    return db.get("last_fit") or {}


# ----------------------------------------------------------------- research
@app.get("/api/research/authors")
def research_authors(q: str):
    if len(q.strip()) < 3:
        raise HTTPException(400, "Type at least 3 characters.")
    return {"authors": scholar().search_authors(q.strip())}


@app.get("/api/research/authors/{author_id}/papers")
def research_author_papers(author_id: str, topic: str = ""):
    prof = db.get("profile") or {"evidence": []}
    client = scholar()
    papers = client.author_papers(author_id)[:40]
    papers = score_papers(papers, topic, prof["evidence"])
    if topic:
        papers.sort(key=lambda p: -(0.6 * p["relevance"] + 0.2 * p["overlap"] + 0.2 * p["recency"]))
    else:
        papers.sort(key=lambda p: -(0.5 * p["recency"] + 0.5 * p["overlap"]))
    top = papers[:15]
    return {"papers": top, "sharedGround": shared_ground(top[:5], prof["evidence"], k=3)}


@app.post("/api/research/topic")
def research_topic(body: TopicIn):
    prof = db.get("profile") or {"evidence": []}
    return rank_researchers(scholar(), body.topic.strip(), prof["evidence"], body.affiliation, body.include_unknown)


# ----------------------------------------------------------------- drafts / verify
@app.post("/api/drafts")
def draft(body: DraftIn):
    prof = profile_or_400()
    ctx = body.model_dump()
    if body.kind in ("cover_letter", "resume_bullets"):
        last = db.get("last_fit")
        if not last:
            raise HTTPException(400, "Run a Job Fit analysis first.")
        ctx["fit"] = last["report"]
        ctx["title"] = body.title or last.get("title", "")
        ctx["org"] = body.org or last.get("org", "")
    elif not body.papers:
        raise HTTPException(400, "Select at least one paper in Scholars first.")
    ctx["papers"] = body.papers[:4]
    return generate(body.kind, prof, ctx, settings())


@app.post("/api/verify")
def verify(body: VerifyIn):
    prof = profile_or_400()
    return verify_text(body.text, build_sources(prof["evidence"], body.papers[:4]), set(body.allowed))


# ----------------------------------------------------------------- pipeline
@app.get("/api/pipeline")
def pipeline_list():
    return {"items": db.pipeline_list(), "statuses": db.STATUSES}


@app.post("/api/pipeline", status_code=201)
def pipeline_create(body: PipelineIn):
    if body.status not in db.STATUSES:
        raise HTTPException(400, "Unknown status.")
    return db.pipeline_create(body.model_dump())


@app.patch("/api/pipeline/{item_id}")
def pipeline_update(item_id: int, body: PipelinePatch):
    data = body.model_dump(exclude_none=True)
    if "status" in data and data["status"] not in db.STATUSES:
        raise HTTPException(400, "Unknown status.")
    item = db.pipeline_update(item_id, data)
    if not item:
        raise HTTPException(404, "Not found.")
    return item


@app.delete("/api/pipeline/{item_id}")
def pipeline_delete(item_id: int):
    if not db.pipeline_delete(item_id):
        raise HTTPException(404, "Not found.")
    return {"ok": True}


# ----------------------------------------------------------------- settings
@app.get("/api/settings")
def get_settings():
    s = settings()
    return {"provider": s["provider"], "model": s["model"], "api_key": mask(s["api_key"]),
            "ollama_url": s["ollama_url"], "s2_api_key": mask(s["s2_api_key"]),
            "default_models": llm.DEFAULT_MODELS}


@app.put("/api/settings")
def put_settings(body: SettingsIn):
    cur = db.get("settings", {})
    data = body.model_dump()
    for k in ("api_key", "s2_api_key"):
        if data[k] is None or data[k].startswith("••"):
            data[k] = cur.get(k, "")
    if data["provider"] != cur.get("provider") and body.api_key is None:
        data["api_key"] = ""  # don't reuse one provider's key for another
    db.put("settings", data)
    return get_settings()


@app.post("/api/settings/test")
def test_settings():
    s = settings()
    if s["provider"] == "offline":
        return {"ok": True, "message": "Offline writer — no connection needed."}
    try:
        out = llm.complete(s, "Reply with exactly: OK", "Say OK.", max_tokens=5)
        return {"ok": True, "message": f"Connected to {s['provider']} ({s['model'] or llm.DEFAULT_MODELS[s['provider']]}): {out.strip()[:20]}"}
    except llm.LLMError as e:
        return {"ok": False, "message": str(e)}


# ----------------------------------------------------------------- frontend
app.mount("/static", StaticFiles(directory=FRONTEND), name="static")


@app.get("/")
def index():
    return FileResponse(FRONTEND / "index.html")
