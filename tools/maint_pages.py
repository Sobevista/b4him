#!/usr/bin/env python3
"""
maint_pages.py - the page-level rows of the maintenance calendar (seat: Maintenance Auditor).

    py tools/maint_pages.py people             # W3  people_registry over every served HTML page
    py tools/maint_pages.py genericize         # Q2  independent git grep for D11's forbidden tokens + the W3 result
    py tools/maint_pages.py witness <seat>     # Q2  record the witness (a seat that did not write the pages)
    py tools/maint_pages.py reread             # Q1  the quarterly re-read, driven by production_board's 90-day rule
    py tools/maint_pages.py hygiene            # Q3  open patches and open findings, by age
    py tools/maint_pages.py walk               # M4  the non-technical reader walkthrough template
    py tools/maint_pages.py inventory          # A2  content inventory + the ROT checklist
    options: --repo <path> (default: this repo)  --today YYYY-MM-DD (what-if)

Every run writes a receipt through tools/maint_receipt.py (.maint/maintenance_log.jsonl) and its evidence under
.maint/audits/ (git-ignored). Exit 0 = PASS or SKIP, 1 = FINDINGS, 2 = UNKNOWN (people_registry's own convention).
UNKNOWN never rounds to PASS.

WHAT "SERVED" MEANS HERE. GitHub Pages runs Jekyll over the repo root, which never serves a path that has a component
starting with "." or "_". The pages are the tracked *.html files at HEAD outside such paths. Jekyll ALSO renders the
tracked *.md docs today (until the serve-exclude lands); they are planning records, which D11 says are not gutted to
genericize, so these rows do not scan them. That limit is written into every evidence file.

This tool reads the tree, the queue and git; it writes only under .maint/. It never runs production_board.py (which
rewrites PRODUCTION_BOARD.md); it imports its constants and load_queue instead.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_receipt as mr  # noqa: E402
import people_registry as pr  # noqa: E402
import production_board as pb  # noqa: E402
import site_pages  # noqa: E402
import voice_check as vc  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
TOOL = "maint_pages.py"
SERVED_ASSET_EXT = (".html", ".css", ".js", ".svg", ".txt", ".xml", ".webmanifest")
NOT_SCANNED = ("Jekyll-rendered *.md docs (served today until the serve-exclude lands; D11: decision records are not "
               "gutted), images and fonts (text only)")

#: The seat roster (seats/ROSTER.json on branch docs/seats-v1, 2026-10-20). Copied as ids only, to validate a witness.
SEATS = ("publisher", "production-coordinator", "managing-editor", "curriculum-designer", "reader-advocate",
         "site-maintainer", "design-accessibility", "release-manager", "maintenance-auditor", "reviewer",
         "privacy-safety", "site-ops-researcher")
#: Who writes pages: the content line (Editorial) and the patch line (Site). [ASSUMED from ROSTER.json departments]
AUTHOR_SEATS = {"managing-editor", "curriculum-designer", "site-maintainer", "design-accessibility"}
SWEEP_SEAT = "maintenance-auditor"          # runs the sweep, so it cannot also witness it
S1_ROUTE = "release-manager + publisher (Daniel)"
HEURISTIC_ROUTE = "reviewer (Independent Reviewer: confirm the heuristic hit)"
STALE_DAYS = 90                             # Q3 flag threshold [ASSUMED]
READING_AGE_TARGET = 9                      # UK public-sector target [S1-39 in the seat pack]
FK_GRADE_TARGET = READING_AGE_TARGET - 5    # [ASSUMED] reading age = US grade + 5
TRIVIAL_WORDS = 150                         # A2 "trivial?" hint threshold [ASSUMED]


# ---------------------------------------------------------------------------------------------------------- plumbing
class CouldNotRun(RuntimeError):
    pass


def git(repo: Path, *args: str, ok=(0,)) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    except OSError as e:
        raise CouldNotRun(f"git could not start: {e}") from None
    if p.returncode not in ok:
        raise CouldNotRun(f"git {' '.join(args[:2])} exited {p.returncode}: "
                          f"{p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return p.returncode, p.stdout.decode("utf-8", "replace")


def head_sha(repo: Path) -> str:
    return git(repo, "rev-parse", "HEAD")[1].strip()


def is_served(path: str) -> bool:
    return site_pages.is_served(path)


def served_files(repo: Path, exts=(".html",)) -> list[str]:
    """The shared page list (tools/site_pages.py), from HEAD's tree."""
    try:
        return site_pages.served_pages(repo, exts, ref="HEAD")
    except site_pages.GitError as e:
        raise CouldNotRun(str(e)) from None


def page_text(repo: Path, path: str) -> str:
    return git(repo, "show", f"HEAD:{path}")[1]


def url_path(path: str) -> str:
    if path == "index.html":
        return "/"
    if path.endswith("/index.html"):
        return "/" + path[: -len("index.html")]
    return "/" + path


def site_base(repo: Path) -> str:
    try:
        host = page_text(repo, "CNAME").strip()
    except CouldNotRun:
        host = ""
    return f"https://{host}" if host else "https://<no CNAME>"


def mdir(repo: Path) -> Path:
    """MAINT_DIR when it is set (maint_receipt's own override), else <repo>/.maint."""
    return Path(os.environ["MAINT_DIR"]) if os.environ.get("MAINT_DIR") else Path(repo) / ".maint"


@contextlib.contextmanager
def _maint_at(repo: Path):
    """maint_receipt writes to MAINT_DIR or its own repo's .maint/; pin it to mdir(repo) for this one call."""
    saved = os.environ.get("MAINT_DIR")
    os.environ["MAINT_DIR"] = str(mdir(repo))
    try:
        yield
    finally:
        if saved is None:
            os.environ.pop("MAINT_DIR", None)
        else:
            os.environ["MAINT_DIR"] = saved


def read_jsonl(path: Path) -> list[dict]:
    """Every line of a .jsonl file; an unparseable line comes back as {"_broken": line_no}, never dropped."""
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except ValueError:
                out.append({"_broken": i})
    return out


def audits(repo: Path) -> Path:
    d = mdir(repo) / "audits"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(repo: Path, p: Path) -> str:
    """Evidence path as maint_receipt wants it: `.maint/<path inside the maintenance dir>`."""
    return ".maint/" + p.resolve().relative_to(mdir(repo).resolve()).as_posix()


def write(p: Path, text: str) -> None:
    p.write_text(text, encoding="utf-8", newline="\n")


def receipt(repo: Path, row: str, outcome: str, n=None, why="", evidence=None) -> dict:
    with _maint_at(repo):
        return mr.write_receipt(row, outcome, n, why, evidence, tool=TOOL)


def finding(repo: Path, row: str, sev: str, subject: str, detail: str, route: str) -> dict:
    with _maint_at(repo):
        return mr.write_finding(row, sev, subject, detail, route)


def last_receipt(repo: Path, row: str) -> dict | None:
    recs = [r for r in read_jsonl(mdir(repo) / mr.LOG_NAME) if r.get("row") == row]
    return recs[-1] if recs else None


