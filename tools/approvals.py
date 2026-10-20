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
(applied: true + SUPERSEDE, the same two events a session writes by hand). A ruling it cannot apply is reported and
left owed: never applied half-way, never dropped.

production-line-v2 (Daniel, 2026-10-20: "The change needs to be in the production program"):
  * REJECT puts the piece back at DRAFTED on main's queue (the row as tiled, branch kept, nothing racked) with
    blocked_on = "REDRAFT owed: <ledger id> <his note verbatim>" ("no note given" when there was none), carries the
    note into the application ledger event and the tile marker, and the board lists it under "Redraft owed".
    Until this, a REJECT marked the tile and moved nothing, and the note was written as null (E00660).
  * APPROVE clears ONLY a blocked_on marked as waiting for the tap (pre_tap), kept as cleared_blocked_on; every
    other label survives and the tile shows it; release.py refuses any row whose blocked_on is not empty.
  * OFFER requires a structured stage-2 PASS record in `reviewed` (stage2_problem); a patch may skip it only as a
    proved case-only change, and must be a patch (patch_problems: served paths only, no index entry, no path a
    racked piece pins). A patch records replaces_blobs and supersedes_pins; its tile says it is on the patch line.
  * A REJECT after an applied APPROVE on the same tile un-racks the piece (requeue + a second marker line).
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
import binding  # noqa: E402
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


# ---------------------------------------------------------------- stage 2 before the tap
# production-line-v2 (orchestrator, after the breaker): stage 2 is a STRUCTURED record, not a phrase. The row's
# `reviewed` field must be
#     {"date": "YYYY-MM-DD", "by": "<the seat that ran it>", "verdict": "PASS", "proof": "<where the report is>"}
# plus "blobs": {path: git blob id}, REQUIRED (round 5): the exact bytes it checked. Every file of the piece must be
# named there at exactly its current blob (the record may name more). Nothing is inferred from which commit wrote the
# record: a commit can write a record and new bytes together. A redraft after a REJECT therefore needs a new record.
# A record marked "unbound" (a legacy migration that could not name its bytes) and any prose never admit an offer.
# The `by` field is an honour-system claim: every commit is authored under Daniel's git identity, so no rule here can
# prove the reviewer differs from the drafter without an OS-enforced identity; it stops accidents and lazy
# self-labels, not a determined forger.
STAGE2_KEYS = ("date", "by", "verdict", "proof")
#: The one patch scope that may skip stage 2, proved on the FULL bytes of every file (head, attributes, CSS, script):
#: every byte equals main's except ASCII letter case. "layout-only" was dropped: visible-text equality let a name in
#: via <title>, alt, CSS content, script and the nav/footer (breaker, 2026-10-20).
CASE_ONLY = "case-only"
#: blocked_on labels a tap clears (round 4): only a label that STARTS "PRE-TAP:" or is exactly one of the known
#: tap-wait strings. A label that merely mentions the tap ("not even after Daniel's one tap") survives it.
PRE_TAP_PREFIX = "PRE-TAP:"
TAP_WAIT_LABELS = frozenset({"Daniel's one tap on the rendered proof (E00472)", "Daniel's one tap"})
#: The author rule (round 4). Rows have not carried who drafted them, so `by` must name a SPECIFIC seat that is
#: provably not the drafter: not the row's drafted_by (recorded going forward), not the git author of any commit
#: that wrote the piece's bytes on its branch, not a bare model/product name (every seat is "claude": the name says
#: nothing about which seat), and not a self-description of the drafting seat.
GENERIC_SEATS = frozenset({"claude", "fable", "opus", "sonnet", "haiku", "assistant", "ai", "gpt", "model", "llm"})
DRAFTER_WORDS = frozenset({"author", "self", "drafted", "drafter", "drafting", "wrote", "writer", "same"})


def pre_tap(label: str) -> bool:
    label = str(label or "").strip()
    return label.upper().startswith(PRE_TAP_PREFIX) or label in TAP_WAIT_LABELS


