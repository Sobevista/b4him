#!/usr/bin/env python3
"""
approvals.py — the one-tap half of E00472. Daniel's tap in the harness app becomes pinned bytes on the rack.

Daniel, 2026-10-13: "make the extraction, updating, and approval of automatic" — ruled as "One tap, auto after".
His tap is RULED and PREVIEWED together (PRODUCTION_PLAN stages 3+4), on the proof he was shown.

    py tools/approvals.py offer GC-GLOSS-2 draft/gc-gloss-2 --proof <url>   # put a tile in front of him
    py tools/approvals.py apply                                            # turn his taps into rack rows
    py tools/approvals.py status

OFFER writes a section to boards/APPROVALS_OWED.md, a board the harness app already scans (review_inbox
SIBLING_ROOTS). The tile's TITLE names the piece and the exact commit, and the app records his ruling under that
title, so an approval can only ever mean the bytes at that commit — the ones the proof showed him.

APPLY reads the ledger for rulings on those titles. An APPROVE pins every file of the piece at that commit
(approved_blobs), copies the piece's row from that commit onto main's queue at PREVIEWED, tags approved/<id> so the
bytes stay reachable, commits on main, marks the board line ruled, and records the application in the ledger
(applied: true + SUPERSEDE, the same two events a session writes by hand). A REJECT marks the line and moves
nothing. A ruling it cannot apply is reported and left owed: never applied half-way, never dropped.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import production_board as pb  # noqa: E402

HARNESS = Path(r"C:\Users\dansl\Claude\Projects\Data Import\Connection")
ACTOR = "b4him-approvals"
TITLE_RE = re.compile(r"^APPROVE (?P<id>[\w-]+) at (?P<commit>[0-9a-f]{7,40}) — ")
PENDING = "**DANIEL:** _pending_"


class ApprovalError(RuntimeError):
    pass


def repo() -> Path:
    return pb.REPO


def board_path() -> Path:
    return repo() / "boards" / "APPROVALS_OWED.md"


def git(*args: str, check: bool = True) -> str:
    p = subprocess.run(["git", "-C", str(repo()), *args], capture_output=True)
    if check and p.returncode:
        raise ApprovalError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout.decode("utf-8", "replace")


def row_at(commit: str, pid: str) -> dict:
    text = git("show", f"{commit}:production_queue.jsonl")
    rows = [json.loads(l) for l in text.splitlines() if l.strip().startswith("{")]
    hits = [r for r in rows if r.get("id") == pid]
    if len(hits) != 1:
        raise ApprovalError(f"{pid}: expected one queue row at {commit[:7]}, found {len(hits)}")
    return hits[0]


def piece_files(row: dict) -> list[str]:
    files = row.get("files") or ([row["page"]] if row.get("page") else [])
    if not files:
        raise ApprovalError(f"{row.get('id')}: the row names no page/files, so there is nothing to pin")
    return files


def blobs_at(commit: str, files: list[str]) -> dict:
    return {f: git("rev-parse", f"{commit}:{f}").strip() for f in files}


def pinned(commit: str, row: dict) -> dict:
    """Everything the tap approves: the piece's files and, if it is listed in the lessons index, that track's
    furniture as it stands at the same commit (release.pin_problems refuses a piece without it)."""
    files = piece_files(row)
    entry = row.get("index_entry")
    if entry:
        if not entry.get("track"):
            raise ApprovalError(f"{row.get('id')}: index_entry names no track")
        files = files + [f"tools/tracks/{entry['track']}.html"]
    return blobs_at(commit, files)


# ---------------------------------------------------------------- offer
def title_for(pid: str, commit: str, row: dict) -> str:
    return f"APPROVE {pid} at {commit[:7]} — {row.get('title', pid)}"


def offer(pid: str, ref: str, proof: str, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    commit = git("rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    row = row_at(commit, pid)
    if pb.STAGES.index(row.get("stage", "SOURCE")) < pb.STAGES.index("DRAFTED"):
        raise ApprovalError(f"{pid} is at {row.get('stage')} at {commit[:7]}: nothing drafted to approve")
    if not proof.startswith("https://"):
        raise ApprovalError("a tile needs the rendered proof's link: he approves what he SAW, not a description")
    blobs = pinned(commit, row)
    title = title_for(pid, commit, row)
    path = board_path()
    text = path.read_text(encoding="utf-8") if path.exists() else (
        "# Approvals owed — b4him\n\n"
        "*Written by `tools/approvals.py offer`; read by the harness app, which records your tap in the ledger. "
        "One tap is RULED + PREVIEWED together (E00472): **Approve publishes exactly the bytes at the commit in the "
        "title** on the first Tue/Fri slot at least 7 days out. `tools/approvals.py apply` puts it on the rack; "
        "`tools/release.py` publishes it. Any edit after that pulls it and comes back here as a new tile.*\n")
    if f"### {title}\n" in text:
        raise ApprovalError(f"already offered: {title}")
    review = row.get("reviewed") or "NOT YET: no independent review is recorded on the row"
    entry = row.get("index_entry")
    lines = [
        "", f"### {title}", "",
        f"- **What this is to the build.** {row.get('title', pid)} ({row.get('track', '?')} track), drafted "
        f"{row.get('drafted', '?')} on `{row.get('branch', ref)}`. The invariant it teaches: "
        f"*{row.get('invariant', 'NOT NAMED')}*. **The rendered proof: {proof}**",
        f"- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. "
        f"Nothing publishes that you have not seen.",
        f"- **What changes if you approve.** These exact bytes go on the rack: "
        + "; ".join(f"`{f}` = blob `{b[:12]}`" for f, b in blobs.items())
        + (f". The lessons index gains: **{entry.get('title')}** — {entry.get('blurb')}" if entry else
           ". No index entry is on the row, so the page will not be listed in the lessons index")
        + f". It takes the first open slot on or after {today + dt.timedelta(days=pb.REVIEW_LEAD_DAYS)}.",
        f"- **What it does to the aggregate, measured.** Runway rises by {1 / pb.PER_WEEK_CAP:.1f} weeks "
        f"(one piece ÷ {pb.PER_WEEK_CAP} a week).",
        f"- **Cross-checked by, including where it is weak.** {review}",
        f"- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; "
        f"a rejected piece goes back to drafting and returns here as a new commit.",
        "", PENDING, "",
    ]
    if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "main" or git("status", "--porcelain").strip():
        raise ApprovalError("the board lives on main: check out main with a clean tree first")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip("\n") + "\n" + "\n".join(lines), encoding="utf-8", newline="\n")
    git("add", "--", path.relative_to(repo()).as_posix())
    git("commit", "-q", "-m", f"Offer {pid} at {commit[:7]} for Daniel's one-tap approval")
    return title


# ---------------------------------------------------------------- apply
def ledger():
    if str(HARNESS) not in sys.path:
        sys.path.insert(0, str(HARNESS))
    from tools.session_ledger.ledger import Ledger
    return Ledger()


def owed_rulings(led) -> list[dict]:
    """Owed RULING events whose decision is an approval tile title. Latest per title wins."""
    latest = {}
    for e in led.rulings_owed():
        if TITLE_RE.match(e["body"].get("decision", "")):
            latest[e["body"]["decision"]] = e
    return list(latest.values())


def mark_board(title: str, verdict: str, event: str, today: dt.date) -> None:
    path = board_path()
    lines = path.read_text(encoding="utf-8").split("\n")
    try:
        i = lines.index(f"### {title}")
    except ValueError:
        raise ApprovalError(f"tile not on the board: {title}") from None
    for j in range(i + 1, len(lines)):
        if lines[j].startswith("### "):
            break
        if lines[j] == PENDING:
            lines[j] = f"**DANIEL:** [RULED {today} {verdict} · ledger {event} · applied by tools/approvals.py]"
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            return
    raise ApprovalError(f"no pending marker under: {title}")


def rack(pid: str, commit: str, event: dict, today: dt.date) -> dict:
    """Copy the approved row onto main's queue at PREVIEWED with its pinned blobs. One line changes (or one is added)."""
    row = row_at(commit, pid)
    blobs = pinned(commit, row)
    stamp = f"{today} - Daniel, one tap in the app on the rendered proof (ledger {event['id']})"
    row.update(stage="PREVIEWED", ruled=stamp, previewed=stamp, approved_blobs=blobs,
               approved_commit=commit, approved_tag=f"approved/{pid}", since=today.isoformat())
    if row.get("index_entry"):
        row["approved_index_entry"] = pb.entry_sha(row["index_entry"])
    text = pb.QUEUE.read_text(encoding="utf-8")
    out, hits = [], 0
    for line in text.split("\n"):
        if line.strip().startswith("{") and json.loads(line).get("id") == pid:
            line, hits = json.dumps(row, ensure_ascii=False), hits + 1
        out.append(line)
    if hits > 1:
        raise ApprovalError(f"{pid} appears {hits} times in main's queue")
    if hits == 0:
        while out and out[-1] == "":
            out.pop()
        out += [json.dumps(row, ensure_ascii=False), ""]
    pb.QUEUE.write_text("\n".join(out), encoding="utf-8", newline="\n")
    return row


