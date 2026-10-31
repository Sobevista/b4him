#!/usr/bin/env python3
"""
maint_receipt.py: the one writer of b4him's maintenance receipts and findings. Every maintenance tool imports it.

THE THREE RULES (maintenance calendar, PROPOSED 2026-10-20): every run writes a receipt whatever happens; the outcome
is PASS, FINDINGS n, UNKNOWN <why> or SKIP <why>; UNKNOWN never rounds to PASS.

WHERE. Everything goes under `.maint/` in the repo root, which .gitignore ignores: release.py refuses an unclean tree,
and the repo is public.
    .maint/maintenance_log.jsonl       one receipt per run
        {"at": ISO-UTC, "row": "<calendar id>", "outcome": "PASS|FINDINGS|UNKNOWN|SKIP", "n": int|null,
         "why": str, "evidence": "<path under .maint/>"|null, "tool": "<repo-relative script path>",
         "run_id": "<uuid4 of the tools/maint_run.py run>"|null}
      and, around each run of tools/maint_run.py, two run records (no "row" key; read_receipts() skips them), the
      runner's first and last writes (the harness counter's spec, delivered.py @ c06bb63e):
        {"at": ISO-UTC, "kind": "run_start", "run_id": <uuid4>, "runner": "tools/maint_run.py", "pid": int,
         "proc_started": <that process's creation time, ISO-UTC>|null, "trigger": "scheduled"|"manual"}
        {"at": ISO-UTC, "kind": "run_end", "run_id": <uuid4>, "runner": "tools/maint_run.py", "exit": int,
         "rows_failed": [row ids whose runner failed]}
TOOL AND RUN. `tool` is the writing script's path relative to the repo root (`tools/linkcheck.py`, never a bare
name), so a counter can match it exactly. `run_id` is the MAINT_RUN_ID that tools/maint_run.py puts in its children's
environment for the length of one run; a tool run by hand has none, so its receipts carry `run_id: null`.
    .maint/maintenance_findings.jsonl  one line per finding
        {"at": ISO-UTC, "row", "severity": "S1|S2|S3", "subject", "detail", "route_to"}
The receipt shape follows release.log() (tools/release.py): the time first, appended, one JSON object per line.

    write_receipt(row, outcome, n=None, why="", evidence=None)   -> the dict written
    write_finding(row, severity, subject, detail="", route_to="", **extra) -> the dict written
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


RUN_ENV = "MAINT_RUN_ID"


def tool_path(tool: str | None = None) -> str:
    """The writing script as a repo-relative posix path. A bare name ("linkcheck.py") is a script in tools/; an
    absolute or relative path is made relative to the repo root when it lies inside it."""
    t = str(tool or (sys.argv[0] if sys.argv and sys.argv[0] else "") or "unknown").replace("\\", "/")
    if "/" not in t:
        return f"tools/{t}"
    p = Path(t)
    if not p.is_absolute():                    # already repo-relative ("tools/linkcheck.py")
        return p.as_posix().removeprefix("./")
    try:
        return p.resolve().relative_to(REPO.resolve()).as_posix()
    except (ValueError, OSError):
        return f"tools/{p.name}"


def run_id() -> str | None:
    return os.environ.get(RUN_ENV) or None


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
             "why": why or "", "evidence": evidence, "tool": tool_path(tool), "run_id": run_id()}
    _append(LOG_NAME, entry)
    return entry


RUN_KINDS = ("run_start", "run_end")


def write_run_marker(kind: str, rid: str, **fields) -> dict:
    """tools/maint_run.py's run_start / run_end line, in the receipt log (exact shape in the module docstring)."""
    if kind not in RUN_KINDS or not rid:
        raise ValueError(f"a run marker is one of {RUN_KINDS} with a run_id")
    entry = {"at": now_utc().isoformat(timespec="seconds"), "kind": kind, "run_id": rid, **fields}
    _append(LOG_NAME, entry)
    return entry


def write_finding(row: str, severity: str, subject: str, detail: str = "", route_to: str = "", **extra) -> dict:
    """Extra keys (linkcheck's W1b proposal, a page list) ride after the six fixed ones and never replace them."""
    if not isinstance(row, str) or not row.strip():
        raise ValueError("a finding needs its calendar row id")
    if severity not in SEVERITIES:
        raise ValueError(f"severity {severity!r} is not one of {', '.join(SEVERITIES)}")
    if not (subject or "").strip():
        raise ValueError("a finding needs a subject")
    entry = {"at": now_utc().isoformat(timespec="seconds"), "row": row, "severity": severity, "subject": subject,
             "detail": detail or "", "route_to": route_to or ""}
    entry.update({k: v for k, v in extra.items() if k not in entry})
    _append(FINDINGS_NAME, entry)
    return entry


#: An ASSIST row whose tool has assembled its evidence and now waits on a person writes SKIP with this prefix, never
#: UNKNOWN: UNKNOWN is kept strictly for "could not run". The judgement closes it (maint_watch.py judge); D2 alarms if
#: none arrives within the row's cadence + grace.
AWAITING = "awaiting "


def awaiting_why(row: str, seat: str, what: str) -> str:
    return (f"{AWAITING}{seat} judgement: {what}; close with `maint_watch.py judge {row} PASS|FINDINGS <n> "
            f"--seat {seat} --note <text>`")


def is_awaiting(e: dict) -> bool:
    return e.get("outcome") == "SKIP" and str(e.get("why") or "").startswith(AWAITING)


def _read(name: str) -> list[dict]:
    p = maint_dir() / name
    if not p.is_file():
        return []
    out = []
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"{p.name} is unreadable ({type(e).__name__})") from None
    for i, raw in enumerate(text.split("\n"), 1):      # JSONL ends lines at \n only: U+0085 may sit in a value
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
    """Receipts only: the run markers (lines with a `kind`) are left out."""
    return [e for e in _read(LOG_NAME) if "kind" not in e]


def read_run_markers() -> list[dict]:
    return [e for e in _read(LOG_NAME) if e.get("kind") in RUN_KINDS]


def read_findings() -> list[dict]:
    return _read(FINDINGS_NAME)
