"""Draft writer: cover letters, research outreach emails and tailored resume bullets.

Two engines:
  * offline  – deterministic templates that only ever re-use evidence text, so every
               claim is grounded by construction (the default; no API key needed).
  * LLM      – Claude / OpenAI / Ollama write more natural prose; the Verifier then
               checks each sentence, asks the LLM to repair failures once, and strikes
               anything still unsupported.
"""
from __future__ import annotations

import re

from . import llm
from .resume import ACTION_START
from .skills import extract_skills
from .text import normalize_ws, truncate
from .verifier import build_sources, verify_text

IRREGULAR = {"Built", "Wrote", "Led", "Held", "Taught", "Ran", "Made", "Gave", "Won", "Drew", "Grew", "Sold", "Kept",
             "Found", "Brought", "Began", "Set", "Put", "Spoke", "Took", "Chose", "Drove", "Met"}
CONNECTORS = [
    "That work maps closely onto the duties described in this posting.",
    "This is close to the day-to-day work the role describes.",
    "I would bring the same care to the work on your team.",
]


# ----------------------------------------------------------------- helpers
def display_name(profile: dict) -> str:
    n = normalize_ws(profile.get("name", ""))
    return n.title() if n.isupper() else n


ROLE_WORDS = re.compile(r"(?i)\b(intern|developer|engineer|analyst|assistant|tutor|scientist|manager|lead|researcher|"
                        r"consultant|associate|fellow|volunteer|president|member|coordinator|specialist|ta|grader|"
                        r"mentor|designer|architect|officer|representative|worker|technician)\b")


def article(word: str) -> str:
    w = word.strip()
    if re.match(r"^[A-Z]\.", w) or (w[:2].isupper() and len(w) > 1):   # abbreviations: "an M.S.", "an ML"
        return "an" if w[0] in "AEFHILMNORSX" else "a"
    return "an" if w[:1].lower() in "aeiou" else "a"


def _context_phrase(e: dict) -> str:
    ctx = re.sub(r"\([^)]*\)", "", e.get("context", ""))
    ctx = re.sub(r"(?i)\b(\d{1,2}/)?\d{4}\s*[–—-]\s*((\d{1,2}/)?\d{4}|present|current)\b", "", ctx)
    ctx = re.sub(r"(?i)\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s*\d{4}", "", ctx)
    ctx = re.sub(r"\s+", " ", ctx).strip(" -—–,|\t")
    if not ctx:
        return ""
    if e["section"] == "Projects":
        name = ctx.split("—")[0].split("|")[0].strip()
        return f"In my {name} project"
    parts = [p.strip() for p in re.split(r"\s*(?:,| at | @ | — | – | \| )\s*", ctx, maxsplit=1)]
    if len(parts) == 2 and parts[1]:
        role, org = parts
        if ROLE_WORDS.search(org) and not ROLE_WORDS.search(role):
            role, org = org, role  # "Org — Role" layout
        return f"As {article(role)} {role} at {org}"
    return f"As {article(parts[0])} {parts[0]}" if parts[0] else ""


def skill_display(s: str) -> str:
    from .skills import category
    generic = {"Data Visualization", "Data Analysis", "Data Cleaning", "Databases", "Machine Learning", "Deep Learning",
               "Computer Vision", "Statistics", "Data Mining", "Feature Engineering", "Time Series", "Classification",
               "Clustering", "Named Entity Recognition", "Sentiment Analysis", "Medical Imaging", "Transformers",
               "Recommender Systems", "Reinforcement Learning", "Prompt Engineering", "AI Agents", "Web Development",
               "REST APIs", "APIs", "Unit Testing", "Cybersecurity"}
    if s in generic:
        return s if s.isupper() or s in ("REST APIs", "APIs", "AI Agents") else s.lower()
    if s.isupper() or category(s) in ("Languages", "Libraries & Frameworks", "Data & Cloud"):
        return s
    return s.lower()


def evidence_sentence(e: dict, with_context: bool = True, seen: set | None = None) -> str | None:
    """'Built a Tableau dashboard ...' -> 'As a Data Analyst Intern at Northwind, I built a Tableau dashboard ... [E5].'"""
    text = e["text"].rstrip(".;")
    first = text.split(" ", 1)[0]
    is_action = first in IRREGULAR or bool(ACTION_START.match(text)) or bool(re.match(r"^[A-Z][a-z]+ed\b", text))
    if e["section"] in ("Skills", "Summary") or not is_action:
        return None
    body = first.lower() + text[len(first):]
    ctx = _context_phrase(e) if with_context else ""
    if seen is not None and ctx:
        if ctx in seen:
            return f"I also {body} [{e['id']}]."
        seen.add(ctx)
    s = f"{ctx}, I {body}" if ctx else f"I {body}"
    return f"{s} [{e['id']}]."