def load_rows(repo: Path) -> list[dict]:
    """production_board.load_queue, pointed at `repo` (it reads the module-level QUEUE)."""
    saved = pb.QUEUE
    pb.QUEUE = Path(repo) / "production_queue.jsonl"
    try:
        return pb.load_queue()
    finally:
        pb.QUEUE = saved


def published_rows(rows: list[dict]) -> list[dict]:
    """The board's own definition (production_board.build): stage PUBLISHED or later."""
    return [r for r in rows if not r.get("_broken") and pb.stage_index(r) >= pb.STAGES.index("PUBLISHED")]


def row_pages(row: dict) -> list[str]:
    return [p for p in [row.get("page"), *(row.get("files") or [])] if p]


# ------------------------------------------------------------------------------------------------------- W3 people
def _registry(repo: Path):
    d = Path(repo) / "data"
    return pr.load_registry(d / "people_registry.json", d / "people_names.local.json", d / "common_first_names.txt")


def people_page(text: str, reg) -> dict:
    """One page through people_registry.check_text, with the CLI's exit mapping (0 clean, 1 refused, 2 could not run)."""
    try:
        r = pr.check_text(text, (), reg)
    except pr.RegistryError as e:
        return {"exit": 2, "outcome": "UNKNOWN", "status": f"COULD NOT RUN: {e}", "findings": [],
                "known_names_loaded": False}
    code = 0 if r.ok else (1 if r.findings else 2)
    return {"exit": code, "outcome": {0: "PASS", 1: "FINDINGS", 2: "UNKNOWN"}[code], "status": r.status(),
            "known_names_loaded": r.known_names_loaded,
            "findings": [{"kind": f.kind, "text": f.text, "rule": f.rule, "label": f.label, "role": f.role}
                         for f in r.findings]}


# ---- the scan layer (tuning lives here, not in people_registry.py) -------------------------------------------------
#: Site furniture: scanned ONCE site-wide as "(site chrome)", not once per page, so it is never unscanned and never
#: counted 23 times.
CHROME_EL = re.compile(r"(?is)<(nav|header|footer)\b[^>]*>.*?</\1\s*>")
#: Block-level tags. people_registry joins capitalised words across any whitespace (newlines included), so a bare
#: newline would not stop "Games Videos Writing" reading as one name: each block edge gets a newline-dot-newline,
#: which ends the run and the sentence and adds no word.
BLOCK = re.compile(r"(?i)</?(?:p|div|li|ul|ol|h[1-6]|section|article|main|aside|header|footer|nav|table|thead|tbody|"
                   r"tr|td|th|blockquote|figure|figcaption|dl|dt|dd|br|hr|label|button|option|select|summary|details|"
                   r"pre|form|fieldset|legend|caption)\b[^>]*>")
BLOCK_SEP = "\n.\n"
SITE_CHROME = "(site chrome)"
#: The per-page lines' row id. W3's own receipt is the SUMMARY line only.
PAGE_ROW = "W3.page"


def _blocks(html_text: str) -> str:
    return BLOCK.sub(lambda m: BLOCK_SEP + m.group(0) + BLOCK_SEP, html_text)


def scan_html(page_html: str) -> tuple[str, list[str]]:
    """(the page with nav/header/footer removed and block edges separated, the removed chrome blocks)."""
    chrome = [m.group(0) for m in CHROME_EL.finditer(page_html)]
    return _blocks(CHROME_EL.sub(BLOCK_SEP, page_html)), chrome


def _words(s: str) -> str:
    return " ".join(pr.WORD.findall(html.unescape(re.sub(r"<[^>]+>", " ", s)))).lower()


def site_vocabulary(texts: dict[str, str]) -> list[str]:
    """The site's own titles: every served page's <title> and <h1>, as word strings. A heuristic hit whose words run
    contiguously inside one of them is the site naming itself, not a person."""
    out = set()
    for t in texts.values():
        for m in re.finditer(r"(?is)<(title|h1)\b[^>]*>(.*?)</\1\s*>", t):
            w = _words(m.group(2))
            if w:
                out.add(w)
    return sorted(out)


def tuned_registry(reg, repo: Path):
    """A copy of the registry whose safe words also hold data/people_registry.json's role_terms (safe_terms are already
    in it). The loaded registry itself is not changed."""
    import copy
    r2 = copy.copy(reg)
    extra = {w.lower() for ws in reg.data.get("role_terms", {}).values() for w in ws}
    r2.safe = set(reg.safe) | extra | {s.lower() for s in reg.data.get("safe_terms", [])}
    return r2


def in_vocab(w: str, vocab: list[str]) -> bool:
    return bool(w) and any(f" {w} " in f" {v} " for v in vocab)


def names_file_words(repo: Path) -> tuple[set[str], set[str]]:
    """(full names, single name words), lower-case, from the git-ignored data/people_names.local.json when it exists.
    Read only to REFUSE an exemption; nothing from it is written anywhere."""
    p = Path(repo) / "data" / "people_names.local.json"
    full: set[str] = set()
    if p.exists():
        try:
            for person in json.loads(p.read_text(encoding="utf-8")).get("people", []):
                full |= {" ".join(pr.WORD.findall(n)).lower() for n in person.get("names", []) if n}
        except (OSError, ValueError, AttributeError):
            pass
    return full, {w for n in full for w in n.split()}


CAP_PAIR = re.compile(r"^[A-Z][\w'’-]*\s+[A-Z][\w'’-]*$")


def exempt(res: dict, is_vocab, names: tuple[set[str], set[str]] = (set(), set())) -> dict:
    """Drop a heuristic unknown-name hit only when it is the title vocabulary of THIS page (is_vocab(words) is the
    page's own <title>/<h1>, never another page's); record what was dropped. Never exempted: a known-person or age
    hit, and a two-word Capitalised pair whose pair or either word is in the names file. The outcome is recomputed
    with the CLI's mapping."""
    if res["exit"] == 2 and not res["findings"] and res["status"].startswith("COULD NOT RUN"):
        return res
    full, single = names
    keep, dropped = [], []
    for f in res["findings"]:
        w = _words(f["text"])
        named = bool(CAP_PAIR.match(f["text"].strip())) and (w in full or any(x in single for x in w.split()))
        if f["kind"] == "unknown-name" and not named and is_vocab(w):
            dropped.append({"text": f["text"], "why": "this page's own title vocabulary (<title>/<h1>)"})
        else:
            keep.append(f)
    code = 1 if keep else (0 if res["known_names_loaded"] else 2)
    if keep:
        status = "REFUSED"
    elif res["known_names_loaded"]:
        status = "CLEAN"
    else:
        status = "UNKNOWN (known-names list not loaded; only the unknown-name heuristic ran)"
    return {**res, "findings": keep, "exempted": dropped, "exit": code,
            "outcome": {0: "PASS", 1: "FINDINGS", 2: "UNKNOWN"}[code], "status": status}


