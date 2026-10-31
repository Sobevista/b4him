#!/usr/bin/env python3
"""
maint_watch.py: the maintenance calendar's own watcher (rows D1, D2, D3, W2, Q6, M5, H2, H3, and the HUMAN reminders
H1, A1, A3). Every run writes receipts through tools/maint_receipt.py into the git-ignored `.maint/`.

    py tools/maint_watch.py daily   [--date D] [--release-log PATH]   D1, then D2, then D3 (daily, after 10:30 local)
    py tools/maint_watch.py digest                                     W2 (weekly, Monday) + M5/H2/H3 + HUMAN reminders
    py tools/maint_watch.py drill   [--date D]                         Q6: withhold one heartbeat on purpose
    py tools/maint_watch.py confirm <at|never>                         Q6: the alarm arrived at <at> (or never)
    py tools/maint_watch.py check   M5|H2|H3                           one receipts-only check on its own
    py tools/maint_watch.py human   H1|A1|A3 <E-number>               close a HUMAN row with Daniel's ledger id

Exit 0 every receipt PASS/SKIP · 1 a FINDINGS (or a refused command) · 2 an UNKNOWN and no FINDINGS.

D1. Today's release_log.jsonl `apply` line must exist by 08:30 + 2 h local. A non-release day's SKIP is present.
    No line by 10:30 is FINDINGS (MISSING). A line whose outcome is not PUBLISHED/SKIP (FAIL, PUSHED-UNVERIFIED,
    COMMITTED, anything unknown) is FINDINGS too: present, but not a release that worked. Before 10:30 with no line:
    UNKNOWN, never PASS. The log reader is adapted from tools/release_watch.py on build/release-watch @ fbe8f58.
D2. Every row in tools/maint_rows.json (generated from the calendar by tools/maint_rows_build.py) against its
    cadence + grace. A row with no receipt ever is overdue from its first scheduled date on/after the epoch. HUMAN
    rows count only a PASS (Daniel's E-number) as done. Overdue rows -> FINDINGS n listing them, one finding each.
    Event rows (E1-E3) have no clock and are not scheduled. D2 does not judge itself (this run is its receipt).
D3. GET MAINT_HEARTBEAT_URL (Healthchecks.io), with `/fail` appended when D1 or D2 is not PASS. Success is HTTP 2xx
    whose body is not "OK (not found)" / "OK (rate limited)": the docs say a UUID ping answers 200 with those bodies
    when the check does not exist or the ping was dropped. No env var -> UNKNOWN no MAINT_HEARTBEAT_URL. The URL is
    never printed or logged.
M5. The Editor's cadence-and-runway review. Its receipt is the production board's own run: the
    "*Generated <date> by `tools/production_board.py`" line at the top of PRODUCTION_BOARD.md. The auditor only
    checks that line is no older than the monthly cadence + grace; it never runs the board.
H2. The Independent Reviewer's publication-gate review note: `.maint/notes/H2_<YYYY-MM-DD>[_*].md`.
H3. The 6-monthly re-read of the calendar and PRODUCTION_PLAN: `.maint/notes/H3_<YYYY-MM-DD>[_*].md` (an amendment
    proposal or "no change"). When due, the digest carries a reminder and the evidence-pack paths.
HUMAN (H1, A1, A3). When the row falls due, the digest gets a DUE FOR DANIEL section and the row gets one receipt
    `UNKNOWN awaiting Daniel ...` saying whether the reminder fired on time. `human <row> <E-number>` closes it (PASS).
"""
from __future__ import annotations

import argparse
import calendar as _cal
import datetime as dt
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import maint_receipt as mr  # noqa: E402

REPO = HERE.parent
ROWS_FILE = HERE / "maint_rows.json"
TOOL = "maint_watch.py"
#: None = the machine's local zone (DST-aware). Tests pin a fixed zone.
LOCAL_TZ = None
RELEASE_RUN_AT = dt.time(8, 30)
RELEASE_CUTOFF = dt.time(10, 30)          # 08:30 + 2 h (calendar row D1)
SLACK = dt.timedelta(minutes=5)
OK_OUTCOMES = {"PUBLISHED", "SKIP"}
HEARTBEAT_ENV = "MAINT_HEARTBEAT_URL"
HUMAN_ROWS = ("H1", "A1", "A3")
CHECK_ROWS = ("M5", "H2", "H3")
E_NUMBER = re.compile(r"^E\d{4,6}$")
DAY = dt.timedelta(days=1)


class Unknown(Exception):
    """Could not read or could not judge. Never rounds to PASS."""


# ------------------------------------------------------------------ time
def local(d: dt.datetime) -> dt.datetime:
    return d.astimezone(LOCAL_TZ) if LOCAL_TZ else d.astimezone()


