#!/usr/bin/env python3
"""
line_profile.py — one reader for where the production line acts and on what clock (stress profile, 2026-11-09).

Daniel, 2026-11-09: "stress test it and have it auto publish a few in five minute intervals somewhere throw away".
The line reads its repo, its live site and its cadence from module constants (production_board.REPO, CADENCE_DAYS,
PER_WEEK_CAP, REVIEW_LEAD_DAYS; release.SITE) and applies only today. A stress run needs the same code pointed at a
throwaway copy on a fast clock, so this module is the one place that may say otherwise, and only when asked.

INERT BY DEFAULT. With env B4HIM_LINE_PROFILE unset, load() returns None and get(key, default) returns `default`
itself: every constant is the module's own value, byte for byte (tools/test_line_profile.py).

A PROFILE is a JSON file named by B4HIM_LINE_PROFILE with exactly these keys:
    repo              the repo the line acts on (never the production repo; see below)
    site              the live URL --verify-live hashes ("http://127.0.0.1:<port>" for the local target)
    cadence_days      release weekdays, Mon=0 .. Sun=6
    per_week_cap      hard cap in any rolling 7 days
    review_lead_days  a piece must be PREVIEWED this many days before its slot
    allow_date_apply  true lets `release.py --apply --date <day>` publish a virtual day (never without a profile)
and optionally
    ledger            a local JSONL file standing in for the harness ledger (approvals.py refuses a profile without
                      it: a stress run never reads or writes the harness)

THE HARD GUARD. A profile whose repo is the production checkout is refused before anything runs: the repo that holds
this file, its git toplevel, the main checkout that shares its git directory (when this file runs from a worktree),
or any repo that shares that git directory or names one of them, or production's own remote URL, as a remote.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

ENV = "B4HIM_LINE_PROFILE"
KEYS = ("repo", "site", "cadence_days", "per_week_cap", "review_lead_days", "allow_date_apply")
OPTIONAL = ("ledger",)
#: The repo this file lives in. On the production machine that is the production checkout.
HOME = Path(__file__).resolve().parent.parent


class ProfileRefused(SystemExit):
    """Raised before anything runs. A SystemExit, so a command line prints the plain message and exits 1."""


@dataclass(frozen=True)
class Profile:
    path: Path
    repo: Path
    site: str
    cadence_days: tuple
    per_week_cap: int
    review_lead_days: int
    allow_date_apply: bool
    ledger: Path | None


def _key(p) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def _git(where: Path, *args: str) -> str | None:
    try:
        p = subprocess.run(["git", "-C", str(where), *args], capture_output=True)
    except OSError:
        return None
    return p.stdout.decode("utf-8", "replace").strip() if p.returncode == 0 else None


def _common_dir(where: Path) -> str | None:
    out = _git(where, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return _key(out) if out else None


def _remote_urls(where: Path) -> list[str]:
    out = _git(where, "config", "--get-regexp", r"^remote\..*\.url$") or ""
    return [line.split(" ", 1)[1] for line in out.splitlines() if " " in line]


def production_roots() -> set[str]:
    """Every path that names the production checkout, normalised (case and links) for comparison."""
    roots = {_key(HOME)}
    top = _git(HOME, "rev-parse", "--show-toplevel")
    if top:
        roots.add(_key(top))
    common = _common_dir(HOME)
    if common:
        roots.add(_key(Path(common).parent))     # <main checkout>/.git -> the main checkout
    return roots


def production_refusal(repo: Path) -> str | None:
    """Why `repo` may not be a profile's repo, or None. Judged on resolved paths, never on names."""
    roots = production_roots()
    if _key(repo) in roots:
        return f"profile repo {repo} is the production repo"
    top = _git(repo, "rev-parse", "--show-toplevel")
    if top and _key(top) in roots:
        return f"profile repo {repo} is inside the production repo ({top})"
    common, prod_common = _common_dir(repo), _common_dir(HOME)
    if common and prod_common and common == prod_common:
        return f"profile repo {repo} shares the production repo's git directory (a worktree of it): its pushes go " \
               f"to production's origin"
    prod_urls = {u.strip() for u in _remote_urls(HOME)}
    for url in _remote_urls(repo):
        if url.strip() in prod_urls:
            return f"profile repo {repo} has production's remote {url} as a remote"
        local = Path(url[len("file://"):] if url.startswith("file://") else url)
        if local.is_absolute() and (_key(local) in roots or (prod_common and _key(local) == prod_common)):
            return f"profile repo {repo} has the production repo ({url}) as a remote"
    return None


