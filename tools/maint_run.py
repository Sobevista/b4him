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
    py tools/maint_run.py --patch-proof <tree>   E1: M1 + M1b + W1(a) + M2 on a patched tree, one proof file

WHEN A ROW IS DUE (the calendar's Days paragraph, as tools/maint_rows.json carries it): daily rows every day; weekly
rows on Monday; monthly rows on the first Monday of the month; quarterly, 6-monthly and annual rows on the first
Monday of their months (the table's `months`, [ASSUMED] in maint_rows_build.py). Event rows (E1, E2) are never due
on the clock; --all and --row give them a SKIP receipt saying why. E3, the standards watch, polls its feeds weekly
(tools/standards_watch.py), so the table makes it a weekly row. A3 (domain registration, "60 days before renewal")
is polled every Monday too: its due date is the registration's expiry minus 60 days, which only RDAP knows
(tools/maint_human.py a3).

ORDER. Every other row first, in table order; then the watcher's own rows (W2 digest, M5/H2/H3 checks, the HUMAN
reminders, Q6); then D1, D2 and D3 last, so D2's overdue list and D3's heartbeat reflect the whole run. It must run
after D1's 10:30 cutoff: `py tools/maint_schedule.py` PRINTS the 10:35 daily schtasks line (nothing registers it until
Daniel pastes it), and D2 alarms while that task is missing or has not run for 26 hours.

ISOLATION. Each runner is its own process with a timeout. A row's outcome is taken ONLY from a receipt written by
THAT runner in THIS run (a log line after the run started, stamped at or after its start, whose tool is the runner's
script); an older line never stands in. A runner that crashes, times out or exits without such a receipt gets
`UNKNOWN <why>` written here; the run goes on. A non-zero exit that its receipts do not explain (exit 1 with no
FINDINGS, exit 2 with no UNKNOWN/SKIP, any other code, or a timeout) turns that runner's PASS or SKIP into UNKNOWN: a
partial run never reads as a pass. One runner may write several rows (linkcheck.py writes W1 and W1b; the digest writes
M5/H2/H3 when it has something to say); a row already receipted earlier in this run is not run a second time.

E1, THE PATCH PROOF. The patch line should call `py tools/maint_run.py --patch-proof <worktree of the patch>` before a
template / nav / CSS patch is offered, attach the printed `.maint/proofs/<date>_<sha>/patch_proof.json` to the
stage-2 record, and offer only on exit 0 (PASS) or after the FINDINGS are reviewed. The scanners' own receipts for the
patched tree go under that proof's folder, never into the calendar's log; only the E1 receipt does. tools/approvals.py
is NOT changed here: enforcement there is owed, and an E1 finding says so until it lands.

Exit 0 every runner ran cleanly and every row has its own receipt · 2 any runner failed: it could not start, crashed,
timed out, exited without its row's receipt, or exited non-zero in a way its receipts do not explain (the row gets
UNKNOWN either way). FINDINGS and UNKNOWN written by a tool that ran cleanly are in the receipts, not in the exit
code: D2 and the W2 digest are where they alarm.

