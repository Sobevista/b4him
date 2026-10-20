#!/usr/bin/env python3
"""
migrate_stage2.py - turn the queue's prose `reviewed` into stage-2 records (production-line-v2 round 3). For a human.

Since round 3, approvals.offer admits a piece only on a STRUCTURED record:
    reviewed = {"date": "YYYY-MM-DD", "by": "<seat>", "verdict": "PASS", "proof": "<where the report is>"}
Prose never admits a new offer. Racked and published rows are never re-offered, so release does not need this; it
makes the record one shape everywhere, and keeps the prose verbatim under "notes".

It converts ONLY rows at PREVIEWED or later whose prose names a stage 2 run by a seat that did not write the page
AND states a pass (T4, T5, GC-GLOSS-1 on 2026-10-20). Anything else is listed as SKIPPED with the reason and left
alone: UNKNOWN never rounds to PASS.

    py tools/migrate_stage2.py            # dry run: prints what it would write, touches nothing
    py tools/migrate_stage2.py --write    # rewrites those queue lines only (main, clean tree); commit it yourself
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import production_board as pb  # noqa: E402

INDEPENDENT = re.compile(r"stage 2 by a seat that (?:neither wrote|did not write)", re.I)
PASSED = re.compile(r"\bPASS\b")
#: round 4: any of these ANYWHERE in the prose means the verdict is not a clean PASS: UNKNOWN never rounds to PASS.
DOUBT = re.compile(r"\bFAIL|\bnot\b|n't\b|\bno\b|\bnever\b|pending|NOT YET|\bawait|\bqueued\b|\bflag|\bunverified\b"
                   r"|\bgap\b|\bcould not\b|\bWITH-FLAGS\b", re.I)
BOUND_AT = re.compile(r"on the approved bytes at ([0-9a-f]{7,40})")


def record(row: dict) -> tuple[dict | None, str]:
    text = row.get("reviewed")
    if isinstance(text, dict):
        return None, "already a record"
    if not isinstance(text, str) or not text.strip():
        return None, "no review recorded"
    if pb.stage_index(row) < pb.ELIGIBLE_STAGE:
        return None, f"at {row.get('stage')}: not racked or published, so it must get a real record before its offer"
    if not INDEPENDENT.search(text):
        return None, "prose does not say a seat that did not write the page ran stage 2"
    if not PASSED.search(text):
        return None, "prose does not record a PASS verdict"
    doubt = DOUBT.search(text)
    if doubt:
        return None, f"prose qualifies its verdict ({doubt.group(0)!r} at char {doubt.start()}): not a clean PASS"
    rec = {"date": text[:10], "by": "independent stage-2 seat (migrated from prose)", "verdict": "PASS",
           "proof": "migrated from prose; see notes", "notes": text}
    bound = BOUND_AT.search(text)
    if bound and str(row.get("approved_commit", "")).startswith(bound.group(1)) and row.get("approved_blobs"):
        rec["blobs"] = dict(row["approved_blobs"])          # the bytes it names are the bytes the tap pinned
    else:
        rec["unbound"] = True                               # cannot name its bytes: admits no new offer
    return rec, "converted" + ("" if "blobs" in rec else " (unbound)")



def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    changes = {}
    for r in pb.load_queue():
        if r.get("_broken") or not r.get("reviewed"):
            continue
        rec, why = record(r)
        print(f"{'CONVERT' if rec else 'SKIPPED'}  {r.get('id')}: {why}")
        if rec:
            changes[r["id"]] = rec
    if not a.write or not changes:
        print(f"{len(changes)} row(s) would change" + ("" if a.write else " (dry run; --write to apply)"))
        return 0
    g = lambda *x: subprocess.run(["git", "-C", str(pb.REPO), *x], capture_output=True, text=True).stdout.strip()
    if g("rev-parse", "--abbrev-ref", "HEAD") != "main" or g("status", "--porcelain"):
        print("REFUSED: check out main with a clean tree first")
        return 1
    out = []
    for line in pb.QUEUE.read_text(encoding="utf-8").split("\n"):
        s = line.strip()
        if s.startswith("{"):
            row = json.loads(s)
            if row.get("id") in changes:
                row["reviewed"] = changes[row["id"]]
                line = json.dumps(row, ensure_ascii=False)
        out.append(line)
    pb.QUEUE.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"wrote {len(changes)} row(s) to {pb.QUEUE}; review the diff, then commit")
    return 0


if __name__ == "__main__":
    sys.exit(main())
