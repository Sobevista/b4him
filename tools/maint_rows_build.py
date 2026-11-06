#!/usr/bin/env python3
"""
maint_rows_build.py: turn the maintenance calendar (CALENDAR.md, PROPOSED 2026-10-20) into tools/maint_rows.json, the
row table maint_watch.py's D2 reads. Run it again whenever the calendar is amended:

    py tools/maint_rows_build.py <path to CALENDAR.md> [--epoch 2026-10-20] [--out tools/maint_rows.json]

The calendar lives with the maintenance-auditor seat, outside this repo, so its path is an argument and never written
into the output. Citations ([S1-nn], ledger claim ids) are stripped: they point into material this public repo does
not carry.

What is read and what is assumed (every [ASSUMED] is Daniel's to rule, as the calendar itself says):
  * grace periods come from the calendar's "Days" paragraph ("daily +2 h, weekly +1 day, monthly +3 days,
    quarterly +7 days, annual +14 days"). The paragraph names no 6-monthly grace: SEMIANNUAL_GRACE_DAYS [ASSUMED].
  * weekly rows run Monday, monthly rows the first Monday of the month (the "Days" paragraph). Quarterly, 6-monthly
    and annual rows run on the first Monday of their months, QUARTER_MONTHS / HALF_MONTHS / YEAR_MONTHS [ASSUMED].
  * "every 5 min" (C1) is an external monitor; its receipt is the W2 digest's monitor line, so D2 watches it weekly.
  * the daily rows after D1 (D2, D3) run once D1's cutoff has passed: at 10:30 local [ASSUMED].
  * event rows (E1, E2) have no clock; D2 does not schedule them (E2 is watched through D1). E3's event is found by
    polling feeds (tools/standards_watch.py), so it is a weekly row: POLLED_EVENTS [ASSUMED].
  * epoch: the first date any row is scheduled from. Default the calendar's PROPOSED date [ASSUMED].
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SEMIANNUAL_GRACE_DAYS = 7
QUARTER_MONTHS = [1, 4, 7, 10]
HALF_MONTHS = [1, 7]
YEAR_MONTHS = [1]
HUMAN_ROWS = {"H1", "A1", "A3"}          # the HUMAN-row reminders: closed by Daniel's ledger E-number
NOTE_ROWS = {"H2", "H3"}                 # receipts-only: a review note under .maint/notes/
BOARD_ROWS = {"M5"}                      # receipts-only: the production board's own run
#: Event rows whose event is found by polling, so they run on a clock. E3's changes (WCAG / Pages / Actions) are
#: found by tools/standards_watch.py reading their feeds weekly [ASSUMED: weekly, set by the 2026-10-31 build brief].
POLLED_EVENTS = {"E3": {"kind": "weekly", "note": "event row polled weekly by tools/standards_watch.py [ASSUMED]"}}


def strip_cites(s: str) -> str:
    s = re.sub(r"\[(?:S1-\d+|[0-9a-f]{16})\]", "", s)
    s = s.replace("**", "")
    return re.sub(r"\s+", " ", s).strip()


def parse_grace(text: str) -> dict:
    m = re.search(r"Grace periods:(.*?)(?:\[ASSUMED\]|\n\n)", text, re.S)
    if not m:
        raise SystemExit("no 'Grace periods:' sentence in the calendar's Days paragraph")
    g = {}
    for kind, num, unit in re.findall(r"(daily|weekly|monthly|quarterly|annual)\s*\+(\d+)\s*(h|day|days)", m.group(1)):
        g[kind] = int(num) * (1 if unit == "h" else 24)
    missing = {"daily", "weekly", "monthly", "quarterly", "annual"} - set(g)
    if missing:
        raise SystemExit(f"the Days paragraph names no grace for: {', '.join(sorted(missing))}")
    g["semiannual"] = SEMIANNUAL_GRACE_DAYS * 24
    return g


def classify(rid: str, cadence: str) -> dict:
    c = cadence.lower()
    if rid in POLLED_EVENTS:
        return dict(POLLED_EVENTS[rid])
    if rid.startswith("E") or c.startswith("on ") or "each release" in c or "changes" in c:
        return {"kind": "event"}
    if "min" in c:
        return {"kind": "weekly", "watched_by": "W2", "note": "external monitor; its receipt is the W2 monitor line"}
    if c.startswith("daily"):
        m = re.search(r"(\d\d:\d\d)", c)
        return {"kind": "daily", "at": m.group(1) if m else "10:30"}
    if c.startswith("weekly") or c.startswith("with w"):
        return {"kind": "weekly"}
    if c.startswith("monthly"):
        return {"kind": "monthly"}
    if c.startswith("quarterly"):
        return {"kind": "quarterly", "months": QUARTER_MONTHS}
    if "6 months" in c:
        return {"kind": "semiannual", "months": HALF_MONTHS}
    if c.startswith("annual"):
        r = {"kind": "annual", "months": YEAR_MONTHS}
        if "renewal" in c:
            r["note"] = "60 days before renewal: the renewal date is not recorded here, so January is [ASSUMED]"
        return r
    raise SystemExit(f"row {rid}: cannot read cadence {cadence!r}")


def check_of(rid: str, kind: str) -> str:
    if kind == "event":
        return "event"
    if rid in HUMAN_ROWS:
        return "human"
    if rid in NOTE_ROWS:
        return "note"
    if rid in BOARD_ROWS:
        return "board"
    return "receipt"


def build(text: str, epoch: str) -> dict:
    grace = parse_grace(text)
    rows = []
    for line in text.splitlines():
        cells = [x.strip() for x in line.strip().strip("|").split("|")] if line.startswith("|") else []
        if len(cells) != 8 or not re.fullmatch(r"[A-Z]\d+b?", cells[0]):
            continue
        rid, cadence, task, tool, mode, receipt, alarm, route = cells
        r = {"id": rid, "cadence": strip_cites(cadence), **classify(rid, cadence)}
        r["grace_hours"] = grace.get(r["kind"]) if r["kind"] != "event" else None
        r["check"] = check_of(rid, r["kind"])
        r["mode"] = strip_cites(mode)
        r["task"] = strip_cites(task)
        r["receipt"] = strip_cites(receipt)
        r["route_to"] = strip_cites(route)
        rows.append(r)
    if not rows:
        raise SystemExit("no calendar rows found (expected an 8-column '| # | Cadence | ...' table)")
    return {"source": "maintenance-auditor seat, CALENDAR.md (PROPOSED 2026-10-20, unruled)",
            "generated_by": "tools/maint_rows_build.py",
            "epoch": epoch, "epoch_note": "first date rows are scheduled from [ASSUMED]: the calendar's PROPOSED date",
            "weekday": "Monday", "grace_hours": grace, "rows": rows}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("calendar")
    ap.add_argument("--epoch", default="2026-10-20")
    ap.add_argument("--out", default=str(HERE / "maint_rows.json"))
    a = ap.parse_args(argv)
    data = build(Path(a.calendar).read_text(encoding="utf-8"), a.epoch)
    Path(a.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    print(f"{len(data['rows'])} rows -> {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