def now_local() -> dt.datetime:
    return local(mr.now_utc())


def parse_at(s) -> dt.datetime:
    d = dt.datetime.fromisoformat(str(s))
    if d.tzinfo is None:
        raise ValueError(f"time with no zone: {s!r}")
    return local(d)


def midnight(day: dt.date, tz) -> dt.datetime:
    return dt.datetime.combine(day, dt.time(0, 0), tzinfo=tz)


# ------------------------------------------------------------------ the row table and its clock
def load_rows(path: Path | None = None) -> dict:
    p = path or ROWS_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        data["rows"] = {r["id"]: r for r in data["rows"]}
        data["epoch_date"] = dt.date.fromisoformat(data["epoch"])
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise Unknown(f"cannot read the row table {p.name}: {e}") from e
    return data


def first_monday(y: int, m: int) -> dt.date:
    d = dt.date(y, m, 1)
    return d + dt.timedelta(days=(0 - d.weekday()) % 7)


def occ_on_or_after(row: dict, t: dt.datetime) -> dt.datetime:
    """The first scheduled moment of `row` at or after t (local). Daily rows at their HH:MM; the rest at midnight of
    their day (the whole day is theirs)."""
    k, tz = row["kind"], t.tzinfo
    if k == "daily":
        h, m = map(int, row.get("at", "10:30").split(":"))
        o = dt.datetime.combine(t.date(), dt.time(h, m), tzinfo=tz)
        return o if o >= t else o + DAY
    day = t.date() if t == midnight(t.date(), tz) else t.date() + DAY
    if k == "weekly":
        return midnight(day + dt.timedelta(days=(0 - day.weekday()) % 7), tz)
    months = list(range(1, 13)) if k == "monthly" else row.get("months")
    if k not in ("monthly", "quarterly", "semiannual", "annual") or not months:
        raise Unknown(f"row {row['id']}: kind {k!r} has no clock")
    y, m = day.year, day.month
    for _ in range(40):
        if m in months:
            fm = first_monday(y, m)
            if fm >= day:
                return midnight(fm, tz)
        m += 1
        if m == 13:
            y, m = y + 1, 1
    raise Unknown(f"row {row['id']}: no occurrence found")


def due_from(row: dict, last: dt.datetime | None, epoch: dt.date, tz) -> dt.datetime:
    """The occurrence the row owes next: the first one after the day of its last receipt, or the first on/after the
    epoch when it has none."""
    start = midnight(epoch, tz) if last is None else midnight(last.date() + DAY, tz)
    return occ_on_or_after(row, start)


def deadline_of(row: dict, due: dt.datetime) -> dt.datetime:
    g = dt.timedelta(hours=row["grace_hours"])
    return due + g if row["kind"] == "daily" else due + DAY + g


def receipts_of(receipts: list[dict], rid: str, outcomes=None) -> list[tuple[dt.datetime, dict]]:
    out = []
    for e in receipts:
        if e.get("row") == rid and (outcomes is None or e.get("outcome") in outcomes):
            out.append((parse_at(e["at"]), e))
    return sorted(out, key=lambda x: x[0])


def fmt(d: dt.datetime | None) -> str:
    return "never" if d is None else f"{d:%Y-%m-%d %H:%M}"


# ------------------------------------------------------------------ D1: the release log (adapted from release_watch.py)
def load_release_log(path: Path) -> list[dict]:
    """From tools/release_watch.py load_log() (build/release-watch @ fbe8f58): a missing or unreadable line is
    UNKNOWN, because a line that cannot be read could be today's."""
    if not path.is_file():
        raise Unknown(f"no release log at {path.name}: no run has ever logged here, or this is the wrong checkout")
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise Unknown(f"cannot read the release log: {e}") from e
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except json.JSONDecodeError as ex:
            raise Unknown(f"release log line {n} is not JSON ({ex})") from ex
        if not isinstance(e, dict):
            raise Unknown(f"release log line {n} is not a JSON object")
        out.append(e)
    return out


def _stamp(e: dict) -> dt.datetime:
    try:
        return parse_at(e.get("at"))
    except (ValueError, TypeError) as ex:
        raise Unknown(f"a release line dated {e.get('date')} has no readable zoned time: at={e.get('at')!r}") from ex


