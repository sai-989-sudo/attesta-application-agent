"""Requirement ↔ evidence matching and fit scoring.

Matching is deliberately transparent (no black box):
  1. Skill groups in the requirement ("Python or R" = one group with alternatives)
     are checked against skills found in the resume evidence.
  2. A skill only counts as *demonstrated* if it appears in Experience / Projects /
     Research / Education items — being listed in a Skills line is weaker evidence.
  3. Requirements without recognisable skills fall back to TF-IDF text similarity,
     which can at most produce a "Good" match (lexical overlap is not proof).
"""
from __future__ import annotations

import re

from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

from .resume import all_skills
from .skills import extract_skills, skill_groups

LEVELS = ["Strong", "Good", "Partial", "Weak", "No Evidence"]
LEVEL_POINTS = {"Strong": 1.0, "Good": 0.8, "Partial": 0.5, "Weak": 0.2, "No Evidence": 0.0}
KIND_WEIGHT = {"required": 3.0, "duty": 1.5, "preferred": 1.0}


_WORD = re.compile(r"[a-z][a-z+#.-]*[a-z+#]|[a-z]")


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "edly", "ed", "es", "ly", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _analyzer(text: str) -> list[str]:
    toks = [_stem(t) for t in _WORD.findall(text.lower()) if t not in ENGLISH_STOP_WORDS]
    return toks + [a + "_" + b for a, b in zip(toks, toks[1:])]


def _query(text: str) -> str:
    return text + " " + " ".join("skill_" + s.replace(" ", "_") for s in extract_skills(text))


def _doc(e: dict) -> str:
    return f"{e.get('context', '')} {e['text']} " + " ".join("skill_" + s.replace(" ", "_") for s in e["skills"])


def similarity_matrix(queries: list[str], evidence: list[dict]):
    docs = [_doc(e) for e in evidence]
    queries = [_query(q) for q in queries]
    vec = TfidfVectorizer(analyzer=_analyzer, sublinear_tf=True, min_df=1)
    vec.fit(docs + queries)
    return cosine_similarity(vec.transform(queries), vec.transform(docs))


def match_requirements(reqs: list[dict], evidence: list[dict]) -> list[dict]:
    if not evidence:
        raise ValueError("Your evidence ledger is empty — add a resume first.")
    skill_index = all_skills(evidence)
    demo_ids = {e["id"] for e in evidence if e["demonstrated"]}
    by_id = {e["id"]: e for e in evidence}
    sims = similarity_matrix([r["text"] for r in reqs], evidence) if reqs else []
    out = []
    for i, r in enumerate(reqs):
        row = sims[i]
        ranked = sorted(range(len(evidence)), key=lambda j: -row[j])
        res = {**r, "level": None, "evidence": [], "missing": [], "note": "", "similarity": round(float(row[ranked[0]]), 3)}
        if r["kind"] == "eligibility":
            res.update(level="Verify", note="Eligibility item — confirm this yourself; it can't be checked from a resume.")
            out.append(res)
            continue

        groups = skill_groups(r["text"])
        if groups:
            covered, demonstrated, ev_ids = 0, 0, []
            for g in groups:
                hits = [s for s in g if s in skill_index]
                if hits:
                    covered += 1
                    ids = [x for s in hits for x in skill_index[s]]
                    if any(x in demo_ids for x in ids):
                        demonstrated += 1
                    # prefer demonstrated items, then by text similarity
                    ids = sorted(set(ids), key=lambda x: (x not in demo_ids, -row[int(x[1:]) - 1]))
                    ev_ids.extend(ids[:2])
                else:
                    res["missing"].append(" or ".join(g))
            n = len(groups)
            if demonstrated == n:
                level, note = "Strong", "Demonstrated in experience or projects."
            elif covered == n:
                level, note = "Good", "Listed in your skills, but not clearly shown in experience or projects."
            elif covered > 0:
                level, note = "Partial", f"Covers {covered} of {n} skill areas."
            elif row[ranked[0]] >= 0.18:
                level, note = "Weak", "Only loosely related wording in your resume."
                ev_ids = [evidence[ranked[0]]["id"]]
            else:
                level, note = "No Evidence", "Nothing in your resume supports this."
            # also surface the most textually similar item (e.g. "cleaned and merged data" for a cleaning duty)
            top_demo = next((j for j in ranked if evidence[j]["demonstrated"]), None)
            if level in ("Strong", "Good", "Partial") and top_demo is not None and row[top_demo] >= 0.15:
                ev_ids.insert(0, evidence[top_demo]["id"])
            res["evidence"] = list(dict.fromkeys(ev_ids))[:3]
        else:
            top = row[ranked[0]]
            if top >= 0.30:
                level, note = "Good", "Closely related experience (text similarity)."
            elif top >= 0.18:
                level, note = "Partial", "Some related experience (text similarity)."
            elif top >= 0.10:
                level, note = "Weak", "Only loosely related wording in your resume."
            else:
                level, note = "No Evidence", "Nothing in your resume supports this."
            if level != "No Evidence":
                res["evidence"] = [evidence[j]["id"] for j in ranked[:2] if row[j] >= 0.10]
        res["level"], res["note"] = level, note
        res["evidence_detail"] = [{"id": x, "text": by_id[x]["text"], "section": by_id[x]["section"]} for x in res["evidence"]]
        out.append(res)
    return out