def people_scan(repo: Path) -> dict:
    """W3 over every served HTML page (body text) plus the site chrome once. Writes nothing."""
    pages = served_files(repo)
    try:
        reg = tuned_registry(_registry(repo), repo)
        reg_err = None
    except pr.RegistryError as e:
        reg, reg_err = None, str(e)
    texts = {p: page_text(repo, p) for p in pages}
    vocab = {p: site_vocabulary({p: t}) for p, t in texts.items()}       # per page: never another page's titles
    names = names_file_words(repo)
    per, chrome, chrome_pages = {}, [], []
    for p in pages:
        body, ch = scan_html(texts[p])
        chrome += [c for c in ch if c not in chrome]
        if ch:
            chrome_pages.append(p)
        if reg is None:
            per[p] = {"exit": 2, "outcome": "UNKNOWN", "status": f"COULD NOT RUN: {reg_err}", "findings": [],
                      "known_names_loaded": False}
        else:
            per[p] = exempt(people_page(body, reg), lambda w, v=vocab[p]: in_vocab(w, v), names)
    if chrome and reg is not None:
        # furniture is a list of separate items (menu links, a wordmark, footer spans): every tag edge separates.
        # The chrome is shared, so only words in the title of EVERY page that carries chrome (the site's own name)
        # are its vocabulary: never one page's title lent to the whole site.
        items = BLOCK_SEP.join(re.sub(r"<[^>]+>", lambda m: BLOCK_SEP + m.group(0) + BLOCK_SEP, c) for c in chrome)
        per[SITE_CHROME] = exempt(people_page(items, reg),
                                  lambda w: all(in_vocab(w, vocab[p]) for p in chrome_pages), names)
        per[SITE_CHROME]["distinct_blocks"] = len(chrome)
    n = sum(len(v["findings"]) for v in per.values())
    unknown = [p for p, v in per.items() if not v["known_names_loaded"] or v["outcome"] == "UNKNOWN"]
    if not pages:
        outcome, why = "UNKNOWN", "no served HTML page found at HEAD"
    elif n:
        outcome = "FINDINGS"
        why = (f"{n} finding(s) on {sum(1 for v in per.values() if v['findings'])} of {len(pages)} pages"
               + (f"; known-names half UNKNOWN on {len(unknown)} scanned units (data/people_names.local.json absent or "
                  f"unreadable)" if unknown else ""))
    elif unknown:
        outcome = "UNKNOWN"
        why = (reg_err and f"could not run: {reg_err}") or (
            f"{len(unknown)} of {len(pages)} pages UNKNOWN: data/people_names.local.json absent, so only the "
            f"unknown-name heuristic ran")
    else:
        outcome, why = "PASS", f"{len(pages)} pages clean with the known-names list loaded"
    ex = sum(len(v.get("exempted", [])) for v in per.values())
    if pages:
        why += (f"; scan layer: body text per page + site chrome once ({per.get(SITE_CHROME, {}).get('distinct_blocks', 0)}"
                f" distinct blocks); {ex} heuristic hit(s) exempted as their own page's title vocabulary (listed in "
                f"evidence)")
    return {"pages": per, "count": len(pages), "n": n, "outcome": outcome, "why": why, "head": head_sha(repo),
            "exempted": ex}


def _classify(f: dict) -> tuple[str, str]:
    """(severity, route): a heuristic-only hit (unknown-name) is S3 "needs review", to the reviewer to confirm; a
    known-name hit or any other rule break stays S1, to the Release Manager and Daniel at once."""
    return ("S3", HEURISTIC_ROUTE) if f["kind"] == "unknown-name" else ("S1", S1_ROUTE)


def cmd_people(repo: Path, today: dt.date) -> list[dict]:
    res = people_scan(repo)
    ev = audits(repo) / f"{today.isoformat()}_people.json"
    write(ev, json.dumps({"row": "W3", "date": today.isoformat(), "not_scanned": NOT_SCANNED, **res}, indent=1,
                         ensure_ascii=False))
    evr = rel(repo, ev)
    out = []
    for page, v in res["pages"].items():
        groups: dict[tuple[str, str], list[str]] = {}
        for f in v["findings"]:
            groups.setdefault(_classify(f) + (f["kind"],), []).append(f["text"])
        for (sev, route, kind), texts in groups.items():
            subj = f"{page}: {kind}" + (" (needs review)" if sev == "S3" else "")
            finding(repo, "W3", sev, subj, f"{len(texts)} hit(s); texts in {evr}", route)
        n = len(v["findings"]) if v["outcome"] == "FINDINGS" else None
        # the calendar's "log line per page", under its own row id so nothing mistakes it for W3's receipt
        out.append(receipt(repo, PAGE_ROW, v["outcome"], n, f"{page}: {v['status']}", evr))
    out.append(receipt(repo, "W3", res["outcome"], res["n"] if res["outcome"] == "FINDINGS" else None,
                       f"SUMMARY {res['count']} pages: {res['why']}", evr))
    return out


# --------------------------------------------------------------------------------------------------- Q2 genericize
D11_ARROW = re.compile(r"(?:`([^`]+)`|\b([A-Z][\w-]*))\s*→\s*(\S+)")


def d11_tokens(repo: Path) -> list[str]:
    """The forbidden tokens D11 itself names ("X → generic replacement"), read from DECISIONS.md at HEAD, so no name
    is copied into this tool. The client's name is deliberately NOT in the repo (D11), so it cannot come from here."""
    text = page_text(repo, "DECISIONS.md")
    m = re.search(r"^## D11\b.*?(?=^## )", text, re.S | re.M)
    if not m:
        raise CouldNotRun("DECISIONS.md has no D11 section")
    line = next((ln for ln in m.group(0).splitlines() if "Genericization is a hard rule" in ln), None)
    if not line:
        raise CouldNotRun("D11 has no 'Genericization is a hard rule' line")
    toks = []
    for a, b, rhs in D11_ARROW.findall(line):
        tok = a or b
        if tok and not rhs.lower().startswith("generic") and tok not in toks:
            toks.append(tok)
    if not toks:
        raise CouldNotRun("no 'X → replacement' token parsed from D11")
    return toks


def local_tokens(repo: Path) -> tuple[list[str], bool]:
    """Git-ignored tokens: data/forbidden_tokens.local.json {"tokens": [...]} (the client's name lives only there) plus
    every name in data/people_names.local.json. Returns (tokens, client_list_loaded)."""
    d = Path(repo) / "data"
    toks: list[str] = []
    ft = d / "forbidden_tokens.local.json"
    loaded = False
    if ft.exists():
        try:
            toks += [t for t in json.loads(ft.read_text(encoding="utf-8")).get("tokens", []) if t]
            loaded = True
        except (OSError, ValueError):
            loaded = False
    pn = d / "people_names.local.json"
    if pn.exists():
        try:
            for p in json.loads(pn.read_text(encoding="utf-8")).get("people", []):
                toks += [n for n in p.get("names", []) if n]
        except (OSError, ValueError):
            pass
    return toks, loaded