def judge_release_day(entries: list[dict], day: dt.date, now: dt.datetime) -> dict:
    """Pure. Adapted from release_watch.judge_day() (fbe8f58) with D1's cutoff of 08:30 + 2 h."""
    tz = now.tzinfo
    start = dt.datetime.combine(day, RELEASE_RUN_AT, tzinfo=tz) - SLACK
    end = dt.datetime.combine(day, RELEASE_CUTOFF, tzinfo=tz)
    if now.date() < day:
        raise Unknown(f"{day} is in the future")
    problems, scheduled, other = [], [], []
    for e in entries:
        if e.get("date") != day.isoformat() or e.get("mode") != "apply":
            continue
        t = _stamp(e)
        d = f"{t:%H:%M} {e.get('outcome')} {e.get('lane') or 'content'}" + (f" {e['piece']}" if e.get("piece") else "")
        (scheduled if start <= t <= end else other).append(d)
        if e.get("outcome") not in OK_OUTCOMES:
            problems.append(d)
        for p in e.get("patch_outcomes") or []:
            if p.get("outcome") not in OK_OUTCOMES:
                problems.append(f"{t:%H:%M} patch {p.get('piece')} {p.get('outcome')}")
    pending = False
    if not scheduled:
        if now < end:
            pending = True
        else:
            problems.insert(0, f"MISSING: no line from the 08:30 run by 10:30"
                               + (f" (later: {'; '.join(other)})" if other else ""))
    return {"problems": list(dict.fromkeys(problems)), "scheduled": scheduled, "other": other, "pending": pending}


def run_d1(release_log: Path, day: dt.date, now: dt.datetime) -> dict:
    try:
        v = judge_release_day(load_release_log(release_log), day, now)
    except Unknown as e:
        return mr.write_receipt("D1", "UNKNOWN", why=str(e), tool=TOOL)
    if v["problems"]:
        for p in v["problems"]:
            mr.write_finding("D1", "S2", f"release run {day}: {p[:80]}", p, "Release Manager")
        return mr.write_receipt("D1", "FINDINGS", n=len(v["problems"]), why=f"{day}: " + "; ".join(v["problems"]),
                                tool=TOOL)
    if v["pending"]:
        return mr.write_receipt("D1", "UNKNOWN", why=f"{day}: no release line yet and 10:30 has not passed", tool=TOOL)
    return mr.write_receipt("D1", "PASS", why=f"{day}: " + "; ".join(v["scheduled"]), tool=TOOL)


# ------------------------------------------------------------------ D2: the calendar watch
def overdue_rows(table: dict, receipts: list[dict], now: dt.datetime, skip=("D2",)) -> tuple[list, list]:
    over, events = [], []
    for rid, row in table["rows"].items():
        if row["kind"] == "event":
            events.append(rid)
            continue
        if rid in skip:
            continue
        mine = receipts_of(receipts, rid, {"PASS"} if row.get("check") == "human" else None)
        last = mine[-1][0] if mine else None
        due = due_from(row, last, table["epoch_date"], now.tzinfo)
        dl = deadline_of(row, due)
        if now > dl:
            over.append({"row": rid, "last": last, "due": due, "deadline": dl, "route_to": row.get("route_to", "")})
    return over, events


def run_d2(now: dt.datetime, rows_file: Path | None = None) -> dict:
    try:
        table = load_rows(rows_file)
        over, events = overdue_rows(table, mr.read_receipts(), now)
    except (Unknown, ValueError, KeyError) as e:
        return mr.write_receipt("D2", "UNKNOWN", why=f"cannot judge the calendar: {e}", tool=TOOL)
    note = f" (event rows not on the clock: {', '.join(events)})" if events else ""
    if not over:
        return mr.write_receipt("D2", "PASS", why=f"{len(table['rows']) - len(events) - 1} rows within cadence + grace"
                                + note, tool=TOOL)
    parts = []
    for o in over:
        what = (f"last receipt {fmt(o['last'])}" if o["last"] else "no receipt ever") + \
               f", due {o['due']:%Y-%m-%d}, overdue since {fmt(o['deadline'])}"
        parts.append(f"{o['row']} ({what})")
        mr.write_finding("D2", "S2", f"OVERDUE {o['row']}", f"MAINTENANCE OVERDUE: row {o['row']}: {what}",
                         f"Daniel; owning seat: {o['route_to']}")
    return mr.write_receipt("D2", "FINDINGS", n=len(over), why="overdue: " + "; ".join(parts) + note, tool=TOOL)


