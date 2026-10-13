#!/usr/bin/env python3
"""
voice_check.py — does a lesson page sound like Daniel, measured, before it reaches him?

Daniel ruled 2026-10-13 (ledger E00480, "Revoice, then offer") after an audit found the Tier 4/5 drafts at 1.4-4.0
first-person words per 1,000 against 27.2 on the About page his wife read as his voice, and thick with estate jargon.
He had asked for "normie / plain people speak" 16 times in 30 days. Prose rules about voice had failed; this is the
rule as code. tools/approvals.py runs it on every lesson-tier page before it offers a tile.

Two checks on the page's VISIBLE text (scripts, styles, tags and the site chrome stripped):
  1. FIRST PERSON  - Daniel's I/me/my/we/our per 1,000 words must be >= FLOOR (10). About sits at 27.
  2. JARGON        - an estate term may appear only if its first use is glossed in plain words right there
                     (a parenthesis, a dash, "means", "is", "which is", "called" within GLOSS_WINDOW chars).
Exit 0 PASS, 1 FAIL. This is a floor, not taste: passing it does not make a page good, it makes it reviewable.

    py tools/voice_check.py lessons/<slug>/index.html [...]
"""
from __future__ import annotations

import html
import re
import sys
from pathlib import Path

FLOOR = 10.0                     # first-person words per 1,000 visible words (E00480)
GLOSS_WINDOW = 90                # chars after a term's first use where a plain gloss must start
FIRST_PERSON = re.compile(r"\b(i|me|my|mine|myself|i'm|i've|i'd|i'll|we|us|our|ours|ourselves|we're|we've)\b", re.I)
# Estate words a reader outside the build would not know. Matched as whole words, case-insensitive.
# "invariant" and "gate" are left out on purpose: they are the lesson template's own section labels ("The
# invariant", "Validator Gates"), explained by the template on every page.
JARGON = ["harness", "seam", "breaker", "seat", "rung", "ledger", "cog", "pipe", "occupant", "applier", "oracle",
          "corpus", "lap", "leg", "orchestrator", "receipt", "spine", "steward", "drift"]
GLOSS_MARK = re.compile(r"\(|—|–| - |\bmeans\b|\bmeaning\b|\bis\b|\bare\b|\bwhich\b|\bcalled\b|\bi\.e\.|:", re.I)
# An appositive gloss: the term followed straight away by ", <plain words>" ("drift, things that had slipped").
APPOSITIVE = re.compile(r"^s?,\s+[a-z]", re.I)
CHROME = re.compile(r"<(head|header|footer|nav)\b.*?</\1>", re.S | re.I)
DROP = re.compile(r"<(script|style)\b.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def visible_text(page_html: str) -> str:
    t = DROP.sub(" ", page_html)
    t = CHROME.sub(" ", t)
    t = TAG.sub(" ", t)
    t = html.unescape(t).replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


def measure(text: str) -> dict:
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", text)
    n = len(words) or 1
    fp = len(FIRST_PERSON.findall(text))
    unglossed = []
    for term in JARGON:
        m = re.search(rf"\b{term}s?\b", text, re.I)
        # glossed before the term counts too: "the real body of findings (the corpus)"
        glossed_before = re.search(r"\((the |a |an )?$", text[max(0, m.start() - 6):m.start()]) if m else None
        after = text[m.end():m.end() + GLOSS_WINDOW] if m else ""
        if m and not glossed_before and not APPOSITIVE.match(after) and not GLOSS_MARK.search(after):
            unglossed.append(f"{term}: …{text[max(0, m.start() - 40):m.end() + 50]}…")
    rate = 1000.0 * fp / n
    return {"words": n, "first_person": fp, "rate": round(rate, 1), "unglossed": unglossed,
            "pass": rate >= FLOOR and not unglossed}


def check(path: Path) -> dict:
    return measure(visible_text(path.read_text(encoding="utf-8")))


def main(argv=None) -> int:
    paths = [Path(p) for p in (argv if argv is not None else sys.argv[1:])]
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ok = True
    for p in paths:
        r = check(p)
        ok &= r["pass"]
        print(f"{'PASS' if r['pass'] else 'FAIL'}  {p}  first person {r['rate']}/1k (floor {FLOOR}), "
              f"{r['words']} words, {len(r['unglossed'])} unglossed term(s)")
        for u in r["unglossed"]:
            print(f"      unglossed {u}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