def drafting_authors(commit: str, files: list[str]) -> set[str]:
    """Names and emails (casefolded) of the git authors who wrote the piece's files on its branch."""
    base = git("merge-base", "main", commit, check=False).strip()
    rng = f"{base}..{commit}" if base else commit
    out = git("log", "--format=%an%x00%ae", rng, "--", *files, check=False)
    return {x.strip().casefold() for line in out.splitlines() for x in line.split("\0") if x.strip()}


def stage2_problem(row: dict, pid: str | None = None, commit: str | None = None) -> str | None:
    """None when `reviewed` is a stage-2 record that admits an offer of `pid` at `commit`, else what is wrong."""
    rec = row.get("reviewed")
    if not isinstance(rec, dict):
        return ("`reviewed` is empty" if not rec else
                "`reviewed` is prose, not a stage-2 record; prose never admits a new offer")
    missing = [k for k in STAGE2_KEYS if not str(rec.get(k) or "").strip()]
    if missing:
        return f"the stage-2 record lacks {', '.join(missing)}"
    try:
        dt.date.fromisoformat(str(rec["date"]))
    except ValueError:
        return f"the stage-2 record's date {rec['date']!r} is not a date"
    if rec["verdict"] != "PASS":
        return f"the stage-2 verdict is {rec['verdict']!r}, not PASS"
    by = str(rec["by"]).strip()
    tokens = [t for t in re.split(r"[^0-9a-z]+", by.casefold()) if t]
    if not tokens or tokens[0] in GENERIC_SEATS:
        return f"stage 2 `by` {by!r} names a model, not a seat: name the specific seat or session that ran it"
    if DRAFTER_WORDS & set(tokens):
        return f"stage 2 `by` {by!r} describes the drafting seat; stage 2 is run by a seat that did not write it"
    if row.get("drafted_by") and by.casefold() == str(row["drafted_by"]).strip().casefold():
        return f"stage 2 was run by {by!r}, the seat recorded as drafting the piece (drafted_by)"
    if rec.get("unbound"):
        return "the stage-2 record is unbound (it cannot name the bytes it checked), so it admits no new offer"
    blobs = rec.get("blobs")
    if not isinstance(blobs, dict) or not blobs:
        return ("the stage-2 record names no `blobs` {path: git blob id}: it must name the exact bytes it checked "
                "(required; nothing is inferred from commits)")
    if pid and commit:
        files = piece_files(row)
        now = blobs_at(commit, files)
        if by.casefold() in drafting_authors(commit, files):
            return f"stage 2 `by` {by!r} is a git author of the piece's own bytes"
        # every file of the piece must be one the record checked, at exactly these bytes (it may name more)
        changed = [rel for rel in files if blobs.get(rel) != now[rel]]
        if changed:
            return (f"the piece's bytes changed since the commit that recorded this stage 2 (its blobs do not match "
                    f"{', '.join(changed)}): a redraft needs a new stage 2")
    return None



def stage2_text(rec) -> str:
    if isinstance(rec, dict):
        return (f"stage 2 {rec.get('verdict')} on {rec.get('date')} by {rec.get('by')} (proof: {rec.get('proof')})"
                + (f"; {rec['notes']}" if rec.get("notes") else ""))
    return str(rec or "NOT YET: no independent review is recorded on the row")


def on_main(rel: str) -> bytes | None:
    p = subprocess.run(["git", "-C", str(repo()), "show", f"main:{rel}"], capture_output=True)
    return None if p.returncode else p.stdout


def racked_holders(rel: str, but: str, patches_only: bool = False) -> list[str]:
    """Ids of RACKED (approved, not yet published) rows on main's queue, other than `but`, that pin `rel`."""
    return [r.get("id") for r in pb.load_queue() if not r.get("_broken") and r.get("id") != but
            and pb.ELIGIBLE_STAGE <= pb.stage_index(r) < pb.STAGES.index("PUBLISHED")
            and rel in (r.get("approved_blobs") or {}) and (pb.is_patch(r) or not patches_only)]


