"""The Verifier: checks every sentence of a draft against its cited sources.

Sentence statuses
  attested    – makes a claim and every claim is found in the cited source(s)
  neutral     – no factual claim about the candidate (greeting, intent, question)
  gap         – openly states something the candidate does NOT have (allowed, honest)
  warn        – supported somewhere, but cited to the wrong source or weakly worded
  unsupported – a claim with no citation, a fake citation, or content not found in any source

It is deterministic and rule-based on purpose: it is auditable and cannot itself
hallucinate. It is conservative (it may flag a fine sentence), never permissive by design.
"""
from __future__ import annotations

import re

from .skills import SKILLS, extract_skills
from .text import extract_numbers, parse_citations, split_sentences

ASSERTION = re.compile(
    r"(?i)\b(I|I've|I have|I am|I'm|my|me)\b.{0,40}?\b(built|developed|designed|created|implemented|led|managed|"
    r"analy[sz]ed|cleaned|trained|deployed|wrote|automated|improved|reduced|increased|tutored|taught|"
    r"documented|conducted|collaborated|compared|engineered|optimi[sz]ed|researched|presented|published|"
    r"worked|used|completed|earned|hold|studied|experience|skills?|background|project|internship|work|"
    r"proficient|expert|familiar|certified|degree|coursework|merged|held|explained|supported|built)\b")
GAP = re.compile(r"(?i)\b(not yet|haven't|have not|no (prior |direct |formal )?experience|limited experience|"
                 r"still learning|am learning|currently learning|plan to (learn|build|strengthen)|new to|"
                 r"do not have|don't have|would need to learn|eager to learn|gap)\b")
# Impact / superlative wording is a common way to inflate a true statement.
INFLATION = re.compile(r"(?i)\b(significant(ly)?|dramatic(ally)?|substantial(ly)?|massive(ly)?|greatly|widely|"
                       r"top[- ]performer|best[- ]in[- ]class|world[- ]class|award[- ]winning|expert|extensive(ly)?|"
                       r"highly (successful|effective)|recogni[sz]ed|adopted across|company[- ]wide|"
                       r"state[- ]of[- ]the[- ]art|cutting[- ]edge|mastery|spearheaded|revolutioni[sz]ed|"
                       r"transformed|major impact|key contributor)\b")
STOP_CAPS = {
    "I", "I'm", "I've", "I'd", "I'll", "My", "Me", "Dear", "Hello", "Hi", "Professor", "Prof", "Dr", "Thank", "Thanks",
    "Best", "Sincerely", "Regards", "Kind", "Warm", "Please", "Would", "Could", "Your", "Yours", "The", "This", "That",
    "These", "In", "As", "At", "During", "Since", "With", "While", "For", "From", "On", "To", "And", "But", "Or", "If",
    "When", "What", "Why", "How", "Which", "It", "Its", "We", "Our", "You", "He", "She", "They", "Hiring", "Manager",
    "Committee", "Team", "Position", "Role", "Mr", "Ms", "Mrs", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
    "November", "December", "Fall", "Spring", "Summer", "Winter", "Re", "Subject", "P.S", "Also", "Finally",
    "Currently", "Recently", "Specifically", "Additionally", "Through", "Because", "Given", "Having", "One", "Two",
}
STOP_LOWER = {w.lower() for w in STOP_CAPS}
CONTENT = re.compile(r"[a-z][a-z+#-]{2,}")
FILLER = {"the", "and", "with", "for", "that", "this", "your", "you", "have", "has", "was", "were", "are", "from", "into",
          "which", "about", "also", "would", "could", "will", "been", "their", "there", "where", "when", "what", "how",
          "using", "used", "work", "worked", "including", "such", "these", "those", "them", "they", "then", "than",
          "very", "more", "most", "some", "any", "each", "both", "other", "over", "under", "while", "during", "within",
          "because", "through", "like", "able", "my", "our", "its", "his", "her", "not", "but", "can", "all", "one",
          "two", "three", "ive", "i'm", "i've", "me", "experience", "believe", "think", "interested", "excited",
          "position", "role", "team", "group", "lab", "research", "would", "love", "opportunity", "contribute", "help",
          "skills", "skill", "strong", "well", "relevant", "directly", "applied", "apply", "applying", "built"}


def _stem(w: str) -> str:
    for suf in ("ations", "ation", "ings", "ing", "ed", "es", "s"):
        if len(w) > len(suf) + 3 and w.endswith(suf):
            return w[: -len(suf)]
    return w


