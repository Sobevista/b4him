#!/usr/bin/env python3
"""
production_board.py — the cog behind PRODUCTION_PLAN.md.

Reads production_queue.jsonl (the one home for pipeline state), computes the
publishing calendar, the review deadlines, the runway and what is overdue, and
writes PRODUCTION_BOARD.md.

Daniel, 2026-08-16: "we tier out the delivery so we control 'time' -- we will be
incredibly ahead of our posts." Runway is that sentence as a number.

NEVER hand-edit PRODUCTION_BOARD.md. Re-run this.

This board reports and computes. It does not publish, it does not advance a
stage, and it never infers that a review happened because time passed.

    py tools/production_board.py
    py tools/production_board.py --today 2026-09-01     # what-if
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
QUEUE = REPO / "production_queue.jsonl"
BOARD = REPO / "PRODUCTION_BOARD.md"

# --- the plan's constants. Changing one here without changing PRODUCTION_PLAN.md
#     is exactly the dual-home defect, so each names its clause. -------------
CADENCE_DAYS = (1, 4)          # Mon=0 .. Tue=1, Fri=4          (plan section 3, D15)
PER_WEEK_CAP = 2               # hard cap in any rolling 7 days (plan section 3, D15)
REVIEW_LEAD_DAYS = 7           # a piece must be PREVIEWED by T-7 (plan section 3)
RUNWAY_TARGET_WEEKS = 6        # (plan section 1)
RUNWAY_FLOOR_WEEKS = 3         # (plan section 1)
MAINT_PAGE_DAYS = 90           # quarterly page review        (plan section 5)

STAGES = ["SOURCE", "DRAFTED", "REVIEWED", "RULED", "PREVIEWED",
          "SCHEDULED", "PUBLISHED", "MAINTAINED"]
STAGE_OWNER = {
    "SOURCE": "build session", "DRAFTED": "Claude", "REVIEWED": "the other seat",
    "RULED": "DANIEL", "PREVIEWED": "DANIEL", "SCHEDULED": "the board",
    "PUBLISHED": "-", "MAINTAINED": "cadence",
}
ELIGIBLE_STAGE = STAGES.index("PREVIEWED")   # stage 4+ may occupy a slot


def load_queue() -> list[dict]:
    if not QUEUE.exists():
        return []
    rows = []
    for i, line in enumerate(QUEUE.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as e:
            # A parse failure is reported, never skipped silently -- a queue that
            # quietly drops a row is a producer not reading its own output.
            rows.append({"id": f"UNPARSEABLE-line-{i}", "title": str(e),
                         "stage": "SOURCE", "_broken": True})
    return rows


def next_slots(start: dt.date, n: int) -> list[dt.date]:
    out, d = [], start
    while len(out) < n:
        if d.weekday() in CADENCE_DAYS and d > start:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def stage_index(row: dict) -> int:
    try:
        return STAGES.index(row.get("stage", "SOURCE"))
    except ValueError:
        return 0


def blob_sha(path: pathlib.Path) -> str | None:
    """The git blob id of a file as this repo stores it (.gitattributes: text=auto eol=lf), computed without git."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" not in data:                     # text: git stores it with LF line endings
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def blob_in_store(blob: str) -> bool:
    """Is this blob in the repo's object store? An approved page waits there until release day."""
    try:
        return subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", f"{blob}^{{blob}}"],
                              capture_output=True).returncode == 0
    except OSError:
        return False


def approval_drift(row: dict) -> list[str]:
    """Files whose bytes are no longer the ones Daniel approved. RULED and PREVIEWED cover the bytes he saw,
    recorded as `approved_blobs` {path: git blob id}; a later edit is a new piece of work, never inherited.

    A file not yet in the tree is not drift while its approved blob sits in the object store: that is a piece
    racked for release (tools/release.py writes those exact bytes on its slot). Once PUBLISHED it must be in the
    tree, and a missing file is drift again."""
    out = []
    unpublished = stage_index(row) < STAGES.index("PUBLISHED")
    for rel, want in (row.get("approved_blobs") or {}).items():
        have = blob_sha(REPO / rel)
        if have == want or (have is None and unpublished and blob_in_store(want)):
            continue
        out.append(f"{rel} (approved {want[:12]}, now {have[:12] if have else 'missing'})")
    return out


def ready_date(row: dict) -> dt.date | None:
    """The day the piece reached PREVIEWED: the ISO date its `previewed` field starts with, if any."""
    try:
        return dt.date.fromisoformat(str(row.get("previewed", ""))[:10])
    except ValueError:
        return None