def score(matches: list[dict]) -> int:
    num = den = 0.0
    for m in matches:
        if m["kind"] not in KIND_WEIGHT:
            continue
        w = KIND_WEIGHT[m["kind"]]
        num += w * LEVEL_POINTS[m["level"]]
        den += w
    return round(100 * num / den) if den else 0


def recommend(fit: int, matches: list[dict]) -> tuple[str, str]:
    req = [m for m in matches if m["kind"] == "required"]
    missing_req = [m for m in req if m["level"] in ("No Evidence", "Weak")]
    if missing_req and len(missing_req) >= max(2, len(req) // 2):
        return "LOW PRIORITY", f"{len(missing_req)} of {len(req)} required qualifications have little or no evidence."
    if fit >= 78 and not missing_req:
        return "APPLY AGGRESSIVELY", "Every required qualification is backed by your resume."
    if fit >= 62:
        return "APPLY", "Most requirements are backed by evidence" + (
            f"; address the gap in {len(missing_req)} required item(s)." if missing_req else ".")
    if fit >= 45:
        return "STRETCH", "Partial fit — worth applying only if the role strongly interests you."
    if fit >= 30:
        return "LOW PRIORITY", "Significant gaps against the posting."
    return "DO NOT PRIORITIZE", "Your resume shows little overlap with this posting."


def fit_report(reqs: list[dict], evidence: list[dict]) -> dict:
    matches = match_requirements(reqs, evidence)
    fit = score(matches)
    rec, why = recommend(fit, matches)
    order = {"required": 0, "duty": 1, "preferred": 2, "eligibility": 3}
    strengths = [m for m in matches if m["level"] in ("Strong", "Good")]
    gaps = [m for m in matches if m["level"] in ("Weak", "No Evidence")]
    strengths.sort(key=lambda m: (order[m["kind"]], LEVELS.index(m["level"])))
    gaps.sort(key=lambda m: order[m["kind"]])
    counts = {lvl: sum(1 for m in matches if m["level"] == lvl) for lvl in LEVELS + ["Verify"]}
    return {
        "score": fit, "recommendation": rec, "reason": why, "matches": matches, "counts": counts,
        "strengths": [{"id": m["id"], "text": m["text"], "kind": m["kind"], "level": m["level"]} for m in strengths[:5]],
        "gaps": [{"id": m["id"], "text": m["text"], "kind": m["kind"], "missing": m["missing"]} for m in gaps[:6]],
        "listed_not_shown": sorted({s for m in matches if m["level"] == "Good" and m["note"].startswith("Listed")
                                    for s in _skills_of(m)}),
    }


def _skills_of(m: dict) -> list[str]:
    return [s for g in skill_groups(m["text"]) for s in g]