# ------------------------------------------------------------------ D3: the out-of-band heartbeat
def _http_get(url: str, timeout: float = 15.0) -> tuple[int, str]:
    req = urllib.request.Request(url, method="GET", headers={"User-Agent": "b4him-maint-watch"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(200).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, (e.read(200) or b"").decode("utf-8", "replace")


#: (url) -> (status, body). Network errors raise. Tests replace it.
HTTP_GET = _http_get


def fail_url(url: str) -> str:
    """Healthchecks.io: the failure signal is the ping URL with `/fail` appended (https://hc-ping.com/<uuid>/fail)."""
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit(p._replace(path=p.path.rstrip("/") + "/fail"))


def _scrub(text: str, url: str) -> str:
    for s in {url, fail_url(url), urllib.parse.urlsplit(url).path.strip("/")}:
        if s:
            text = text.replace(s, "<MAINT_HEARTBEAT_URL>")
    return text


def run_d3(fail: bool, why_fail: str, now: dt.datetime) -> dict:
    drill = armed_drill()
    if drill and drill["skip_date"] == now.date().isoformat():
        return mr.write_receipt("D3", "SKIP", why=f"drill (Q6): the {drill['skip_date']} heartbeat is withheld on "
                                "purpose; the external alarm should fire", tool=TOOL)
    url = os.environ.get(HEARTBEAT_ENV, "").strip()
    if not url:
        return mr.write_receipt("D3", "UNKNOWN", why=f"no {HEARTBEAT_ENV}", tool=TOOL)
    signal = "fail" if fail else "success"
    try:
        status, body = HTTP_GET(fail_url(url) if fail else url)
    except Exception as e:  # noqa: BLE001 - any failure to reach the service is UNKNOWN, with its reason
        return mr.write_receipt("D3", "UNKNOWN", why=_scrub(f"heartbeat ({signal}) not delivered: "
                                                            f"{type(e).__name__}: {e}", url), tool=TOOL)
    body = (body or "").strip()
    if not 200 <= status < 300:
        mr.write_finding("D3", "S2", f"heartbeat refused HTTP {status}", _scrub(body[:120], url), "Daniel")
        return mr.write_receipt("D3", "FINDINGS", n=1, why=_scrub(f"heartbeat ({signal}) HTTP {status} {body[:80]}",
                                                                   url), tool=TOOL)
    if body.startswith("OK (") and body != "OK":
        mr.write_finding("D3", "S2", f"heartbeat not recorded: {body[:40]}",
                         "Healthchecks answered 200 but did not record the ping", "Daniel")
        return mr.write_receipt("D3", "FINDINGS", n=1, why=f"heartbeat ({signal}) HTTP {status} {body[:40]}: not "
                                "recorded by the service", tool=TOOL)
    return mr.write_receipt("D3", "PASS", why=f"heartbeat {signal} signal delivered, HTTP {status}"
                            + (f" ({why_fail})" if fail else ""), tool=TOOL)


def cmd_daily(a, now: dt.datetime) -> int:
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    rlog = Path(a.release_log) if a.release_log else REPO / "release_log.jsonl"
    d1 = run_d1(rlog, day, now)
    d2 = run_d2(now)
    bad = [f"{r['row']} {r['outcome']}" for r in (d1, d2) if r["outcome"] != "PASS"]
    d3 = run_d3(bool(bad), ", ".join(bad), now)
    return show([d1, d2, d3])


def show(receipts: list[dict]) -> int:
    for r in receipts:
        print(json.dumps(r, ensure_ascii=False))
    outs = {r["outcome"] for r in receipts}
    return 1 if "FINDINGS" in outs else 2 if "UNKNOWN" in outs else 0


# ------------------------------------------------------------------ receipts-only checks (M5, H2, H3)
BOARD_STAMP = re.compile(r"\*Generated (\d{4}-\d{2}-\d{2}) by `tools/production_board\.py`")


def board_date(repo: Path) -> dt.date:
    p = repo / "PRODUCTION_BOARD.md"
    try:
        head = p.read_text(encoding="utf-8")[:2000]
    except OSError as e:
        raise Unknown(f"cannot read PRODUCTION_BOARD.md: {e}") from e
    m = BOARD_STAMP.search(head)
    if not m:
        raise Unknown("PRODUCTION_BOARD.md carries no '*Generated <date> by `tools/production_board.py`' line")
    return dt.date.fromisoformat(m.group(1))


NOTE_RE = re.compile(r"^(?P<row>[A-Z]\d+)_(?P<date>\d{4}-\d{2}-\d{2})(?:_[^/\\]*)?\.md$")


def newest_note(rid: str) -> tuple[dt.date, str] | None:
    d = mr.maint_dir() / "notes"
    best = None
    if d.is_dir():
        for f in d.iterdir():
            m = NOTE_RE.match(f.name)
            if m and m["row"] == rid:
                key = (dt.date.fromisoformat(m["date"]), f.name)
                best = key if best is None or key > best else best
    return (best[0], f".maint/notes/{best[1]}") if best else None


def run_check(rid: str, now: dt.datetime, repo: Path | None = None, table: dict | None = None) -> dict:
    try:
        table = table or load_rows()
        row = table["rows"][rid]
        evidence = None
        if rid == "M5":
            last_day, what = board_date(repo or REPO), "board run"
        else:
            n = newest_note(rid)
            last_day, evidence = (n if n else (None, None))
            what = "review note" if rid == "H2" else "re-read note"
    except (Unknown, KeyError, ValueError) as e:
        return mr.write_receipt(rid, "UNKNOWN", why=f"cannot check: {e}", tool=TOOL)
    last = midnight(last_day, now.tzinfo) if last_day else None
    due = due_from(row, last, table["epoch_date"], now.tzinfo)
    dl = deadline_of(row, due)
    where = ("PRODUCTION_BOARD.md 'Generated' line" if rid == "M5" else f".maint/notes/{rid}_<date>.md")
    if now < due:
        if last_day is None:
            return mr.write_receipt(rid, "SKIP", why=f"not yet scheduled: first due {due:%Y-%m-%d} ({where})",
                                    tool=TOOL)
        return mr.write_receipt(rid, "PASS", why=f"{what} {last_day} found ({where}); next due {due:%Y-%m-%d}",
                                evidence=evidence, tool=TOOL)
    if now <= dl:
        return mr.write_receipt(rid, "UNKNOWN", why=f"awaiting the {what} due {due:%Y-%m-%d} (grace to {fmt(dl)}); "
                                f"last {last_day or 'never'} ({where})", evidence=evidence, tool=TOOL)
    mr.write_finding(rid, "S3", f"{rid} {what} overdue", f"due {due:%Y-%m-%d}, last {last_day or 'never'}, "
                     f"looked for {where}", row.get("route_to", ""))
    return mr.write_receipt(rid, "FINDINGS", n=1, why=f"{what} overdue: due {due:%Y-%m-%d}, last "
                            f"{last_day or 'never'} ({where})", evidence=evidence, tool=TOOL)


# ------------------------------------------------------------------ HUMAN rows
def human_status(rid: str, table: dict, receipts: list[dict], now: dt.datetime) -> dict:
    row = table["rows"][rid]
    closed = receipts_of(receipts, rid, {"PASS"})
    last = closed[-1][0] if closed else None
    due = due_from(row, last, table["epoch_date"], now.tzinfo)
    dl = deadline_of(row, due)
    fired = [t for t, e in receipts_of(receipts, rid, {"UNKNOWN"}) if t >= due]
    return {"row": row, "last": last, "last_e": closed[-1][1]["why"] if closed else None, "due": due,
            "deadline": dl, "is_due": now >= due, "overdue": now > dl, "fired": fired[0] if fired else None}


def fire_reminders(table: dict, now: dt.datetime) -> list[dict]:
    out = []
    for rid in HUMAN_ROWS:
        s = human_status(rid, table, mr.read_receipts(), now)
        if s["is_due"] and s["fired"] is None:
            late = (now.date() - s["due"].date()).days
            when = "on time" if late == 0 else f"late by {late} day(s)"
            out.append(mr.write_receipt(rid, "UNKNOWN", why=f"awaiting Daniel's ruling: reminder fired "
                                        f"{now:%Y-%m-%d} for due {s['due']:%Y-%m-%d} ({when}); close with "
                                        f"maint_watch.py human {rid} <E-number>", tool=TOOL))
    return out


def cmd_human(a, now: dt.datetime) -> int:
    rid, e = a.row.upper(), a.e_number.upper()
    if rid not in HUMAN_ROWS:
        print(f"REFUSED: {rid} is not a HUMAN row ({', '.join(HUMAN_ROWS)})")
        return 1
    if not E_NUMBER.match(e):
        print(f"REFUSED: {a.e_number!r} is not a ledger E-number (E followed by digits, e.g. E00571)")
        return 1
    return show([mr.write_receipt(rid, "PASS", why=f"closed by Daniel's ledger {e} (recorded here; the ledger itself "
                                  "is not read by this tool)", tool=TOOL)])


# ------------------------------------------------------------------ W2: the weekly digest
def _age(d: dt.datetime, now: dt.datetime) -> str:
    days = (now - d).days
    return f"{days} d" if days else f"{int((now - d).total_seconds() // 3600)} h"


def open_findings(receipts: list[dict], findings: list[dict]) -> list[dict]:
    """A row's open findings are the ones its latest run wrote (after its previous receipt, up to its latest)."""
    by_row: dict[str, list[dt.datetime]] = {}
    for e in receipts:
        by_row.setdefault(e["row"], []).append(parse_at(e["at"]))
    first_seen: dict[tuple, dt.datetime] = {}
    for f in findings:
        t = parse_at(f["at"])
        k = (f["row"], f["subject"])
        first_seen[k] = min(first_seen.get(k, t), t)
    out, seen = [], set()
    for f in findings:
        ts = sorted(by_row.get(f["row"], []))
        if not ts:
            continue
        lo = ts[-2] if len(ts) > 1 else None
        t = parse_at(f["at"])
        k = (f["row"], f["subject"])
        if t <= ts[-1] and (lo is None or t > lo) and k not in seen:
            seen.add(k)
            out.append({**f, "first_seen": first_seen[k]})
    return sorted(out, key=lambda x: x["first_seen"])


def unknown_streaks(receipts: list[dict]) -> list[tuple[str, dt.datetime, dict]]:
    by: dict[str, list[tuple[dt.datetime, dict]]] = {}
    for e in receipts:
        by.setdefault(e["row"], []).append((parse_at(e["at"]), e))
    out = []
    for rid, xs in by.items():
        xs.sort(key=lambda x: x[0])
        if xs[-1][1]["outcome"] != "UNKNOWN":
            continue
        i = len(xs) - 1
        while i > 0 and xs[i - 1][1]["outcome"] == "UNKNOWN":
            i -= 1
        out.append((rid, xs[i][0], xs[-1][1]))
    return sorted(out, key=lambda x: x[1])


def r_line(e: dict) -> str:
    o = e["outcome"] + (f" {e['n']}" if e["outcome"] == "FINDINGS" else "")
    return f"{e['at']} {e['row']} {o}" + (f": {e['why']}" if e["why"] else "")


def evidence_pack() -> list[str]:
    cal = os.environ.get("MAINT_CALENDAR_PATH")
    audits = sorted(p.name for p in (mr.maint_dir() / "audits").glob("*.md")) if (mr.maint_dir() / "audits").is_dir() \
        else []
    return [cal or "the maintenance-auditor seat's CALENDAR.md (set MAINT_CALENDAR_PATH to print its path here)",
            "PRODUCTION_PLAN.md section 5", "tools/maint_rows.json (the calendar as data)",
            ".maint/maintenance_log.jsonl", ".maint/maintenance_findings.jsonl",
            ".maint/audits/: " + (", ".join(audits[-26:]) if audits else "(none yet)")]


C1_READER = "headers_tls_check.py"


def c1_monitor_line(now: dt.datetime) -> dict:
    """The digest's C1 line. The uptime reader (`headers_tls_check.py uptime`) writes C1's receipt; the digest uses
    its newest one from the last 7 days. With none, the digest writes C1 UNKNOWN itself: never a silent PASS."""
    try:
        mine = [e for t, e in receipts_of(mr.read_receipts(), "C1")
                if e.get("tool") == C1_READER and t > now - dt.timedelta(days=7)]
    except ValueError:
        mine = []
    if mine:
        return mine[-1]
    return mr.write_receipt("C1", "UNKNOWN", why=f"no C1 reader receipt in the last 7 days: run `{C1_READER} "
                            "uptime` (needs UPTIMEROBOT_API_KEY); status not read", tool=TOOL)


def cmd_digest(a, now: dt.datetime) -> int:
    try:
        table = load_rows()
    except Unknown as e:
        return show([mr.write_receipt("W2", "UNKNOWN", why=str(e), tool=TOOL)])
    pre = [c1_monitor_line(now)]
    checks = [run_check(r, now, table=table) for r in CHECK_ROWS]
    pre += checks + fire_reminders(table, now)
    try:
        receipts, findings = mr.read_receipts(), mr.read_findings()
    except ValueError as e:
        return show(pre + [mr.write_receipt("W2", "UNKNOWN", why=f"cannot read the receipts: {e}", tool=TOOL)])
    week = [e for e in receipts if parse_at(e["at"]) > now - dt.timedelta(days=7)]
    opens = open_findings(receipts, findings)
    unknowns = unknown_streaks(receipts)
    d3 = receipts_of(receipts, "D3")
    L = [f"# b4him maintenance digest, week to {now:%Y-%m-%d}", "",
         f"*Written by `tools/maint_watch.py digest` (calendar row W2) at {now:%Y-%m-%d %H:%M} local.*", "",
         "## Monitor status",
         f"- C1 uptime monitor: {pre[0]['outcome']} {pre[0]['why']}",
         f"- D3 heartbeat: " + (r_line(d3[-1][1]) if d3 else "no D3 receipt ever"), "",
         f"## Open findings by age ({len(opens)})"]
    L += [f"- {_age(f['first_seen'], now)} · {f['row']} {f['severity']} {f['subject']} -> {f['route_to']}"
          for f in opens] or ["0 findings"]
    L += ["", f"## UNKNOWNs by age ({len(unknowns)})"]
    L += [f"- {_age(t, now)} · {rid}: {e['why']}" for rid, t, e in unknowns] or ["0 UNKNOWN"]
    L += ["", "## DUE FOR DANIEL"]
    due_any = False
    for rid in HUMAN_ROWS:
        s = human_status(rid, table, mr.read_receipts(), now)
        if s["is_due"]:
            due_any = True
            L.append(f"- **{rid}** due {s['due']:%Y-%m-%d}" + (" **OVERDUE**" if s["overdue"] else
                     f", grace to {fmt(s['deadline'])}") + f". Look at: {s['row']['task']}. "
                     f"Close: `py tools/maint_watch.py human {rid} <E-number>`")
        else:
            L.append(f"- {rid}: not due; next {s['due']:%Y-%m-%d}" + (f" (last closed: {s['last_e']})"
                                                                      if s["last_e"] else ""))
    if not due_any:
        L.append("- nothing due for Daniel this week")
    L += ["", "## Receipts-only checks (M5, H2, H3)"] + [f"- {r_line(c)}" for c in checks]
    h3 = checks[2]
    L += ["", "## H3: the 6-monthly re-read of the calendar and PRODUCTION_PLAN"]
    if h3["outcome"] in ("UNKNOWN", "FINDINGS"):
        L += ["REMINDER: the re-read is due. Write the amendment proposal or \"no change\" to "
              "`.maint/notes/H3_<YYYY-MM-DD>.md`. Evidence pack:"] + [f"- {p}" for p in evidence_pack()]
    else:
        L.append(f"- {h3['outcome']}: {h3['why']}")
    L += ["", f"## Receipts of the week ({len(week)})"] + ([f"- {r_line(e)}" for e in week] or ["- none"])
    rel = f"audits/{now:%Y-%m-%d}_weekly.md"
    p = mr.maint_dir() / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(L) + "\n", encoding="utf-8", newline="\n")
    w2 = mr.write_receipt("W2", "PASS", why=f"digest written: {len(opens)} open finding(s), {len(unknowns)} UNKNOWN",
                          evidence=f".maint/{rel}", tool=TOOL)
    return show(pre + [w2])


# ------------------------------------------------------------------ Q6: the alarm fire drill
DRILLS = "drills.jsonl"


def _drills() -> list[dict]:
    p = mr.maint_dir() / DRILLS
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.is_file() else []


def _drill_append(rec: dict) -> None:
    mr.maint_dir().mkdir(parents=True, exist_ok=True)
    with (mr.maint_dir() / DRILLS).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(rec) + "\n")