def is_furniture(rel: str) -> bool:
    return rel.startswith(pb.SHARED_PREFIX) or rel == "lessons/index.html"


def patch_problems(pid: str, row: dict, files: list[str]) -> list[str]:
    """What makes a kind:"patch" row not a patch, or not one that may go now. A patch changes only what main already
    serves: no new page, no lessons-index listing (that is content). It may not touch a PAGE a racked piece pins
    (that piece's approved text would be silently replaced, or would erase the fix), nor any path another racked
    patch pins (the second would erase the first). Shared FURNITURE pinned by racked content IS allowed (round 4,
    Daniel: "a website fix shouldnt take a week"): the patch supersedes those furniture pins, recorded on each
    affected racked row (rack) and shown on the tile; those pieces publish with the patched furniture."""
    out = []
    if row.get("index_entry"):
        out.append("it carries an index_entry: a new lessons-index listing is content, not a patch")
    for rel in files:
        if on_main(rel) is None:
            out.append(f"{rel} is not a page main already serves: a new page is content, not a patch")
        held = racked_holders(rel, pid, patches_only=is_furniture(rel))
        if held:
            out.append(f"{rel} is pinned by racked {', '.join(held)}: publish or pull that first, then redraft "
                       f"the patch on current main")
    return out


def furniture_repins(pid: str, files) -> dict[str, list[str]]:
    """{racked content id: [furniture paths]} whose furniture pins this patch supersedes."""
    out: dict[str, list[str]] = {}
    for rel in files:
        if is_furniture(rel):
            for holder in racked_holders(rel, pid):
                out.setdefault(holder, []).append(rel)
    return out