def eligible_pieces(rows: list[dict]) -> tuple[list[dict], dict]:
    """(pieces that may hold a slot, {id: drift}). A piece whose approved bytes changed holds no slot until
    Daniel rules and previews it again."""
    pipeline = [r for r in rows if not r.get("_broken") and stage_index(r) < STAGES.index("PUBLISHED")]
    drifted = {r.get("id"): d for r in pipeline if stage_index(r) >= STAGES.index("RULED")
               for d in [approval_drift(r)] if d}
    eligible = [r for r in pipeline if stage_index(r) >= ELIGIBLE_STAGE and r.get("id") not in drifted]
    return eligible, drifted


def assign_slots(eligible: list[dict], slots: list[dt.date]) -> tuple[list[dict], dict[dt.date, dict]]:
    """Eligible pieces fill slots in queue order. A piece with a recorded preview date takes the earliest open
    slot whose review-by date (T-7) it met, so a piece previewed today never lands in a slot whose window closed
    last week. A piece with no recorded date keeps the old rule: the next open slot."""
    queue_order = sorted(eligible, key=lambda r: (r.get("order", 999), r.get("id", "")))
    taken: dict[dt.date, dict] = {}
    for piece in queue_order:
        ready = ready_date(piece)
        for s in slots:
            if s in taken or (ready and ready > s - dt.timedelta(days=REVIEW_LEAD_DAYS)):
                continue
            taken[s] = piece
            break
    return queue_order, taken


