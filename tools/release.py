#!/usr/bin/env python3
"""
release.py — the egg rack's actuator. On a release day it publishes the piece the board gives that slot.

Daniel, 2026-10-13 (ledger E00472, amending PRODUCTION_PLAN sections 2-3): "every release day we should have
content ... make the extraction, updating, and approval of automatic", ruled as "One tap, auto after". He stays
the only gate; everything after his approval runs by itself.

HOW A PIECE WAITS (the rack). His approval pins the exact bytes he previewed as `approved_blobs`
{path: git blob id} on the piece's queue row, on main — the page AND, for a piece listed in the lessons index, the
track's furniture file, with the index entry's text pinned by hash (`approved_index_entry`). The bytes wait in
git's object store (kept reachable by an `approved/<id>` tag), so nothing is live early and no branch is merged.

WHAT A RELEASE DOES, refusing at the first thing that is not exactly right:
  0. (--push) main is not behind origin, and carries nothing unpushed except a release commit stranded from
     today, which is re-pushed: a push sends every local commit, so anything else would go live unapproved
  1. today is a Tue/Fri slot, nothing has published today, the 2-per-7-days cap has room, and the board gives
     the slot a piece whose pins are whole
  2. main is checked out and clean
  3. each approved blob is written to its path and re-hashed to the approved id
  4. the row becomes PUBLISHED (only that queue line changes), the lessons-index track blocks and the board are
     regenerated, and every site-root link in the touched pages resolves in the new tree
  5. one commit, explicit paths; --push pushes it; --verify-live waits for the live bytes to hash to the blobs
Any refusal restores the tree. Every --apply run appends one line to release_log.jsonl, whatever happens: a
release day with no log line is a job that did not run, never a quiet success. Outcomes say what is KNOWN:
COMMITTED (not pushed), PUSHED-UNVERIFIED, PUBLISHED (live bytes matched), SKIP, FAIL.

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
ENTRY_KEYS = ("track", "numeral", "href", "title", "blurb")
LINK_RE = re.compile(r'(?:href|src)="(/[^"#?]*)')
RELEASE_SUBJECT = "PUBLISHED {pid} on its {day:%a} {day} slot: {title}"
#: The only files an unpushed non-release commit may touch and still ride out with a release (approvals.py).
BOOKKEEPING = {"production_queue.jsonl", "PRODUCTION_BOARD.md", "boards/APPROVALS_OWED.md"}


class ReleaseError(RuntimeError):
    pass


def repo() -> Path:
    return pb.REPO           # read at call time so tests can point it at a scratch repo


def git(*args: str, binary: bool = False, check: bool = True):
    p = subprocess.run(["git", "-C", str(repo()), *args], capture_output=True)
    if check and p.returncode:
        raise ReleaseError(f"git {' '.join(args)} failed: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def furniture_rel(track: str) -> str:
    return f"tools/tracks/{track}.html"


# ---------------------------------------------------------------- what is due
def published_on(row: dict) -> dt.date | None:
    try:
        return dt.date.fromisoformat(str(row.get("published", ""))[:10])
    except ValueError:
        return None


def pin_problems(row: dict) -> list[str]:
    """What is not pinned that would go live with this piece. The index entry is site content: its text and its
    track's furniture are approved with the page or the piece does not publish."""
    if not row.get("approved_blobs"):
        return ["no approved_blobs: there are no pinned bytes to publish"]
    entry = row.get("index_entry")
    if not entry:
        return []
    out = []
    missing = [k for k in ENTRY_KEYS if not entry.get(k)]
    if missing:
        out.append(f"index_entry lacks {', '.join(missing)}")
    if row.get("approved_index_entry") != pb.entry_sha(entry):
        out.append("index_entry text is not the text Daniel approved (approved_index_entry missing or changed)")
    if entry.get("track") and furniture_rel(entry["track"]) not in row["approved_blobs"]:
        out.append(f"the track furniture {furniture_rel(entry.get('track'))} is not pinned in approved_blobs")
    return out


