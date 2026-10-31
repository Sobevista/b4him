#!/usr/bin/env python3
"""
maint_cite_mutants.py: proves the row cites in tools/test_row_cites.py DISCRIMINATE. For every row it applies one
gutting mutant per facet of the row's task to the row's tool (a one-line edit that switches the facet off), runs that
row's cites, and records which fail. A mutant that no cite kills means a cite is missing.

    py tools/maint_cite_mutants.py --repo <a scratch checkout>      the kill matrix; exit 1 if any mutant survives
    py tools/maint_cite_mutants.py --repo <checkout> --check         only check that every mutant applies once

Run it on a SCRATCH checkout (a worktree): each mutant edits a tool file there and restores it afterwards (in a
finally block), but a crash of this script could leave one edited. Never on the live checkout.
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

#: (row, facet, tool file under tools/, old text, new text). Each `old` must occur exactly once.
MUTANTS = [
    ("C1", "home page coverage", "headers_tls_check.py",
     'home = next((m for m in monitors if _same_url(m.get("url"), HOME_URL)), None)',
     'home = monitors[0] if monitors else None'),
    ("C1", "lesson coverage", "headers_tls_check.py",
     'lesson = next((m for m in monitors if LESSON_URL.match((m.get("url") or "").strip())), None)',
     'lesson = monitors[0] if monitors else None'),
    ("C1", "down monitor is S1", "headers_tls_check.py", 'if m["status"] in (8, 9):', 'if False:'),
    ("C1", "no key is UNKNOWN", "headers_tls_check.py",
     'return maint_receipt.write_receipt("C1", "UNKNOWN", why="no UPTIMEROBOT_API_KEY", tool=TOOL)',
     'return maint_receipt.write_receipt("C1", "SKIP", why="no UPTIMEROBOT_API_KEY", tool=TOOL)'),
    ("D1", "missing line", "maint_watch.py", 'problems.insert(0, f"MISSING: no line from the 08:30 run by 10:30"',
     '(lambda *a: None)(0, f"MISSING: no line from the 08:30 run by 10:30"'),
    ("D1", "failed release", "maint_watch.py", 'OK_OUTCOMES = {"PUBLISHED", "SKIP"}',
     'OK_OUTCOMES = {"PUBLISHED", "SKIP", "FAIL"}'),
    ("D1", "pending before the cutoff", "maint_watch.py", "            pending = True", "            pending = False"),
    ("D2", "overdue rows", "maint_watch.py", "        if now > dl:\n            what =", "        if False:\n            what ="),
    ("D2", "stuck UNKNOWN", "maint_watch.py", "(stuck if now > since + grace else pending).append(e)", "pending.append(e)"),
    ("D2", "awaiting clock", "maint_watch.py", "        if owed:\n            closes", "        if False:\n            closes"),
    ("D3", "UNKNOWN watch pings fail", "maint_watch.py", "return bool(bad or new), why, current",
     "return bool(new), why, current"),
    ("D3", "new alarm only once", "maint_watch.py", "new = [a for a in current if a not in seen]", "new = list(current)"),
    ("D3", "a new alarm pings fail", "maint_watch.py", "new = [a for a in current if a not in seen]", "new = []"),
    ("D3", "no URL is UNKNOWN", "maint_watch.py", 'return mr.write_receipt("D3", "UNKNOWN", why=f"no {HEARTBEAT_ENV}"',
     'return mr.write_receipt("D3", "SKIP", why=f"no {HEARTBEAT_ENV}"'),
    ("W1", "internal relative links", "linkcheck.py", "        if not resolves(target, served):", "        if False:"),
    ("W1", "every page", "linkcheck.py", "        return site_pages.served_pages(root)\n",
     "        return site_pages.served_pages(root)[:3]\n"),
    ("W1", "dead outbound", "linkcheck.py", "DEAD_CODES = {404, 410}", "DEAD_CODES = set()"),
    ("W1", "outbound cache", "linkcheck.py", "and t is not None and now - t < MAX_AGE", "and False"),
    ("W1b", "Wayback proposal", "linkcheck.py", '                    if wb["status"] == "FOUND" else None)',
     '                    if False else None)'),
    ("W1b", "failed lookup is UNKNOWN", "linkcheck.py", "    if lookups_failed:", "    if False:"),
    ("W2", "open findings", "maint_watch.py", "    opens = open_findings(receipts, findings)", "    opens = []"),
    ("W2", "UNKNOWNs", "maint_watch.py", "    unknowns = unknown_streaks(receipts)", "    unknowns = []"),
    ("W2", "monitor line", "maint_watch.py", "f\"- C1 uptime monitor: {pre[0]['outcome']} {pre[0]['why']}\",",
     '"- C1 uptime monitor: (not read)",'),
    ("W2", "empty week says 0 findings", "maint_watch.py", 'for f in opens] or ["0 findings"]', 'for f in opens] or []'),
    ("W3", "known name is S1", "maint_pages.py",
     'return ("S3", HEURISTIC_ROUTE) if f["kind"] == "unknown-name" else ("S1", S1_ROUTE)',
     'return ("S3", HEURISTIC_ROUTE)'),
    ("W3", "every published page", "maint_pages.py", '        return site_pages.served_pages(repo, exts, ref="HEAD")',
     '        return site_pages.served_pages(repo, exts, ref="HEAD")[:4]'),
    ("W3", "no names file is UNKNOWN", "maint_pages.py", '    elif unknown:\n        outcome = "UNKNOWN"',
     '    elif False:\n        outcome = "UNKNOWN"'),
    ("M1", "page failures are FINDINGS", "maint_quality.py",
     '        return "FINDINGS", n, f"{n} WCAG2AA issue(s) on {pages} page(s) (axe + htmlcs)"',
     '        return "PASS", 0, "gutted"'),
    ("M1", "the report parser", "maint_quality.py", "def parse_pa11y(stdout: str) -> dict | None:\n",
     "def parse_pa11y(stdout: str) -> dict | None:\n    return None\n"),
    ("M1", "a technical fault is UNKNOWN", "maint_quality.py",
     '        return "UNKNOWN", None, "pa11y-ci exit 1:', '        return "PASS", 0, "pa11y-ci exit 1:'),
    ("M1b", "failing pairs", "maint_quality.py", '    if g["failure_causes"]:', '    if False:'),
    ("M1b", "pseudo-elements await the eye", "maint_quality.py",
     '        return "SKIP", None, maint_receipt.awaiting_why(\n            "M1b"',
     '        return "PASS", 0, maint_receipt.awaiting_why(\n            "M1b"'),
    ("M2", "median of runs", "maint_quality.py", "statistics.median(", "max("),
    ("M2", "budget miss", "maint_quality.py", "            elif m[a] > cap:", "            elif False:"),
    ("M2", "missing run", "maint_quality.py", '        if m["_runs"] < runs:', '        if False:'),
    ("M2b", "p75 miss", "maint_quality.py", "        if v > cap:", "        if False:"),
    ("M2b", "no field data", "maint_quality.py", 'return "UNKNOWN", None, "UNKNOWN-field: no CrUX data for the origin',
     'return "PASS", 0, "UNKNOWN-field: no CrUX data for the origin'),
    ("M2b", "no key", "maint_quality.py", 'return receipt(root, "M2b", "UNKNOWN", why="no CRUX_API_KEY", evidence=ev)',
     'return receipt(root, "M2b", "SKIP", why="no CRUX_API_KEY", evidence=ev)'),
    ("M3", "certificate expiry", "headers_tls_check.py", "        if days < CERT_S1_DAYS:", "        if False:"),
    ("M3", "HTTP to HTTPS redirect", "headers_tls_check.py",
     '        if r["status"] not in (301, 308) or not loc.lower().startswith(f"https://{host}"):', "        if False:"),
    ("M3", "header diff", "headers_tls_check.py", "            changes = diff_headers(old, headers)",
     "            changes = []"),
    ("M3", "mixed content", "headers_tls_check.py", "        hits = mixed_content(git_grep_http(repo()))",
     "        hits = []"),
    ("M4", "jargon on the route", "maint_pages.py", "        jargon_total += len(m[\"unglossed\"])",
     "        jargon_total += 0"),
    ("M4", "broken reader path", "maint_pages.py", '            broken.append(f"{a} -> {b}")', "            pass"),
    ("M4", "awaits the editor", "maint_pages.py", '    return [receipt(repo, "M4", "SKIP", None, mr.awaiting_why(',
     '    return [receipt(repo, "M4", "PASS", 0, mr.awaiting_why('),
    ("M5", "board stamp read", "maint_watch.py", 'BOARD_STAMP = re.compile(r"\\*Generated (',
     'BOARD_STAMP = re.compile(r"\\*Generatedx ('),
    ("M5", "awaiting in grace", "maint_watch.py", "    if now <= dl:                              # the check ran",
     "    if False:                              # the check ran"),
    ("M5", "overdue is FINDINGS", "maint_watch.py", "    if now < due:\n        if last_day is None:",
     "    if now < due + dt.timedelta(days=9999):\n        if last_day is None:"),
    ("M5", "unreadable board is UNKNOWN", "maint_watch.py",
     "        raise Unknown(\"PRODUCTION_BOARD.md carries no '*Generated <date> by `tools/production_board.py`' line\")",
     "        return dt.date.today()"),
    ("Q1", "pages due", "maint_pages.py", '    due = [x for x in per if x["due"]]', "    due = []"),
    ("Q1", "awaits the editor", "maint_pages.py", '        return [receipt(repo, "Q1", "SKIP", None, mr.awaiting_why(',
     '        return [receipt(repo, "Q1", "PASS", 0, mr.awaiting_why('),
    ("Q2", "the grep", "maint_pages.py", "    code, out = git(repo, *args, ok=(0, 1))", '    code, out = 0, ""'),
    ("Q2", "every served file type", "maint_pages.py", '    args += ["HEAD", "--"]\n',
     '    args += ["HEAD", "--", "*.html"]\n'),
    ("Q2", "the witness is independent", "maint_pages.py",
     '    if seat in state["authors"] or seat == SWEEP_SEAT:', "    if False:"),
    ("Q2", "the client token list", "maint_pages.py",
     '            toks += [t for t in json.loads(ft.read_text(encoding="utf-8")).get("tokens", []) if t]',
     "            pass"),
    ("Q3", "stale findings", "maint_pages.py", "STALE_DAYS = 90", "STALE_DAYS = 10 ** 6"),
    ("Q3", "stale patches", "maint_pages.py", "    for r in patches:\n        age, since", "    for r in []:\n        age, since"),
    ("Q4", "A records", "headers_tls_check.py", 'res.find("S1", f"{host} A points outside',
     '(lambda *a: None)("S1", f"{host} A points outside'),
    ("Q4", "verification TXT", "headers_tls_check.py", 'res.find("S2", f"verification TXT',
     '(lambda *a: None)("S2", f"verification TXT'),
    ("Q4", "wildcard", "headers_tls_check.py", '    if st == "ok" or st_c == "ok":', "    if False:"),
    ("Q5", "Daniel's OK", "headers_tls_check.py", '    if os.environ.get("MAINT_OBSERVATORY_OK") != "1":',
     "    if False:"),
    ("Q5", "a failing test", "headers_tls_check.py", 'res.find("S3", f"Observatory test {t} fails"',
     '(lambda *a: None)("S3", f"Observatory test {t} fails"'),
    ("Q5", "frame-ancestors filed once", "headers_tls_check.py", "            if t in known:", "            if False:"),
    ("Q6", "armed drill awaits", "maint_watch.py", 'return show([mr.write_receipt("Q6", "SKIP", why=f"awaiting alarm',
     'return show([mr.write_receipt("Q6", "PASS", why=f"awaiting alarm'),
    ("Q6", "the close carries the evidence", "maint_watch.py", '    ev = aw["evidence"]', "    ev = None"),
    ("Q6", "no alarm is S1", "maint_watch.py", 'mr.write_finding("Q6", "S1", "alarm fire drill FAILED"',
     '(lambda *a: None)("Q6", "S1", "alarm fire drill FAILED"'),
    ("Q6", "no heartbeat is UNKNOWN", "maint_watch.py",
     'return show([mr.write_receipt("Q6", "UNKNOWN", why=f"no {HEARTBEAT_ENV}: there is no heartbeat',
     'return show([mr.write_receipt("Q6", "SKIP", why=f"no {HEARTBEAT_ENV}: there is no heartbeat'),
    ("H1", "not due", "maint_human.py", '    if not s["is_due"]:', "    if True:"),
    ("H1", "the D9 reference", "maint_human.py",
     '    table = [ln for ln in m.group(0).splitlines() if ln.startswith("|")][:12]', "    table = []"),
    ("H1", "the capture check", "maint_human.py", "    if problems:\n        mr.write_finding(\"H1\"",
     "    if False:\n        mr.write_finding(\"H1\""),
    ("H1", "Daniel's close carries the pack", "maint_watch.py",
     "\"is not read by this tool)\", evidence=aw[\"evidence\"], tool=TOOL)])",
     "\"is not read by this tool)\", evidence=None, tool=TOOL)])"),
    ("H2", "the note is read", "maint_watch.py",
     "            if n:                              # a dated filename is not a review: read it",
     "            if False:                              # a dated filename is not a review: read it"),
    ("H2", "an independent reviewer", "maint_watch.py", '    elif rid == "H2" and seat in mp.AUTHOR_SEATS:',
     "    elif False:"),
    ("H2", "the Date: line matches", "maint_watch.py", "        if file_date and note_date != file_date:",
     "        if False:"),
    ("H2", "due without a note awaits", "maint_watch.py",
     "    if now <= dl:                              # the check ran", "    if False:                              # the check ran"),
    ("H3", "the note is read", "maint_watch.py",
     "            if n:                              # a dated filename is not a review: read it",
     "            if False:                              # a dated filename is not a review: read it"),
    ("H3", "no future-dated note", "maint_watch.py", "    if file_date and today and file_date > today:",
     "    if False:"),
    ("H3", "due without a note awaits", "maint_watch.py",
     "    if now <= dl:                              # the check ran", "    if False:                              # the check ran"),
    ("A1", "every page in the Easy Checks", "maint_human.py",
     '    L += [f"| `{p}` | " + " | ".join("[ ]" for _ in EASY_CHECKS) + " |" for p in pages]', "    L += []"),
    ("A1", "the automated results", "maint_human.py",
     '        shutil.copyfile(m1[-1], out / "automated_axe_pa11y.json")\n', "        pass\n"),
    ("A1", "no page list is UNKNOWN", "maint_human.py",
     'return mr.write_receipt("A1", "UNKNOWN", why=f"A1 pack: no page list',
     'return mr.write_receipt("A1", "SKIP", why=f"A1 pack: no page list'),
    ("A1", "Daniel's sign-off carries the pack", "maint_watch.py",
     "\"is not read by this tool)\", evidence=aw[\"evidence\"], tool=TOOL)])",
     "\"is not read by this tool)\", evidence=None, tool=TOOL)])"),
    ("A2", "true duplicates", "maint_pages.py", "    dups = [v for v in by_sha.values() if len(v) > 1]", "    dups = []"),
    ("A2", "awaits the editor", "maint_pages.py", '    return [receipt(repo, "A2", "SKIP", None, mr.awaiting_why(',
     '    return [receipt(repo, "A2", "PASS", 0, mr.awaiting_why('),
    ("A3", "the 60-day window", "maint_human.py", "    if days <= WINDOW_DAYS and not closed:", "    if False:"),
    ("A3", "a hold status", "maint_human.py", '    if bad:\n        mr.write_finding("A3", "S1"',
     '    if False:\n        mr.write_finding("A3", "S1"'),
    ("A3", "Daniel's close ends the window", "maint_human.py",
     "    closed = [t for t, e in mw.receipts_of(", "    closed = [] and [t for t, e in mw.receipts_of("),
    ("A4", "a blind scanner", "maint_quality.py", "    if not hits:\n        return False",
     "    if not hits:\n        return True"),
    ("A4", "a noisy scanner", "maint_quality.py",
     '                problems.append(f"{s} flagged the clean control page")', "                pass"),
    ("A4", "linkcheck's internal pass", "maint_quality.py",
     "            bad = lc.internal_check(site, pages, lc.scan(site, pages), None)", "            bad = []"),
    ("A4", "the people registry", "maint_quality.py",
     "        out[r] = [f\"{f.kind}:{f.label or ''}:{f.text}\" for f in res.findings]", "        out[r] = []"),
    ("A4", "the mixed-content grep", "maint_quality.py",
     "        hits = htc.mixed_content(htc.git_grep_http(site))", "        hits = []"),
]

FAILED = re.compile(r"^FAILED .*?::(test_\w+)", re.M)


def run_cites(repo: Path, row: str) -> list[str]:
    p = subprocess.run([sys.executable, "-m", "pytest", str(repo / "tools" / "test_row_cites.py"), "-q", "--tb=no",
                        "-rf", "-p", "no:cacheprovider", "-k", f"_{row}_", "--rootdir", str(repo)],
                       capture_output=True, encoding="utf-8", errors="replace", cwd=str(repo))
    return sorted(set(FAILED.findall(p.stdout)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="a SCRATCH checkout of b4him at the commit under test")
    ap.add_argument("--check", action="store_true", help="only check every mutant applies exactly once")
    a = ap.parse_args(argv)
    repo = Path(a.repo).resolve()
    bad = []
    for row, facet, tool, old, new in MUTANTS:
        n = (repo / "tools" / tool).read_text(encoding="utf-8").count(old)
        if n != 1:
            bad.append(f"{row} {facet}: occurs {n} time(s) in {tool}")
    if bad:
        print("MUTANTS THAT DO NOT APPLY:\n  " + "\n  ".join(bad))
        return 2
    if a.check:
        print(f"{len(MUTANTS)} mutants apply")
        return 0
    survivors = []
    print("| row | mutant (facet gutted) | tool | failing cite(s) |\n|---|---|---|---|")
    for row, facet, tool, old, new in MUTANTS:
        f = repo / "tools" / tool
        orig = f.read_text(encoding="utf-8")
        try:
            f.write_text(orig.replace(old, new), encoding="utf-8", newline="\n")
            killed = run_cites(repo, row)
        finally:
            f.write_text(orig, encoding="utf-8", newline="\n")
        if not killed:
            survivors.append(f"{row} {facet}")
        print(f"| {row} | {facet} | tools/{tool} | {', '.join(killed) or '**SURVIVED**'} |", flush=True)
    clean = run_cites_all(repo)
    print(f"\n{len(MUTANTS)} mutants, {len(MUTANTS) - len(survivors)} killed, {len(survivors)} survived; "
          f"unmutated cites: {clean}")
    if survivors:
        print("SURVIVORS (a cite is missing): " + "; ".join(survivors))
    return 1 if survivors else 0


def run_cites_all(repo: Path) -> str:
    p = subprocess.run([sys.executable, "-m", "pytest", str(repo / "tools" / "test_row_cites.py"), "-q", "--tb=no",
                        "-p", "no:cacheprovider", "--rootdir", str(repo)],
                       capture_output=True, encoding="utf-8", errors="replace", cwd=str(repo))
    return (p.stdout.strip().splitlines() or ["?"])[-1]


if __name__ == "__main__":
    sys.exit(main())
