"""maint_receipt.py: the maintenance calendar's receipt and finding writers (shared by every maintenance tool).

The calendar's first rule: every run writes a receipt line, whatever happens. The outcome is one of PASS,
FINDINGS n, UNKNOWN <why> or SKIP <why>, and UNKNOWN never rounds to PASS. The shape follows release.log().

    .maint/maintenance_log.jsonl       one line per run:
        {"at", "row", "outcome", "n", "why", "evidence", "tool"}
    .maint/maintenance_findings.jsonl  one line per finding:
        {"at", "row", "severity", "subject", "detail", "route_to", ...extra}

`.maint/` sits in the repo root and is git-ignored, so a run never dirties the tree the 08:30 release needs clean.
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from pathlib import Path

#: The repo root. A tool pointed at another tree (or a test) sets this before writing.
ROOT = Path(__file__).resolve().parent.parent
OUTCOMES = ("PASS", "FINDINGS", "UNKNOWN", "SKIP")
SEVERITIES = ("S1", "S2", "S3")


def maint_dir() -> Path:
    d = ROOT / ".maint"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def _append(name: str, entry: dict) -> dict:
    with (maint_dir() / name).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def write_receipt(row: str, outcome: str, n: int | None = None, why: str = "", evidence: str | None = None,
                  tool: str | None = None) -> dict:
    """Append one receipt line. FINDINGS needs n; UNKNOWN and SKIP need a why (a bare UNKNOWN says nothing)."""
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {OUTCOMES}, not {outcome!r}")
    if outcome == "FINDINGS" and not isinstance(n, int):
        raise ValueError("a FINDINGS receipt needs n (an int)")
    if outcome in ("UNKNOWN", "SKIP") and not why:
        raise ValueError(f"an {outcome} receipt needs a why")
    return _append("maintenance_log.jsonl", {
        "at": _now(), "row": row, "outcome": outcome, "n": n, "why": why, "evidence": evidence,
        "tool": tool or Path(sys.argv[0] or "unknown").name})


def write_finding(row: str, severity: str, subject: str, detail: str, route_to: str, **extra) -> dict:
    """Append one finding line. Extra keys (a proposal, a page list) ride after the fixed ones."""
    if severity not in SEVERITIES:
        raise ValueError(f"severity must be one of {SEVERITIES}, not {severity!r}")
    entry = {"at": _now(), "row": row, "severity": severity, "subject": subject, "detail": detail,
             "route_to": route_to}
    entry.update({k: v for k, v in extra.items() if k not in entry})
    return _append("maintenance_findings.jsonl", entry)