def live_drift(rows: list[dict], skip=()) -> list[str]:
    """Content the lessons index would render that no approval pinned: a PUBLISHED row's index_entry that no longer
    hashes to its approved_index_entry, or track furniture in the tree that differs from the blob its latest
    published owner pinned. The index is regenerated from all of it on every release, so all of it must be pinned.
    `skip` names furniture the releasing piece replaces itself; apply() refuses a hand edit there on its own."""
    out = []
    for r in rows:
        if r.get("_broken") or pb.stage_index(r) < pb.STAGES.index("PUBLISHED"):
            continue
        if not r.get("index_entry"):
            if r.get("approved_index_entry"):
                out.append(f"{r.get('id')}: published index_entry was removed from the queue (an approved entry "
                           f"would vanish from the live index)")
            continue
        if r.get("approved_index_entry") != pb.entry_sha(r["index_entry"]):
            out.append(f"{r.get('id')}: published index_entry is not the text Daniel approved")
    for rel, (owner, want) in sorted(pb.published_owners(rows).items()):
        if rel.startswith(pb.SHARED_PREFIX) and rel not in skip:
            have = pb.blob_sha(repo() / rel)
            if have != want:
                out.append(f"{rel} is not the bytes {owner} pinned (pinned {want[:12]}, now "
                           f"{have[:12] if have else 'missing'})")
    return out


def plan(day: dt.date) -> dict:
    """What the release for `day` would do. Pure reading; never touches the tree."""
    rows = [r for r in pb.load_queue() if not r.get("_broken")]
    if day.weekday() not in pb.CADENCE_DAYS:
        return {"outcome": "SKIP", "why": f"{day:%a} is not a release day (Tue/Fri)"}
    today_pub = [r["id"] for r in rows if published_on(r) == day]
    if today_pub:
        return {"outcome": "SKIP", "why": f"already published today: {', '.join(today_pub)} (one slot, one piece)"}
    recent = [r for r in rows if (p := published_on(r)) and day - dt.timedelta(days=6) <= p <= day]
    if len(recent) >= pb.PER_WEEK_CAP:
        return {"outcome": "SKIP", "why": f"cap: {len(recent)} published in the 7 days to {day} "
                                          f"({', '.join(r['id'] for r in recent)})"}
    eligible, drifted = pb.eligible_pieces(rows)
    lost = [r["id"] for r in rows if pb.STAGES.index("RULED") <= pb.stage_index(r) < pb.STAGES.index("PUBLISHED")
            and any(not pb.blob_in_store(b) for b in (r.get("approved_blobs") or {}).values())]
    _, taken = pb.assign_slots(eligible, pb.next_slots(day - dt.timedelta(days=1), 12))
    piece = taken.get(day)
    live = live_drift(rows, skip=(piece.get("approved_blobs") or {}) if piece else ())
    if live:
        why = "live content that no approval pinned would be re-rendered: " + "; ".join(live)
        if piece is None and drifted:
            why += f"; changed since approval, so back with Daniel: {', '.join(drifted)}"
        return {"outcome": "FAIL", "why": why, **({"piece": piece["id"]} if piece else {})}
    if piece is None:
        if lost:
            return {"outcome": "FAIL", "why": f"approved bytes are gone from the object store for {', '.join(lost)}: "
                                              f"an approved piece lost its slot (restore its approved/<id> tag)"}
        why = "no eligible piece holds this slot (nothing PREVIEWED by T-7)"
        if drifted:
            why += f"; changed since approval, so back with Daniel: {', '.join(drifted)}"
        return {"outcome": "SKIP", "why": why}
    problems = pin_problems(piece)
    if problems:
        return {"outcome": "FAIL", "piece": piece["id"], "why": "; ".join(problems)}
    return {"outcome": "PUBLISH", "piece": piece["id"], "row": piece}


