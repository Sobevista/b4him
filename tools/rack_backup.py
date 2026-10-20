#!/usr/bin/env python3
"""
rack_backup.py - the egg rack's off-machine copy.

Daniel, 2026-10-20 (ledger E00762): "weekly sha256-stamped git bundle of refs/tags/approved/* into Daniel's Google
Drive for desktop folder; approved tags never pushed to the public origin." ("Sure go with Drive that is a cool
seperation of concerns.")

The approved/<id> tags keep Daniel's approved bytes reachable in git's object store. They live on this machine
only - b4him's origin is public, so they are never pushed. This tool copies them somewhere else that is not GitHub.

WHAT A RUN DOES, refusing at the first thing that is not exactly right:
  1. resolve the destination, in order: --dest, env B4HIM_RACK_DEST, else "<X>:\\My Drive\\b4him-rack" on the first
     drive letter that has a "My Drive" (Google Drive for desktop). A named destination that does not exist is a
     FAIL - it never falls through to the next source, never creates a stand-in, never writes anywhere else.
  2. list refs/tags/approved/* (zero tags is a FAIL: there is nothing to back up, and that is not normal)
  3. `git bundle create` from exactly those refs, `git bundle verify` it, and check the bundle's heads equal the
     tags (name AND object id); only then is it moved into place as <name>.bundle beside <name>.sha256
  4. keep the newest --keep bundles (default 8) in the destination; only files this tool names are touched
  5. ask origin, read-only, whether any approved/* tag is on it (`git ls-remote`): they must not be
  6. append one line to rack_backup_log.jsonl (git-ignored), whatever happened

This tool never pushes: every git call goes through _git(), which runs only an allowlist of read/bundle
subcommands (ALLOWED_GIT) and refuses anything else before git starts.

EXIT CODES - outcomes say what is KNOWN; UNKNOWN never rounds to OK:
  0  backup written and verified; origin checked and holds no approved tags
  2  could not back up (no destination, no tags, git failure, verify failure). Nothing was written.
  3  backup written - but approved tags ARE on origin (a leak to the public repo; act on it)
  4  backup written - but the origin check could not run (offline, no origin): origin state UNKNOWN

    py tools/rack_backup.py                          # weekly run (Task Scheduler)
    py tools/rack_backup.py --dest D:\\somewhere     # explicit destination (must already exist)
    py tools/rack_backup.py --restore-check "G:\\My Drive\\b4him-rack\\b4him-approved-....bundle"
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import string
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_NAME = "rack_backup_log.jsonl"
PREFIX = "b4him-approved-"
NAME_RE = re.compile(r"^b4him-approved-\d{8}T\d{6}\d{6}Z\.bundle$")
TAG_NS = "refs/tags/approved/"
DRIVE_SUBFOLDER = "b4him-rack"
ENV_DEST = "B4HIM_RACK_DEST"

OK, FAIL, LEAK, ORIGIN_UNKNOWN = 0, 2, 3, 4


class RackError(Exception):
    """A reason the backup cannot be made. Always exit 2."""


# ---------------------------------------------------------------- git (the only door; it has no push)

# An allowlist, not a denylist: the only git subcommands this tool may run. None of them writes to a remote
# (fetch runs only inside restore_check's throwaway scratch repo). No "-c" overrides either.
ALLOWED_GIT = frozenset({"for-each-ref", "bundle", "ls-remote", "init", "fetch"})


def _git(args, cwd, stdin=None, check=True):
    args = [str(a) for a in args]
    if not args or args[0] not in ALLOWED_GIT or any(a == "-c" or a.startswith("--config") for a in args):
        raise RackError(f"refused: rack_backup never pushes and runs only {sorted(ALLOWED_GIT)} "
                        f"(asked for: git {' '.join(args)})")
    p = subprocess.run(["git", *args], cwd=str(cwd), input=stdin, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if check and p.returncode != 0:
        raise RackError(f"git {' '.join(map(str, args))} failed ({p.returncode}): {p.stderr.strip()}")
    return p


def approved_tags(repo):
    """{refname: object id} for refs/tags/approved/*."""
    out = _git(["for-each-ref", "--format=%(objectname) %(refname)", TAG_NS], repo).stdout
    tags = {}
    for line in out.splitlines():
        if line.strip():
            oid, ref = line.split(" ", 1)
            tags[ref] = oid
    return tags


def bundle_heads(bundle, repo):
    """{refname: object id} the bundle carries."""
    out = _git(["bundle", "list-heads", str(bundle)], repo).stdout
    heads = {}
    for line in out.splitlines():
        if line.strip():
            oid, ref = line.split(" ", 1)
            heads[ref] = oid
    return heads


def origin_check(repo):
    """('clean', []) | ('leak', [refs]) | ('unknown', reason). Read-only: ls-remote."""
    p = _git(["ls-remote", "--tags", "origin", TAG_NS + "*"], repo, check=False)
    if p.returncode != 0:
        return "unknown", (p.stderr.strip() or f"ls-remote exit {p.returncode}")
    refs = sorted({line.split("\t", 1)[1].removesuffix("^{}") for line in p.stdout.splitlines() if "\t" in line})
    return ("leak", refs) if refs else ("clean", [])


# ---------------------------------------------------------------- destination

def find_drive_mydrive():
    """The first '<X>:\\My Drive' that exists, or None. Google Drive for desktop mounts here."""
    for letter in string.ascii_uppercase:
        p = Path(f"{letter}:\\My Drive")
        try:
            if p.is_dir():
                return p
        except OSError:
            continue
    return None


def resolve_dest(cli_dest, env=None, find_drive=find_drive_mydrive):
    """(Path, source). Raises RackError; never falls through past a destination that was named but is missing."""
    env = os.environ if env is None else env
    if cli_dest:
        d = Path(cli_dest)
        if not d.is_dir():
            raise RackError(f"--dest {d} does not exist (it is not created for you)")
        return d, "--dest"
    if env.get(ENV_DEST):
        d = Path(env[ENV_DEST])
        if not d.is_dir():
            raise RackError(f"{ENV_DEST}={d} does not exist (it is not created for you)")
        return d, ENV_DEST
    mydrive = find_drive()
    if mydrive is None:
        raise RackError("no destination: no --dest, no " + ENV_DEST + ", and no Google Drive for desktop "
                        "'<X>:\\My Drive' on any drive letter (is Drive for desktop installed, signed in, running?)")
    d = mydrive / DRIVE_SUBFOLDER
    d.mkdir(exist_ok=True)  # only ever inside a My Drive that is really there
    return d, "google-drive"


# ---------------------------------------------------------------- files

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def read_sidecar(bundle):
    side = Path(bundle).with_suffix(".sha256")
    if not side.is_file():
        raise RackError(f"no sha256 sidecar beside the bundle: {side}")
    text = side.read_text(encoding="utf-8").strip()
    digest = text.split()[0].lower() if text else ""
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RackError(f"sidecar {side} does not hold a sha256")
    return digest


def stamp():
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def prune(dest, keep):
    """Delete all but the newest `keep` bundles this tool named (and their sidecars). Returns removed names."""
    bundles = sorted(p for p in Path(dest).iterdir() if NAME_RE.match(p.name))
    removed = []
    for old in bundles[:-keep] if keep > 0 else []:
        old.unlink()
        side = old.with_suffix(".sha256")
        if side.exists():
            side.unlink()
        removed.append(old.name)
    return removed


def append_log(log_path, entry):
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, sort_keys=True) + "\n")


# ---------------------------------------------------------------- the run

def backup(repo, dest, keep=8):
    """Write, verify and place one bundle. Returns (bundle_path, sha256, tag count, pruned)."""
    tags = approved_tags(repo)
    if not tags:
        raise RackError(f"no {TAG_NS}* tags in {repo}: nothing to back up")
    name = PREFIX + stamp()
    final = Path(dest) / (name + ".bundle")
    side = Path(dest) / (name + ".sha256")
    if final.exists() or side.exists():
        raise RackError(f"{final} already exists; refusing to overwrite")
    with tempfile.TemporaryDirectory(prefix="rack_") as tmp:
        work = Path(tmp) / (name + ".bundle")
        _git(["bundle", "create", str(work), "--stdin"], repo, stdin="\n".join(sorted(tags)) + "\n")
        _git(["bundle", "verify", str(work)], repo)
        heads = bundle_heads(work, repo)
        if heads != tags:
            raise RackError(f"bundle heads do not equal the approved tags: missing {sorted(set(tags) - set(heads))}, "
                            f"extra {sorted(set(heads) - set(tags))}, moved "
                            f"{sorted(r for r in tags if r in heads and heads[r] != tags[r])}")
        digest = sha256_file(work)
        partial = final.with_suffix(".bundle.partial")
        shutil.copyfile(work, partial)
        if sha256_file(partial) != digest:
            partial.unlink()
            raise RackError(f"copy into {dest} did not hash back to {digest}")
        partial.replace(final)
    side.write_text(f"{digest}  {final.name}\n", encoding="utf-8")
    pruned = prune(dest, keep)
    return final, digest, len(tags), pruned


def restore_check(bundle):
    """Verify sha256 against the sidecar, verify the bundle, and fetch it into a fresh scratch repo.
    Returns {"sha256", "tags": {ref: oid}}. Raises RackError."""
    bundle = Path(bundle)
    if not bundle.is_file():
        raise RackError(f"no such bundle: {bundle}")
    want = read_sidecar(bundle)
    got = sha256_file(bundle)
    if got != want:
        raise RackError(f"sha256 MISMATCH: sidecar {want}, bundle {got}")
    with tempfile.TemporaryDirectory(prefix="rack_restore_") as tmp:
        _git(["init", "-q", tmp], tmp)
        _git(["bundle", "verify", str(bundle)], tmp)
        heads = bundle_heads(bundle, tmp)
        _git(["fetch", "-q", str(bundle), "refs/tags/*:refs/tags/*"], tmp)
        restored = approved_tags(tmp)
    if restored != heads:
        raise RackError(f"fetch from the bundle restored {len(restored)} tags, bundle lists {len(heads)}")
    return {"sha256": got, "tags": heads}


def run(argv=None, env=None, find_drive=find_drive_mydrive):
    ap = argparse.ArgumentParser(description="Back up refs/tags/approved/* as a sha256-stamped git bundle.")
    ap.add_argument("--dest", help="destination folder (must exist)")
    ap.add_argument("--repo", default=str(REPO_ROOT), help="repository to back up (default: this tool's repo)")
    ap.add_argument("--keep", type=int, default=8, help="bundles to keep in the destination (default 8)")
    ap.add_argument("--log", help=f"log file (default <repo>/{LOG_NAME})")
    ap.add_argument("--restore-check", metavar="BUNDLE", help="drill: verify a bundle and list its tags")
    a = ap.parse_args(argv)

    if a.restore_check:
        try:
            r = restore_check(a.restore_check)
        except RackError as e:
            print(f"RESTORE-CHECK FAIL: {e}", file=sys.stderr)
            return FAIL
        for ref, oid in sorted(r["tags"].items()):
            print(f"{oid} {ref}")
        print(f"RESTORE-CHECK OK: sha256 {r['sha256']} matches; {len(r['tags'])} tags verified and restored "
              f"into a scratch repo")
        return OK

    repo = Path(a.repo)
    log_path = Path(a.log) if a.log else repo / LOG_NAME
    entry = {"date": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "repo": str(repo)}
    if a.keep < 1:
        print("FAIL: --keep must be at least 1", file=sys.stderr)
        return FAIL
    try:
        dest, source = resolve_dest(a.dest, env=env, find_drive=find_drive)
        entry.update(dest=str(dest), dest_source=source)
        bundle, digest, count, pruned = backup(repo, dest, a.keep)
        entry.update(bundle=bundle.name, sha256=digest, tag_count=count, pruned=pruned)
    except RackError as e:
        entry.update(outcome="FAIL", reason=str(e))
        append_log(log_path, entry)
        print(f"FAIL (exit 2): {e}", file=sys.stderr)
        return FAIL

    state, detail = origin_check(repo)
    entry["origin_check"] = state
    print(f"WROTE {bundle} ({count} tags, sha256 {digest}); kept newest {a.keep}, pruned {len(pruned)}")
    if state == "clean":
        entry["outcome"] = "OK"
        code = OK
        print("origin: holds no approved/* tags (checked)")
    elif state == "leak":
        entry.update(outcome="LEAK", origin_tags=detail)
        code = LEAK
        print("!" * 72 + f"\nLEAK: {len(detail)} approved/* tag(s) ARE ON ORIGIN (public): {', '.join(detail)}\n"
              + "!" * 72, file=sys.stderr)
    else:
        entry.update(outcome="ORIGIN-UNKNOWN", origin_reason=detail)
        code = ORIGIN_UNKNOWN
        print(f"ORIGIN UNKNOWN (exit 4): could not ask origin about approved/* tags: {detail}", file=sys.stderr)
    append_log(log_path, entry)
    return code


if __name__ == "__main__":
    sys.exit(run())