def stage2_gate(pid: str, commit: str, row: dict) -> str | None:
    """production-line-v2: T5 was tapped before its stage-2 name check and a blocked_on label was the only trace. So
    stage 2 gates the OFFER. Content needs a PASS record by another seat. A patch needs the same, unless it is
    `patch_scope: "case-only"` AND every file's full bytes equal main's except ASCII letter case. Returns None when
    the record admits it, else the exemption text the tile shows; raises with what is missing otherwise."""
    problem = stage2_problem(row, pid, commit)
    if problem is None:
        return None
    if pb.is_patch(row) and row.get("patch_scope") == CASE_ONLY:
        for rel in piece_files(row):
            before = on_main(rel)
            after = subprocess.run(["git", "-C", str(repo()), "show", f"{commit}:{rel}"], capture_output=True).stdout
            if before is None or before.lower() != after.lower():
                raise ApprovalError(f"{pid}: claims case-only but {rel} changes more than letter case (full bytes "
                                    f"compared, head and attributes included); it needs a stage-2 record: {problem}")
        return ("EXEMPT from stage 2 as a case-only patch: proved by tools/approvals.py on the full bytes (every file "
                "equals main's except ASCII letter case)")
    raise ApprovalError(
        f"{pid} at {commit[:7]} has no stage-2 PASS on record, so it does not go in front of Daniel: {problem}. "
        f"Record it on the row as reviewed = {{\"date\", \"by\", \"verdict\": \"PASS\", \"proof\"}}"
        + ("; layout-only no longer exempts a patch, only a proved case-only change does" if pb.is_patch(row) else ""))



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
    if str(row.get("track", "")).startswith("tier"):
        # E00480: a lesson that does not sound like Daniel never reaches him. Measured on the committed bytes.
        import voice_check
        for rel in piece_files(row):
            v = voice_check.measure(voice_check.visible_text(git("show", f"{commit}:{rel}")))
            if not v["pass"]:
                raise ApprovalError(f"{rel} fails the voice check: first person {v['rate']}/1k (floor "
                                    f"{voice_check.FLOOR}), unglossed {[u.split(':')[0] for u in v['unglossed']]}")
    if pb.is_patch(row):
        bad = patch_problems(pid, row, list(blobs))
        if bad:
            raise ApprovalError(f"{pid} is labelled a patch but is not one: " + "; ".join(bad))
    exemption = stage2_gate(pid, commit, row)
    repins = furniture_repins(pid, blobs) if pb.is_patch(row) else {}
    title = title_for(pid, commit, row)
    path = board_path()
    text = path.read_text(encoding="utf-8") if path.exists() else (
        "# Approvals owed — b4him\n\n"
        "*Written by `tools/approvals.py offer`; read by the harness app, which records your tap in the ledger. "
        "One tap is RULED + PREVIEWED together (E00472): **Approve publishes exactly the bytes at the commit in the "
        "title** on the first Tuesday slot at least 7 days out. `tools/approvals.py apply` puts it on the rack; "
        "`tools/release.py` publishes it. Any edit after that pulls it and comes back here as a new tile.*\n")
    if f"### {title}\n" in text:
        raise ApprovalError(f"already offered: {title}")
    review = exemption or stage2_text(row.get("reviewed"))
    label = str(row.get("blocked_on") or "").strip()
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
        + (". This is a PATCH (the patch line, outside the content cadence): it publishes on the next daily "
           "release run after your tap, any day of the week, and takes no content slot."
           if pb.is_patch(row) else
           f". It takes the first open slot on or after {today + dt.timedelta(days=pb.REVIEW_LEAD_DAYS)}."),
        (f"- **What it does to the aggregate, measured.** Runway is unchanged: a patch is on the patch line, "
         f"not the content line." if pb.is_patch(row) else
         f"- **What it does to the aggregate, measured.** Runway rises by {1 / pb.PER_WEEK_CAP:.1f} weeks "
         f"(one piece ÷ {pb.PER_WEEK_CAP} a week)."),
        f"- **Cross-checked by, including where it is weak.** {review}",
        *([f"- **Open label on this row (blocked_on).** {label}"
           + (" — marked pre-tap: your approval clears it." if pre_tap(label) else
              " — your tap does NOT clear it; release refuses the piece until a session clears it once the gate "
              "is met.")] if label else []),
        *([f"- **Furniture re-pinned by {pid}.** These racked pieces will publish with this patch's furniture "
           f"instead of the furniture they were approved with: "
           + "; ".join(f"{h} ({', '.join(f'`{r}`' for r in rels)})" for h, rels in repins.items())]
          if repins else []),
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


def mark_board(title: str, verdict: str, event: str, today: dt.date, note: str | None = None) -> None:
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
            lines[j] = (f"**DANIEL:** [RULED {today} {verdict} · ledger {event} · applied by tools/approvals.py]"
                        + (f" — his note: {' '.join(note.splitlines())}" if note else ""))
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
            return
    if verdict == "REJECT":
        # a REJECT tapped after an APPROVE on the same tile was applied: record it under the earlier ruling
        for j in range(i + 1, len(lines)):
            if lines[j].startswith("### "):
                break
            if lines[j].startswith("**DANIEL:** [RULED") and " APPROVE " in lines[j]:
                lines.insert(j + 1, f"**DANIEL:** [RULED {today} REJECT after the APPROVE above was applied · ledger "
                                    f"{event} · unracked by tools/approvals.py]"
                                    + (f" — his note: {' '.join(note.splitlines())}" if note else ""))
                path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
                return
    raise ApprovalError(f"no pending marker under: {title}")


def ruling_note(event: dict) -> str | None:
    """His note on a ruling, verbatim (the harness app writes it to body.note). None only when he gave none."""
    note = event.get("body", {}).get("note")
    return note if isinstance(note, str) and note.strip() else None


def put_row(pid: str, row: dict) -> None:
    """Replace the piece's one line on main's queue (or add it). Every other byte stays."""
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


def main_row(pid: str) -> dict | None:
    hits = [r for r in pb.load_queue() if r.get("id") == pid]
    return hits[0] if hits else None