def _education(evidence: list[dict]) -> dict | None:
    return next((e for e in evidence if e["section"] == "Education"), None)


def _skills_sentence(matches: list[dict], by_id: dict) -> str | None:
    """'My most relevant experience is in Python, SQL and Tableau [E4, E6].' – every skill cited."""
    picks, cites = [], []
    for m in matches:
        if m.get("level") not in ("Strong",) or not m["evidence"]:
            continue
        for sk in extract_skills(m["text"], strict=True):
            ids = [i for i in m["evidence"] if sk in by_id[i]["skills"] and by_id[i]["demonstrated"]]
            if ids and sk not in picks:
                picks.append(sk)
                cites.append(ids[0])
            if len(picks) == 3:
                break
        if len(picks) == 3:
            break
    if len(picks) < 2:
        return None
    picks = [skill_display(p) for p in picks]
    lst = ", ".join(picks[:-1]) + " and " + picks[-1]
    return f"My most relevant hands-on experience is with {lst} [{', '.join(dict.fromkeys(cites))}]."


# ----------------------------------------------------------------- offline drafts
def offline_cover_letter(profile: dict, fit: dict, title: str, org: str) -> str:
    ev = profile["evidence"]
    by_id = {e["id"]: e for e in ev}
    name = display_name(profile) or "[Your Name]"
    role = title or "this"
    paras = ["Dear Hiring Committee,"]
    p1 = [f"I am writing to apply for the {role} position{f' with {org}' if org else ''}."]
    if (sk := _skills_sentence(fit["matches"], by_id)):
        p1.append(sk)
    paras.append(" ".join(p1))

    used, body, seen = set(), [], set()
    order = {"required": 0, "duty": 1, "preferred": 2}
    strong = sorted([m for m in fit["matches"] if m["level"] in ("Strong", "Good") and m["kind"] in order],
                    key=lambda m: (order[m["kind"]], m["level"] != "Strong"))
    for m in strong:
        for eid in m["evidence"]:
            if eid in used:
                continue
            s = evidence_sentence(by_id[eid], seen=seen)
            if s:
                used.add(eid)
                body.append(s)
                break
        if len(body) == 4:
            break
    if body:
        mid = len(body) // 2 or 1
        paras.append(" ".join(body[:mid] + [CONNECTORS[0]]))
        if body[mid:]:
            paras.append(" ".join(body[mid:] + [CONNECTORS[1]]))

    gaps = [g for g in fit["gaps"] if g["missing"]][:2]
    if gaps:
        missing = [g["missing"][0] for g in gaps]
        paras.append(f"I have not yet worked with {' or '.join(skill_display(m) for m in missing)}, and I would plan to build "
                     f"{'that skill' if len(missing) == 1 else 'those skills'} early in the role.")
    paras.append(f"I would welcome the chance to discuss how I could support {org or 'your team'}. "
                 "Thank you for your time and consideration.")
    paras.append(f"Sincerely,\n{name}")
    return "\n\n".join(paras)


def offline_outreach(profile: dict, professor: str, papers: list[dict], interest: str) -> tuple[str, str]:
    ev = profile["evidence"]
    name = display_name(profile) or "[Your Name]"
    last = professor.split()[-1] if professor else ""
    paras = [f"Dear Professor {last}," if last else "Dear Professor,"]
    intro = []
    school_e = next((e for e in ev if e["section"] == "Education" and re.search(r"(?i)universit|college|institute|school", e["text"])), None)
    degree_e = next((e for e in ev if e["section"] == "Education" and re.search(r"(?i)\b(M\.?S\.?|M\.?Tech|Master|MBA|Ph\.?D|MEng)\b", e["text"])), None)
    if school_e and degree_e and school_e is not degree_e:
        school = re.split(r",|\s[—–-]\s|\t", school_e["text"])[0].strip()
        degree = re.split(r"\||\(|,|\s[—–-]\s", degree_e["text"])[0].strip()
        intro.append(f"My name is {name}, and I am {article(degree)} {degree} student at {school} [{school_e['id']}, {degree_e['id']}].")
    elif (edu := school_e or degree_e or _education(ev)):
        program = re.sub(r"\([^)]*\)", "", edu["text"]).strip(" -—–")
        parts = re.split(r"\s+[—–-]\s+|\s*\|\s*", program, maxsplit=1)
        if len(parts) == 2 and re.search(r"(?i)universit|college|institute|school", parts[0]):
            intro.append(f"My name is {name}, and I am {article(parts[1])} {parts[1].strip()} student at {parts[0].strip()} [{edu['id']}].")
        else:
            intro.append(f"My name is {name}, and I am currently studying {program} [{edu['id']}].")
    else:
        intro.append(f"My name is {name}.")
    if interest:
        intro.append(f"I am writing because I am hoping to learn more about research in {interest}.")
    paras.append(" ".join(intro))

    src_papers = papers[:3]
    ptxt = []
    for i, p in enumerate(src_papers[:2], 1):
        yr = f"{p['year']} " if p.get("year") else ""
        ptxt.append(f"I read your {yr}paper “{p['title'].rstrip('.')}” [P{i}].")
    if ptxt:
        paras.append(" ".join(ptxt))

    from .scholar import shared_ground
    ground = shared_ground(src_papers, ev, k=3)
    by_id = {e["id"]: e for e in ev}
    conn, seen = [], set()
    for g in ground:
        s = evidence_sentence(by_id[g["id"]], seen=seen)
        if s:
            conn.append(s)
        if len(conn) == 2:
            break
    if conn:
        paras.append("The closest connection to my own work is this: " + conn[0][0].lower() + conn[0][1:]
                     + (" " + conn[1] if len(conn) > 1 else ""))

    paper_skills = set(extract_skills(" ".join(f"{p['title']} {p.get('abstract', '')}" for p in src_papers), strict=True))
    mine = {s for e in ev for s in e["skills"]}
    missing = [s for s in paper_skills - mine if s not in ("Research Experience", "Statistics", "Data Analysis")][:2]
    if missing:
        paras.append(f"I have not yet worked directly with {' or '.join(skill_display(m) for m in sorted(missing))}, and I am actively building that background.")
    paras.append("Would you be open to a brief conversation about whether there might be a way for me to contribute "
                 "to your group, even in a small capacity? I have attached my resume for reference.")
    paras.append(f"Thank you for your time,\n{name}")
    subject = f"Prospective student interested in your work{f' on {interest}' if interest else ''}"
    return subject, "\n\n".join(paras)


