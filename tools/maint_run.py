#!/usr/bin/env python3
"""
maint_run.py: the maintenance calendar's one entry point. It reads tools/maint_rows.json (the calendar as data, written
by tools/maint_rows_build.py), works out which rows are due today, runs each row's tool, and makes sure every row it
ran has a receipt in .maint/maintenance_log.jsonl.

    py tools/maint_run.py               the rows due today (local date)
    py tools/maint_run.py --date D      the rows due on D (what-if; the tools still run now)
    py tools/maint_run.py --all         every row in the table, now
    py tools/maint_run.py --row W1      one row (repeatable)
    py tools/maint_run.py --list        print what would run, run nothing

WHEN A ROW IS DUE (the calendar's Days paragraph, as tools/maint_rows.json carries it): daily rows every day; weekly
rows on Monday; monthly rows on the first Monday of the month; quarterly, 6-monthly and annual rows on the first
Monday of their months (the table's `months`, [ASSUMED] in maint_rows_build.py). Event rows (E1, E2) are never due
on the clock; --all and --row give them a SKIP receipt saying why. E3, the standards watch, polls its feeds weekly
(tools/standards_watch.py), so the table makes it a weekly row.

ORDER. Every other row first, in table order; then the watcher's own rows (W2 digest, M5/H2/H3 checks, the HUMAN
reminders, Q6); then D1, D2 and D3 last, so D2's overdue list and D3's heartbeat reflect the whole run. Schedule this
after D1's 10:30 cutoff (the schtasks line is 10:35).

ISOLATION. Each runner is its own process with a timeout. A runner that crashes, times out or exits without writing
its row's receipt gets `UNKNOWN <why>` written for that row here; the run goes on. One runner may write several rows
(linkcheck.py writes W1 and W1b; the digest writes C1/M5/H2/H3/H1/A1/A3 when it has something to say); a row already
receipted earlier in this run is not run a second time.

Exit 0 every row run has a receipt · 2 a row's runner could not start (its tool is missing, or the process would not
launch). FINDINGS and UNKNOWN are in the receipts, not in the exit code: D2 and the W2 digest are where they alarm.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import maint_receipt as mr  # noqa: E402

REPO = HERE.parent
ROWS_FILE = HERE / "maint_rows.json"
TOOL = "maint_run.py"
TOOLS_DIR = HERE                              # where the runners' scripts live; tests point it at fakes
MIN, HOUR = 60, 3600

#: row -> (tool script, args, timeout seconds). Rows sharing a (tool, args) share one run.
RUNNERS: dict[str, tuple[str, tuple[str, ...], int]] = {
    "C1": ("headers_tls_check.py", ("uptime",), 2 * MIN),
    "W1": ("linkcheck.py", (), HOUR),
    "W1b": ("linkcheck.py", (), HOUR),
    "W3": ("maint_pages.py", ("people",), 15 * MIN),
    "M1": ("maint_quality.py", ("a11y",), 2 * HOUR),
    "M1b": ("maint_quality.py", ("contrast",), HOUR),
    "M2": ("maint_quality.py", ("perf",), 2 * HOUR),
    "M2b": ("maint_quality.py", ("crux",), 5 * MIN),
    "M3": ("headers_tls_check.py", ("tls",), 10 * MIN),
    "M4": ("maint_pages.py", ("walk",), 10 * MIN),
    "Q1": ("maint_pages.py", ("reread",), 10 * MIN),
    "Q2": ("maint_pages.py", ("genericize",), 15 * MIN),
    "Q3": ("maint_pages.py", ("hygiene",), 10 * MIN),
    "Q4": ("headers_tls_check.py", ("dns",), 10 * MIN),
    "Q5": ("headers_tls_check.py", ("observatory",), 10 * MIN),
    "A2": ("maint_pages.py", ("inventory",), 15 * MIN),
    "A4": ("maint_quality.py", ("calibrate",), HOUR),
    "E3": ("standards_watch.py", (), 5 * MIN),
    # the watcher's rows: after the rest, so the digest sees this run's receipts
    "W2": ("maint_watch.py", ("digest",), 5 * MIN),
    "M5": ("maint_watch.py", ("check", "M5"), 2 * MIN),
    "H2": ("maint_watch.py", ("check", "H2"), 2 * MIN),
    "H3": ("maint_watch.py", ("check", "H3"), 2 * MIN),
    "H1": ("maint_watch.py", ("one", "H1"), 2 * MIN),
    "A1": ("maint_watch.py", ("one", "A1"), 2 * MIN),
    "A3": ("maint_watch.py", ("one", "A3"), 2 * MIN),
    "Q6": ("maint_watch.py", ("drill",), 2 * MIN),
    # last: D1, then D2 (judges every row's receipts), then D3 (the heartbeat, fail if D1 or D2 is not PASS)
    "D1": ("maint_watch.py", ("one", "D1"), 2 * MIN),
    "D2": ("maint_watch.py", ("one", "D2"), 2 * MIN),
    "D3": ("maint_watch.py", ("one", "D3"), 2 * MIN),
}
WATCH_ROWS = ("W2", "M5", "H2", "H3", "H1", "A1", "A3", "Q6")
LAST_ROWS = ("D1", "D2", "D3")
#: Event rows have no clock and no runner here. Their receipt says why.
EVENT_RECEIPTS = {
    "E1": ("SKIP", "event row: runs on each template/nav/CSS patch before the tap (M1 + M1b + W1(a) + M2 on the "
                   "patched tree); a calendar run is not that event"),
    "E2": ("SKIP", "event row: each release's --verify-live outcome is judged by D1 (a release line that is not "
                   "PUBLISHED or SKIP, PUSHED-UNVERIFIED included, is a D1 finding)"),
}


class CouldNotStart(Exception):
    """The runner itself could not start (its tool is missing, or the process would not launch)."""


# ------------------------------------------------------------------ the clock
def first_monday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(0 - d.weekday()) % 7)


def is_due(row: dict, day: dt.date) -> bool:
    """The Days paragraph: daily every day; weekly Monday; monthly the first Monday; quarterly / 6-monthly / annual the
    first Monday of their months. Event rows never."""
    k = row.get("kind")
    if k == "daily":
        return True
    if k == "weekly":
        return day.weekday() == 0
    if k == "monthly":
        return day == first_monday(day.year, day.month)
    if k in ("quarterly", "semiannual", "annual"):
        return day.month in (row.get("months") or []) and day == first_monday(day.year, day.month)
    return False


def load_table(path: Path | None = None) -> list[dict]:
    return json.loads((path or ROWS_FILE).read_text(encoding="utf-8"))["rows"]


def due_rows(rows: list[dict], day: dt.date) -> list[str]:
    return [r["id"] for r in rows if is_due(r, day)]


def ordered(ids: list[str]) -> list[str]:
    """Table order, with the watcher's rows after the rest and D1, D2, D3 last."""
    rest = [i for i in ids if i not in WATCH_ROWS and i not in LAST_ROWS]
    return rest + [i for i in WATCH_ROWS if i in ids] + [i for i in LAST_ROWS if i in ids]


