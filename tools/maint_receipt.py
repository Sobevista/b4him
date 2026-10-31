#!/usr/bin/env python3
"""
maint_receipt.py - the one way a maintenance run records what it saw.  (maintenance calendar, B4HIM_BUILDER_RULES)

    from maint_receipt import write_receipt, write_finding
    write_receipt("M1", "FINDINGS", n=3, why="3 WCAG2AA issues on 2 pages", evidence=".maint/2026-10-31_a11y.json")
    write_finding("M1", "S2", "lessons/index.html", "color-contrast: ...", "Site Maintainer")

Every run writes exactly one receipt line to .maint/maintenance_log.jsonl:
    {"at": ISO-UTC, "row": "<calendar id>", "outcome": "PASS|FINDINGS|UNKNOWN|SKIP", "n": int|null, "why": str,
     "evidence": "<path under .maint/ or null>", "tool": "<script>"}
Findings go one per line to .maint/maintenance_findings.jsonl: {at, row, severity S1|S2|S3, subject, detail, route_to}.

.maint/ is git-ignored: the 08:30 release refuses an unclean tree, so run output never lands in a tracked path.
UNKNOWN never rounds to PASS: a PASS with a reason that says the check could not run is refused here.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTCOMES = ("PASS", "FINDINGS", "UNKNOWN", "SKIP")
SEVERITIES = ("S1", "S2", "S3")


class ReceiptError(ValueError):
    pass


def maint_dir(root: Path | None = None) -> Path:
    d = (root or REPO) / ".maint"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _append(path: Path, rec: dict) -> None:
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def write_receipt(row: str, outcome: str, n: int | None = None, why: str = "", evidence: str | None = None,
                  tool: str | None = None, root: Path | None = None) -> dict:
    if outcome not in OUTCOMES:
        raise ReceiptError(f"outcome must be one of {OUTCOMES}, not {outcome!r}")
    if n is not None and (not isinstance(n, int) or isinstance(n, bool) or n < 0):
        raise ReceiptError(f"n must be a non-negative int or None, not {n!r}")
    if outcome == "FINDINGS" and not n:
        raise ReceiptError("FINDINGS needs n >= 1")
    if outcome in ("UNKNOWN", "SKIP") and not why:
        raise ReceiptError(f"{outcome} needs a why")
    if evidence is not None:
        ev = str(evidence).replace("\\", "/")
        if not ev.startswith(".maint/") or ".." in ev.split("/"):
            raise ReceiptError(f"evidence must be a path under .maint/, not {evidence!r}")
        evidence = ev
    rec = {"at": _now(), "row": row, "outcome": outcome, "n": n, "why": why, "evidence": evidence,
           "tool": tool or Path(sys.argv[0]).name or "?"}
    _append(maint_dir(root) / "maintenance_log.jsonl", rec)
    return rec


def write_finding(row: str, severity: str, subject: str, detail: str, route_to: str,
                  root: Path | None = None) -> dict:
    if severity not in SEVERITIES:
        raise ReceiptError(f"severity must be one of {SEVERITIES}, not {severity!r}")
    rec = {"at": _now(), "row": row, "severity": severity, "subject": subject, "detail": detail, "route_to": route_to}
    _append(maint_dir(root) / "maintenance_findings.jsonl", rec)
    return rec