#: The one line that must name the tokens: D11's own rule, in DECISIONS.md. Recorded as exempt, never counted.
D11_RULE_LINE = "Genericization is a hard rule"


def d11_voice_tokens(repo: Path) -> list[str]:
    """The D11 tokens whose replacement is the first person ("X → first person"): the voice rule. It binds the
    Lessons; outside lessons/ it is not a genericization leak, so the non-lesson sweep does not count it."""
    text = page_text(repo, "DECISIONS.md")
    m = re.search(r"^## D11\b.*?(?=^## )", text, re.S | re.M)
    line = next((ln for ln in (m.group(0) if m else "").splitlines() if D11_RULE_LINE in ln), "")
    return [a or b for a, b, rhs in D11_ARROW.findall(line) if rhs.lower().startswith("first")]


def grep_tokens(repo: Path, tokens: list[str], exempted: list | None = None,
                voice: list[str] | None = None, scoped: list | None = None) -> list[dict]:
    """An independent `git grep` over EVERY served text file at HEAD, whatever its type (html, css, js, svg, md, json,
    txt, xml...: Pages serves them all; `-I` skips binaries, which a grep cannot read). Not people_registry, not the
    author's report. D11's own rule line is the one exemption, appended to `exempted`."""
    args = ["grep", "-n", "-I", "-i", "-F", "-w", "--full-name"]
    for t in tokens:
        args += ["-e", t]
    args += ["HEAD", "--"]
    code, out = git(repo, *args, ok=(0, 1))
    hits = []
    for line in out.splitlines():
        parts = line.split(":", 3)
        if len(parts) < 4 or not is_served(parts[1]):
            continue
        _, path, ln, text = parts
        which = [t for t in tokens if re.search(rf"(?<!\w){re.escape(t)}(?!\w)", text, re.I)]
        if path == "DECISIONS.md" and D11_RULE_LINE in text:
            if exempted is not None:
                exempted.append({"path": path, "line": int(ln), "why": "D11's own rule line names the tokens"})
            continue
        vl = {v.lower() for v in (voice or [])}
        if vl and not path.startswith("lessons/"):
            rest = [t for t in which if t.lower() not in vl]
            if not rest:                       # only the voice rule's token, outside the Lessons: out of scope
                if scoped is not None:
                    scoped.append({"path": path, "line": int(ln)})
                continue
            which = rest
        hits.append({"path": path, "line": int(ln), "tokens": which, "text": text.strip()[:200]})
    return hits


def page_authors(rows: list[dict]) -> set[str]:
    """The seats that wrote the pages: the content and patch lines' seats, plus any seat named in a drafted_by."""
    seats = set(AUTHOR_SEATS)
    for r in rows:
        by = str(r.get("drafted_by") or "").lower().replace(" ", "-")
        seats |= {s for s in SEATS if s in by}
    return seats


def hit_severity(path: str) -> tuple[str, str]:
    """D11 is written for the Lessons ("a published lesson is not done until an independent grep confirms zero
    forbidden tokens"): a hit there is S1. A hit on another page (the About page in his own voice, say) is S2 for the
    witness to judge whether D11 binds that page; that judgement is doctrine, so it is not made here."""
    if path.startswith("lessons/"):
        return "S1", S1_ROUTE
    return "S2", "reviewer (witness: does D11 bind this non-lesson page? doctrine -> publisher) + site-maintainer"


def genericize_outcome(state: dict) -> tuple[str, int | None, str]:
    if state.get("error"):
        return "UNKNOWN", None, f"could not run: {state['error']}"
    if state["hits"]:
        s1 = sum(1 for h in state["hits"] if hit_severity(h["path"])[0] == "S1")
        return "FINDINGS", len(state["hits"]), (f"{len(state['hits'])} forbidden-token line(s) on served files: {s1} "
                                                f"in lessons/ (S1), {len(state['hits']) - s1} elsewhere (S2, D11 scope "
                                                f"for the witness)")
    # setup debts: the sweep could not fully run, so it stays UNKNOWN (and D2 calls it STUCK past its grace)
    gaps = []
    if not state["client_list_loaded"]:
        gaps.append("the client-name list (data/forbidden_tokens.local.json) is absent, so D11's one non-negotiable "
                    "token was not searched")
    if state["w3"]["outcome"] == "UNKNOWN":
        gaps.append(f"W3 could not fully run ({state['w3']['why'][:160]})")
    if gaps:
        return "UNKNOWN", None, "could not fully run: " + "; ".join(gaps)
    w3 = "W3 PASS" if state["w3"]["outcome"] == "PASS" else f"W3 {state['w3']['outcome']} (its findings stand in W3)"
    if not state.get("witness"):
        return "SKIP", None, mr.awaiting_why("Q2", "reviewer", f"0 forbidden tokens, {w3}; a witness seat that did "
                                             "not write the pages re-reads the sweep (or `maint_pages.py witness <seat>`)")
    return "PASS", 0, f"0 forbidden tokens, {w3}, witnessed by {state['witness']['seat']}"


def render_genericize(state: dict) -> str:
    o, n, why = genericize_outcome(state)
    w = state.get("witness")
    L = [f"# Genericization sweep (Q2), {state['date']}", "",
         f"- head: `{state['head']}`",
         f"- witness: {w['seat'] + ' at ' + w['at'] if w else '(none recorded; the receipt stays UNKNOWN)'}",
         f"- the pages' authors (a witness may not be one): {', '.join(sorted(state['authors']))}; "
         f"nor `{SWEEP_SEAT}`, which ran the sweep",
         f"- outcome: **{o}**{f' {n}' if o == 'FINDINGS' else ''}: {why}", "",
         "## 1. Independent git grep (D11)", "",
         f"- tokens from D11 (DECISIONS.md at HEAD): {state.get('d11_count', 0)}; local git-ignored tokens: "
         f"{state.get('local_count', 0)} (not echoed); client-name list loaded: {state['client_list_loaded']}",
         f"- surface: every tracked text file at HEAD outside `.`/`_` paths, whatever its type (Pages serves them "
         f"all). Not scanned: binary files (images, fonts), which a grep cannot read.",
         f"- exempt: {len(state.get('exempted') or [])} line(s), D11's own rule line in DECISIONS.md",
         f"- out of scope: {len(state.get('voice_scoped') or [])} line(s) outside lessons/ whose only token is the "
         f"voice rule's (D11 \"→ first person\" binds the Lessons; it is still swept there)", ""]
    if state.get("error"):
        L.append(f"**COULD NOT RUN:** {state['error']}")
    elif not state["hits"]:
        L.append("0 hits.")
    else:
        L += ["| file | line | token(s) | severity |", "|---|---|---|---|"]
        L += [f"| `{h['path']}` | {h['line']} | {', '.join(h['tokens'])} | {hit_severity(h['path'])[0]} |"
              for h in state["hits"]]
    L += ["", "## 2. W3 people registry (fresh run, same HEAD)", "",
          f"- {state['w3']['outcome']}{' ' + str(state['w3']['n']) if state['w3']['outcome'] == 'FINDINGS' else ''}: "
          f"{state['w3']['why']}", "",
          "## 3. Witness", "",
          "The witness re-reads sections 1 and 2 against the served pages and records `maint_pages.py witness <seat>`. "
          "A witness is refused if HEAD moved since the sweep (re-run the sweep).", ""]
    return "\n".join(L) + "\n"


