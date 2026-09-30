"""Claim-injection benchmark for the Verifier.

Builds true sentences from real evidence, then creates fabricated variants with
known perturbations and measures how often the Verifier flags them.

This is a SYNTHETIC benchmark on the fictional sample profile. The perturbation
types mirror what the verifier was designed to catch, so results are optimistic
for those types. "inflation_held_out" uses paraphrased boasts the rules were
never written for, and shows the real blind spot.

Run:  python -m eval.claim_injection
"""
from __future__ import annotations

import random
from collections import defaultdict
from pathlib import Path

from backend.engine.resume import parse_resume
from backend.engine.verifier import build_sources, verify_text
from backend.engine.writer import evidence_sentence

ROOT = Path(__file__).resolve().parent.parent
FAKE_SKILLS = ["Kubernetes", "PyTorch", "Spark", "Power BI", "MongoDB", "React", "Docker", "Snowflake"]
FAKE_ORGS = ["Google", "Microsoft", "Mayo Clinic", "NASA", "Intel"]
FAKE_NUMS = ["35%", "12,000", "4x", "$2M", "98%"]
INFLATE = [", significantly improving team productivity", ", which became widely adopted across the company",
           " and was recognised as a top performer"]
# Held out: written AFTER the inflation check, deliberately avoiding its word list.
INFLATE_HELD_OUT = [", which the whole organisation ended up relying on", ", saving the team many hours every week",
                    ", which leadership called the best work that year", ", making it the go-to tool for everyone"]


def perturb(sent: str, eid: str, rng: random.Random, all_ids: list[str]) -> dict[str, str]:
    body = sent[: sent.rfind(" [")]
    cite = f" [{eid}]."
    return {
        "invented_skill": f"{body} using {rng.choice(FAKE_SKILLS)}{cite}",
        "invented_number": f"{body}, improving accuracy by {rng.choice(FAKE_NUMS)}{cite}",
        "invented_org": f"{body} while working with {rng.choice(FAKE_ORGS)}{cite}",
        "missing_citation": f"{body}.",
        "fake_citation": f"{body} [E{len(all_ids) + 7}].",
        "paper_cited_for_self": f"{body} [P1].",
        "inflation_listed_words": f"{body}{rng.choice(INFLATE)}{cite}",
        "inflation_held_out": f"{body}{rng.choice(INFLATE_HELD_OUT)}{cite}",
    }


def main(seed: int = 7):
    rng = random.Random(seed)
    ev = parse_resume((ROOT / "samples" / "sample_resume.txt").read_text())["evidence"]
    paper = {"title": "A fictional paper on data pipelines", "abstract": "Data cleaning at scale.", "year": 2024,
             "venue": "Test", "authors": [{"name": "Test Author"}]}
    src = build_sources(ev, [paper])
    ids = [e["id"] for e in ev]
    truths = [(e["id"], s) for e in ev if (s := evidence_sentence(e))]

    fp = sum(verify_text(s, src)["sentences"][0]["status"] == "unsupported" for _, s in truths)
    caught, total = defaultdict(int), defaultdict(int)
    for eid, s in truths:
        for kind, fake in perturb(s, eid, rng, ids).items():
            total[kind] += 1
            caught[kind] += verify_text(fake, src)["sentences"][0]["status"] in ("unsupported", "warn")

    print(f"True sentences: {len(truths)} | wrongly flagged as unsupported: {fp} ({100 * fp / len(truths):.0f}%)\n")
    print(f"{'Fabrication type':24s} {'caught':>8s}")
    all_c = all_t = 0
    for k in total:
        print(f"{k:24s} {caught[k]:>3d}/{total[k]:<3d} {100 * caught[k] / total[k]:5.0f}%")
        all_c += caught[k]
        all_t += total[k]
    print(f"{'overall':24s} {all_c:>3d}/{all_t:<3d} {100 * all_c / all_t:5.0f}%")


if __name__ == "__main__":
    main()