#: Fields that only an approval writes. A rejected piece carries none of them back to drafting.
APPROVAL_FIELDS = ("ruled", "previewed", "approved_blobs", "approved_commit", "approved_tag", "approved_index_entry",
                   "binding", "replaces_blobs", "supersedes_pins", "cleared_blocked_on", "repins_furniture_of",
                   "furniture_repinned_by")


def requeue(pid: str, commit: str, event: dict, today: dt.date) -> dict:
    """A REJECT (production-line-v2, Daniel 2026-10-20: "The change needs to be in the production program"). The
    piece goes back to DRAFTED on main's queue with his note verbatim in blocked_on, its branch kept, and nothing
    racked. The row is the one at the tiled commit (what he was shown), so a piece main has no row for yet
    (GC-GLOSS-3's case) gets one. Refused, and left owed, when main's row is already live or racked at another
    commit: a rejection of one commit never unpublishes or unracks different bytes."""
    have = main_row(pid)
    if have is not None:
        if pb.stage_index(have) >= pb.STAGES.index("PUBLISHED"):
            raise ApprovalError(f"{pid} is already {have.get('stage')} on main: a rejection never unpublishes; "
                                f"a fix to a live page is a patch (a human looks)")
        if pb.stage_index(have) >= pb.ELIGIBLE_STAGE and have.get("approved_commit") not in (None, commit):
            raise ApprovalError(f"{pid} is racked on main at {str(have['approved_commit'])[:7]}, not the rejected "
                                f"{commit[:7]}: a human looks")
    try:
        row = row_at(commit, pid)
    except ApprovalError:
        if have is None:
            raise
        row = dict(have)
    for k in APPROVAL_FIELDS:
        row.pop(k, None)
    note = ruling_note(event)
    row.update(stage="DRAFTED", since=today.isoformat(),
               blocked_on=f"{pb.REDRAFT_PREFIX} {event['id']} {note if note else 'no note given'}",
               rejected=f"{today} - Daniel, one tap: REJECT of {commit[:7]} (ledger {event['id']})")
    if not row.get("branch") and have and have.get("branch"):
        row["branch"] = have["branch"]
    put_row(pid, row)
    return row


