#!/usr/bin/env python3
"""
maint_receipt.py - the maintenance calendar's receipt and finding log (the calendar's rule 1: every run writes a receipt).

    from maint_receipt import write_receipt, write_finding
    write_receipt("W3", "UNKNOWN", why="known-names list absent", evidence=".maint/audits/2026-10-31_people.json")
    write_finding("W3", "S1", "index.html: unknown-name", "2 heuristic hits", "reviewer")

Receipts go to .maint/maintenance_log.jsonl, one JSON line per run (shape follows release.log()):
    {"at": ISO-UTC, "row": "<calendar id>", "outcome": "PASS|FINDINGS|UNKNOWN|SKIP", "n": int|null, "why": str,
     "evidence": "<path under .maint/ or null>", "tool": "<script>"}
Findings go to .maint/maintenance_findings.jsonl: {at, row, severity S1|S2|S3, subject, detail, route_to}.

.maint/ is git-ignored: tools/release.py refuses to publish from an unclean tree, so a run must never leave a tracked
or untracked file behind. UNKNOWN never rounds to PASS: a check that could not run says UNKNOWN and why.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTCOMES = ("PASS", "FINDINGS", "UNKNOWN", "SKIP")
SEVERITIES = ("S1", "S2", "S3")
LOG_NAME = "maintenance_log.jsonl"
FINDINGS_NAME = "maintenance_findings.jsonl"


def maint_dir(root: Path | None = None) -> Path:
    """The .maint/ folder of the repo at `root` (default: this repo)."""
    return Path(root or REPO) / ".maint"


def now_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def _append(path: Path, rec: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def write_receipt(row: str, outcome: str, n: int | None = None, why: str = "", evidence: str | None = None, *,
                  tool: str | None = None, root: Path | None = None) -> dict:
    """Append one receipt line and return it. `outcome` must be PASS, FINDINGS, UNKNOWN or SKIP."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {OUTCOMES}")
    if outcome == "FINDINGS" and n is None:
        raise ValueError("a FINDINGS receipt carries its count n")
    if outcome in ("UNKNOWN", "SKIP") and not why:
        raise ValueError(f"an {outcome} receipt says why")
    rec = {"at": now_utc(), "row": row, "outcome": outcome, "n": n, "why": why, "evidence": evidence,
           "tool": tool or Path(sys.argv[0]).name}
    return _append(maint_dir(root) / LOG_NAME, rec)


def write_finding(row: str, severity: str, subject: str, detail: str, route_to: str, *,
                  root: Path | None = None) -> dict:
    """Append one finding line and return it."""
    if severity not in SEVERITIES:
        raise ValueError(f"severity {severity!r} is not one of {SEVERITIES}")
    rec = {"at": now_utc(), "row": row, "severity": severity, "subject": subject, "detail": detail,
           "route_to": route_to}
    return _append(maint_dir(root) / FINDINGS_NAME, rec)


def read_jsonl(path: Path) -> list[dict]:
    """Every parseable line of a .jsonl file; an unparseable line is returned as {"_broken": line_no}, never dropped."""
    if not path.exists():
        return []
    out = []
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            out.append({"_broken": i})
    return out