def armed_drill() -> dict | None:
    """The newest drill that has been armed and not confirmed."""
    armed = None
    for r in _drills():
        if r.get("event") == "armed":
            armed = r
        elif r.get("event") == "confirmed" and armed and r.get("skip_date") == armed["skip_date"]:
            armed = None
    return armed


def retire_candidates(table: dict, receipts: list[dict], findings: list[dict], now: dt.datetime) -> list[str]:
    since = now - dt.timedelta(days=365)
    out = []
    for rid, row in table["rows"].items():
        if row["kind"] == "event":
            continue
        mine = receipts_of(receipts, rid)
        if not mine:
            out.append(f"- {rid}: no receipt ever (never ran): not a candidate")
            continue
        nf = sum(1 for t, e in mine if t >= since and e["outcome"] == "FINDINGS")
        nf += sum(1 for f in findings if f["row"] == rid and parse_at(f["at"]) >= since)
        na = sum(1 for f in findings if f["subject"] == f"OVERDUE {rid}" and parse_at(f["at"]) >= since)
        if nf or na:
            continue
        if mine[0][0] <= since:
            out.append(f"- **{rid}**: zero findings and zero alarms in 4 quarters: candidate to retire")
        else:
            out.append(f"- {rid}: zero findings and zero alarms so far, but history only since {mine[0][0]:%Y-%m-%d}"
                       " (under 4 quarters): not yet a candidate")
    return out