def genericize_sweep(repo: Path, today: dt.date) -> dict:
    rows = load_rows(repo)
    state = {"row": "Q2", "date": today.isoformat(), "head": head_sha(repo), "authors": sorted(page_authors(rows)),
             "witness": None, "hits": [], "client_list_loaded": False}
    try:
        d11 = d11_tokens(repo)
        loc, loaded = local_tokens(repo)
        state.update(d11_count=len(d11), local_count=len(loc), client_list_loaded=loaded)
        state["exempted"], state["voice_scoped"] = [], []
        state["hits"] = grep_tokens(repo, d11 + loc, state["exempted"], d11_voice_tokens(repo), state["voice_scoped"])
    except CouldNotRun as e:
        state["error"] = str(e)
    w3 = people_scan(repo)
    state["w3"] = {"outcome": w3["outcome"], "n": w3["n"], "why": w3["why"]}
    return state


def _save_genericize(repo: Path, state: dict) -> tuple[str, Path]:
    d = audits(repo)
    js = d / f"{state['date']}_genericize.json"
    md = d / f"{state['date']}_genericize.md"
    write(js, json.dumps(state, indent=1, ensure_ascii=False))
    write(md, render_genericize(state))
    return rel(repo, md), js


def cmd_genericize(repo: Path, today: dt.date) -> list[dict]:
    state = genericize_sweep(repo, today)
    evr, _ = _save_genericize(repo, state)
    by_path: dict[str, list[dict]] = {}
    for h in state["hits"]:
        by_path.setdefault(h["path"], []).append(h)
    for path, hs in by_path.items():
        sev, route = hit_severity(path)
        finding(repo, "Q2", sev, f"{path}: forbidden token",
                f"{len(hs)} line(s): " + ", ".join(sorted({t for h in hs for t in h["tokens"]})), route)
    o, n, why = genericize_outcome(state)
    return [receipt(repo, "Q2", o, n if o == "FINDINGS" else None, why, evr)]


def cmd_witness(repo: Path, today: dt.date, seat: str, date: str | None = None) -> list[dict]:
    d = audits(repo)
    files = sorted(d.glob(f"{date}_genericize.json" if date else "*_genericize.json"))
    if not files:
        raise CouldNotRun("no genericize sweep to witness: run `maint_pages.py genericize` first")
    state = json.loads(files[-1].read_text(encoding="utf-8"))
    seat = seat.strip().lower()
    if seat not in SEATS:
        raise CouldNotRun(f"{seat!r} is not a b4him seat ({', '.join(SEATS)})")
    if seat in state["authors"] or seat == SWEEP_SEAT:
        raise CouldNotRun(f"{seat!r} wrote the pages or ran the sweep; the witness must be another seat")
    head = head_sha(repo)
    if head != state["head"]:
        raise CouldNotRun(f"HEAD moved since the sweep ({state['head'][:12]} -> {head[:12]}): re-run genericize")
    state["witness"] = {"seat": seat, "at": mr.now_utc().isoformat(timespec="seconds"), "head": head}
    evr, _ = _save_genericize(repo, state)
    o, n, why = genericize_outcome(state)
    return [receipt(repo, "Q2", o, n if o == "FINDINGS" else None, why, evr)]


# ------------------------------------------------------------------------------------------------------- Q1 reread
def rows_due(rows: list[dict], today: dt.date) -> list[tuple[dict, str]]:
    """production_board.build's "Maintenance due" block (production_board.py:443-455), row for row."""
    due = []
    for r in published_rows(rows):
        last = r.get("last_reviewed") or r.get("published")
        if not last:
            due.append((r, "never recorded"))
            continue
        try:
            age = (today - dt.date.fromisoformat(last)).days
        except ValueError:
            due.append((r, f"unreadable date {last!r}"))
            continue
        if age >= pb.MAINT_PAGE_DAYS:
            due.append((r, f"{age} days since last review"))
    return due


def pages_due(repo: Path, rows: list[dict], today: dt.date) -> list[dict]:
    """The same rule per served page: a page's clock is the newest last_reviewed/published of the published rows that
    carry it (page or files). A served page no published row carries is due: "never recorded"."""
    out = []
    pub = published_rows(rows)
    for p in served_files(repo):
        dates, ids, bad = [], [], []
        for r in pub:
            if p in row_pages(r):
                ids.append(r.get("id"))
                last = r.get("last_reviewed") or r.get("published")
                try:
                    dates.append(dt.date.fromisoformat(last))
                except (TypeError, ValueError):
                    bad.append(f"{r.get('id')}: {last!r}")
        if not ids:
            out.append({"page": p, "rows": [], "last": None, "due": True, "why": "never recorded (no published row)"})
        elif not dates:
            out.append({"page": p, "rows": ids, "last": None, "due": True, "why": "unreadable date " + "; ".join(bad)})
        else:
            last = max(dates)
            age = (today - last).days
            out.append({"page": p, "rows": ids, "last": last.isoformat(), "due": age >= pb.MAINT_PAGE_DAYS,
                        "why": f"{age} days since last review",
                        "next_due": (last + dt.timedelta(days=pb.MAINT_PAGE_DAYS)).isoformat()})
    return out


def later_rulings(repo: Path, since: str | None) -> list[str]:
    try:
        text = page_text(repo, "DECISIONS.md")
    except CouldNotRun:
        return ["(DECISIONS.md unreadable)"]
    out = []
    for m in re.finditer(r"^## (D\d+[^\n]*?LOCKED (\d{4}-\d\d-\d\d))", text, re.M):
        if since is None or m.group(2) > since:
            out.append(m.group(1).strip())
    return out


def _receipt_line(repo: Path, row: str) -> str:
    r = last_receipt(repo, row)
    if not r:
        return f"{row} has no receipt yet: UNKNOWN for this item"
    return f"{row} {r['outcome']}{' ' + str(r['n']) if r.get('n') is not None else ''} at {r['at']} ({r['why'][:90]})"