def build(today: dt.date) -> str:
    rows = load_queue()
    broken = [r for r in rows if r.get("_broken")]
    live = [r for r in rows if not r.get("_broken")]

    published = [r for r in live if stage_index(r) >= STAGES.index("PUBLISHED")]
    pipeline = [r for r in live if stage_index(r) < STAGES.index("PUBLISHED")]
    eligible, drifted = eligible_pieces(live)

    runway_weeks = len(eligible) / PER_WEEK_CAP if PER_WEEK_CAP else 0
    if runway_weeks < RUNWAY_FLOOR_WEEKS:
        runway_state = "**BELOW FLOOR** - stop opening new rungs, drain the queue"
    elif runway_weeks < RUNWAY_TARGET_WEEKS:
        runway_state = "below target, above floor - keep building"
    else:
        runway_state = "healthy"

    slots = next_slots(today, 12)
    # Eligible pieces fill slots (assign_slots); the rest are printed as skips, a missed window flagged.
    queue_order, taken = assign_slots(eligible, slots)
    assigned: list[tuple[dt.date, dict | None, str]] = []
    for s in slots:
        deadline = s - dt.timedelta(days=REVIEW_LEAD_DAYS)
        piece = taken.get(s)
        if piece is not None:
            note = "" if (ready_date(piece) or today) <= deadline else "review window already passed"
            assigned.append((s, piece, note))
        elif any(ready_date(r) and ready_date(r) > deadline for r in queue_order):
            assigned.append((s, None, "SLOT SKIPS - the next ready piece was previewed after this slot's "
                                      "review-by date (recorded, not backfilled)"))
        else:
            assigned.append((s, None, "no eligible piece - SLOT SKIPS (recorded, not backfilled)"))

    L: list[str] = []
    A = L.append
    A("# PRODUCTION BOARD")
    A("")
    A(f"*Generated {today.isoformat()} by `tools/production_board.py` from "
      f"`production_queue.jsonl`. **Never hand-edit — re-run the generator.** "
      f"Doctrine: `PRODUCTION_PLAN.md`.*")
    A("")
    A(f"**RUNWAY: {runway_weeks:.1f} weeks** — {runway_state}  ")
    A(f"*(target {RUNWAY_TARGET_WEEKS}w · floor {RUNWAY_FLOOR_WEEKS}w · "
      f"{len(eligible)} piece(s) at stage ≥ PREVIEWED ÷ {PER_WEEK_CAP}/week)*")
    A("")
    A(f"{len(pipeline)} in the pipeline · {len(published)} published · "
      f"cadence Tue + Fri, hard cap {PER_WEEK_CAP} per 7 days")
    A("")

    if broken:
        A("## ⚠ UNPARSEABLE QUEUE ROWS")
        A("")
        A("*Reported, never skipped — a queue that silently drops a row is the thing this repo "
          "minted a law about on 2026-08-16.*")
        A("")
        for b in broken:
            A(f"- `{b['id']}` — {b['title']}")
        A("")

    if drifted:
        A("## ⚠ CHANGED SINCE DANIEL'S APPROVAL")
        A("")
        A("*RULED and PREVIEWED cover the bytes he saw (`approved_blobs`). These files changed after that, so "
          "the piece holds no slot until he rules and previews it again (`PRODUCTION_PLAN` §2: never inherited "
          "from a previous yes).*")
        A("")
        for r in pipeline:
            if r.get("id") in drifted:
                A(f"- {r.get('title','?')}: " + "; ".join(drifted[r.get("id")]))
        A("")

    # ---- what is blocked on Daniel -----------------------------------------
    on_daniel = [r for r in pipeline if r.get("stage") in ("RULED", "REVIEWED") or r.get("id") in drifted]
    A("## Waiting on Daniel")
    A("")
    if not on_daniel:
        A("*Nothing. Every piece is blocked on someone else or already through his gates.*")
    else:
        A("| piece | at stage | he owes | since |")
        A("|---|---|---|---|")
        for r in sorted(on_daniel, key=lambda x: x.get("since", "")):
            if r.get("id") in drifted:
                owes = "a new RULING and PREVIEW: changed since he approved it"
            else:
                owes = "a per-piece RULING" if r["stage"] == "REVIEWED" else "a rendered PREVIEW"
            A(f"| {r.get('title','?')} | {r['stage']} | {owes} | {r.get('since','unknown')} |")
    A("")

    # ---- the calendar -------------------------------------------------------
    A("## The next 12 slots")
    A("")
    A(f"*A piece must be at **PREVIEWED** by **T-{REVIEW_LEAD_DAYS} days** to hold a slot "
      f"(`PRODUCTION_PLAN` §3). An empty slot skips and says so.*")
    A("")
    A("| slot | piece | review by | note |")
    A("|---|---|---|---|")
    for s, piece, note in assigned:
        deadline = (s - dt.timedelta(days=REVIEW_LEAD_DAYS)).isoformat()
        title = piece.get("title", "?") if piece else "— *(skip)* —"
        A(f"| **{s.isoformat()}** {s.strftime('%a')} | {title} | {deadline if piece else '—'} | {note} |")
    A("")

    # ---- the pipeline -------------------------------------------------------
    A("## The pipeline, by stage")
    A("")
    for st in STAGES[:STAGES.index("PUBLISHED")]:
        at = [r for r in pipeline if r.get("stage") == st]
        A(f"**{st}** ({STAGE_OWNER[st]}) — {len(at)}")
        for r in sorted(at, key=lambda x: x.get("order", 999)):
            src = f" · source: `{r['source']}`" if r.get("source") else ""
            blocked = f" · **BLOCKED: {r['blocked_on']}**" if r.get("blocked_on") else ""
            A(f"  - {r.get('title','?')}{src}{blocked}")
        A("")

    # ---- maintenance --------------------------------------------------------
    A("## Maintenance due")
    A("")
    A(f"*Published pages are re-checked every {MAINT_PAGE_DAYS} days "
      f"(`PRODUCTION_PLAN` §5). Corrections publish immediately and outside the cadence.*")
    A("")
    due = []
    for r in published:
        last = r.get("last_reviewed") or r.get("published")
        if not last:
            due.append((r, "never recorded"))
            continue
        try:
            age = (today - dt.date.fromisoformat(last)).days
        except ValueError:
            due.append((r, f"unreadable date {last!r}"))
            continue
        if age >= MAINT_PAGE_DAYS:
            due.append((r, f"{age} days since last review"))
    if not due:
        A("*Nothing due.*" if published else "*Nothing published yet, so nothing to maintain.*")
    else:
        A("| piece | why |")
        A("|---|---|")
        for r, why in due:
            A(f"| {r.get('title','?')} | {why} |")
    A("")

    A("---")
    A("")
    A("**This board publishes nothing, advances no stage, and infers no review from the passage "
      "of time.** Stages RULED and PREVIEWED move only on Daniel's explicit word.")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--today", help="ISO date, for what-if runs")
    ap.add_argument("--print", action="store_true", dest="to_stdout",
                    help="print instead of writing the board")
    a = ap.parse_args()

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    out = build(today)

    if a.to_stdout:
        # A Windows console or pipe hands the process cp1252, which has no "≥": pin UTF-8 at the boundary.
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        print(out)
        return 0

    BOARD.write_text(out, encoding="utf-8", newline="\n")
    rows = [r for r in load_queue() if not r.get("_broken")]
    elig = [r for r in rows if ELIGIBLE_STAGE <= stage_index(r) < STAGES.index("PUBLISHED")]
    print(f"wrote {BOARD}")
    print(f"  runway {len(elig)/PER_WEEK_CAP:.1f} weeks "
          f"({len(elig)} eligible / {PER_WEEK_CAP} per week)")
    print(f"  {len(rows)} piece(s) in the queue")
    return 0


if __name__ == "__main__":
    sys.exit(main())