def _content_words(text: str) -> set[str]:
    return {_stem(w) for w in CONTENT.findall(text.lower()) if w not in FILLER}


def _entities(sentence: str) -> list[str]:
    """Capitalised multi-word names that are not the first word of the sentence."""
    no_quotes = re.sub(r"[“\"][^”\"]+[”\"]", " ", sentence)
    ents, cur, prev_end = [], [], None
    for i, m in enumerate(re.finditer(r"[A-Za-z][A-Za-z0-9&.+#'-]*", no_quotes)):
        t = m.group(0)
        gap = no_quotes[prev_end:m.start()] if prev_end is not None else ""
        prev_end = m.end()
        if cur and gap.strip() and gap.strip() not in ("&", "-", "of"):
            ents.append(" ".join(cur))  # punctuation breaks a name: "Python, Tableau" is two
            cur = []
        cap = t[0].isupper() and i > 0 and t.rstrip(".") not in STOP_CAPS
        if cap:
            cur.append(t.rstrip(".'"))
        elif cur and t == "of" and no_quotes[m.end():m.end() + 2].strip()[:1].isupper():
            cur.append(t)  # "University of Arizona"
        else:
            if cur:
                ents.append(" ".join(cur))
            cur = []
    if cur:
        ents.append(" ".join(cur))
    skill_names = {a.lower() for s in SKILLS.values() for a in s["aliases"]}
    return [e for e in ents if e.lower() not in skill_names and e.lower() not in STOP_LOWER and len(e) > 1]


def _quoted(sentence: str) -> list[str]:
    return [q.strip() for q in re.findall(r"[“\"]([^”\"]{6,})[”\"]", sentence)]


def _source_text(src: dict) -> str:
    if src["type"] == "evidence":
        return f"{src.get('section', '')} {src.get('context', '')} {src['text']}"
    authors = " ".join(a["name"] for a in src.get("authors", []))
    return f"{src['title']} {src.get('abstract', '')} {src.get('venue', '')} {src.get('year', '')} {authors}"


def _norm(s: str) -> str:
    return " " + re.sub(r"[\s.,;:()—–-]+", " ", s.lower()).strip() + " "


def _num_norm(n: str) -> str:
    return n.replace(",", "").replace("$", "").lower()