def cmd_reread(repo: Path, today: dt.date) -> list[dict]:
    rows = load_rows(repo)
    per = pages_due(repo, rows, today)
    due = [x for x in per if x["due"]]
    board = rows_due(rows, today)
    base = site_base(repo)
    L = [f"# Quarterly page re-read (Q1), {today.isoformat()}", "",
         f"*Driven by production_board's Maintenance-due rule: every {pb.MAINT_PAGE_DAYS} days "
         f"(`MAINT_PAGE_DAYS`, PRODUCTION_PLAN section 5), applied per served page. ASSIST: this file is the evidence; "
         f"the seat re-reads and records the outcome. A board row's clock is its `last_reviewed` or `published` date, "
         f"so a patch's publish date restarts the clock of every page it carried [the board's rule, reused as is].*", "",
         f"- served pages: {len(per)}; due: **{len(due)}**",
         f"- the board's own due rows: {len(board)}" + (" (" + ", ".join(f"{r.get('id')}: {w}" for r, w in board) + ")"
                                                        if board else ""), ""]
    for x in due:
        L += [f"## {x['page']}  ({base}{url_path(x['page'])})", "",
              f"*Due: {x['why']}; rows: {', '.join(x['rows']) or 'none'}.*", "",
              f"1. [ ] Links, including links into other lessons. Latest {_receipt_line(repo, 'W1')}",
              "2. [ ] Facts that age: tool names, versions, prices, URLs, \"currently\" claims.",
              "3. [ ] A later ruling that supersedes the page (DECISIONS and the ledger since " + (x["last"] or "first publish")
              + "). Locked since then in DECISIONS.md: " + ("; ".join(later_rulings(repo, x["last"])) or "none"),
              "4. [ ] Voice (D1), tone floor (D2), audience (D3), Title Case headings (D21).",
              f"5. [ ] People and forbidden tokens. Latest {_receipt_line(repo, 'W3')}; anything new by eye.",
              "6. [ ] Accessibility spot check: heading order, alt text, focus.",
              "7. [ ] Outcome: `MAINTAINED <date>` (nothing found is still recorded) or findings filed "
              "(correction -> Site Maintainer, S2; voice -> Editor; doctrine -> Daniel).", ""]
    if not due:
        L += ["Nothing due.", ""]
    L += ["## Not due", "", "| page | last review | next due | rows |", "|---|---|---|---|"]
    L += [f"| `{x['page']}` | {x['last']} | {x.get('next_due')} | {', '.join(x['rows'])} |" for x in per if not x["due"]]
    ev = audits(repo) / f"{today.isoformat()}_reread.md"
    write(ev, "\n".join(L) + "\n")
    evr = rel(repo, ev)
    if due:
        return [receipt(repo, "Q1", "SKIP", None, mr.awaiting_why(
        "Q1", "managing-editor", f"{len(due)} of {len(per)} pages due for re-read (listed in the evidence)"), evr)]
    nxt = min((x["next_due"] for x in per if x.get("next_due")), default=None)
    return [receipt(repo, "Q1", "SKIP", 0, f"0 of {len(per)} pages due (next due {nxt})", evr)]


# ------------------------------------------------------------------------------------------------------ Q3 hygiene
def _age(today: dt.date, *dates) -> tuple[int | None, str | None]:
    for d in dates:
        if not d:
            continue
        try:
            day = dt.date.fromisoformat(str(d)[:10])
        except ValueError:
            continue
        return (today - day).days, day.isoformat()
    return None, None


def cmd_hygiene(repo: Path, today: dt.date) -> list[dict]:
    rows = load_rows(repo)
    patches = [r for r in rows if not r.get("_broken") and pb.is_patch(r)
               and pb.stage_index(r) < pb.STAGES.index("PUBLISHED")]
    broken = [r for r in rows if r.get("_broken")]
    raw = read_jsonl(mdir(repo) / mr.FINDINGS_NAME)
    groups: dict[tuple, dict] = {}
    for f in raw:
        if f.get("_broken"):
            continue
        key = (f.get("row"), f.get("subject"))
        g = groups.setdefault(key, {"row": key[0], "subject": key[1], "first": f.get("at"), "count": 0,
                                    "severity": f.get("severity"), "route_to": f.get("route_to"), "status": "open"})
        g["count"] += 1
        g["last"] = f.get("at")
        if f.get("status") in ("closed", "wont-do"):
            g["status"] = f["status"]
    open_f = [g for g in groups.values() if g["status"] == "open"]
    items = []
    for r in patches:
        age, since = _age(today, r.get("drafted"), r.get("since"))
        items.append({"kind": "patch", "id": r.get("id"), "stage": r.get("stage"), "since": since, "age": age,
                      "blocked_on": (r.get("blocked_on") or "")[:120]})
    for g in open_f:
        age, since = _age(today, g["first"])
        items.append({"kind": "finding", "id": f"{g['row']} {g['subject']}", "stage": g["severity"], "since": since,
                      "age": age, "blocked_on": f"x{g['count']} -> {g['route_to']}"})
    stale = [i for i in items if i["age"] is None or i["age"] > STALE_DAYS]
    L = [f"# Patch-queue hygiene (Q3), {today.isoformat()}", "",
         f"*Every open patch (`kind: \"patch\"`, stage before PUBLISHED) in production_queue.jsonl and every open "
         f"finding in .maint/maintenance_findings.jsonl (grouped by row + subject; a line with `status` closed or "
         f"wont-do closes its group). Older than {STALE_DAYS} days [ASSUMED threshold] is flagged. Each item is "
         f"re-prioritised or closed as won't-do with a reason; won't-do closures go to Daniel as a tile.*", "",
         f"- open patches: {len(patches)}; open findings: {len(open_f)}; flagged stale: **{len(stale)}**"
         + (f"; UNPARSEABLE queue lines: {len(broken)}" if broken else ""), "",
         "| kind | item | stage / severity | opened | age (days) | flag | note |", "|---|---|---|---|---|---|---|"]
    for i in sorted(items, key=lambda x: -(x["age"] or 10 ** 6)):
        flag = "STALE" if i in stale else ""
        L.append(f"| {i['kind']} | {i['id']} | {i['stage']} | {i['since']} | {i['age']} | {flag} | {i['blocked_on']} |")
    L += ["", "Decision per item (seat): re-prioritise (new severity / window) or close won't-do (reason; Daniel's tile).", ""]
    ev = audits(repo) / f"{today.isoformat()}_hygiene.md"
    write(ev, "\n".join(L) + "\n")
    evr = rel(repo, ev)
    if broken:
        return [receipt(repo, "Q3", "UNKNOWN", None, f"{len(broken)} unparseable queue line(s)", evr)]
    if stale:
        return [receipt(repo, "Q3", "FINDINGS", len(stale), f"{len(stale)} of {len(items)} open items older than "
                                                             f"{STALE_DAYS} days or undated", evr)]
    return [receipt(repo, "Q3", "PASS", 0, f"{len(items)} open item(s) ({len(patches)} patch, {len(open_f)} finding), "
                                           f"none older than {STALE_DAYS} days", evr)]


# --------------------------------------------------------------------------------------------------------- M4 walk
HREF = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)