def cmd_drill(a, now: dt.datetime) -> int:
    try:
        table = load_rows()
        receipts, findings = mr.read_receipts(), mr.read_findings()
    except (Unknown, ValueError) as e:
        return show([mr.write_receipt("Q6", "UNKNOWN", why=f"cannot run the drill: {e}", tool=TOOL)])
    rel = f"audits/{now:%Y-%m-%d}_drill.md"
    cands = retire_candidates(table, receipts, findings, now)
    (mr.maint_dir() / "audits").mkdir(parents=True, exist_ok=True)
    (mr.maint_dir() / rel).write_text(
        f"# Q6 calendar self-audit, {now:%Y-%m-%d}\n\n## Rows with zero findings and zero alarms over 4 quarters\n\n"
        + ("\n".join(cands) or "- (none)") + "\n", encoding="utf-8", newline="\n")
    if not os.environ.get(HEARTBEAT_ENV, "").strip():
        return show([mr.write_receipt("Q6", "UNKNOWN", why=f"no {HEARTBEAT_ENV}: there is no heartbeat to withhold, "
                                      "so no alarm can be drilled; the retire list is written",
                                      evidence=f".maint/{rel}", tool=TOOL)])
    if armed_drill():
        print(f"REFUSED: a drill is already armed for {armed_drill()['skip_date']}; confirm it first")
        return 1
    today = now.date()
    pinged_today = [t for t, e in receipts_of(receipts, "D3") if t.date() == today and e["outcome"] != "SKIP"]
    skip = dt.date.fromisoformat(a.date) if a.date else (today + DAY if pinged_today else today)
    if skip < today:
        print(f"REFUSED: {skip} is in the past")
        return 1
    last_ping = [t for t, e in receipts_of(receipts, "D3", {"PASS"})]
    _drill_append({"event": "armed", "at": now.isoformat(timespec="seconds"), "skip_date": skip.isoformat()})
    return show([mr.write_receipt("Q6", "UNKNOWN", why=f"awaiting alarm confirmation: the {skip} heartbeat is "
                                  f"withheld on purpose; the external alarm should fire about a day plus the check's "
                                  f"grace after the last ping ({fmt(last_ping[-1]) if last_ping else 'none recorded'})"
                                  f". Record it: maint_watch.py confirm <at|never>", evidence=f".maint/{rel}",
                                  tool=TOOL)])


