#!/usr/bin/env python3
"""
binding.py - the v3 approval binding, and the one named exception to it.  (build: production-boundary-v1)

WHY. Until now a queue row alone said "approved": approved_blobs {path: blob} on a row at PREVIEWED. Anything that can
write production_queue.jsonl could therefore forge a publishable piece. The v3 binding makes the release re-derive
the approval at release time instead of trusting the row:

    row["binding"] = {"version": 3, "commit": <approved commit>, "digest": sha256(id, blobs, index-entry pin, commit)}

and `problems(row)` holds a piece back unless ALL of these are true at the moment of release:
  * the marker is there and is version 3 (so pieces racked before this build are UNVERIFIED, not assumed fine);
  * the digest recomputes from the row as it is NOW (an altered package or hand-edited blob id breaks it);
  * the approved commit exists in this repo, and every pinned path holds exactly the pinned blob at that commit;
  * the tag approved/<id> (written by approvals.apply) points at that same commit.

THE ONE EXCEPTION. data/release_legacy_exceptions.json names GC-GLOSS-1 (Glossary I): Daniel approved it before v3 and
restated it on 2026-10-15. The file is data, but the id is ALSO pinned in code (LEGACY_ALLOWED_IDS), so widening the
exception takes a deliberate change in two places. It covers an exact id and nothing else (no prefix, no case fold,
no revisions of that piece), and it pins the approved bytes by digest, so a forged or altered row under that id is
refused too.

WHAT THIS DOES NOT DO. It cannot stop a process that holds the repo and can write the queue, the commit AND the tag
from forging all three: that needs an identity the OS enforces (see the build report). It removes the cheap forgeries
and makes the expensive one leave git history.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import production_board as pb

BINDING_VERSION = 3
DATA = Path(__file__).resolve().parent.parent / "data"
LEGACY_FILE = DATA / "release_legacy_exceptions.json"
UNVERIFIED_FILE = DATA / "unverified_tiles.json"
#: The legacy exception may name these ids and no others, whatever the data file says.
LEGACY_ALLOWED_IDS = frozenset({"GC-GLOSS-1"})


class BindingError(RuntimeError):
    pass


def digest(row: dict) -> str:
    """What the approval covers: the piece, its exact bytes, its index-entry pin and the commit Daniel saw."""
    body = {"id": row.get("id"), "approved_blobs": row.get("approved_blobs") or {},
            "approved_index_entry": row.get("approved_index_entry"), "approved_commit": row.get("approved_commit"),
            "version": BINDING_VERSION}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def bytes_digest(row: dict) -> str:
    """The legacy pin: the approved bytes and index-entry pin only (a pre-v3 row has no commit recorded)."""
    body = {"id": row.get("id"), "approved_blobs": row.get("approved_blobs") or {},
            "approved_index_entry": row.get("approved_index_entry")}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def make(row: dict) -> dict:
    """The binding approvals.rack writes onto a row it has just racked."""
    if not row.get("approved_commit"):
        raise BindingError(f"{row.get('id')}: no approved_commit, so there is nothing to bind to")
    return {"version": BINDING_VERSION, "commit": row["approved_commit"], "digest": digest(row)}


def _git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(pb.REPO), *args], capture_output=True)


def legacy_exceptions(path: Path | None = None) -> dict[str, dict]:
    """{id: entry} from the data file. Refuses a file that names more than one piece or any id the code does not
    also name: the exception is single by construction."""
    path = path or LEGACY_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BindingError(f"legacy exception file unreadable ({path}): {e}") from None
    entries = data.get("exceptions") if isinstance(data, dict) else None
    if not isinstance(entries, list):
        raise BindingError("legacy exception file has no 'exceptions' list")
    if len(entries) > 1:
        raise BindingError(f"the legacy exception is single: {len(entries)} entries named")
    out = {}
    for e in entries:
        pid = e.get("id") if isinstance(e, dict) else None
        if not isinstance(pid, str) or pid not in LEGACY_ALLOWED_IDS:
            raise BindingError(f"legacy exception names {pid!r}, which the code does not allow")
        out[pid] = e
    return out


def legacy_problems(row: dict, path: Path | None = None) -> list[str]:
    """[] if `row` is exactly the piece the legacy exception names AND holds exactly the bytes its approved_digest pins.
    The digest is REQUIRED: an entry without one covers nothing."""
    try:
        exc = legacy_exceptions(path)
    except BindingError as e:
        return [str(e)]
    rid = row.get("id")
    entry = exc.get(rid) if isinstance(rid, str) else None
    if entry is None:
        return [f"{rid} is not covered by the legacy exception"]
    want = entry.get("approved_digest")
    if not isinstance(want, str) or not want.strip():
        return [f"{rid}: the legacy exception carries no approved_digest, so it pins no bytes and covers nothing"]
    if bytes_digest(row) != want:
        return [f"{row.get('id')}: the approved bytes are not the ones the legacy exception pins"]
    return []


def problems(row: dict, legacy_path: Path | None = None) -> list[str]:
    """Why this piece may not be released now. [] means eligible. Every reason says UNVERIFIED where the cause is a
    missing or unprovable binding, so a pre-v3 piece is never read as merely 'not yet'."""
    b = row.get("binding")
    if not isinstance(b, dict) or b.get("version") is None:
        # No v3 marker. Only the one named piece may go on without it.
        leg = legacy_problems(row, legacy_path)
        if not leg:
            return []
        return [f"UNVERIFIED: {row.get('id')} carries no v3 binding (racked before production-boundary-v1) and is "
                f"not the named legacy piece ({'; '.join(leg)}); it must be re-qualified by a fresh approval"]
    out = []
    if b.get("version") != BINDING_VERSION:
        return [f"UNVERIFIED: binding version {b.get('version')!r}, release requires {BINDING_VERSION}"]
    if not row.get("approved_commit") or b.get("commit") != row.get("approved_commit"):
        out.append("binding commit does not match approved_commit")
    if b.get("digest") != digest(row):
        out.append("binding digest does not match the row (blobs, index-entry pin or commit were changed after "
                   "the approval was bound)")
    commit = row.get("approved_commit")
    if commit:
        if _git("cat-file", "-e", f"{commit}^{{commit}}").returncode:
            out.append(f"approved commit {str(commit)[:7]} is not in this repository")
        else:
            for rel, blob in (row.get("approved_blobs") or {}).items():
                p = _git("rev-parse", f"{commit}:{rel}")
                have = p.stdout.decode().strip() if p.returncode == 0 else None
                if have != blob:
                    out.append(f"{rel}: the approved commit holds {have[:12] if have else 'nothing'}, the row pins "
                               f"{blob[:12]}")
            tag = _git("rev-parse", f"refs/tags/approved/{row.get('id')}^{{commit}}")
            if tag.returncode or tag.stdout.decode().strip() != _git("rev-parse", commit).stdout.decode().strip():
                out.append(f"tag approved/{row.get('id')} is missing or does not point at the approved commit")
    return [f"UNVERIFIED: {x}" for x in out]


def unverified_tiles(path: Path | None = None) -> dict[str, dict]:
    """The tiles waiting on boards/APPROVALS_OWED.md that were offered before v3: {id: entry}. They hold no
    binding, so problems() refuses them whenever they are racked; this list is the record of that, as data."""
    data = json.loads((path or UNVERIFIED_FILE).read_text(encoding="utf-8"))
    return {e["id"]: e for e in data["tiles"]}