def syllables(word: str) -> int:
    w = word.lower().strip("'’")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def fk_grade(text: str) -> dict:
    """Flesch-Kincaid grade level: 0.39 (words/sentences) + 11.8 (syllables/words) - 15.59. An INDICATOR, never a gate."""
    words = re.findall(r"[A-Za-z][A-Za-z'’]*", text)
    sentences = max(1, len([s for s in re.split(r"[.!?]+(?:\s|$)", text) if re.search(r"[A-Za-z]", s)]))
    if not words:
        return {"words": 0, "sentences": 0, "syllables": 0, "grade": None}
    syl = sum(syllables(w) for w in words)
    g = 0.39 * len(words) / sentences + 11.8 * syl / len(words) - 15.59
    return {"words": len(words), "sentences": sentences, "syllables": syl, "grade": round(g, 1)}


def links_of(page: str, text: str, served: set[str]) -> dict[str, list[str]]:
    """{target page: [labels]} for every internal href in the raw HTML (script strings included)."""
    base = "https://site.invalid" + url_path(page)
    out: dict[str, list[str]] = {}
    for href in set(HREF.findall(text)):
        u = urlsplit(urljoin(base, html.unescape(href)))
        if u.netloc != "site.invalid":
            continue
        path = u.path.lstrip("/")
        target = (path + "index.html") if (path == "" or path.endswith("/")) else path
        if target not in served or target == page:
            continue
        labels = []
        for m in re.finditer(rf"""<a\b[^>]*href\s*=\s*["']{re.escape(href)}["'][^>]*>(.*?)</a>""", text, re.S | re.I):
            lab = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", m.group(1)))).strip()
            aria = re.search(r"""aria-label\s*=\s*["']([^"']+)""", m.group(0), re.I)
            labels.append(lab or (aria and f"[aria-label] {aria.group(1)}") or "(no text)")
        out.setdefault(target, []).extend(labels or ["(href outside an <a>, e.g. a script string)"])
    return out


def shortest_path(start: str, goal: str, graph: dict[str, dict[str, list[str]]]) -> list[str] | None:
    prev, q = {start: None}, deque([start])
    while q:
        cur = q.popleft()
        if cur == goal:
            path = []
            while cur is not None:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        for nxt in sorted(graph.get(cur, {})):
            if nxt not in prev:
                prev[nxt] = cur
                q.append(nxt)
    return None


def first_tier1_lesson(texts: dict[str, str]) -> str | None:
    t = texts.get("lessons/index.html", "")
    i = t.find('id="lessons-list"')
    m = re.search(r"""class="mod"\s+href="([^"]+)\"""", t[i:]) if i >= 0 else None
    if not m:
        return None
    return m.group(1).strip("/") + "/index.html"


def cmd_walk(repo: Path, today: dt.date, lesson: str | None = None) -> list[dict]:
    served = served_files(repo)
    texts = {p: page_text(repo, p) for p in served}
    graph = {p: links_of(p, t, set(served)) for p, t in texts.items()}
    lesson = lesson or first_tier1_lesson(texts)
    waypoints = ["index.html", "lessons/find-your-door/index.html", lesson]
    route, broken = ["index.html"], []
    for a, b in zip(waypoints, waypoints[1:]):
        seg = shortest_path(a, b, graph) if (a in texts and b and b in texts) else None
        if seg is None:
            broken.append(f"{a} -> {b}")
            break
        route += seg[1:]
    base = site_base(repo)
    L = [f"# Non-technical reader walkthrough (M4), {today.isoformat()}", "",
         "*ASSIST: a template with the evidence filled in. The seat walks it as the persona and answers. Persona "
         "[ASSUMED, seat pack section 8]: curious, no faith background, no coding background, on a phone, arrived from "
         "a shared link. Warmth (D4) is not scored here: write what you saw; Daniel rules it in H1.*", "",
         f"- path: home -> Find Your Door -> a Tier 1 lesson (`{lesson}`, the first Tier One module on the lessons page)",
         f"- shortest click route found: {' -> '.join(url_path(p) for p in route)}"
         + (f"  **BROKEN: no link route {broken[0]}**" if broken else ""), ""]
    for i, (a, b) in enumerate(zip(route, route[1:]), 1):
        L += [f"## Step {i}: {url_path(a)} -> {url_path(b)}", "",
              f"Controls on {url_path(a)} that lead there: " + "; ".join(f'"{x}"' for x in graph[a].get(b, [])), "",
              "1. Would they know this step moves them toward what they came for?  Answer (seat): ____",
              "2. Can they see the control?  Answer (seat): ____",
              "3. Does its label predict where it goes? (INV-W4: familiarity is not clarity)  Answer (seat): ____",
              "4. After acting, can they tell they made progress?  Answer (seat): ____", ""]
    L += ["## Each page on the route", "",
          f"*Plain-language indicator: Flesch-Kincaid grade of the visible text (header, nav and footer dropped, as "
          f"voice_check does). Target reading age {READING_AGE_TARGET} ~ grade {FK_GRADE_TARGET} [ASSUMED mapping: "
          f"reading age = grade + 5]. An indicator only, never a gate: Daniel's voice wins (D1). Text a script builds "
          f"(the Find Your Door questions and result) is not in the static page, so it is not measured: read it in "
          f"the browser.*", "",
          "| page | words | sentences | FK grade | vs target | unglossed jargon |", "|---|---|---|---|---|---|"]
    jargon_total, detail = 0, []
    for p in route:
        vis = vc.visible_text(texts[p])
        fk = fk_grade(vis)
        m = vc.measure(vis)
        jargon_total += len(m["unglossed"])
        rel_t = "n/a" if fk["grade"] is None else ("at/below" if fk["grade"] <= FK_GRADE_TARGET else "above")
        L.append(f"| {base}{url_path(p)} | {fk['words']} | {fk['sentences']} | {fk['grade']} | {rel_t} | "
                 f"{len(m['unglossed'])} |")
        detail += [f"- `{p}`: {u}" for u in m["unglossed"]]
    L += ["", f"### Unexplained jargon (voice_check.JARGON, {len(vc.JARGON)} terms; first use must be glossed)", ""]
    L += detail or ["- none on the route"]
    L += ["", "### Also note (seat)", "", "- any sentence that assumes competence (D3): ____",
          "- any line that preaches (D2): ____", "- anything about warmth goes to Daniel as taste, not a finding: ____", ""]
    ev = audits(repo) / f"{today.isoformat()}_reader.md"
    write(ev, "\n".join(L) + "\n")
    evr = rel(repo, ev)
    n = jargon_total + len(broken)
    for p in route:
        u = vc.measure(vc.visible_text(texts[p]))["unglossed"]
        if u:
            finding(repo, "M4", "S3", f"{p}: unglossed jargon", f"{len(u)} term(s): " +
                    ", ".join(x.split(":")[0] for x in u), "managing-editor (Editor: words)")
    for b in broken:
        finding(repo, "M4", "S2", f"reader path broken: {b}", "no link route between the waypoints",
                "site-maintainer (nav)")
    if n:
        return [receipt(repo, "M4", "FINDINGS", n, f"{jargon_total} unglossed jargon term(s), {len(broken)} broken "
                                                   f"path segment(s); the four questions await the seat", evr)]
    return [receipt(repo, "M4", "SKIP", None, mr.awaiting_why(
        "M4", "managing-editor", "evidence assembled, no mechanical finding; the four walkthrough questions are the "
        "seat's to answer"), evr)]