# ------------------------------------------------------------------ running one tool
def _kill_tree(p: subprocess.Popen) -> None:
    if os.name == "nt":                       # a timed-out Node scanner leaves Chromium children; take the whole tree
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
    else:
        p.kill()


def run_process(argv: list[str], timeout: int) -> tuple[int | None, str, str]:
    """(exit code or None on timeout, stdout, stderr). Raises CouldNotStart when the process cannot launch."""
    try:
        p = subprocess.Popen(argv, cwd=str(REPO), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             env={**os.environ, "PYTHONIOENCODING": "utf-8"}, encoding="utf-8", errors="replace")
    except OSError as e:
        raise CouldNotStart(f"{type(e).__name__}: {e}") from e
    try:
        out, err = p.communicate(timeout=timeout)
        return p.returncode, out, err
    except subprocess.TimeoutExpired:
        _kill_tree(p)
        out, err = p.communicate()
        return None, out or "", err or ""


#: (argv, timeout) -> (code | None, stdout, stderr). Tests replace it.
RUN = run_process


def _log_len() -> int:
    p = mr.maint_dir() / mr.LOG_NAME
    if not p.is_file():
        return 0
    return len([x for x in p.read_text(encoding="utf-8-sig").splitlines() if x.strip()])


def _new_receipts(since: int) -> list[dict]:
    return [e for e in mr.read_receipts()[since:]]


def _tail(text: str, n: int = 160) -> str:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    return (lines[-1] if lines else "")[:n]