def apply(today: dt.date | None = None, led=None) -> list[str]:
    today = today or dt.date.today()
    led = led or ledger()
    report = []
    for ev in owed_rulings(led):
        title, verdict = ev["body"]["decision"], ev["body"]["verdict"]
        m = TITLE_RE.match(title)
        pid, short = m["id"], m["commit"]
        try:
            if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
                raise ApprovalError("not on main")
            if git("status", "--porcelain").strip():
                raise ApprovalError("main's tree is not clean")
            commit = git("rev-parse", "--verify", f"{short}^{{commit}}").strip()
            touched = [board_path()]
            if verdict == "APPROVE":
                rack(pid, commit, ev, today)
                git("tag", "-f", f"approved/{pid}", commit)
                touched.append(pb.QUEUE)
            mark_board(title, verdict, ev["id"], today)
            pb.BOARD.write_text(pb.build(today), encoding="utf-8", newline="\n")
            touched.append(pb.BOARD)
            git("add", "--", *sorted({p.relative_to(repo()).as_posix() for p in touched}))
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
                fh.write(f"{'APPROVED' if verdict == 'APPROVE' else verdict} {pid} at {commit[:7]}: "
                         f"Daniel's tap, ledger {ev['id']}\n\nApplied by tools/approvals.py. "
                         + ("Pinned to approved_blobs and racked; tools/release.py publishes it on its slot.\n"
                            if verdict == "APPROVE" else "Nothing moved on the rack.\n"))
                msg = fh.name
            git("commit", "-q", "-F", msg)
            Path(msg).unlink(missing_ok=True)
            done = led.append("RULING", ACTOR, {
                "decision": title, "verdict": verdict, "by": "daniel", "applied": True, "note": None,
                "binds": f"APPLIED {today} to b4him by tools/approvals.py: commit {git('rev-parse', 'HEAD').strip()[:7]}"
                         + (f"; {pid} racked at PREVIEWED, pinned to {commit[:7]}" if verdict == "APPROVE" else "")})
            led.append("SUPERSEDE", ACTOR, {"target": ev["id"], "replacement": done["id"],
                                            "reason": "application recorded; the original stays in the log forever"})
            report.append(f"APPLIED  {verdict}  {pid} at {commit[:7]}  ({ev['id']} -> {done['id']})")
        except ApprovalError as e:
            git("reset", "-q", "--", ".", check=False)
            git("checkout", "--", ".", check=False)
            report.append(f"OWED     {verdict}  {pid} at {short}  could not apply: {e}")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("offer")
    o.add_argument("piece")
    o.add_argument("ref")
    o.add_argument("--proof", required=True)
    sub.add_parser("apply")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    try:
        if a.cmd == "offer":
            print("offered:", offer(a.piece, a.ref, a.proof))
        elif a.cmd == "apply":
            lines = apply()
            print("\n".join(lines) or "no approval rulings owed")
            return 1 if any(l.startswith("OWED") for l in lines) else 0
        else:
            owed = owed_rulings(ledger())
            print("\n".join(f"{e['id']}  {e['body']['verdict']}  {e['body']['decision']}" for e in owed)
                  or "no approval rulings owed")
    except ApprovalError as e:
        print("REFUSED:", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