def cmd_confirm(a, now: dt.datetime) -> int:
    d = armed_drill()
    if not d:
        print("REFUSED: no drill is awaiting confirmation (run `maint_watch.py drill` first)")
        return 1
    skip = dt.date.fromisoformat(d["skip_date"])
    if a.at.lower() in ("never", "none", "fail"):
        _drill_append({"event": "confirmed", "at": now.isoformat(timespec="seconds"), "skip_date": d["skip_date"],
                       "alarm": None})
        mr.write_finding("Q6", "S1", "alarm fire drill FAILED", f"the {skip} heartbeat was withheld and no alarm "
                         "arrived: the out-of-band alarm path is broken", "Release Manager + Daniel")
        return show([mr.write_receipt("Q6", "FINDINGS", n=1, why=f"drill FAIL: no alarm after the {skip} heartbeat "
                                      "was withheld", tool=TOOL)])
    try:
        if re.fullmatch(r"\d{1,2}:\d{2}", a.at):
            h, m = map(int, a.at.split(":"))
            at = dt.datetime.combine(skip, dt.time(h, m), tzinfo=now.tzinfo)
        else:
            at = dt.datetime.fromisoformat(a.at)
            at = local(at) if at.tzinfo else at.replace(tzinfo=now.tzinfo)
    except ValueError:
        print(f"REFUSED: {a.at!r} is not HH:MM, an ISO time, or 'never'")
        return 1
    if at < midnight(skip, now.tzinfo) or at > now + dt.timedelta(minutes=5):
        print(f"REFUSED: an alarm at {fmt(at)} cannot belong to the {skip} drill (before it, or in the future)")
        return 1
    _drill_append({"event": "confirmed", "at": now.isoformat(timespec="seconds"), "skip_date": d["skip_date"],
                   "alarm": at.isoformat(timespec="minutes")})
    return show([mr.write_receipt("Q6", "PASS", why=f"alarm fired at {at:%H:%M} on {at:%Y-%m-%d} (drill withheld "
                                  f"the {skip} heartbeat)", tool=TOOL)])


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--now", help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("daily", help="D1, D2, D3")
    s.add_argument("--date", help="the release day D1 judges (default today, local)")
    s.add_argument("--release-log", help="release_log.jsonl to read (default: this checkout's)")
    sub.add_parser("digest", help="W2 weekly digest")
    s = sub.add_parser("drill", help="Q6: withhold one heartbeat")
    s.add_argument("--date", help="the day whose heartbeat is withheld (default: today, or tomorrow if pinged)")
    s = sub.add_parser("confirm", help="Q6: when the alarm arrived")
    s.add_argument("at", help="HH:MM (on the drill day), an ISO time, or 'never'")
    s = sub.add_parser("check", help="one receipts-only check")
    s.add_argument("row", choices=CHECK_ROWS)
    s = sub.add_parser("human", help="close a HUMAN row")
    s.add_argument("row")
    s.add_argument("e_number")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.now:                                    # a fixed clock for the receipts too (tests, replays)
        now = parse_at(a.now)
        mr.now_utc = lambda: now.astimezone(dt.timezone.utc)
    else:
        now = now_local()
    if a.cmd == "daily":
        return cmd_daily(a, now)
    if a.cmd == "digest":
        return cmd_digest(a, now)
    if a.cmd == "drill":
        return cmd_drill(a, now)
    if a.cmd == "confirm":
        return cmd_confirm(a, now)
    if a.cmd == "check":
        return show([run_check(a.row, now)])
    return cmd_human(a, now)


if __name__ == "__main__":
    sys.exit(main())
