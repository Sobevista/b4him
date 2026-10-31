#!/usr/bin/env python3
"""
maint_receipt.py: the one writer of b4him's maintenance receipts and findings. Every maintenance tool imports it.

THE THREE RULES (maintenance calendar, PROPOSED 2026-10-20): every run writes a receipt whatever happens; the outcome
is PASS, FINDINGS n, UNKNOWN <why> or SKIP <why>; UNKNOWN never rounds to PASS.

WHERE. Everything goes under `.maint/` in the repo root, which .gitignore ignores: release.py refuses an unclean tree,
and the repo is public.
    .maint/maintenance_log.jsonl       one receipt per run
        {"at": ISO-UTC, "row": "<calendar id>", "outcome": "PASS|FINDINGS|UNKNOWN|SKIP", "n": int|null,
         "why": str, "evidence": "<path under .maint/>"|null, "tool": "<script>"}
    .maint/maintenance_findings.jsonl  one line per finding
        {"at": ISO-UTC, "row", "severity": "S1|S2|S3", "subject", "detail", "route_to"}
The receipt shape follows release.log() (tools/release.py): the time first, appended, one JSON object per line.

    write_receipt(row, outcome, n=None, why="", evidence=None)   -> the dict written
    write_finding(row, severity, subject, detail="", route_to="") -> the dict written
    read_receipts() / read_findings()                             -> list[dict], oldest first

The log is append-only: nothing here rewrites or deletes a line. A malformed call raises ValueError and writes nothing,
so a tool cannot leave a receipt that lies about its own shape. Set MAINT_DIR to write elsewhere (the tests do).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTCOMES = ("PASS", "FINDINGS", "UNKNOWN", "SKIP")
SEVERITIES = ("S1", "S2", "S3")
LOG_NAME = "maintenance_log.jsonl"
FINDINGS_NAME = "maintenance_findings.jsonl"


def maint_dir() -> Path:
    """`.maint/` in the repo root, unless MAINT_DIR says otherwise."""
    return Path(os.environ.get("MAINT_DIR") or (REPO / ".maint"))


def now_utc() -> dt.datetime:
    """The clock. Tests replace it."""
    return dt.datetime.now(dt.timezone.utc)


def _tool() -> str:
    return Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "unknown"


def _append(name: str, entry: dict) -> None:
    d = maint_dir()
    d.mkdir(parents=True, exist_ok=True)
    with (d / name).open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def write_receipt(row: str, outcome: str, n: int | None = None, why: str = "", evidence: str | None = None,
                  tool: str | None = None) -> dict:
    if not isinstance(row, str) or not row.strip():
        raise ValueError("a receipt needs its calendar row id")
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome {outcome!r} is not one of {', '.join(OUTCOMES)}")
    if outcome == "FINDINGS":
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError("FINDINGS needs n >= 1 (zero findings is PASS)")
    elif n is not None and (not isinstance(n, int) or isinstance(n, bool)):
        raise ValueError("n is an int or None")
    if outcome in ("UNKNOWN", "SKIP") and not (why or "").strip():
        raise ValueError(f"{outcome} needs a why: '{outcome} <why>'")
    if evidence is not None:
        ev = str(evidence).replace("\\", "/")
        if not ev.startswith(".maint/") or ".." in ev.split("/"):
            raise ValueError(f"evidence must be a path under .maint/, got {evidence!r}")
        evidence = ev
    entry = {"at": now_utc().isoformat(timespec="seconds"), "row": row, "outcome": outcome, "n": n,
             "why": why or "", "evidence": evidence, "tool": tool or _tool()}
    _append(LOG_NAME, entry)
    return entry


def write_finding(row: str, severity: str, subject: str, detail: str = "", route_to: str = "") -> dict:
    if not isinstance(row, str) or not row.strip():
        raise ValueError("a finding needs its calendar row id")
    if severity not in SEVERITIES:
        raise ValueError(f"severity {severity!r} is not one of {', '.join(SEVERITIES)}")
    if not (subject or "").strip():
        raise ValueError("a finding needs a subject")
    entry = {"at": now_utc().isoformat(timespec="seconds"), "row": row, "severity": severity, "subject": subject,
             "detail": detail or "", "route_to": route_to or ""}
    _append(FINDINGS_NAME, entry)
    return entry


def _read(name: str) -> list[dict]:
    p = maint_dir() / name
    if not p.is_file():
        return []
    out = []
    for i, raw in enumerate(p.read_text(encoding="utf-8-sig").splitlines(), 1):
        if raw.strip():
            try:
                e = json.loads(raw)
            except json.JSONDecodeError as ex:
                raise ValueError(f"{p.name}:{i} is not JSON ({ex})") from ex
            if not isinstance(e, dict):
                raise ValueError(f"{p.name}:{i} is not a JSON object")
            out.append(e)
    return out


def read_receipts() -> list[dict]:
    return _read(LOG_NAME)


def read_findings() -> list[dict]:
    return _read(FINDINGS_NAME)