# ---------------------------------------------------------------- the index
def render_tracks(index_html: str, rows: list[dict], furniture_text=None) -> str:
    """Fill every `b4him:track` block from PUBLISHED rows carrying an index_entry for that track. A track with
    nothing published renders empty, so an empty heading never goes live."""
    def fill(m: re.Match) -> str:
        track = m.group("track")
        furniture = repo() / furniture_rel(track)
        entries = sorted((r for r in rows if pb.stage_index(r) >= pb.STAGES.index("PUBLISHED")
                          and (r.get("index_entry") or {}).get("track") == track),
                         key=lambda r: (r["index_entry"].get("position", r.get("order", 999)), r.get("id", "")))
        if not entries:
            return m.group(1) + m.group(4)
        text = furniture_text(track) if furniture_text else (
            furniture.read_text(encoding="utf-8") if furniture.exists() else None)
        if text is None:
            raise ReleaseError(f"track '{track}' has published entries but no furniture at {furniture}")
        try:
            items = "\n".join(ENTRY.format(**r["index_entry"]) for r in entries)
        except KeyError as e:
            raise ReleaseError(f"an index_entry in track '{track}' lacks {e}") from None
        block = text.replace("{{entries}}", items)
        return m.group(1) + block.lstrip("\n") + m.group(4)
    return TRACK_RE.sub(fill, index_html)


def broken_links(paths: list[Path]) -> list[str]:
    bad = []
    for p in paths:
        if p.suffix != ".html" or not p.exists() or "tools" in p.relative_to(repo()).parts:
            continue
        for link in LINK_RE.findall(p.read_text(encoding="utf-8")):
            if link.startswith("//"):
                continue
            target = repo() / link.lstrip("/")
            ok = (target / "index.html").exists() if link.endswith("/") else (
                target.is_file() or (target / "index.html").exists())
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


