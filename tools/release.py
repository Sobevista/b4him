#!/usr/bin/env python3
"""
release.py — the egg rack's actuator. On a release day it publishes the piece the board gives that slot.

Daniel, 2026-10-13 (ledger E00472, amending PRODUCTION_PLAN sections 2-3): "every release day we should have
content ... make the extraction, updating, and approval of automatic", ruled as "One tap, auto after". He stays
the only gate; everything after his approval runs by itself.

HOW A PIECE WAITS (the rack). His approval pins the exact bytes he previewed as `approved_blobs`
{path: git blob id} on the piece's queue row, on main. The bytes wait in git's object store (kept reachable by a
`approved/<id>` tag), not in the tree, so nothing is live early and no branch has to be merged on the day.

WHAT A RELEASE DOES, in order, refusing at the first thing that is not exactly right:
  1. today is a Tue/Fri slot, the board gives it a piece, and the 2-per-7-days cap has room
  2. main is checked out and clean (and, with --push, not behind origin)
  3. each approved blob is written to its path and re-hashed to the approved id
  4. the row becomes PUBLISHED (only that line of the queue changes), the lessons index track blocks and the
     board are regenerated, and every site-root link in the touched pages resolves in the new tree
  5. one commit, explicit paths; --push pushes main, --verify-live waits for the live bytes to hash to the
     approved blob
Any refusal after step 2 restores the tree. Every run, publish or skip or failure, appends to release_log.jsonl:
a release day with no log line is a job that did not run, never a quiet success.

    py tools/release.py                      # dry run for today: what would publish, and why
    py tools/release.py --date 2026-10-20    # dry run for another day
    py tools/release.py --apply --push --verify-live    # the scheduled run (today only)
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import production_board as pb  # noqa: E402

SITE = "https://b4him.com"
TRACK_RE = re.compile(r"(<!-- b4him:track (?P<track>[\w-]+) [^>]*-->\n)(?P<body>.*?)(<!-- /b4him:track (?P=track) -->)",
                      re.S)
ENTRY = ('    <a class="mod" href="{href}">\n'
         '      <span class="n">{numeral}</span>\n'
         '      <span><h2>{title}</h2><p>{blurb}</p></span>\n'
         '    </a>')
LINK_RE = re.compile(r'(?:href|src)="(/[^"#?]*)')


class ReleaseError(RuntimeError):
    pass


def repo() -> Path:
    return pb.REPO           # read at call time so tests can point it at a scratch repo


def git(*args: str, binary: bool = False, check: bool = True):
    p = subprocess.run(["git", "-C", str(repo()), *args], capture_output=True)
    if check and p.returncode:
        raise ReleaseError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


# ---------------------------------------------------------------- what is due
def published_on(row: dict) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(row.get("published", ""))[:10])
    except ValueError:
        return None


def plan(day: dt.date) -> dict:
    """What the release for `day` would do. Pure reading; never touches the tree."""
    rows = [r for r in pb.load_queue() if not r.get("_broken")]
    if day.weekday() not in pb.CADENCE_DAYS:
        return {"outcome": "SKIP", "why": f"{day:%a} is not a release day (Tue/Fri)"}
    recent = [r for r in rows if (p := published_on(r)) and day - dt.timedelta(days=6) <= p <= day]
    if len(recent) >= pb.PER_WEEK_CAP:
        return {"outcome": "SKIP", "why": f"cap: {len(recent)} published in the 7 days to {day} "
                                          f"({', '.join(r['id'] for r in recent)})"}
    eligible, _ = pb.eligible_pieces(rows)
    _, taken = pb.assign_slots(eligible, pb.next_slots(day - dt.timedelta(days=1), 12))
    piece = taken.get(day)
    if piece is None:
        return {"outcome": "SKIP", "why": "no eligible piece holds this slot (nothing PREVIEWED by T-7, or drifted)"}
    if not piece.get("approved_blobs"):
        return {"outcome": "FAIL", "piece": piece["id"],
                "why": "the piece holds the slot but has no approved_blobs: there are no pinned bytes to publish"}
    return {"outcome": "PUBLISH", "piece": piece["id"], "row": piece}


# ---------------------------------------------------------------- the index
def render_tracks(index_html: str, rows: list[dict]) -> str:
    """Fill every `b4him:track` block from PUBLISHED rows carrying an index_entry for that track. A track with
    nothing published renders empty, so an empty heading never goes live."""
    def fill(m: re.Match) -> str:
        track = m.group("track")
        furniture = repo() / "tools" / "tracks" / f"{track}.html"
        entries = sorted((r for r in rows if pb.stage_index(r) >= pb.STAGES.index("PUBLISHED")
                          and (r.get("index_entry") or {}).get("track") == track),
                         key=lambda r: (r["index_entry"].get("position", r.get("order", 999)), r.get("id", "")))
        if not entries:
            return m.group(1) + m.group(4)
        if not furniture.exists():
            raise ReleaseError(f"track '{track}' has published entries but no furniture at {furniture}")
        block = furniture.read_text(encoding="utf-8").replace(
            "{{entries}}", "\n".join(ENTRY.format(**r["index_entry"]) for r in entries))
        return m.group(1) + block.lstrip("\n") + m.group(4)
    return TRACK_RE.sub(fill, index_html)


def broken_links(paths: list[Path]) -> list[str]:
    bad = []
    for p in paths:
        if p.suffix != ".html" or not p.exists():
            continue
        for link in LINK_RE.findall(p.read_text(encoding="utf-8")):
            if link.startswith("//"):
                continue
            target = repo() / link.lstrip("/")
            ok = (target / "index.html").exists() if link.endswith("/") else (
                target.exists() and target.is_file() or (target / "index.html").exists())
            if not ok:
                bad.append(f"{p.relative_to(repo()).as_posix()} -> {link}")
    return bad


# ---------------------------------------------------------------- the act
def set_published(queue_text: str, pid: str, day: dt.date) -> str:
    """Rewrite exactly one queue line; every other byte stays."""
    out, hits = [], 0
    for line in queue_text.split("\n"):
        s = line.strip()
        if s.startswith("{") and json.loads(s).get("id") == pid:
            row = json.loads(s)
            row.update(stage="PUBLISHED", published=day.isoformat(), since=day.isoformat())
            line, hits = json.dumps(row, ensure_ascii=False), hits + 1
        out.append(line)
    if hits != 1:
        raise ReleaseError(f"expected exactly one queue row with id {pid}, found {hits}")
    return "\n".join(out)


def apply(day: dt.date, decision: dict, push: bool) -> str:
    if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
        raise ReleaseError("not on main: a release writes to main and nowhere else")
    if git("status", "--porcelain").strip():
        raise ReleaseError("the tree is not clean: a release commits only its own changes, so it refuses to "
                           "start on top of someone else's")
    if push:
        git("fetch", "-q", "origin", "main")
        if git("rev-list", "--count", "main..origin/main").strip() != "0":
            raise ReleaseError("main is behind origin: something was pushed from elsewhere; a human looks first")

    row, pid = decision["row"], decision["piece"]
    root = repo()
    created, touched = [], []
    try:
        for rel, blob in row["approved_blobs"].items():
            dest = root / rel
            if dest.exists() and pb.blob_sha(dest) != blob and row.get("kind") != "revision of a published page":
                raise ReleaseError(f"{rel} already exists with other bytes, and the piece is not a revision")
            if not dest.exists():
                created.append(dest)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(git("cat-file", "blob", blob, binary=True))
            if pb.blob_sha(dest) != blob:
                raise ReleaseError(f"{rel}: wrote the approved blob and it hashed to something else")
            touched.append(dest)

        pb.QUEUE.write_text(set_published(pb.QUEUE.read_text(encoding="utf-8"), pid, day),
                            encoding="utf-8", newline="\n")
        touched.append(pb.QUEUE)
        index = root / "lessons" / "index.html"
        if index.exists():
            new = render_tracks(index.read_text(encoding="utf-8"), [r for r in pb.load_queue() if not r.get("_broken")])
            index.write_text(new, encoding="utf-8", newline="\n")
            touched.append(index)
        bad = broken_links(touched)
        if bad:
            raise ReleaseError("links that would 404 once live: " + "; ".join(bad))
        pb.BOARD.write_text(pb.build(day), encoding="utf-8", newline="\n")
        touched.append(pb.BOARD)

        rels = sorted({p.relative_to(root).as_posix() for p in touched})
        git("add", "--", *rels)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".txt", delete=False) as fh:
            fh.write(f"PUBLISHED {pid} on its {day:%a} {day} slot: {row.get('title', pid)}\n\n"
                     f"Written by tools/release.py from the bytes Daniel approved (approved_blobs), "
                     f"re-hashed before commit.\n")
            msg = fh.name
        git("commit", "-q", "-F", msg)
        Path(msg).unlink(missing_ok=True)
    except Exception:
        git("reset", "-q", "--", ".", check=False)
        git("checkout", "--", ".", check=False)
        for p in created:
            p.unlink(missing_ok=True)
        raise
    return git("rev-parse", "HEAD").strip()


def verify_live(row: dict, minutes: int) -> str:
    deadline = time.time() + minutes * 60
    pending = dict(row["approved_blobs"])
    while pending and time.time() < deadline:
        for rel, blob in list(pending.items()):
            url = f"{SITE}/{rel[:-len('index.html')] if rel.endswith('/index.html') else rel}"
            try:
                req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "b4him-release"})
                data = urllib.request.urlopen(req, timeout=20).read().replace(b"\r\n", b"\n")
                if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob:
                    del pending[rel]
            except OSError:
                pass
        if pending:
            time.sleep(30)
    if pending:
        raise ReleaseError(f"pushed, but after {minutes} min the live bytes do not match yet: {', '.join(pending)}")
    return "live bytes match the approved blobs"


def log(entry: dict) -> None:
    entry = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **entry}
    entry.pop("row", None)
    with (repo() / "release_log.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--date", help="ISO date (dry runs only)")
    ap.add_argument("--apply", action="store_true", help="publish (today only)")
    ap.add_argument("--push", action="store_true", help="push main after the commit")
    ap.add_argument("--verify-live", action="store_true", help="wait for the live bytes to match")
    ap.add_argument("--live-minutes", type=int, default=15)
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    today = dt.date.today()
    day = dt.date.fromisoformat(a.date) if a.date else today
    if a.apply and day != today:
        print(f"REFUSED: --apply publishes today ({today}) only; {day} is a dry run.")
        return 1
    decision = plan(day)
    entry = {"date": day.isoformat(), "mode": "apply" if a.apply else "dry-run", **decision}
    code = 0
    if decision["outcome"] == "PUBLISH" and a.apply:
        try:
            entry["commit"] = apply(day, decision, a.push)
            entry["pushed"] = False
            if a.push:
                git("push", "-q", "origin", "main")
                entry["pushed"] = True
                if a.verify_live:
                    entry["live"] = verify_live(decision["row"], a.live_minutes)
        except ReleaseError as e:
            # A failure after the commit leaves that commit on local main: say so, so nobody believes the page is live.
            where = f" (commit {entry['commit'][:7]} is on local main, pushed={entry['pushed']})" if entry.get("commit") else ""
            entry.update(outcome="FAIL", why=str(e) + where)
            code = 1
    elif decision["outcome"] == "FAIL":
        code = 1
    if a.apply:
        log(entry)
    print(f"{entry['outcome']}  {day} {day:%a}  {entry.get('piece', '')}  {entry.get('why', '')}"
          + (f"  commit {entry['commit'][:7]}" if entry.get("commit") else "")
          + (f"  {entry['live']}" if entry.get("live") else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