def rack(pid: str, commit: str, event: dict, today: dt.date) -> dict:
    """Copy the approved row onto main's queue at PREVIEWED with its pinned blobs. One line changes (or one is added).

    blocked_on (production-line-v2 round 4): a tap clears ONLY a label that starts "PRE-TAP:" or is exactly a known
    tap-wait string (pre_tap), kept in cleared_blocked_on. Every other label
    survives the tap, the tile showed it to him, and release.py refuses the row until a session clears it.

    A patch is re-checked here (it may have changed since the offer: a piece racked in between): no new page, no
    index entry, no path a racked piece pins. It records replaces_blobs (the bytes main holds at each pinned path at
    the tap; the release replaces exactly those) and supersedes_pins. A content piece that pins the PRE-patch bytes
    of a path a published patch changed was drafted before the patch: refused, redraft on current main."""
    row = row_at(commit, pid)
    blobs = pinned(commit, row)
    rows_now = [r for r in pb.load_queue() if not r.get("_broken")]
    if pb.is_patch(row):
        bad = patch_problems(pid, row, list(blobs))
        if bad:
            raise ApprovalError(f"{pid} cannot be racked as a patch: " + "; ".join(bad))
    else:
        stale = [f"{rel} (patch {p.get('id')} changed it on {p.get('published')})" for rel, blob in blobs.items()
                 for p in rows_now if pb.is_patch(p) and pb.stage_index(p) >= pb.STAGES.index("PUBLISHED")
                 and (p.get("replaces_blobs") or {}).get(rel) == blob != (p.get("approved_blobs") or {}).get(rel)]
        if stale:
            raise ApprovalError(f"{pid} at {commit[:7]} pins bytes a published patch has since replaced: "
                                f"{'; '.join(stale)}. Redraft on current main and offer it again")
    stamp = f"{today} - Daniel, one tap in the app on the rendered proof (ledger {event['id']})"
    row.update(stage="PREVIEWED", ruled=stamp, previewed=stamp, approved_blobs=blobs,
               approved_commit=commit, approved_tag=f"approved/{pid}", since=today.isoformat())
    label = str(row.get("blocked_on") or "").strip()
    if label and pre_tap(label):
        row["cleared_blocked_on"] = f"{label} (cleared by Daniel's tap, ledger {event['id']})"
        row.pop("blocked_on", None)
    elif not label:
        row.pop("blocked_on", None)
    if pb.is_patch(row):
        # furniture re-pin over RACKED content, recorded visibly on each affected row (not part of its binding)
        repins = furniture_repins(pid, blobs)
        if repins:
            row["repins_furniture_of"] = repins
            for holder, rels in repins.items():
                other = main_row(holder)
                marks = dict(other.get("furniture_repinned_by") or {})
                marks.update({rel: f"{pid} (tapped {today}, ledger {event['id']}; takes effect when it publishes)"
                              for rel in rels})
                other["furniture_repinned_by"] = marks
                put_row(holder, other)
        row["replaces_blobs"] = {rel: pb.blob_sha(repo() / rel) for rel in blobs}
        # RE-PIN, recorded: for every path a PUBLISHED piece pinned, this patch's bytes become the pin once it
        # publishes (pb.published_owners: a patch owns its paths from its publish day). Named here, never silent.
        owners = pb.published_owners([r for r in pb.load_queue() if not r.get("_broken")])
        row["supersedes_pins"] = {rel: {"piece": owners[rel][0], "blob": owners[rel][1]}
                                  for rel in blobs if rel in owners and owners[rel][1] != blobs[rel]}
    if row.get("index_entry"):
        row["approved_index_entry"] = pb.entry_sha(row["index_entry"])
    row["binding"] = binding.make(row)        # v3 (production-boundary-v1): release re-derives the approval from this
    put_row(pid, row)
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
            note = ruling_note(ev)
            said = f'his note, verbatim: "{note}"' if note else "no note given"
            if verdict == "APPROVE":
                rack(pid, commit, ev, today)
                touched.append(pb.QUEUE)
            elif verdict == "REJECT":
                requeue(pid, commit, ev, today)
                touched.append(pb.QUEUE)
            mark_board(title, verdict, ev["id"], today, note)
            if verdict == "APPROVE":      # the tag moves only after every check that can refuse
                git("tag", "-f", f"approved/{pid}", commit)
            pb.BOARD.write_text(pb.build(today), encoding="utf-8", newline="\n")
            touched.append(pb.BOARD)
            git("add", "--", *sorted({p.relative_to(repo()).as_posix() for p in touched}))
            with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
                fh.write(f"{'APPROVED' if verdict == 'APPROVE' else verdict} {pid} at {commit[:7]}: "
                         f"Daniel's tap, ledger {ev['id']}\n\nApplied by tools/approvals.py. "
                         + ("Pinned to approved_blobs and racked; tools/release.py publishes it on its slot.\n"
                            if verdict == "APPROVE" else
                            f"Back to DRAFTED on main's queue, redraft owed; {said}.\n" if verdict == "REJECT" else
                            "Nothing moved on the rack.\n"))
                msg = fh.name
            git("commit", "-q", "-F", msg)
            Path(msg).unlink(missing_ok=True)
            done = led.append("RULING", ACTOR, {
                "decision": title, "verdict": verdict, "by": "daniel", "applied": True, "note": note,
                "binds": f"APPLIED {today} to b4him by tools/approvals.py: commit {git('rev-parse', 'HEAD').strip()[:7]}"
                         + (f"; {pid} racked at PREVIEWED, pinned to {commit[:7]}" if verdict == "APPROVE" else
                            f"; {pid} back to DRAFTED on main, blocked_on REDRAFT owed; {said}"
                            if verdict == "REJECT" else "")})
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