def offline_bullets(profile: dict, fit: dict) -> str:
    by_id = {e["id"]: e for e in profile["evidence"]}
    ranked: list[str] = []
    for m in sorted(fit["matches"], key=lambda m: ["Strong", "Good", "Partial", "Weak", "No Evidence", "Verify"].index(m["level"])):
        for eid in m["evidence"]:
            if eid not in ranked and by_id[eid]["demonstrated"] and by_id[eid]["section"] != "Education":
                ranked.append(eid)
    lines = [f"- {by_id[i]['text'].rstrip('.')} [{i}]." for i in ranked[:8]]
    return "\n".join(lines)


# ----------------------------------------------------------------- LLM drafts
SYSTEM = """You are Attesta's writing agent. You write application materials for a student.
Hard rules:
1. Use ONLY facts from the EVIDENCE and PAPERS lists. Never invent skills, tools, numbers, employers, results or publications.
2. Every sentence that states something about the student must end with its citations before the period, e.g. "... pipeline in spaCy [E4]." Use [P1] for papers. Cite only ids that exist.
3. Do not exaggerate: "used" stays "used", not "expert in". Do not add metrics that are not in the evidence.
4. If the student lacks something important, say so plainly in one sentence (e.g. "I have not yet worked with Power BI.").
5. Sentences without factual claims (greeting, intent, a question, thanks) need no citation.
6. Tone: confident, specific, academically mature, concise. No clichés ("I am passionate", "fast-paced", "team player").
Output only the draft text. Separate paragraphs with a blank line."""


def _evidence_block(ev: list[dict]) -> str:
    return "\n".join(f"[{e['id']}] ({e['section']}{' · ' + e['context'] if e['context'] else ''}) {e['text']}" for e in ev)


def _paper_block(papers: list[dict]) -> str:
    return "\n".join(f"[P{i}] {p['title']} ({p.get('year') or 'n.d.'}, {p.get('venue') or p.get('source', '')}). "
                     f"Abstract: {truncate(p.get('abstract', ''), 700)}" for i, p in enumerate(papers, 1))