def apply(day: dt.date, decision: dict, push: bool = False) -> str:
    """Write, check and commit one release. Returns the commit. `push` is accepted for old callers; pushing and
    the origin checks live in preflight()/main()."""
    if decision.get("outcome") != "PUBLISH":
        raise ReleaseError(f"nothing to publish: {decision.get('outcome')} - {decision.get('why', '')}")
    if git("rev-parse", "--abbrev-ref", "HEAD").strip() != "main":
        raise ReleaseError("not on main: a release writes to main and nowhere else")
    if git("status", "--porcelain").strip():
        raise ReleaseError("the tree is not clean: a release commits only its own changes, so it refuses to "
                           "start on top of someone else's")

    row, pid = decision["row"], decision["piece"]
    live = live_drift([r for r in pb.load_queue() if not r.get("_broken")], skip=row.get("approved_blobs") or {})
    if live:
        raise ReleaseError("the lessons index would render content no approval pinned: " + "; ".join(live))
    root = repo()
    approved = pb.approved_bytes([r for r in pb.load_queue() if not r.get("_broken")])
    created_files: list[Path] = []
    created_dirs: list[Path] = []
    touched: list[Path] = []
    try:
        for rel, blob in row["approved_blobs"].items():
            dest = root / rel
            have = pb.blob_sha(dest) if dest.exists() else None
            if have is not None and have != blob:
                # Replacing bytes is allowed only where the piece may replace (a revision, or shared track
                # furniture) AND the tree holds bytes some approval pinned: a file edited outside an approval is
                # never overwritten, it is refused.
                if not pb.replaceable(row, rel):
                    raise ReleaseError(f"{rel} already exists with other bytes, and the piece is not a revision")
                if have not in approved.get(rel, set()):
                    raise ReleaseError(f"{rel} holds bytes no published piece approved ({have[:12]}); refusing "
                                       f"to overwrite an edit made outside an approval")
            if not dest.exists():
                created_files.append(dest)
                d = dest.parent
                while not d.exists():
                    created_dirs.append(d)
                    d = d.parent
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
            new = render_tracks(index.read_text(encoding="utf-8"),
                                [r for r in pb.load_queue() if not r.get("_broken")])
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
            fh.write(RELEASE_SUBJECT.format(pid=pid, day=day, title=row.get("title", pid)) + "\n\n"
                     "Written by tools/release.py from the bytes Daniel approved (approved_blobs), "
                     "re-hashed before commit.\n")
            msg = fh.name
        git("commit", "-q", "-F", msg)
        Path(msg).unlink(missing_ok=True)
    except Exception:
        git("reset", "-q", "--", ".", check=False)
        git("checkout", "--", ".", check=False)
        for p in created_files:
            p.unlink(missing_ok=True)
        for d in sorted(created_dirs, key=lambda p: len(p.parts), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass
        raise
    return git("rev-parse", "HEAD").strip()


def commit_paths(h: str) -> set[str]:
    """Every path commit `h` changes relative to ANY parent (a merge shows nothing against itself)."""
    parents = git("rev-list", "--parents", "-n", "1", h).split()[1:]
    if not parents:
        return set(git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", "-z", h).split("\0")) - {""}
    out: set[str] = set()
    for p in parents:
        out |= set(git("diff", "--no-renames", "--name-only", "-z", p, h).split("\0"))
    return out - {""}


def is_release_of(h: str, paths: set[str], row: dict) -> bool:
    """Is commit `h` the release of `row` (published today)? By paths and bytes: it touches only what the row
    pinned plus the queue/board/lessons-index the release writes, and every pinned path it touches holds the
    pinned blob."""
    pinned = row.get("approved_blobs") or {}
    if not paths <= set(pinned) | BOOKKEEPING | {"lessons/index.html"}:
        return False
    # a release rewrites the queue and holds at least one pinned path at its pinned blob
    hit = paths & set(pinned)
    if "production_queue.jsonl" not in paths or not hit:
        return False
    if not all(git("rev-parse", f"{h}:{rel}", check=False).strip() == pinned[rel] for rel in hit):
        return False
    # exactly one parent: the release is one step on top of main, never a merge
    parents = git("rev-list", "--parents", "-n", "1", h).split()[1:]
    if len(parents) != 1:
        return False
    parent = parents[0]
    try:
        if "lessons/index.html" not in paths:
            return git("rev-parse", f"{h}:lessons/index.html", check=False) == \
                git("rev-parse", f"{parent}:lessons/index.html", check=False)
        # the index is generated: render the PARENT's index (so nav, head and footer are the parent's, not the
        # commit's own) with this commit's queue and furniture; it must equal the committed index exactly
        lines = git("show", f"{h}:production_queue.jsonl").splitlines()
        rows = [json.loads(s) for s in (l.strip() for l in lines) if s and not s.startswith("#")]

        def furn(track: str):
            p = subprocess.run(["git", "-C", str(repo()), "show", f"{h}:{furniture_rel(track)}"],
                               capture_output=True)
            return p.stdout.decode("utf-8") if p.returncode == 0 else None
        return render_tracks(git("show", f"{parent}:lessons/index.html"), rows, furn) == \
            git("show", f"{h}:lessons/index.html")
    except (ReleaseError, ValueError):
        return False


def preflight(day: dt.date) -> list[str]:
    """Before a --push run: [] if main carries nothing unpushed, else the hashes of release commits stranded from
    TODAY (to re-push). Anything else unpushed refuses: `git push` would send it live with the release."""
    git("fetch", "-q", "origin", "main")
    if git("rev-list", "--count", "main..origin/main").strip() != "0":
        raise ReleaseError("main is behind origin: something was pushed from elsewhere; a human looks first")
    ahead = [l.split("\t", 1) for l in git("log", "--format=%H\t%s", "origin/main..main").splitlines() if l]
    if not ahead:
        return []
    # Every commit is judged by the PATHS it touches against each parent (a merge lists none against itself),
    # never by its message, so nothing can ride along by naming itself well. approvals.py's own commits (an offer,
    # a tap applied) change only bookkeeping; a stranded release commit changes only what a row published today
    # pinned, plus the files the release itself writes.
    todays = [r for r in pb.load_queue() if not r.get("_broken")
              and pb.stage_index(r) >= pb.STAGES.index("PUBLISHED") and published_on(r) == day]
    paths = {h: commit_paths(h) for h, _ in ahead}
    stranded = [h for h, _ in ahead if any(is_release_of(h, paths[h], r) for r in todays)]
    bookkeeping = [h for h, _ in ahead if h not in stranded and paths[h] <= BOOKKEEPING]
    others = [s for h, s in ahead if h not in stranded and h not in bookkeeping]
    if others:
        raise ReleaseError(f"main has {len(others)} unpushed commit(s) that are not today's release "
                           f"({'; '.join(others[:3])}); a push would publish them unapproved")
    return stranded


def verify_live(row: dict, minutes: int) -> str:
    deadline = time.time() + minutes * 60
    pending = {rel: blob for rel, blob in row["approved_blobs"].items() if not rel.startswith("tools/")}
    while True:                                           # always look at least once
        for rel, blob in list(pending.items()):
            url = f"{SITE}/{rel[:-len('index.html')] if rel.endswith('/index.html') else rel}"
            try:
                req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "b4him-release"})
                data = urllib.request.urlopen(req, timeout=20).read()
                if b"\0" not in data:                      # text: compare as git stores it (LF), like blob_sha
                    data = data.replace(b"\r\n", b"\n")
                if hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest() == blob:
                    del pending[rel]
            except OSError:
                pass
        if not pending or time.time() >= deadline:
            break
        time.sleep(30)
    if pending:
        raise ReleaseError(f"pushed, but after {minutes} min the live bytes do not match yet: {', '.join(pending)}")
    return "live bytes match the approved blobs"


