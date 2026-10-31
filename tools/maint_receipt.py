"""Shared receipt helper for the maintenance calendar (one JSON line per run, one per finding).

Every maintenance run writes exactly one receipt to `.maint/maintenance_log.jsonl`:
    {"at": ISO-UTC, "row": "<calendar id>", "outcome": "PASS|FINDINGS|UNKNOWN|SKIP", "n": int|null,
     "why": str, "evidence": "<path under .maint/ or null>", "tool": "<script>"}
and each finding one line to `.maint/maintenance_findings.jsonl`:
    {"at", "row", "severity": "S1|S2|S3", "subject", "detail", "route_to"}

`.maint/` is git-ignored: tools/release.py refuses an unclean tree, so run outputs must never be tracked.
UNKNOWN never rounds to PASS: a check that could not run says UNKNOWN and why.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

OUTCOMES = ("PASS", "FINDINGS", "UNKNOWN", "SKIP")
SEVERITIES = ("S1", "S2", "S3")


def repo() -> Path:
    return Path(__file__).resolve().parent.parent


def maint_dir() -> Path:
    return repo() / ".maint"


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _append(name: str, entry: dict) -> dict:
    d = maint_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / name).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def write_receipt(row: str, outcome: str, n: int | None = None, why: str = "", evidence: str | None = None,
                  tool: str | None = None) -> dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, got {outcome!r}")
    if outcome == "FINDINGS" and not isinstance(n, int):
        raise ValueError("FINDINGS needs an integer n")
    entry = {"at": _now(), "row": row, "outcome": outcome, "n": n, "why": why, "evidence": evidence,
             "tool": tool or Path(sys.argv[0]).name}
    return _append("maintenance_log.jsonl", entry)


def write_finding(row: str, severity: str, subject: str, detail: str = "", route_to: str = "") -> dict:
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}, got {severity!r}")
    entry = {"at": _now(), "row": row, "severity": severity, "subject": subject, "detail": detail,
             "route_to": route_to}
    return _append("maintenance_findings.jsonl", entry)