# ---------------------------------------------------------------------------------------------------- A2 inventory
def owner_of(page: str, rows: list[dict]) -> tuple[list[str], str]:
    ids, content = [], False
    for r in rows:
        if r.get("_broken"):
            continue
        if page in row_pages(r):
            ids.append(r.get("id"))
            content |= not pb.is_patch(r)
    if content:
        return ids, "managing-editor (content line)"
    if page.startswith(pb.SHARED_PREFIX):
        return ids, "site-maintainer (track furniture, tools/tracks/)"
    if ids:
        return ids, "managing-editor [ASSUMED: served before the production line; only patches carry it]"
    return ids, "unowned in the queue [ASSUMED: managing-editor]"


def git_dates(repo: Path, path: str) -> dict:
    out = git(repo, "log", "--follow", "--format=%as", "HEAD", "--", path)[1].split()
    return {"first": out[-1] if out else None, "last": out[0] if out else None, "commits": len(out)}


def cmd_inventory(repo: Path, today: dt.date) -> list[dict]:
    rows = load_rows(repo)
    base = site_base(repo)
    inv = []
    for p in served_files(repo):
        t = page_text(repo, p)
        title = re.search(r"<title>(.*?)</title>", t, re.S | re.I)
        vis = vc.visible_text(t)
        ids, owner = owner_of(p, rows)
        inv.append({"page": p, "url": base + url_path(p), "title": html.unescape(title.group(1).strip()) if title else None,
                    "owner": owner, "rows": ids, **git_dates(repo, p), "words": len(vis.split()),
                    "text_sha": hashlib.sha256(re.sub(r"\s+", " ", vis.lower()).encode("utf-8")).hexdigest()[:16]})
    by_sha: dict[str, list[str]] = {}
    for x in inv:
        by_sha.setdefault(x["text_sha"], []).append(x["page"])
    dups = [v for v in by_sha.values() if len(v) > 1]
    L = [f"# Content inventory and ROT audit (A2), {today.isoformat()}", "",
         "**Mission rule:** \"outdated\" means **annotate, never erase**. A failure stays in the record beside the wins "
         "(README). Only true duplicates are candidates to merge, and **only Daniel rules a removal**.", "",
         f"*Inventory: every served HTML page at HEAD ({len(inv)}). Dates are git commit dates (first and last commit "
         f"touching the file, `--follow`), not publish dates; owners come from production_queue.jsonl rows. "
         f"tools/capability_inventory/inventory.py was read for reuse: it inventories scheduled tasks and n8n flows, "
         f"not pages, so nothing of it fits here beyond its git-ignored-output pattern.*", "",
         "| URL | title | owner | queue rows | first commit | last commit | commits | words |",
         "|---|---|---|---|---|---|---|---|"]
    L += [f"| {x['url']} | {x['title']} | {x['owner']} | {', '.join(x['rows'])} | {x['first']} | {x['last']} | "
          f"{x['commits']} | {x['words']} |" for x in inv]
    L += ["", "## Mechanical hints (evidence, not verdicts)", "",
          f"- identical visible text (true-duplicate candidates): " + ("; ".join(" = ".join(d) for d in dups) or "none"),
          f"- under {TRIVIAL_WORDS} visible words [ASSUMED threshold] (a \"trivial?\" question, e.g. an honest "
          f"\"coming\" shell): " + (", ".join(x["page"] for x in inv if x["words"] < TRIVIAL_WORDS) or "none"), "",
          "## ROT checklist (one block per page; the Editor answers)", ""]
    for x in inv:
        L += [f"### {x['url']}", "",
              "- [ ] Redundant? A true duplicate of another page -> propose a merge to Daniel (never remove).",
              "- [ ] Outdated? -> annotate the page to say what changed and when; the old text stays in the record.",
              "- [ ] Trivial? -> say why it still earns its place, or propose a change to Daniel.",
              "- [ ] Decision: keep / edit (annotate) / propose merge (Daniel) / propose removal (Daniel only).", ""]
    ev = audits(repo) / f"{today.isoformat()}_content_audit.md"
    write(ev, "\n".join(L) + "\n")
    write(audits(repo) / f"{today.isoformat()}_inventory.json", json.dumps(inv, indent=1, ensure_ascii=False))
    evr = rel(repo, ev)
    for d in dups:
        finding(repo, "A2", "S3", "duplicate visible text: " + " = ".join(d), "true-duplicate candidate; a merge or "
                "removal is Daniel's ruling", "managing-editor (Editor); removal -> publisher (Daniel)")
    if dups:
        return [receipt(repo, "A2", "FINDINGS", len(dups), f"{len(inv)} pages inventoried; {len(dups)} duplicate "
                                                           f"group(s); ROT judgement awaits the Editor", evr)]
    return [receipt(repo, "A2", "SKIP", None, mr.awaiting_why(
        "A2", "managing-editor", f"{len(inv)} pages inventoried, no duplicate; the ROT (redundant / outdated / "
        "trivial) judgement is the Editor's"), evr)]


# ------------------------------------------------------------------------------------------------------------- CLI
EXIT = {"PASS": 0, "SKIP": 0, "FINDINGS": 1, "UNKNOWN": 2}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", type=Path, default=REPO)
    ap.add_argument("--today", help="ISO date (what-if)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for c in ("people", "genericize", "reread", "hygiene", "inventory"):
        sub.add_parser(c)
    w = sub.add_parser("witness")
    w.add_argument("seat")
    w.add_argument("--date", help="which sweep (default: the newest)")
    wk = sub.add_parser("walk")
    wk.add_argument("--lesson", help="the Tier 1 lesson file (default: the first Tier One module)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    repo = a.repo.resolve()
    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    row = {"people": "W3", "genericize": "Q2", "witness": "Q2", "reread": "Q1", "hygiene": "Q3", "walk": "M4",
           "inventory": "A2"}[a.cmd]
    try:
        if a.cmd == "people":
            recs = cmd_people(repo, today)
        elif a.cmd == "genericize":
            recs = cmd_genericize(repo, today)
        elif a.cmd == "witness":
            recs = cmd_witness(repo, today, a.seat, a.date)
        elif a.cmd == "reread":
            recs = cmd_reread(repo, today)
        elif a.cmd == "hygiene":
            recs = cmd_hygiene(repo, today)
        elif a.cmd == "walk":
            recs = cmd_walk(repo, today, a.lesson)
        else:
            recs = cmd_inventory(repo, today)
    except CouldNotRun as e:
        if a.cmd == "witness":                      # a refused witness is not a run of Q2: no receipt, just the refusal
            print("REFUSED:", e)
            return 2
        recs = [receipt(repo, row, "UNKNOWN", None, f"could not run: {e}")]
    for r in recs:
        print(json.dumps(r, ensure_ascii=False))
    return EXIT[recs[-1]["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