def llm_prompt(kind: str, profile: dict, ctx: dict) -> str:
    ev = profile["evidence"]
    name = display_name(profile) or "the student"
    if kind == "cover_letter":
        fit = ctx["fit"]
        reqs = "\n".join(f"- ({m['kind']}, {m['level']}) {m['text']}  evidence: {', '.join(m['evidence']) or 'none'}"
                         for m in fit["matches"] if m["kind"] != "eligibility")
        return (f"Write a cover letter (250-330 words) from {name} for the position '{ctx.get('title') or 'the role'}'"
                f"{' at ' + ctx['org'] if ctx.get('org') else ''}.\n\nREQUIREMENTS with the matcher's assessment:\n{reqs}\n\n"
                f"EVIDENCE:\n{_evidence_block(ev)}\n\nFocus on the strongest matches; acknowledge at most one gap honestly. "
                f"Start with 'Dear Hiring Committee,' and end with 'Sincerely,' and the name {name}.")
    if kind == "outreach_email":
        return (f"Write a cold email (150-220 words) from {name} to Professor {ctx.get('professor') or ''} asking about "
                f"research involvement. Student interest: {ctx.get('interest') or 'their research area'}.\n\n"
                f"PAPERS by the professor:\n{_paper_block(ctx['papers'])}\n\nEVIDENCE:\n{_evidence_block(ev)}\n\n"
                "Reference one or two papers specifically and connect them to the most relevant evidence. Be honest about "
                "gaps. Ask for a brief conversation. Do not include a subject line.")
    if kind == "resume_bullets":
        fit = ctx["fit"]
        reqs = "\n".join(f"- {m['text']}" for m in fit["matches"] if m["kind"] != "eligibility")
        return (f"Rewrite the student's most relevant evidence as 6-8 resume bullets tailored to these requirements:\n{reqs}\n\n"
                f"EVIDENCE:\n{_evidence_block(ev)}\n\nEach bullet: one line starting with '- ', a strong past-tense verb, "
                "keywords from the posting ONLY where the evidence supports them, and its citation, e.g. '- Built ... [E5].'")
    raise ValueError("Unknown draft type")


def _repair_prompt(draft: str, flagged: list[dict]) -> str:
    issues = "\n".join(f"- \"{s['clean']}\" → {' '.join(s['reasons'])}" for s in flagged)
    return (f"The verifier rejected these sentences:\n{issues}\n\nRewrite the draft so each flagged sentence is either "
            f"supported by the cited evidence (fix the citation or the wording) or removed. Keep everything else. "
            f"Return only the full corrected draft.\n\nDRAFT:\n{draft}")


def _strike(text: str, verification: dict) -> tuple[str, list[dict]]:
    """Remove sentences the verifier marked unsupported."""
    struck = [s for s in verification["sentences"] if s["status"] == "unsupported"]
    out = text
    for s in struck:
        out = out.replace(s["text"], "")
    out = re.sub(r"[ \t]+\n", "\n", re.sub(r"  +", " ", out))
    out = "\n".join(l.strip() for l in out.split("\n"))
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, [{"text": s["clean"], "reasons": s["reasons"]} for s in struck]


# ----------------------------------------------------------------- entry point
def generate(kind: str, profile: dict, ctx: dict, settings: dict) -> dict:
    papers = ctx.get("papers") or []
    sources = build_sources(profile["evidence"], papers)
    allowed = {ctx.get("title", ""), ctx.get("org", ""), ctx.get("professor", ""), display_name(profile),
               ctx.get("interest", "")}
    allowed |= set((ctx.get("professor") or "").split())
    allowed |= set(display_name(profile).split())
    subject = ""
    provider = settings.get("provider", "offline")
    rounds, engine, note = 0, "offline", ""

    text = None
    if provider != "offline":
        try:
            text = llm.complete(settings, SYSTEM, llm_prompt(kind, profile, ctx)).strip()
            engine, rounds = provider, 1
            ver = verify_text(text, sources, allowed)
            flagged = [s for s in ver["sentences"] if s["status"] == "unsupported"]
            if flagged:
                text = llm.complete(settings, SYSTEM, _repair_prompt(text, flagged)).strip()
                rounds = 2
        except llm.LLMError as e:
            note = f"{e} — used the offline writer instead."
            text = None
    if text is None:
        if kind == "cover_letter":
            text = offline_cover_letter(profile, ctx["fit"], ctx.get("title", ""), ctx.get("org", ""))
        elif kind == "outreach_email":
            subject, text = offline_outreach(profile, ctx.get("professor", ""), papers, ctx.get("interest", ""))
        elif kind == "resume_bullets":
            text = offline_bullets(profile, ctx["fit"])
        else:
            raise ValueError("Unknown draft type")
    elif kind == "outreach_email":
        subject = f"Prospective student interested in your work{' on ' + ctx['interest'] if ctx.get('interest') else ''}"

    first = verify_text(text, sources, allowed)
    final_text, struck = _strike(text, first)
    final = verify_text(final_text, sources, allowed) if struck else first
    return {"kind": kind, "subject": subject, "text": final_text, "verification": final, "struck": struck,
            "engine": engine, "rounds": rounds, "note": note,
            "sources": {k: _public_source(v) for k, v in sources.items()},
            "allowed": sorted(a for a in allowed if a)}


def _public_source(s: dict) -> dict:
    if s["type"] == "evidence":
        return {"type": "evidence", "id": s["id"], "section": s["section"], "context": s["context"], "text": s["text"]}
    return {"type": "paper", "id": s["pid"], "title": s["title"], "year": s.get("year"), "venue": s.get("venue"),
            "url": s.get("url"), "snippet": truncate(s.get("abstract", ""), 280)}