def verify_sentence(sentence: str, sources: dict[str, dict], allowed: set[str], evidence_ids: list[str]) -> dict:
    clean, cites = parse_citations(sentence)
    res = {"text": sentence, "clean": clean, "cites": cites, "status": "neutral", "reasons": [],
           "claims": {"skills": [], "numbers": [], "entities": []}}
    bad = [c for c in cites if c not in sources]
    allowed_low = {a.lower() for a in allowed if a}
    probe = clean
    for a in sorted((a for a in allowed if a and len(a) > 2), key=len, reverse=True):
        probe = re.sub(re.escape(a), " ", probe, flags=re.I)  # target names / stated interest are not claims
    skills = extract_skills(probe, strict=True)
    numbers = extract_numbers(probe)
    ents = [e for e in _entities(probe) if e.lower() not in allowed_low
            and not any(e.lower() in a or a in e.lower() for a in allowed_low if len(a) > 3)]
    quotes = _quoted(clean)
    asserts = bool(ASSERTION.search(clean))
    res["claims"] = {"skills": skills, "numbers": numbers, "entities": ents}

    if bad:
        res["status"] = "unsupported"
        res["reasons"].append(f"Cites a source that doesn't exist: {', '.join(bad)}.")
        return res
    if GAP.search(clean):
        res["status"] = "gap"
        res["reasons"].append("States a gap honestly — allowed.")
        return res
    needs = bool(skills or numbers or ents or quotes or asserts)
    if not needs and not cites:
        return res
    if needs and not cites:
        res["status"] = "unsupported"
        what = skills + numbers + ents
        res["reasons"].append("Makes a claim but cites no source" + (f" ({', '.join(what[:4])})." if what else "."))
        return res

    cited = [sources[c] for c in cites]
    cited_text = " ".join(_source_text(s) for s in cited)
    cited_low = _norm(cited_text)
    cited_skills = set(extract_skills(cited_text))
    for s in cited:
        cited_skills.update(s.get("skills", []))
        cited_skills.update(s.get("context_skills", []))
    all_ev = [sources[i] for i in evidence_ids if i in sources]
    status = "attested"

    only_papers = all(sources[c]["type"] == "paper" for c in cites)
    if asserts and only_papers and re.search(r"(?i)\b(I|I've|I have|my)\b", clean):
        return {**res, "status": "unsupported",
                "reasons": ["Claims about you must cite your own evidence (E#), not a paper."]}

    for sk in skills:
        if sk in cited_skills:
            continue
        others = [e["id"] for e in all_ev if sk in e.get("skills", []) or sk in e.get("context_skills", [])]
        if others:
            status = "warn" if status == "attested" else status
            res["reasons"].append(f"“{sk}” is in your resume ({', '.join(others[:2])}) but not in the cited source.")
        else:
            status = "unsupported"
            res["reasons"].append(f"“{sk}” does not appear in your resume or the cited source.")
    cited_nums = {_num_norm(n) for n in extract_numbers(cited_text)}
    for n in numbers:
        if _num_norm(n) not in cited_nums and _num_norm(n).rstrip("%+xkm") not in cited_nums:
            status = "unsupported"
            res["reasons"].append(f"The number “{n}” is not in the cited source.")
    for e in ents:
        if _norm(e) in cited_low:
            continue
        elsewhere = [x["id"] for x in all_ev if _norm(e) in _norm(_source_text(x))]
        if elsewhere:
            status = "warn" if status == "attested" else status
            res["reasons"].append(f"“{e}” appears in {', '.join(elsewhere[:2])}, not the cited source.")
        else:
            status = "unsupported"
            res["reasons"].append(f"“{e}” is not found in any source.")
    for q in quotes:
        qw = _content_words(q)
        titles = [s for s in cited if s["type"] == "paper"]
        if not any(len(qw & _content_words(s["title"])) >= max(1, int(0.6 * len(qw))) for s in titles):
            status = "unsupported"
            res["reasons"].append("Quoted title doesn't match a cited paper.")

    for m in INFLATION.finditer(clean):
        if m.group(0).lower() not in cited_low:
            status = "warn" if status == "attested" else status
            res["reasons"].append(f"“{m.group(0)}” overstates the source — it doesn't say that.")
            break

    if status == "attested" and asserts:
        sw = _content_words(clean) - {w.lower() for w in allowed_low}
        overlap = len(sw & _content_words(cited_text)) / max(1, len(sw))
        if sw and overlap < 0.2:
            status = "warn"
            res["reasons"].append("Wording has little overlap with the cited source — check it says the same thing.")
    if status == "attested":
        res["reasons"].append("All claims found in the cited source.")
    res["status"] = status
    return res


def verify_text(text: str, sources: dict[str, dict], allowed: set[str] | None = None) -> dict:
    """Verify a whole draft. `sources` maps E#/P# ids to evidence items or papers."""
    allowed = set(allowed or [])
    ev_ids = [k for k, v in sources.items() if v["type"] == "evidence"]
    paragraphs = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    out = []
    for pi, para in enumerate(paragraphs):
        lines = [l.strip() for l in para.split("\n") if l.strip()]
        breaks: set[int] = set()
        bullets = bool(lines) and all(re.match(r"^[-*•]\s+", l) for l in lines)
        if bullets:
            units = [re.sub(r"^[-*•]\s+", "", l) for l in lines]  # bullet list: one unit per bullet
        elif len(lines) > 1 and len(lines[-1].split()) <= 4:
            units = split_sentences(" ".join(lines[:-1])) + [lines[-1]]  # sign-off: "Sincerely,\nName"
            breaks.add(len(units) - 1)
        else:
            units = split_sentences(para)
        for ui, s in enumerate(units):
            r = verify_sentence(s, sources, allowed, ev_ids)
            r["paragraph"] = pi
            r["br"] = ui in breaks
            r["bullet"] = bullets
            out.append(r)
    return {"sentences": out, "summary": summarize(out)}


def summarize(sentences: list[dict]) -> dict:
    counts = {k: 0 for k in ("attested", "neutral", "gap", "warn", "unsupported")}
    for s in sentences:
        counts[s["status"]] += 1
    claims = counts["attested"] + counts["warn"] + counts["unsupported"]
    counts["integrity"] = round(100 * counts["attested"] / claims) if claims else 100
    counts["total"] = len(sentences)
    return counts


def build_sources(evidence: list[dict], papers: list[dict] | None = None) -> dict[str, dict]:
    src = {e["id"]: {**e, "type": "evidence"} for e in evidence}
    for i, p in enumerate(papers or [], 1):
        src[f"P{i}"] = {**p, "type": "paper", "pid": f"P{i}"}
    return src