def log(entry: dict) -> None:
    entry = {"at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **entry}
    entry.pop("row", None)
    with (repo() / "release_log.jsonl").open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def alarm(entry: dict) -> None:
    """A FAIL must reach Daniel, not sit in a log nobody opens. The harness app tiles any b4him *.md carrying a
    decision block and an open DANIEL marker (review_inbox SIBLING_ROOTS), so a failed run writes one; the next run
    that does not fail removes it. The file is git-ignored, so it never dirties the tree a release needs clean."""
    path = repo() / "release_alarm.md"
    if entry.get("outcome") != "FAIL":
        path.unlink(missing_ok=True)
        return
    path.write_text(
        "# b4him release alarm\n\n"
        f"### Release run failed {entry.get('date')} — {entry.get('piece') or 'no piece'}\n\n"
        f"- **What this is to the build.** The scheduled publish (`tools/release.py`) refused or broke: "
        f"{entry.get('why', '?')}\n"
        f"- **Why this decision exists.** A release that fails silently is a site that looks abandoned; this tile "
        f"is the run telling you rather than a log line nobody reads.\n"
        f"- **What changes if you approve.** Approve means 'seen, have Claude fix it next session'. Nothing "
        f"publishes from this tile.\n"
        f"- **Recommendation.** Approve, and start a b4him session; the full line is in `release_log.jsonl`.\n\n"
        "**DANIEL:** _pending_\n", encoding="utf-8", newline="\n")


def run(a, day: dt.date, entry: dict) -> int:
    if a.push:
        stranded = preflight(day)
        if stranded and plan(day).get("outcome") != "SKIP":
            raise ReleaseError("a release commit from today is unpushed but the queue does not show today's piece "
                               "as published; a human looks first")
        if stranded:
            git("push", "-q", "origin", "main")
            entry.update(outcome="PUSHED-UNVERIFIED", pushed=True, commit=stranded[0],
                         why="re-pushed today's release commit that an earlier run committed but could not push")
            return 0
    decision = plan(day)
    entry.update(decision)
    if decision["outcome"] == "FAIL":
        return 1
    if decision["outcome"] != "PUBLISH":
        return 0
    entry["commit"] = apply(day, decision)
    entry.update(outcome="COMMITTED", pushed=False)
    if a.push:
        git("push", "-q", "origin", "main")
        entry.update(outcome="PUSHED-UNVERIFIED", pushed=True)
        if a.verify_live:
            entry["live"] = verify_live(decision["row"], a.live_minutes)
            entry["outcome"] = "PUBLISHED"
    return 0


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
    entry = {"date": day.isoformat(), "mode": "apply" if a.apply else "dry-run"}
    if not a.apply:
        entry.update(plan(day))
        code = 1 if entry["outcome"] == "FAIL" else 0
    else:
        try:
            code = run(a, day, entry)
        except Exception as e:                 # noqa: BLE001 - every failure is logged, never a bare traceback
            where = (f" (commit {entry['commit'][:7]} is on local main, pushed={entry.get('pushed', False)})"
                     if entry.get("commit") else "")
            entry.update(outcome="FAIL", why=f"{type(e).__name__}: {e}{where}")
            code = 1
        log(entry)
        alarm(entry)
    print(f"{entry['outcome']}  {day} {day:%a}  {entry.get('piece', '')}  {entry.get('why', '')}"
          + (f"  commit {entry['commit'][:7]}" if entry.get("commit") else "")
          + (f"  {entry['live']}" if entry.get("live") else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