def run_tool(tool: str, args: tuple[str, ...], timeout: int, rows: list[str], tools_dir: Path | None = None) -> dict:
    """Run one tool for `rows`. Every row in `rows` leaves here with a receipt from this run: the tool's own, or an
    UNKNOWN written here naming why the tool did not write one."""
    script = (tools_dir or TOOLS_DIR) / tool
    before = _log_len()
    started, why, code = True, "", None
    if not script.is_file():
        started, why = False, f"runner could not start: {tool} is not in tools/"
    else:
        try:
            code, out, err = RUN([sys.executable, str(script), *args], timeout)
            if code is None:
                why = f"{tool} {' '.join(args)} timed out after {timeout} s and was stopped"
            else:                           # a Python traceback exits 1, like FINDINGS: the missing receipt is the tell
                why = f"{tool} {' '.join(args)} exited {code} without a {{row}} receipt: " \
                      f"{((_tail(err) or _tail(out)) if code else (_tail(out) or _tail(err))) or 'no output'}"
        except CouldNotStart as e:
            started, why = False, f"runner could not start: {e}"
    try:
        new = _new_receipts(before)
    except ValueError as e:                 # the log itself is unreadable: say so for every row of this runner
        new, why = [], f"receipt log unreadable after {tool}: {e}"
    got = {e["row"]: e for e in new}
    out_rows = {}
    for r in rows:
        if r in got:
            out_rows[r] = got[r]
        else:
            out_rows[r] = mr.write_receipt(r, "UNKNOWN", why=why.replace("{row}", r), tool=TOOL)
    return {"started": started, "code": code, "receipts": out_rows, "also": [e for e in new if e["row"] not in rows]}


# ------------------------------------------------------------------ the run
def run(ids: list[str], rows_by_id: dict[str, dict], tools_dir: Path | None = None) -> dict:
    done: dict[str, dict] = {}
    could_not_start: list[str] = []
    for rid in ordered(ids):
        if rid in done:
            continue
        row = rows_by_id.get(rid)
        if rid in EVENT_RECEIPTS or (row and row.get("kind") == "event"):
            outcome, why = EVENT_RECEIPTS.get(rid, ("SKIP", "event row: no clock, no runner"))
            done[rid] = mr.write_receipt(rid, outcome, why=why, tool=TOOL)
            continue
        if rid not in RUNNERS:
            could_not_start.append(rid)
            done[rid] = mr.write_receipt(rid, "UNKNOWN", why=f"runner could not start: no runner wired for {rid}",
                                         tool=TOOL)
            continue
        tool, args, timeout = RUNNERS[rid]
        group = [r for r in ordered(ids) if r not in done and RUNNERS.get(r, (None, None))[:2] == (tool, args)]
        res = run_tool(tool, args, timeout, group, tools_dir)
        if not res["started"]:
            could_not_start += group
        done.update(res["receipts"])
        for e in res["also"]:                # the digest's C1/M5/H2/H3/HUMAN lines count for those rows this run
            if e["row"] in ids and e["row"] not in done:
                done[e["row"]] = e
    return {"receipts": [done[r] for r in ordered(ids) if r in done], "could_not_start": could_not_start}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="every row in the table, now")
    g.add_argument("--row", action="append", help="one row id (repeatable)")
    ap.add_argument("--date", help="the day whose due rows run (default today, local)")
    ap.add_argument("--list", action="store_true", help="print what would run; run nothing")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        rows = load_table()
    except (OSError, ValueError, KeyError) as e:
        print(f"UNKNOWN: cannot read {ROWS_FILE.name}: {e}")
        return 2
    by_id = {r["id"]: r for r in rows}
    if a.all:
        ids = [r["id"] for r in rows]
    elif a.row:
        bad = [r for r in a.row if r not in by_id]
        if bad:
            print(f"REFUSED: not a calendar row: {', '.join(bad)}")
            return 2
        ids = list(dict.fromkeys(a.row))
    else:
        day = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
        ids = due_rows(rows, day)
    if a.list:
        print(" ".join(ordered(ids)))
        return 0
    res = run(ids, by_id)
    for e in res["receipts"]:
        print(json.dumps(e, ensure_ascii=False))
    print(f"maint_run: {len(res['receipts'])} receipt(s) for {len(ids)} row(s)"
          + (f"; runner could not start for {', '.join(res['could_not_start'])}" if res["could_not_start"] else ""))
    return 2 if res["could_not_start"] or len(res["receipts"]) < len(ids) else 0


if __name__ == "__main__":
    sys.exit(main())
