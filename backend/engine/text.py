"""Small text utilities shared by the engine."""
from __future__ import annotations

import re

BULLET_RE = re.compile(r"^\s*(?:[-*•▪◦●○■□➢➤►–—]|\d{1,2}[.)])\s+")
NUMBER_RE = re.compile(r"(?<![\w.])(?:\$\s?)?\d[\d,]*(?:\.\d+)?\s?(?:%|\+|x|k|K|M)?(?![\w])")
CITE_RE = re.compile(r"\[((?:[EP]\d+)(?:\s*,\s*[EP]\d+)*)\]")
YEAR_RE = re.compile(r"^(19|20)\d{2}$")


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def strip_bullet(line: str) -> str:
    return BULLET_RE.sub("", line).strip()


def is_bullet(line: str) -> bool:
    return bool(BULLET_RE.match(line))


def split_sentences(text: str) -> list[str]:
    """Split prose into sentences, keeping inline citations attached to their sentence."""
    text = normalize_ws(text)
    if not text:
        return []
    # protect common abbreviations
    protected = re.sub(r"\b(e\.g|i\.e|etc|Dr|Prof|Mr|Ms|Mrs|vs|Inc|Ltd|Jr|Sr|U\.S|al)\.",
                       lambda m: m.group(0).replace(".", "§"), text)
    # degree / initial abbreviations: M.S., B.Tech., Ph.D., U.S.A.
    protected = re.sub(r"\b(?:[A-Z][a-z]{0,3}\.){2,}", lambda m: m.group(0).replace(".", "§"), protected)
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9“\"(\[])", protected)
    out: list[str] = []
    for p in parts:
        p = p.replace("§", ".").strip()
        # a piece that starts with citations belongs to the previous sentence ("... done. [E2] Next")
        m = re.match(r"^((?:\[[EP]\d+(?:\s*,\s*[EP]\d+)*\]\s*)+)(.*)$", p)
        if m and out:
            out[-1] = out[-1] + " " + m.group(1).strip()
            p = m.group(2).strip()
        if p:
            out.append(p)
    return out


def split_lines(text: str) -> list[str]:
    return [ln.rstrip() for ln in (text or "").replace("\r", "").split("\n")]


def extract_numbers(text: str) -> list[str]:
    nums = []
    for m in NUMBER_RE.finditer(text or ""):
        tok = m.group(0).replace(" ", "")
        core = tok.strip("$%+xkKM").replace(",", "")
        if not core:
            continue
        if YEAR_RE.match(core):  # years are dates, not metrics
            continue
        nums.append(tok)
    return nums


def parse_citations(sentence: str) -> tuple[str, list[str]]:
    """Return (sentence without citation markers, list of cited ids)."""
    ids: list[str] = []
    for m in CITE_RE.finditer(sentence):
        ids.extend(x.strip() for x in m.group(1).split(","))
    clean = normalize_ws(CITE_RE.sub("", sentence))
    clean = re.sub(r"\s+([.,;:!?])", r"\1", clean)
    return clean, list(dict.fromkeys(ids))


def truncate(s: str, n: int = 140) -> str:
    s = normalize_ws(s)
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"
