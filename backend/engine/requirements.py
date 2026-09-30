"""Extract requirements from a job posting.

Each requirement: {"id": "R1", "text": ..., "kind": "required|preferred|duty|eligibility", "skills": [...]}
"""
from __future__ import annotations

import re

from .skills import extract_skills
from .text import is_bullet, normalize_ws, split_lines, split_sentences, strip_bullet

SECTION_KIND = [
    (re.compile(r"(?i)(about (us|the (role|position|job|team|department|lab|university|company))|overview|who we are|benefits|how to apply|equal opportunity|compensation|pay|salary|schedule)"), "skip"),
    (re.compile(r"(?i)(minimum|required|basic|must[- ]have|essential)\s+(qualifications|requirements|skills)|^requirements|^qualifications|what you('| wi)ll need|who you are"), "required"),
    (re.compile(r"(?i)(desired|preferred|additional|bonus|nice[- ]to[- ]have)\s*(qualifications|skills|requirements)?|^preferred|pluses"), "preferred"),
    (re.compile(r"(?i)(duties|responsibilities|what you('| wi)ll do|essential functions|job description|the role|key tasks|your role)"), "duty"),
]
BOILERPLATE = re.compile(r"(?i)equal opportunity|affirmative action|without regard to|reasonable accommodation|"
                         r"background check|e-verify|pay rate|per hour|salary|benefits|click apply|apply now|"
                         r"posting (date|number)|job id|department:|location:|close date")
ELIGIBILITY = re.compile(r"(?i)\b(enrolled|enrollment|eligible for (on-campus )?employment|work[- ]study|federal work|"
                         r"gpa|credit hours|work authori[sz]ation|citizen|visa|background check|hours per week|"
                         r"available to work|availability|must be a (current )?student|degree[- ]seeking)\b")
PREFERRED_CUE = re.compile(r"(?i)\b(preferred|a plus|is a plus|nice to have|desired|bonus|ideally|familiarity with)\b")
REQUIRED_CUE = re.compile(r"(?i)\b(must|required|requires|minimum|at least|proficien|strong|experience (with|in)|knowledge of|ability to|able to)\b")
DUTY_CUE = re.compile(r"(?i)^(assist|support|clean|build|develop|create|answer|maintain|write|analy[sz]e|prepare|"
                      r"help|conduct|collect|manage|design|document|run|perform|provide|train|monitor|update|"
                      r"coordinate|review|test|implement|research|tutor|teach|grade|respond)")


def _section_kind(line: str) -> str | None:
    t = normalize_ws(line).strip(":").strip()
    if len(t) > 60 or is_bullet(line):
        return None
    for pat, kind in SECTION_KIND:
        if pat.search(t):
            return kind
    return None


def extract_requirements(posting: str) -> list[dict]:
    kind_ctx = "unknown"
    reqs: list[dict] = []
    seen = set()

    def add(text: str, kind_hint: str):
        text = normalize_ws(text).rstrip(";").strip()
        if len(text) < 12 or len(text) > 400 or BOILERPLATE.search(text):
            return
        key = text.lower()
        if key in seen:
            return
        skills = extract_skills(text)
        if ELIGIBILITY.search(text):
            kind = "eligibility"
        elif kind_hint in ("required", "preferred", "duty"):
            kind = "preferred" if kind_hint == "required" and PREFERRED_CUE.search(text) else kind_hint
        elif PREFERRED_CUE.search(text):
            kind = "preferred"
        elif REQUIRED_CUE.search(text):
            kind = "required"
        elif DUTY_CUE.search(text):
            kind = "duty"
        elif skills:
            kind = "required"
        else:
            return  # descriptive prose, not a requirement
        seen.add(key)
        reqs.append({"text": text, "kind": kind, "skills": skills})

    for raw in split_lines(posting):
        line = normalize_ws(raw)
        if not line:
            continue
        k = _section_kind(raw)
        if k:
            kind_ctx = k
            continue
        if kind_ctx == "skip":
            for s in split_sentences(line):  # keep eligibility facts (hours, enrollment) even in "about" text
                if ELIGIBILITY.search(s) and not BOILERPLATE.search(s):
                    add(s, "eligibility")
            continue
        if is_bullet(raw):
            add(strip_bullet(raw), kind_ctx)
        else:
            # prose paragraph: only keep sentences with requirement signals or skills
            for s in split_sentences(line):
                if REQUIRED_CUE.search(s) or PREFERRED_CUE.search(s) or ELIGIBILITY.search(s) or \
                        (kind_ctx in ("required", "preferred", "duty") and (DUTY_CUE.search(s) or extract_skills(s))):
                    add(s, kind_ctx)

    for i, r in enumerate(reqs, 1):
        r["id"] = f"R{i}"
    return reqs


def guess_title(posting: str) -> str:
    for raw in split_lines(posting):
        t = normalize_ws(raw)
        if t and not _section_kind(raw) and len(t) <= 90:
            return t
    return ""