RUN RECORDS (the harness counter's spec, delivered.py @ c06bb63e). Every run of this runner writes, in the same log,
a run_start line as its FIRST write (seconds after launch, before any tool runs) and a run_end line as its LAST, in a
finally block so a crash still closes the run; neither has a "row" key:
    {"at", "kind": "run_start", "run_id": <uuid4, new per run>, "runner": "tools/maint_run.py",
     "pid": <the process Task Scheduler created>, "proc_started": <that process's creation time, GetProcessTimes>,
     "trigger": "scheduled"|"manual"}
pid is this process, unless the py launcher (py.exe) started it, in which case it is the launcher, which is what
Task Scheduler created (its event 129 ProcessID). tools/maint_schedule.py prints a /TR that runs python.exe itself, so
on the scheduled path pid and proc_started are this process's own.
    {"at", "kind": "run_end", "run_id", "runner": "tools/maint_run.py", "exit": <the runner's exit code, int>,
     "rows_failed": [<row ids whose runner failed this run>]}
A crash of the runner itself records exit 1 and the rows that had failed before it.
The run_id goes to every child tool as MAINT_RUN_ID, so each receipt of the run carries it (tools/maint_receipt.py);
a tool run by hand writes run_id null. trigger is "scheduled" only when MAINT_TRIGGER=scheduled, which only the
scheduled task's action sets: its /TR passes `--scheduled` (tools/maint_schedule.py), which sets MAINT_TRIGGER for
the run. schtasks /TR cannot set an environment variable, and a `cmd /c set ...&&` wrapper pasted into cmd.exe would
split on the `&&` (cmd does not honour \\" inside the quoted /TR), so the flag is the safe carrier. A person can type
--scheduled by hand; this marks intent, it does not authenticate.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import subprocess
import sys
import uuid
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
    "H1": ("maint_human.py", ("h1",), 20 * MIN),        # screenshots beside the D9 reference, then the reminder
    "A1": ("maint_human.py", ("a1",), 5 * MIN),         # the WCAG-EM evidence pack, then the reminder
    "A3": ("maint_human.py", ("a3",), 2 * MIN),         # RDAP: expiry and status, alarm 60 days ahead
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
    "E1": ("SKIP", "event row: each template/nav/CSS patch runs `maint_run.py --patch-proof <tree>` (M1 + M1b + W1(a) "
                   "+ M2 on the patched tree) before the tap; a calendar run is not that event"),
    "E2": ("SKIP", "event row: each release's --verify-live outcome is judged by D1 (a release line that is not "
                   "PUBLISHED or SKIP, PUSHED-UNVERIFIED included, is a D1 finding)"),
}


#: Rows polled every Monday whatever their table cadence (see the docstring).
WEEKLY_POLL = {"A3"}
#: E1's four checks, in the calendar's order: (row, tool, args before the tree, args after, timeout).
PROOF_STEPS = (("M1", "maint_quality.py", ("a11y", "--root"), (), 2 * HOUR),
               ("M1b", "maint_quality.py", ("contrast", "--root"), (), HOUR),
               ("W1", "linkcheck.py", ("--repo",), ("--internal-only",), HOUR),
               ("M2", "maint_quality.py", ("perf", "--root"), (), 2 * HOUR))
OWED = "E1 enforcement owed in tools/approvals.py"


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
    if row.get("id") in WEEKLY_POLL and day.weekday() == 0:
        return True
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
    """How many receipts the log holds now (run markers are not receipts)."""
    try:
        return len(mr.read_receipts())
    except ValueError:
        return 0


def _new_receipts(since: int, start: dt.datetime, tool: str) -> list[dict]:
    """Receipts of THIS run of THIS tool: after the log position the run began at, stamped at or after its start,
    written by the runner's own script (tools/<tool>), carrying this run's run_id (null outside a scheduled run)."""
    out, rid = [], mr.run_id()
    for e in mr.read_receipts()[since:]:
        try:
            t = dt.datetime.fromisoformat(str(e.get("at")))
        except ValueError:
            continue
        if t >= start and Path(str(e.get("tool") or "")).name == tool and e.get("run_id") == rid:
            out.append(e)
    return out


EXPLAINS = {1: {"FINDINGS"}, 2: {"UNKNOWN", "SKIP"}}


def _tail(text: str, n: int = 160) -> str:
    lines = [x.strip() for x in (text or "").splitlines() if x.strip()]
    return (lines[-1] if lines else "")[:n]


def run_tool(tool: str, args: tuple[str, ...], timeout: int, rows: list[str], tools_dir: Path | None = None) -> dict:
    """Run one tool for `rows`. Every row in `rows` leaves here with a receipt from this run: the tool's own, or an
    UNKNOWN written here naming why the tool did not write one."""
    script = (tools_dir or TOOLS_DIR) / tool
    before = _log_len()
    start = mr.now_utc().replace(microsecond=0)
    started, why, code, tail = True, "", None, ""
    if not script.is_file():
        started, why = False, f"runner could not start: {tool} is not in tools/"
    else:
        try:
            code, out, err = RUN([sys.executable, str(script), *args], timeout)
            tail = ((_tail(err) or _tail(out)) if code else (_tail(out) or _tail(err))) or "no output"
            if code is None:
                why = f"{tool} {' '.join(args)} timed out after {timeout} s and was stopped"
            else:                           # a Python traceback exits 1, like FINDINGS: the missing receipt is the tell
                why = f"{tool} {' '.join(args)} exited {code} without a {{row}} receipt: " \
                      f"{((_tail(err) or _tail(out)) if code else (_tail(out) or _tail(err))) or 'no output'}"
        except CouldNotStart as e:
            started, why = False, f"runner could not start: {e}"
    try:
        new = _new_receipts(before, start, tool)
    except ValueError as e:                 # the log itself is unreadable: say so for every row of this runner
        new, why = [], f"receipt log unreadable after {tool}: {e}"
    got = {e["row"]: e for e in new}        # the last line per row wins (W3's per-page lines are row W3.page)
    outs = {e["outcome"] for e in new}
    unexplained = started and code != 0 and (code not in EXPLAINS or not (outs & EXPLAINS[code]))
    out_rows = {}
    failed = (not started or code is None or code not in (0, 1, 2) or unexplained
              or any(r not in got for r in rows))
    for r in rows:
        if r not in got:
            out_rows[r] = mr.write_receipt(r, "UNKNOWN", why=why.replace("{row}", r), tool=TOOL)
        elif unexplained and got[r]["outcome"] in ("PASS", "SKIP"):
            how = "timed out" if code is None else f"exited {code}"
            out_rows[r] = mr.write_receipt(r, "UNKNOWN", why=f"{tool} {' '.join(args)} {how} after writing {r} "
                                           f"{got[r]['outcome']}: a non-zero exit is not a pass ({tail})", tool=TOOL)
        else:
            out_rows[r] = got[r]
    return {"started": started, "code": code, "failed": failed, "receipts": out_rows,
            "also": [e for e in new if e["row"] not in rows]}


# ------------------------------------------------------------------ E1: the patch proof
def owed_finding() -> None:
    """One standing finding until approvals.py enforces the proof. Written once, not every run."""
    try:
        if any(f.get("row") == "E1" and f.get("subject") == OWED for f in mr.read_findings()):
            return
    except ValueError:
        pass
    mr.write_finding("E1", "S2", OWED, "the patch line can offer a template/nav/CSS patch without running "
                     "`maint_run.py --patch-proof <tree>`; the calendar says it cannot. approvals.py was not changed "
                     "by the maintenance build: wiring the proof into the offer is owed",
                     "Release Manager (approvals.py) + Site Maintainer")


def patch_proof(tree: Path) -> dict:
    """E1: run M1, M1b, W1(a) and M2 on `tree`, write one proof file, write the E1 receipt."""
    tree = Path(tree).resolve()
    now = mr.now_utc()
    p = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, encoding="utf-8",
                       errors="replace")
    if not tree.is_dir() or p.returncode:
        owed_finding()
        return mr.write_receipt("E1", "UNKNOWN", why=f"patch proof: {tree.name} is not a git checkout", tool=TOOL)
    head = p.stdout.strip()
    pdir = mr.maint_dir() / "proofs" / f"{now:%Y-%m-%d}_{head[:12]}"
    sub = pdir / "maint"
    sub.mkdir(parents=True, exist_ok=True)
    steps, saved = [], os.environ.get("MAINT_DIR")
    for row, tool, pre, post, timeout in PROOF_STEPS:
        os.environ["MAINT_DIR"] = str(sub)       # the patched tree's receipts stay in the proof, not the calendar
        try:
            res = run_tool(tool, (*pre, str(tree), *post), timeout, [row])
        finally:
            if saved is None:
                os.environ.pop("MAINT_DIR", None)
            else:
                os.environ["MAINT_DIR"] = saved
        steps.append({"row": row, "tool": tool, "exit": res["code"], "receipt": res["receipts"][row]})
    outs = [s["receipt"]["outcome"] for s in steps]
    if "UNKNOWN" in outs:
        outcome, n = "UNKNOWN", None
    elif "FINDINGS" in outs:
        outcome, n = "FINDINGS", sum(s["receipt"]["n"] or 0 for s in steps if s["receipt"]["outcome"] == "FINDINGS")
    else:
        outcome, n = "PASS", 0
    proof = pdir / "patch_proof.json"
    proof.write_text(json.dumps({"row": "E1", "tree": tree.name, "head": head, "at": now.isoformat(timespec="seconds"),
                                 "outcome": outcome, "steps": steps,
                                 "attach": "attach this file to the patch's stage-2 record; offer only on PASS or "
                                           "after the FINDINGS are reviewed"}, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8", newline="\n")
    owed_finding()
    why = "; ".join(f"{s['row']} {s['receipt']['outcome']}" + (f" {s['receipt']['n']}" if s['receipt']['outcome'] ==
                    "FINDINGS" else "") for s in steps) + f" on {head[:12]}"
    if outcome == "UNKNOWN":
        why = "patch proof incomplete: " + why
    return mr.write_receipt("E1", outcome, n=n, why=why,
                            evidence=".maint/" + proof.relative_to(mr.maint_dir()).as_posix(), tool=TOOL)


# ------------------------------------------------------------------ the run
def run(ids: list[str], rows_by_id: dict[str, dict], tools_dir: Path | None = None) -> dict:
    done: dict[str, dict] = {}
    could_not_start: list[str] = []
    failed: list[str] = []
    for rid in ordered(ids):
        if rid in done:
            continue
        row = rows_by_id.get(rid)
        if rid in EVENT_RECEIPTS or (row and row.get("kind") == "event"):
            outcome, why = EVENT_RECEIPTS.get(rid, ("SKIP", "event row: no clock, no runner"))
            done[rid] = mr.write_receipt(rid, outcome, why=why, tool=TOOL)
            if rid == "E1":
                owed_finding()
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
        elif res["failed"]:
            failed += group
        done.update(res["receipts"])
        for e in res["also"]:                # the digest's C1/M5/H2/H3/HUMAN lines count for those rows this run
            if e["row"] in ids and e["row"] not in done:
                done[e["row"]] = e
    return {"receipts": [done[r] for r in ordered(ids) if r in done], "could_not_start": could_not_start,
            "failed": failed}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--all", action="store_true", help="every row in the table, now")
    g.add_argument("--row", action="append", help="one row id (repeatable)")
    g.add_argument("--patch-proof", metavar="TREE", help="E1: M1 + M1b + W1(a) + M2 on a patched tree")
    ap.add_argument("--date", help="the day whose due rows run (default today, local)")
    ap.add_argument("--list", action="store_true", help="print what would run; run nothing")
    ap.add_argument("--scheduled", action="store_true", help="set only by the scheduled task's /TR: trigger=scheduled")
    a = ap.parse_args(argv)
    if a.scheduled:
        os.environ[TRIGGER_ENV] = "scheduled"
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.patch_proof:
        def proof(rows_failed: list) -> int:
            r = patch_proof(Path(a.patch_proof))
            if r["outcome"] == "UNKNOWN":      # a proof step's runner failed, or the tree was not a checkout
                rows_failed.append("E1")
            print(json.dumps(r, ensure_ascii=False))
            return {"PASS": 0, "FINDINGS": 1, "UNKNOWN": 2}[r["outcome"]]
        return in_run(proof)
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
    def body(rows_failed: list) -> int:
        res = run(ids, by_id)
        rows_failed += res["could_not_start"] + res["failed"]
        for e in res["receipts"]:
            print(json.dumps(e, ensure_ascii=False))
        print(f"maint_run: {len(res['receipts'])} receipt(s) for {len(ids)} row(s), run_id {mr.run_id()}"
              + (f"; runner could not start for {', '.join(res['could_not_start'])}" if res["could_not_start"] else "")
              + (f"; runner failed for {', '.join(res['failed'])}" if res["failed"] else ""))
        return 2 if res["could_not_start"] or res["failed"] or len(res["receipts"]) < len(ids) else 0
    return in_run(body)


RUNNER = "tools/maint_run.py"
TRIGGER_ENV = "MAINT_TRIGGER"        # set to "scheduled" only by the scheduled task's action (tools/maint_schedule.py)


LAUNCHERS = {"py.exe", "pyw.exe"}        # the Windows py launcher: Task Scheduler's process when /TR runs py.exe
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000


def process_info(pid: int | None = None) -> tuple[str | None, str | None]:
    """(image path, creation time ISO-8601 UTC) of `pid`, or of this process when None. (None, None) where the OS
    will not say (not Windows, the process is gone, access denied)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcess.restype = wintypes.HANDLE
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        h = k32.GetCurrentProcess() if pid is None else k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return None, None
        try:
            buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            image = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
                return image, None
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime      # 100 ns since 1601-01-01 UTC
            t = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=ticks // 10)
            return image, t.isoformat(timespec="seconds")
        finally:
            if pid is not None:
                k32.CloseHandle(h)
    except (AttributeError, OSError, ImportError):
        return None, None


def choose_launch(own: tuple[int, str | None, str | None],
                  parent: tuple[int, str | None, str | None]) -> dict:
    """The process Task Scheduler created (its event 129 ProcessID): this one, unless this one was started by the py
    launcher, in which case the launcher is what Task Scheduler created. Each tuple is (pid, image, created)."""
    pid, image, created = parent if parent[1] and Path(parent[1]).name.lower() in LAUNCHERS else own
    return {"pid": pid, "proc_started": created}


def launched_process() -> dict:
    own = (os.getpid(), *process_info())
    ppid = os.getppid()
    return choose_launch(own, (ppid, *process_info(ppid)))


def proc_started() -> str | None:
    """The creation time of the process Task Scheduler created (see launched_process)."""
    return launched_process()["proc_started"]


def trigger() -> str:
    return "scheduled" if os.environ.get(TRIGGER_ENV) == "scheduled" else "manual"


def in_run(body) -> int:
    """One run of the runner: run_start is its first write, BEFORE any tool runs; MAINT_RUN_ID is in the environment
    so every receipt written during the run (here or in a child tool) carries this run_id; run_end is its last write,
    in a finally block, so a crash still closes the run (and the process exits non-zero)."""
    rid = str(uuid.uuid4())
    saved = os.environ.get(mr.RUN_ENV)
    launch = launched_process()
    mr.write_run_marker("run_start", rid, runner=RUNNER, pid=launch["pid"], proc_started=launch["proc_started"],
                        trigger=trigger())
    os.environ[mr.RUN_ENV] = rid
    rows_failed: list[str] = []                # body() fills it: the rows whose runner failed this run
    code = CRASH_EXIT
    try:
        code = int(body(rows_failed))
        return code
    finally:
        if saved is None:
            os.environ.pop(mr.RUN_ENV, None)
        else:
            os.environ[mr.RUN_ENV] = saved
        mr.write_run_marker("run_end", rid, runner=RUNNER, exit=code, rows_failed=sorted(set(rows_failed)))


CRASH_EXIT = 1                                 # the exit code recorded when the runner itself raised


def in_process(module, *pre):
    """A RUN (see RUN above) that runs an already-imported tool `module`'s main(pre + args) in THIS process, stdout and
    stderr captured, its exit code returned as a child's would be. For a caller that has the tool imported (the row
    cites). It runs only when the script maint_run asked for resolves to the very file `module` was loaded from: any
    other module, even one declaring the same TOOL, is CouldNotStart (the runner's UNKNOWN), never a run."""
    import contextlib
    import io

    def run_here(argv: list[str], timeout: int) -> tuple[int | None, str, str]:
        want = Path(argv[1]).resolve()
        got = getattr(module, "__file__", None)
        if not got or Path(got).resolve() != want:
            raise CouldNotStart(f"{want.name}: the module handed in is not this script ({got or 'it has no file'})")
        out, err = io.StringIO(), io.StringIO()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = module.main([*pre, *argv[2:]])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001 - a tool crash is the runner's to judge, as in a real child process
            return 1, out.getvalue(), f"{type(e).__name__}: {e}"
        return code, out.getvalue(), err.getvalue()
    return run_here


if __name__ == "__main__":
    sys.exit(main())