def _refuse(path, why: str) -> ProfileRefused:
    return ProfileRefused(f"REFUSED: line profile {path} ({ENV}): {why}. Nothing ran.")


def load(path=None) -> Profile | None:
    """The active profile, or None when B4HIM_LINE_PROFILE is unset (or empty). Refuses, before anything runs, a
    profile that is unreadable, has missing, unknown or mistyped keys, or names the production repo."""
    path = path if path is not None else os.environ.get(ENV, "").strip()
    if not path:
        return None
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _refuse(path, f"unreadable ({type(e).__name__}: {e})") from None
    if not isinstance(data, dict):
        raise _refuse(path, "not a JSON object")
    missing = [k for k in KEYS if k not in data]
    unknown = sorted(set(data) - set(KEYS) - set(OPTIONAL))
    if missing or unknown:
        raise _refuse(path, "; ".join(([f"missing {', '.join(missing)}"] if missing else [])
                                      + ([f"unknown {', '.join(unknown)}"] if unknown else [])))
    days, cap, lead = data["cadence_days"], data["per_week_cap"], data["review_lead_days"]
    if not (isinstance(days, list) and days and all(type(d) is int and 0 <= d <= 6 for d in days)):
        raise _refuse(path, "cadence_days must be a non-empty list of weekdays 0..6")
    if type(cap) is not int or cap < 1 or type(lead) is not int or lead < 0:
        raise _refuse(path, "per_week_cap must be an int >= 1 and review_lead_days an int >= 0")
    if type(data["allow_date_apply"]) is not bool:
        raise _refuse(path, "allow_date_apply must be true or false")
    site = data["site"]
    if not (isinstance(site, str) and site.startswith(("http://", "https://"))):
        raise _refuse(path, "site must be an http(s) URL")
    repo = Path(str(data["repo"]))
    if not repo.is_absolute() or not repo.is_dir():
        raise _refuse(path, f"repo {repo} is not an existing absolute directory")
    why = production_refusal(repo)
    if why:
        raise _refuse(path, why)
    ledger = data.get("ledger")
    return Profile(path=Path(path), repo=repo.resolve(), site=site.rstrip("/"), cadence_days=tuple(sorted(set(days))),
                   per_week_cap=cap, review_lead_days=lead, allow_date_apply=data["allow_date_apply"],
                   ledger=Path(ledger) if ledger else None)


def get(key: str, default):
    """The profile's value for `key`, or `default` itself (same object) when no profile is set."""
    if key not in KEYS + OPTIONAL:
        raise KeyError(key)
    prof = load()
    return default if prof is None else getattr(prof, key)


class FileLedger:
    """A local stand-in for the harness ledger, used only under a profile (approvals.ledger). Same surface approvals.py
    and release.py use: rulings_owed(), append(), path. One JSON event per line; ids S00001.."""

    def __init__(self, path):
        self.path = Path(path)

    def raw(self) -> list[dict]:
        if not self.path.exists():
            return []
        return [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def append(self, kind: str, by: str, body: dict, subject: str | None = None) -> dict:
        ev = {"id": f"S{len(self.raw()) + 1:05d}", "kind": kind, "by": by, "body": body}
        with self.path.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def rulings_owed(self) -> list[dict]:
        events = self.raw()
        superseded = {e["body"]["target"] for e in events if e["kind"] == "SUPERSEDE"}
        return [e for e in events if e["kind"] == "RULING" and not e["body"].get("applied")
                and e["id"] not in superseded]
