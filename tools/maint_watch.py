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
    py tools/maint_watch.py one     D1|D2|D3|H1|A1|A3                  one row alone (tools/maint_run.py runs these)

Exit 0 every receipt PASS/SKIP · 1 a FINDINGS (or a refused command) · 2 an UNKNOWN and no FINDINGS.

D1. Today's release_log.jsonl `apply` line must exist by 08:30 + 2 h local. A non-release day's SKIP is present.
    No line by 10:30 is FINDINGS (MISSING). A line whose outcome is not PUBLISHED/SKIP (FAIL, PUSHED-UNVERIFIED,
    COMMITTED, anything unknown) is FINDINGS too: present, but not a release that worked. Before 10:30 with no line:
    UNKNOWN, never PASS. The log reader is adapted from tools/release_watch.py on build/release-watch @ fbe8f58.
D2. Every row in tools/maint_rows.json (generated from the calendar by tools/maint_rows_build.py) against its
    cadence + grace. A row with no receipt ever is overdue from its first scheduled date on/after the epoch. HUMAN
    rows count only a PASS (Daniel's E-number) as done. Overdue rows -> FINDINGS n listing them, one finding each.
    UNKNOWN never rounds to PASS: a row whose latest receipt is UNKNOWN for longer than its own grace (the same grace
    as its cadence: daily 2 h ... annual 14 d) is STUCK, an alarm like an overdue row; inside that grace it makes D2
    UNKNOWN, naming it, never PASS. The schedule is checked too (tools/maint_schedule.py): a missing or stalled
    b4him-maint-run task is a D2 finding. Event rows (E1, E2) have no clock. D2 does not judge itself.
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
NOTE FORMAT (H2, H3: .maint/notes/<row>_<YYYY-MM-DD>[_*].md). A dated filename is not a review; the note is read and
    must carry these lines, each with a real value (a placeholder such as <...>, TODO or ___ does not count):
        Date: 2027-01-12
        Reviewer: reviewer                       (a seat id)
        Reviewed: what was reviewed
        Verdict: the verdict (e.g. "no change", "amend section 5")
        Finding: one line per finding            (or the single line "Findings: none")
    Each value needs real content (3+ characters; not ".", "x", "n/a", a placeholder). The filename's date may not
    be in the future and must equal the Date: line. H2 is the Independent Reviewer's: its Reviewer may not be a
    page-author seat. A note missing any part is UNKNOWN naming what is missing.
ASSIST ROWS (M1b, M4, A2, Q1, Q2). The scanner's result is evidence (findings filed, the evidence file); the row's
    receipt is `SKIP awaiting <seat> judgement` until the seat judges. The cadence + grace clock runs from the FIRST
    awaiting line and no re-run or new scanner output resets it; only a close does (a judgement or a PASS).
JUDGE. `judge <row> PASS|FINDINGS [n] --seat S --note T` closes an ASSIST row only when its latest receipt is an
    `awaiting ... judgement` SKIP written by that row's own runner (tools/maint_run.py RUNNERS) whose evidence file
    exists under .maint/; the judgement carries that evidence. D1-D3 and AUTOMATE rows are refused; `judge` and
    `human` refuse --now. SAME-ACCOUNT LIMIT: these checks stop mistakes, not a forger. Anyone who can write .maint/
    (this Windows account, any process it runs) can append a receipt, an awaiting line or an evidence file by hand,
    and nothing here can tell. Closing that needs the log written by a separate account (or an append-only store the
    judging account cannot write), which this repo does not have.
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
def last_done(mine: list[tuple[dt.datetime, dict]]) -> tuple[dt.datetime | None, dict | None]:
    """The moment a row's clock restarts from. Every receipt counts, except while a judgement is owed: from the FIRST
    `awaiting <seat> judgement` line the seat has one cadence + grace to judge, and nothing but a close restarts the
    clock - not a re-run that is still waiting, not new scanner output (FINDINGS, SKIP), not an UNKNOWN. A close is
    a PASS (a judgement, a note found, a witness) or a judgement's FINDINGS (`judged by <seat>: ...`)."""
    last, entry, owed = None, None, False
    for t, e in mine:
        if owed:
            closes = e.get("outcome") == "PASS" or (e.get("outcome") == "FINDINGS"
                                                     and str(e.get("why") or "").startswith("judged by "))
            if mr.is_awaiting(e) or not closes:
                continue
            last, entry, owed = t, e, False
            continue
        last, entry, owed = t, e, mr.is_awaiting(e)
    return last, entry


EXPIRES = re.compile(r"\bexpires (\d{4}-\d{2}-\d{2})\b")
#: Rows on the RDAP clock (A3: "annually, 60 days before renewal"). Their due date is expiry - 60 days, read from
#: their own receipts (tools/maint_human.py a3 writes "expires YYYY-MM-DD"), and they are polled every Monday.
RDAP_ROWS = {"A3": 60}


def rdap_overdue(rid: str, row: dict, receipts: list[dict], now: dt.datetime, epoch: dt.date) -> dict | None:
    """A3 on the RDAP clock: overdue when (a) the Monday poll has stopped (no A3 receipt by the Monday after the last
    one + 1 day + 24 h), or (b) the 60-day window opened more than the row's grace ago and no PASS (Daniel's close)
    has arrived since it opened. Weekly SKIPs far from expiry are on time; January is nothing special."""
    poll = {"id": rid, "kind": "weekly", "grace_hours": 24}
    mine = receipts_of(receipts, rid)
    last = mine[-1][0] if mine else None
    due = due_from(poll, last, epoch, now.tzinfo)
    dl = deadline_of(poll, due)
    base = {"row": rid, "last": last, "route_to": row.get("route_to", "")}
    if now > dl:
        return {**base, "due": due, "deadline": dl, "what": "RDAP poll stopped" if last else "RDAP never polled"}
    exp = next((EXPIRES.search(str(e.get("why") or "")) for _, e in reversed(mine)
                if EXPIRES.search(str(e.get("why") or ""))), None)
    if not exp:
        return None                           # an RDAP failure is UNKNOWN, judged by the STUCK rule
    expires = dt.date.fromisoformat(exp.group(1))
    opens = midnight(expires - dt.timedelta(days=RDAP_ROWS[rid]), now.tzinfo)
    deadline = opens + dt.timedelta(hours=row.get("grace_hours") or 0)
    closed = [t for t, e in mine if e.get("outcome") == "PASS" and t >= opens]
    if now > deadline and not closed:
        return {**base, "due": opens, "deadline": deadline,
                "what": f"expires {expires}; the 60-day window opened {opens:%Y-%m-%d} and Daniel has not closed it"}
    return None


def overdue_rows(table: dict, receipts: list[dict], now: dt.datetime, skip=("D2",)) -> tuple[list, list]:
    over, events = [], []
    for rid, row in table["rows"].items():
        if row["kind"] == "event":
            events.append(rid)
            continue
        if rid in skip:
            continue
        if rid in RDAP_ROWS:
            o = rdap_overdue(rid, row, receipts, now, table["epoch_date"])
            if o:
                over.append(o)
            continue
        if row.get("check") in ("human", "note", "board"):
            # closed only by a PASS: Daniel's E-number, or a complete note / a board run found. The check's own
            # awaiting, UNKNOWN (an incomplete note) and FINDINGS (note overdue) lines never restart the clock.
            mine = receipts_of(receipts, rid, {"PASS"})
            last, entry = (mine[-1] if mine else (None, None))
        else:
            last, entry = last_done(receipts_of(receipts, rid))
        due = due_from(row, last, table["epoch_date"], now.tzinfo)
        dl = deadline_of(row, due)
        if now > dl:
            what = (f"awaiting judgement since {fmt(last)}, none by {fmt(dl)}" if entry and mr.is_awaiting(entry)
                    else None)
            over.append({"row": rid, "last": last, "due": due, "deadline": dl, "route_to": row.get("route_to", ""),
                         "what": what})
    return over, events


def unknown_rows(table: dict, receipts: list[dict], now: dt.datetime, skip=("D2",)) -> tuple[list, list]:
    """UNKNOWN never rounds to PASS. A row whose LATEST receipt is UNKNOWN is either
      stuck:   the UNKNOWN streak began more than the row's own grace_hours ago (daily 2 h, weekly 24 h, monthly
               72 h, quarterly / 6-monthly 168 h, annual 336 h): an alarm, exactly like an overdue row; or
      pending: inside that grace. Not an alarm yet, but never silent: D2 is UNKNOWN (not PASS) and names the rows.
    A fresh receipt is not a done one: an UNKNOWN is a row that ran and could not judge."""
    stuck, pending = [], []
    for rid, row in table["rows"].items():
        if row["kind"] == "event" or rid in skip:
            continue
        mine = receipts_of(receipts, rid)
        if not mine or mine[-1][1].get("outcome") != "UNKNOWN":
            continue
        i = len(mine) - 1
        while i > 0 and mine[i - 1][1].get("outcome") == "UNKNOWN":
            i -= 1
        since = mine[i][0]
        grace = dt.timedelta(hours=row.get("grace_hours") or 0)
        e = {"row": rid, "since": since, "until": since + grace, "why": mine[-1][1].get("why", ""),
             "route_to": row.get("route_to", "")}
        (stuck if now > since + grace else pending).append(e)
    return stuck, pending


def _schedule_check(now: dt.datetime) -> dict:
    import maint_schedule
    return maint_schedule.check(now)


#: (now) -> maint_schedule.check()'s dict. Tests replace it.
SCHEDULE_CHECK = _schedule_check


def run_d2(now: dt.datetime, rows_file: Path | None = None) -> dict:
    try:
        table = load_rows(rows_file)
        receipts = mr.read_receipts()
        over, events = overdue_rows(table, receipts, now)
        late = {o["row"] for o in over}
        stuck, pending = unknown_rows(table, receipts, now)
        stuck = [s for s in stuck if s["row"] not in late]
        pending = [s for s in pending if s["row"] not in late]
    except (Unknown, ValueError, KeyError) as e:
        return mr.write_receipt("D2", "UNKNOWN", why=f"cannot judge the calendar: {e}", tool=TOOL)
    try:
        sched = SCHEDULE_CHECK(now)
    except Exception as e:  # noqa: BLE001 - a check that could not run is UNKNOWN, with its reason
        sched = {"state": "unknown", "problems": [], "why": f"{type(e).__name__}: {e}"}
    note = f" (event rows not on the clock: {', '.join(events)})" if events else ""
    parts, alarms = [], []
    for o in over:
        what = ((o.get("what") + "; ") if o.get("what") else "") + \
               (f"last receipt {fmt(o['last'])}" if o["last"] else "no receipt ever") + \
               f", due {o['due']:%Y-%m-%d}, overdue since {fmt(o['deadline'])}"
        parts.append(f"{o['row']} ({what})")
        alarms.append(alarm_key(o["row"], "overdue", "awaiting judgement" if (o.get("what") or "").startswith(
            "awaiting") else ""))
        mr.write_finding("D2", "S2", f"OVERDUE {o['row']}", f"MAINTENANCE OVERDUE: row {o['row']}: {what}",
                         f"Daniel; owning seat: {o['route_to']}")
    for s in stuck:
        what = f"UNKNOWN since {fmt(s['since'])}, past its {fmt(s['until'])} grace: {s['why'][:120]}"
        parts.append(f"{s['row']} STUCK ({what})")
        alarms.append(alarm_key(s["row"], "stuck-unknown", s["why"]))
        mr.write_finding("D2", "S2", f"STUCK UNKNOWN {s['row']}", f"MAINTENANCE STUCK UNKNOWN: row {s['row']}: {what}",
                         f"Daniel; owning seat: {s['route_to']}")
    for p in sched.get("problems", []) if sched.get("state") in ("missing", "stale") else []:
        parts.append(f"SCHEDULE ({p})")
        alarms.append(alarm_key("SCHEDULE", sched["state"], p))
        mr.write_finding("D2", "S2", "SCHEDULE " + sched["state"].upper(), p, "Daniel (the paste is his)")
    r = _d2_receipt(table, events, parts, pending, sched, note)
    _save_state(D2_ALARMS, {"at": r["at"], "alarms": alarms})
    return r


def cause_class(why: str) -> str:
    """The short cause of an alarm: the first line of its reason, its first clause (up to ':' or ';') plus, when there
    is one, the class after that first ':' up to the next delimiter (':' ';' ',' '('), so "linkcheck crashed:
    KeyError" and "linkcheck crashed: TimeoutError" are different causes. Standalone numbers (dates, counts, times) are
    blurred so the same cause on another day is the same class; a number inside a word ("pa11y", "b4him") is kept."""
    first = (why or "").strip().splitlines()[0] if (why or "").strip() else ""
    head, sep, rest = re.match(r"([^:;]*)([:;]?)(.*)", first).groups()
    cls = head.strip()
    if sep == ":":
        nxt = re.split(r"[:;,(]", rest, maxsplit=1)[0].strip()
        if nxt:
            cls += ": " + nxt
    return re.sub(r"(?<![A-Za-z_])\d+(?![A-Za-z_])", "#", cls.lower())[:80]


def alarm_key(row: str, kind: str, why: str = "") -> str:
    """D3's newness key: the row, the alarm kind (overdue / stuck-unknown / findings / a schedule state) and the cause
    class. A stuck row whose cause changes is a NEW alarm and sends /fail."""
    c = cause_class(why)
    return f"{row} {kind}" + (f": {c}" if c else "")


D2_ALARMS = "d2_alarms.json"         # D2's alarm list for the run whose receipt has this `at` (D3 and W2 read it)
PING_STATE = "heartbeat_state.json"   # the alarms the last delivered heartbeat already reported


def _save_state(name: str, data: dict) -> None:
    d = mr.maint_dir()
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(json.dumps(data, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def _load_state(name: str) -> dict | None:
    p = mr.maint_dir() / name
    try:
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None
    except (OSError, ValueError):
        return None


def _d2_receipt(table, events, parts, pending, sched, note) -> dict:
    if parts:
        tail = (f"; also UNKNOWN, in grace: {', '.join(s['row'] for s in pending)}" if pending else "") + \
               (f"; schedule UNKNOWN: {sched['why']}" if sched.get("state") == "unknown" else "")
        return mr.write_receipt("D2", "FINDINGS", n=len(parts), why="overdue: " + "; ".join(parts) + tail + note,
                                tool=TOOL)
    if pending or sched.get("state") == "unknown":
        bits = ([f"UNKNOWN inside grace: " + "; ".join(f"{s['row']} (until {fmt(s['until'])})" for s in pending)]
                if pending else []) + ([f"schedule UNKNOWN: {sched['why']}"] if sched.get("state") == "unknown" else [])
        return mr.write_receipt("D2", "UNKNOWN", why="; ".join(bits) + note, tool=TOOL)
    return mr.write_receipt("D2", "PASS", why=f"{len(table['rows']) - len(events) - 1} rows within cadence + grace, "
                            f"none UNKNOWN; schedule: {sched.get('why', 'ok')}" + note, tool=TOOL)


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


def run_d3(fail: bool, why_fail: str, now: dt.datetime, note: str = "") -> dict:
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
                            + (f" ({why_fail})" if fail else "") + note, tool=TOOL)


def d3_signal(now: dt.datetime) -> tuple[bool, str, list[str]]:
    """(fail?, why, the alarms standing now). D3 is a liveness signal, not a second alarm tile:
      /fail when today's D1 or D2 is missing or UNKNOWN (the watch itself could not judge), or when an alarm is NEW
      since the last delivered ping; otherwise success. Standing alarms stay on the D2 tile and in the W2 digest.
    An alarm is a D1 FINDINGS line or one of D2's OVERDUE / STUCK UNKNOWN / SCHEDULE alarms (.maint/d2_alarms.json)."""
    try:
        receipts = mr.read_receipts()
    except ValueError as e:
        return True, f"cannot read today's D1/D2: {e}", []
    bad, current = [], []
    for r in ("D1", "D2"):
        today = [e for t, e in receipts_of(receipts, r) if t.date() == now.date()]
        if not today:
            bad.append(f"{r} no receipt today")
            continue
        e = today[-1]
        if e["outcome"] == "UNKNOWN":
            bad.append(f"{r} UNKNOWN")
        elif e["outcome"] == "FINDINGS" and r == "D1":
            current.append(alarm_key("D1", "findings", e["why"].split(": ", 1)[-1]))   # the day prefix is not a cause
        elif e["outcome"] == "FINDINGS":
            st = _load_state(D2_ALARMS)
            if not st or st.get("at") != e["at"]:
                bad.append("D2's alarm list does not match its receipt")
            else:
                current += st.get("alarms", [])
    seen = set((_load_state(PING_STATE) or {}).get("alarms", []))
    new = [a for a in current if a not in seen]
    why = ", ".join(bad + [f"NEW {a}" for a in new])
    return bool(bad or new), why, current


def run_d3_watch(now: dt.datetime) -> dict:
    fail, why, current = d3_signal(now)
    note = f" ({len(current)} standing alarm(s) already reported; see D2 / W2)" if current and not fail else ""
    r = run_d3(fail, why, now, note)
    if r["outcome"] == "PASS":                # delivered: these alarms have now been reported once
        _save_state(PING_STATE, {"at": r["at"], "alarms": current})
    return r


def cmd_daily(a, now: dt.datetime) -> int:
    day = dt.date.fromisoformat(a.date) if a.date else now.date()
    rlog = Path(a.release_log) if a.release_log else REPO / "release_log.jsonl"
    d1 = run_d1(rlog, day, now)
    d2 = run_d2(now)
    return show([d1, d2, run_d3_watch(now)])


ONE_ROWS = ("D1", "D2", "D3") + HUMAN_ROWS


def cmd_one(a, now: dt.datetime) -> int:
    """One row on its own, for tools/maint_run.py, which runs D1 then D2 then D3 as separate rows (D2 and D3 last, so
    the heartbeat reflects the whole run). D3 signals fail when today's newest D1 or D2 receipt is not PASS or is
    missing. A HUMAN row writes its reminder when due (UNKNOWN), or SKIP with its next due date when not."""
    rid = a.row
    if rid == "D1":
        day = dt.date.fromisoformat(a.date) if a.date else now.date()
        rlog = Path(a.release_log) if a.release_log else REPO / "release_log.jsonl"
        return show([run_d1(rlog, day, now)])
    if rid == "D2":
        return show([run_d2(now)])
    if rid == "D3":
        return show([run_d3_watch(now)])
    try:
        table = load_rows()
    except Unknown as e:
        return show([mr.write_receipt(rid, "UNKNOWN", why=str(e), tool=TOOL)])
    s = human_status(rid, table, mr.read_receipts(), now)
    if not s["is_due"]:
        return show([mr.write_receipt(rid, "SKIP", why=f"HUMAN row not due: next due {s['due']:%Y-%m-%d}" +
                                      (f" (last closed: {s['last_e']})" if s["last_e"] else ""), tool=TOOL)])
    if s["fired"] is None:
        return show(fire_reminders(table, now, only=(rid,)))
    return show([mr.write_receipt(rid, "SKIP", why=f"awaiting Daniel's ruling: reminder fired {fmt(s['fired'])} for "
                                  f"due {s['due']:%Y-%m-%d}; close with maint_watch.py human {rid} <E-number>",
                                  tool=TOOL)])


# ------------------------------------------------------------------ judge: closing an ASSIST row
#: Rows whose calendar text requires a judge who did not do the work (Q2: "witnessed by a seat that did not write the
#: pages"; H2: the Independent Reviewer's). The refused seats are maint_pages.AUTHOR_SEATS + the sweep seat.
INDEPENDENT = {"Q2", "H2"}


def cmd_judge(a, now: dt.datetime) -> int:
    import maint_pages as mp
    rid, outcome, seat, note = a.row, a.outcome.upper(), a.seat.strip().lower(), (a.note or "").strip()
    try:
        table = load_rows()
    except Unknown as e:
        print(f"REFUSED: {e}")
        return 1
    if rid not in table["rows"] or table["rows"][rid]["kind"] == "event":
        print(f"REFUSED: {rid} is not a calendar row with a clock")
        return 1
    if rid in HUMAN_ROWS:
        print(f"REFUSED: {rid} is a HUMAN row; it closes only with Daniel's ledger E-number: "
              f"maint_watch.py human {rid} <E-number>")
        return 1
    row = table["rows"][rid]
    if rid in ("D1", "D2", "D3") or str(row.get("mode", "")).startswith("AUTOMATE"):
        print(f"REFUSED: {rid} is an AUTOMATE row; its own tool judges it, a person does not")
        return 1
    awaiting, why = awaiting_line(rid)
    if awaiting is None:
        print(f"REFUSED: {why}")
        return 1
    if seat not in mp.SEATS:
        print(f"REFUSED: {seat!r} is not a seat ({', '.join(mp.SEATS)})")
        return 1
    if rid in INDEPENDENT and seat in (set(mp.AUTHOR_SEATS) | {mp.SWEEP_SEAT}):
        print(f"REFUSED: {rid} needs a judge who did not do the work; {seat} wrote the pages or ran the sweep")
        return 1
    if not note:
        print("REFUSED: a judgement says what was judged (--note <text>)")
        return 1
    if outcome == "FINDINGS":
        if a.n is None or a.n < 1:
            print("REFUSED: FINDINGS needs n >= 1 (zero findings is PASS)")
            return 1
        n = a.n
        mr.write_finding(rid, "S3", f"{rid} judged by {seat}: {note[:80]}", note, table["rows"][rid].get("route_to", ""))
    else:
        n = 0
    return show([mr.write_receipt(rid, outcome, n=n, why=f"judged by {seat}: {note}",
                                  evidence=awaiting.get("evidence"), tool=TOOL)])


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


NOTE_FIELD = re.compile(r"^\s*[-*]?\s*(?P<k>date|reviewer|reviewed|verdict|findings?)\s*:\s*(?P<v>.*)$", re.I)
PLACEHOLDER = re.compile(r"^(?:<.*>|\.+|_+|-+|x|n/?a|none\??|tbd|todo|\[\s*\]|yyyy-mm-dd)?$", re.I)
MIN_VALUE = 3                                  # a value shorter than this carries no content ("x", "ok", ".")


def _real(v: str, key: str) -> bool:
    v = v.strip()
    if key == "finding" and v.lower() == "none":          # "Findings: none" is the explicit no-findings line
        return True
    return len(v) >= MIN_VALUE and not PLACEHOLDER.match(v)


def note_problems(path: Path, rid: str = "", file_date: dt.date | None = None,
                  today: dt.date | None = None) -> list[str]:
    """What a review note lacks (NOTE FORMAT in the module docstring); [] means complete. An empty file, the template
    with its placeholders left in, or trivial values ('.', 'x', 'n/a') name every part they are missing. The filename's
    date must not be in the future and must equal the Date: line; H2's Reviewer must not be a page-author seat."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        return [f"a readable file ({type(e).__name__})"]
    import maint_pages as mp
    got: dict[str, list[str]] = {}
    for line in text.splitlines():
        m = NOTE_FIELD.match(line)
        if m:
            k = m["k"].lower().rstrip("s")
            if _real(m["v"], k):
                got.setdefault(k, []).append(m["v"].strip())
    missing = []
    if file_date and today and file_date > today:
        missing.append(f"a filename date not in the future ({file_date} is after {today})")
    try:
        note_date = dt.date.fromisoformat((got.get("date") or [""])[0][:10])
        if file_date and note_date != file_date:
            missing.append(f"a Date: line equal to the filename's date ({note_date} != {file_date})")
    except ValueError:
        missing.append("Date: YYYY-MM-DD")
    seat = (got.get("reviewer") or [""])[0].lower()
    if seat not in mp.SEATS:
        missing.append("Reviewer: <a seat>")
    elif rid == "H2" and seat in mp.AUTHOR_SEATS:
        missing.append(f"an independent Reviewer for H2 ({seat} writes the pages)")
    if not got.get("reviewed"):
        missing.append("Reviewed: <what was reviewed>")
    if not got.get("verdict"):
        missing.append("Verdict: <the verdict>")
    if not got.get("finding"):
        missing.append("at least one 'Finding: ...' line, or 'Findings: none'")
    return missing


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
            if n:                              # a dated filename is not a review: read it
                missing = note_problems(mr.maint_dir() / n[1][len(".maint/"):], rid, n[0], now.date())
                if missing:
                    return mr.write_receipt(rid, "UNKNOWN", why=f"{what} {n[1]} is not a complete note: missing "
                                            f"{', '.join(missing)} (see maint_watch.py NOTE FORMAT)",
                                            evidence=n[1], tool=TOOL)
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
    if now <= dl:                              # the check ran; it is waiting on a person, not failing to run
        seat = {"M5": "managing-editor", "H2": "reviewer", "H3": "publisher"}[rid]
        return mr.write_receipt(rid, "SKIP", why=f"{mr.AWAITING}{seat}: the {what} due {due:%Y-%m-%d} (grace to "
                                f"{fmt(dl)}); last {last_day or 'never'} ({where})", evidence=evidence, tool=TOOL)
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
    fired = [t for t, e in receipts_of(receipts, rid) if t >= due and (mr.is_awaiting(e) or e.get("outcome") == "UNKNOWN")]
    return {"row": row, "last": last, "last_e": closed[-1][1]["why"] if closed else None, "due": due,
            "deadline": dl, "is_due": now >= due, "overdue": now > dl, "fired": fired[0] if fired else None}


def fire_reminders(table: dict, now: dt.datetime, only=HUMAN_ROWS) -> list[dict]:
    out = []
    for rid in only:
        s = human_status(rid, table, mr.read_receipts(), now)
        if s["is_due"] and s["fired"] is None:
            late = (now.date() - s["due"].date()).days
            when = "on time" if late == 0 else f"late by {late} day(s)"
            out.append(mr.write_receipt(rid, "SKIP", why=f"awaiting Daniel's ruling: reminder fired "
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
    aw, why = awaiting_line(rid)
    if aw is None:
        print(f"REFUSED: {why}")
        return 1
    return show([mr.write_receipt(rid, "PASS", why=f"closed by Daniel's ledger {e} (recorded here; the ledger itself "
                                  "is not read by this tool)", evidence=aw["evidence"], tool=TOOL)])


def cmd_witness(a, now: dt.datetime) -> int:
    """Q2's close: a seat that did not write the pages witnesses the sweep. Written HERE (the closer), carrying the
    awaiting line's evidence; the rules of a valid witness are maint_pages.cmd_witness's."""
    import maint_pages as mp
    repo = Path(a.repo) if a.repo else mp.REPO
    with mp._maint_at(repo):                   # the sweep's receipts live beside the tree it swept
        aw, why = awaiting_line("Q2")
        if aw is None:
            print(f"REFUSED: {why}")
            return 1
        try:
            recs = mp.cmd_witness(repo, now.date(), a.seat, a.date, tool=TOOL, evidence=aw["evidence"])
        except mp.CouldNotRun as e:
            print(f"REFUSED: {e}")
            return 1
    return show(recs)


def awaiting_line(rid: str) -> tuple[dict | None, str]:
    """The HAND CLOSE rule's precondition: (the row's latest receipt, "") when it is an `awaiting ...` SKIP written
    by that row's own runner (tools/maint_run.py RUNNERS) whose evidence file exists under .maint/; else (None, why).
    Every close (judge, human, confirm, witness) copies that evidence onto its own line, written by this tool."""
    import maint_run
    try:
        mine = receipts_of(mr.read_receipts(), rid)
    except ValueError as e:
        return None, f"cannot read the receipts: {e}"
    if not mine or not mr.is_awaiting(mine[-1][1]):
        last = mine[-1][1] if mine else None
        return None, (f"{rid}'s latest receipt is not `awaiting ...` "
                      f"({(last['outcome'] + ' ' + last['why'][:60]) if last else 'no receipt'}); run its tool first "
                      f"so there is an evidence pack to close")
    aw = mine[-1][1]
    runner = maint_run.RUNNERS.get(rid, (None,))[0]
    if Path(str(aw.get("tool") or "")).name != runner:
        return None, f"{rid}'s awaiting line was written by {aw.get('tool')!r}, not by its runner {runner}"
    ev = aw.get("evidence")
    if not ev or not str(ev).startswith(".maint/") or not (mr.maint_dir() / str(ev)[len(".maint/"):]).is_file():
        return None, f"{rid}'s awaiting line names no evidence on disk ({ev!r}); there is nothing to close"
    return aw, ""


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
                if Path(str(e.get("tool") or "")).name == C1_READER and t > now - dt.timedelta(days=7)]
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
    # HUMAN reminders are written by their packs (tools/maint_human.py, the H1/A1/A3 runner), with the evidence a
    # close must carry; the digest only lists what is due (DUE FOR DANIEL below).
    pre += checks
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
    waiting = sorted({e["row"]: e for e in receipts}.values(), key=lambda e: e["at"])
    waiting = [e for e in waiting if mr.is_awaiting(e) and "." not in e["row"]]
    L += ["", f"## Awaiting a judgement ({len(waiting)})"]
    L += [f"- {e['row']}: {e['why'][:200]}" for e in waiting] or ["- none"]
    st = _load_state(D2_ALARMS) or {}
    L += ["", f"## Standing D2 alarms ({len(st.get('alarms', []))}, as of {st.get('at', 'no D2 run yet')})"]
    L += [f"- {x}" for x in st.get("alarms", [])] or ["- none"]
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
    if h3["outcome"] in ("UNKNOWN", "FINDINGS") or mr.is_awaiting(h3):
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
    return show([mr.write_receipt("Q6", "SKIP", why=f"awaiting alarm confirmation: the {skip} heartbeat is "
                                  f"withheld on purpose; the external alarm should fire about a day plus the check's "
                                  f"grace after the last ping ({fmt(last_ping[-1]) if last_ping else 'none recorded'})"
                                  f". Record it: maint_watch.py confirm <at|never>", evidence=f".maint/{rel}",
                                  tool=TOOL)])


def cmd_confirm(a, now: dt.datetime) -> int:
    d = armed_drill()
    if not d:
        print("REFUSED: no drill is awaiting confirmation (run `maint_watch.py drill` first)")
        return 1
    aw, why = awaiting_line("Q6")
    if aw is None:
        print(f"REFUSED: {why}")
        return 1
    ev = aw["evidence"]                        # the HAND CLOSE carries the drill's evidence
    skip = dt.date.fromisoformat(d["skip_date"])
    if a.at.lower() in ("never", "none", "fail"):
        _drill_append({"event": "confirmed", "at": now.isoformat(timespec="seconds"), "skip_date": d["skip_date"],
                       "alarm": None})
        mr.write_finding("Q6", "S1", "alarm fire drill FAILED", f"the {skip} heartbeat was withheld and no alarm "
                         "arrived: the out-of-band alarm path is broken", "Release Manager + Daniel")
        return show([mr.write_receipt("Q6", "FINDINGS", n=1, why=f"drill FAIL: no alarm after the {skip} heartbeat "
                                      "was withheld", evidence=ev, tool=TOOL)])
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
                                  f"the {skip} heartbeat)", evidence=ev, tool=TOOL)])


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
    s = sub.add_parser("witness", help="close Q2: a seat that did not write the pages witnesses the sweep")
    s.add_argument("seat")
    s.add_argument("--date", help="which sweep (default: the newest)")
    s.add_argument("--repo", help="the b4him checkout the sweep ran on (default: maint_pages' own)")
    s = sub.add_parser("judge", help="close an ASSIST row: the seat's judgement")
    s.add_argument("row")
    s.add_argument("outcome", choices=["PASS", "FINDINGS", "pass", "findings"])
    s.add_argument("n", nargs="?", type=int)
    s.add_argument("--seat", required=True)
    s.add_argument("--note", required=True)
    s = sub.add_parser("one", help="one row on its own (D1, D2, D3, or a HUMAN row's reminder); maint_run.py uses it")
    s.add_argument("row", choices=ONE_ROWS)
    s.add_argument("--date", help="D1: the release day it judges (default today, local)")
    s.add_argument("--release-log", help="D1: release_log.jsonl to read (default: this checkout's)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.now and a.cmd in ("judge", "human", "witness"):
        print(f"REFUSED: `{a.cmd}` records a person's act; its receipt is stamped with the real clock only (no --now)")
        return 1
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
    if a.cmd == "one":
        return cmd_one(a, now)
    if a.cmd == "judge":
        return cmd_judge(a, now)
    if a.cmd == "witness":
        return cmd_witness(a, now)
    return cmd_human(a, now)


if __name__ == "__main__":
    sys.exit(main())
