#!/usr/bin/env python3
"""
hopper_stress.py — prove the hopper and the publish on a fast clock, against a throwaway target (plan 2026-11-09, 1b-1c).

Daniel, 2026-11-09: "stress test it and have it auto publish a few in five minute intervals somewhere throw away if
needed. Lets prove the hopper and publish work".

WHAT IT BUILDS, all under --root (nothing else is written; nothing leaves 127.0.0.1):
  clone/        a scratch clone of this checkout's HEAD, on main; its ONLY remote is origin = origin.git
  origin.git/   a local bare repo; its post-receive hook checks main out into live/
  live/         what the "site" serves: `python -m http.server` on 127.0.0.1:<free port> (the profile's `site`)
  profile.json  the line profile (tools/line_profile.py): repo = clone/, site = the local server, the PRODUCTION
                cadence (Tuesday only, cap 1 per 7 days, T-7), allow_date_apply = true, ledger = ledger.jsonl
  ledger.jsonl  the taps, standing in for the harness ledger (the harness is never read or written)
  stress_log.jsonl  one line per tick, then one summary line

THE HOPPER. N rows STRESS-1..N go on main's queue at SOURCE; each is drafted on draft/stress-<i> (a small page, its
lessons-index entry on the n8n track, the track furniture pinned by approvals.py), gets a structured stage-2 PASS by a
seat that is not its drafter, and is offered with the real `approvals.py offer`. The tap is an APPROVE RULING on the
tile's title written to ledger.jsonl; the real `approvals.py apply` (first line of daily.cmd) racks it.

THE CLOCK. Virtual release days are consecutive Tuesdays, the first at least review_lead_days after today, so the
production cadence rules (Tuesday, 1 per 7 days, T-7) are the ones exercised. Each tick runs the two lines of
tools/daily.cmd under the profile, the second with `--date <virtual day>`, from this checkout's tools/ against clone/,
then waits --every seconds.

Exit 0 only when every tick is PUBLISHED for the expected piece, the live bytes of each tick's piece hash to its pins,
the final live/ tree hashes to every pin of every STRESS row, and the production checkout's HEAD and status are the
same after as before. 1 with the reason otherwise; 2 if the target could not be built (UNKNOWN, not a pass).

    py tools/stress/hopper_stress.py --ticks 3 --every 300 --root <scratch dir> [--keep]
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

TOOLS = Path(__file__).resolve().parent.parent
SRC = TOOLS.parent
sys.path.insert(0, str(TOOLS))
import line_profile  # noqa: E402  (its classes only: this process never loads a profile)

DRAFTER = ("stress drafter seat", "drafter@stress.invalid")
REVIEWER = ("stress review seat", "review@stress.invalid")
REVIEW_BY = "stress-review-seat"
TRACK = "n8n"                                  # the one track with furniture (tools/tracks/n8n.html)
PROOF = "https://example.invalid/stress-proof/{pid}"
#: The production cadence, written into the profile (stated, so a reader can check the virtual days against it).
CADENCE_DAYS, PER_WEEK_CAP, REVIEW_LEAD_DAYS = [1], 1, 7


class StressFail(RuntimeError):
    pass


def sh(cmd, cwd=None, env=None, check=True) -> subprocess.CompletedProcess:
    p = subprocess.run([str(c) for c in cmd], cwd=cwd, env=env, capture_output=True, encoding="utf-8",
                       errors="replace")
    if check and p.returncode:
        raise StressFail(f"{' '.join(str(c) for c in cmd)} failed ({p.returncode}): {(p.stderr or p.stdout).strip()}")
    return p


def git(repo: Path, *args, check=True, env=None) -> str:
    return sh(["git", "-C", repo, *args], env=env, check=check).stdout.strip()


def blob_sha(path: Path) -> str | None:
    """The git blob id of a file as the repo stores it (text=auto eol=lf), like production_board.blob_sha."""
    try:
        data = path.read_bytes()
    except OSError:
        return None
    if b"\0" not in data:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


# ---------------------------------------------------------------- 1b: the throwaway target
def build_scratch(root: Path, src: Path = SRC) -> dict:
    """clone/ of src's HEAD on main, origin.git/ as its one remote, live/ filled by the post-receive hook."""
    clone, bare, live = root / "clone", root / "origin.git", root / "live"
    for p in (clone, bare, live):
        if p.exists():
            raise StressFail(f"{p} already exists: a stress run starts from an empty --root")
    root.mkdir(parents=True, exist_ok=True)
    head = git(src, "rev-parse", "HEAD")
    sh(["git", "clone", "-q", "--no-checkout", "--no-hardlinks", src, clone])
    git(clone, "remote", "remove", "origin")          # the real origin is never configured here
    for k, v in (("user.name", DRAFTER[0]), ("user.email", DRAFTER[1]), ("core.autocrlf", "false"),
                 ("commit.gpgsign", "false"), ("tag.gpgsign", "false")):
        git(clone, "config", k, v)
    git(clone, "checkout", "-q", "-B", "main", head)
    for b in git(clone, "for-each-ref", "--format=%(refname:short)", "refs/heads").splitlines():
        if b != "main":
            git(clone, "branch", "-q", "-D", b)
    # The bare repo is seeded by cloning, never by a push: release.py stays the only code under tools/ that pushes
    # (tools/test_production_boundary.py). Its own remote back to clone/ is removed, so it points nowhere.
    sh(["git", "clone", "-q", "--bare", "--no-hardlinks", clone, bare])
    git(bare, "remote", "remove", "origin")
    live.mkdir()
    checkout = ["git", f"--git-dir={bare.as_posix()}", f"--work-tree={live.as_posix()}", "-c", "core.autocrlf=false",
                "checkout", "-f", "-q", "main"]
    hook = bare / "hooks" / "post-receive"
    hook.write_text("#!/bin/sh\nexec " + " ".join(f'"{c}"' if " " in c else c for c in checkout) + "\n",
                    encoding="utf-8", newline="\n")
    hook.chmod(hook.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    sh(checkout)                                      # live/ starts as main; every later push goes through the hook
    git(clone, "remote", "add", "origin", str(bare))
    git(clone, "fetch", "-q", "origin")
    if not (live / "index.html").exists():
        raise StressFail("main was not checked out into live/")
    return {"clone": clone, "bare": bare, "live": live, "head": head}


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def serve(live: Path, root: Path) -> tuple[subprocess.Popen, str]:
    port = free_port()
    out = (root / "server.log").open("ab")
    proc = subprocess.Popen([sys.executable, "-m", "http.server", str(port), "--bind", "127.0.0.1",
                             "--directory", str(live)], stdout=out, stderr=subprocess.STDOUT)
    site = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            urllib.request.urlopen(site + "/", timeout=2).read()
            return proc, site
        except OSError:
            if proc.poll() is not None:
                break
            time.sleep(0.1)
    proc.kill()
    raise StressFail(f"the local server on {site} never answered")


def write_profile(root: Path, clone: Path, site: str) -> Path:
    path = root / "profile.json"
    path.write_text(json.dumps({"repo": str(clone), "site": site, "cadence_days": CADENCE_DAYS,
                                "per_week_cap": PER_WEEK_CAP, "review_lead_days": REVIEW_LEAD_DAYS,
                                "allow_date_apply": True, "ledger": str(root / "ledger.jsonl")}, indent=2),
                    encoding="utf-8")
    return path


# ---------------------------------------------------------------- 1c: the hopper
def page_html(i: int) -> str:
    return ("<!doctype html>\n<html lang=\"en\">\n<head><meta charset=\"utf-8\"><title>Stress piece "
            f"{i}</title><link rel=\"stylesheet\" href=\"/lesson.css\"></head>\n<body>\n<h1>Stress Piece {i}</h1>\n"
            f"<p>A throwaway page the hopper stress run publishes on its own clock.</p>\n"
            "<p><a href=\"/lessons/\">All lessons</a></p>\n</body>\n</html>\n")


def queue_rows(clone: Path) -> list[dict]:
    text = (clone / "production_queue.jsonl").read_text(encoding="utf-8")
    return [json.loads(s) for s in (l.strip() for l in text.splitlines()) if s.startswith("{")]


def put_row(clone: Path, row: dict) -> None:
    q = clone / "production_queue.jsonl"
    lines, hit = q.read_text(encoding="utf-8").split("\n"), False
    for k, line in enumerate(lines):
        if line.strip().startswith("{") and json.loads(line).get("id") == row["id"]:
            lines[k], hit = json.dumps(row, ensure_ascii=False), True
    if not hit:
        while lines and lines[-1] == "":
            lines.pop()
        lines += [json.dumps(row, ensure_ascii=False), ""]
    q.write_text("\n".join(lines), encoding="utf-8", newline="\n")


def seed_pieces(clone: Path, n: int, today: dt.date) -> list[str]:
    """N rows at SOURCE on main (pushed), each drafted on draft/stress-<i> and given a stage-2 record by another seat."""
    ids = [f"STRESS-{i}" for i in range(1, n + 1)]
    for i, pid in enumerate(ids, 1):
        put_row(clone, {"id": pid, "order": i - 1000, "title": f"Stress Piece {i}", "stage": "SOURCE",
                        "track": "stress", "source": "tools/stress/hopper_stress.py", "since": today.isoformat(),
                        "invariant": "a release publishes exactly the approved bytes on its own clock"})
    git(clone, "add", "production_queue.jsonl")
    git(clone, "commit", "-q", "-m", f"Stress: {n} SOURCE rows")   # queue only: bookkeeping, rides out with tick 1
    for i, pid in enumerate(ids, 1):
        branch, page = f"draft/stress-{i}", f"lessons/stress-{i}/index.html"
        git(clone, "checkout", "-q", "-b", branch, "main")
        (clone / page).parent.mkdir(parents=True, exist_ok=True)
        (clone / page).write_text(page_html(i), encoding="utf-8", newline="\n")
        row = next(r for r in queue_rows(clone) if r["id"] == pid)
        row.update(stage="DRAFTED", page=page, branch=branch, drafted=today.isoformat(),
                   drafted_by="stress-drafting-seat",
                   index_entry={"track": TRACK, "numeral": f"S{i}", "href": f"/lessons/stress-{i}/",
                                "title": f"Stress Piece {i}", "blurb": "A throwaway piece for the stress run."})
        put_row(clone, row)
        git(clone, "add", page, "production_queue.jsonl")
        git(clone, "commit", "-q", "-m", f"Draft {pid}")
        row["reviewed"] = {"date": today.isoformat(), "by": REVIEW_BY, "verdict": "PASS",
                           "proof": "tools/stress/hopper_stress.py (fixture page, checked by the runner)",
                           "blobs": {page: blob_sha(clone / page)}}
        put_row(clone, row)
        git(clone, "add", "production_queue.jsonl")
        git(clone, "-c", f"user.name={REVIEWER[0]}", "-c", f"user.email={REVIEWER[1]}",
            "commit", "-q", "-m", f"Stage 2 PASS for {pid}")
        git(clone, "checkout", "-q", "main")
    return ids


def offer_and_tap(clone: Path, ids: list[str], env: dict, ledger: Path) -> list[str]:
    """The real `approvals.py offer` for each piece, then the tap: an APPROVE ruling on the tile title in ledger.jsonl."""
    led = line_profile.FileLedger(ledger)
    titles = []
    for i, pid in enumerate(ids, 1):
        p = sh([sys.executable, TOOLS / "approvals.py", "offer", pid, f"draft/stress-{i}",
                "--proof", PROOF.format(pid=pid)], cwd=clone, env=env, check=False)
        line = next((l for l in p.stdout.splitlines() if l.startswith("offered: ")), None)
        if p.returncode or not line:
            raise StressFail(f"approvals.py offer {pid} refused: {(p.stdout + p.stderr).strip()}")
        title = line[len("offered: "):]
        led.append("RULING", "stress-runner", {"decision": title, "verdict": "APPROVE", "applied": False,
                                               "note": None, "by": "stress-runner standing in for the tap"})
        titles.append(title)
    return titles


def virtual_days(today: dt.date, n: int) -> list[dt.date]:
    """Consecutive Tuesdays, the first at least REVIEW_LEAD_DAYS after today (a tap today meets its T-7)."""
    d = today + dt.timedelta(days=REVIEW_LEAD_DAYS)
    while d.weekday() not in CADENCE_DAYS:
        d += dt.timedelta(days=1)
    return [d + dt.timedelta(weeks=k) for k in range(n)]


def log_lines(clone: Path) -> list[dict]:
    p = clone / "release_log.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()] if p.exists() else []


def pins_live(live: Path, row: dict) -> list[str]:
    """Pinned paths whose bytes in live/ do not hash to the pin ([] = every pin matches)."""
    return [rel for rel, blob in (row.get("approved_blobs") or {}).items() if blob_sha(live / rel) != blob]


def production_state() -> dict:
    out = {}
    for root in sorted(line_profile.production_roots()):
        head = sh(["git", "-C", root, "rev-parse", "HEAD"], check=False).stdout.strip()
        status = sh(["git", "-C", root, "status", "--porcelain"], check=False).stdout
        out[root] = {"head": head, "status_sha": hashlib.sha256(status.encode()).hexdigest()[:12],
                     "clean": status.strip() == ""}
    return out


def _rmtree(p: Path) -> None:
    def writable_then_retry(func, path, _exc):      # git marks its objects read-only; Windows refuses to delete those
        os.chmod(path, stat.S_IWRITE)
        func(path)
    if p.exists():
        shutil.rmtree(p, onexc=writable_then_retry)


def run(ticks: int, every: float, root: Path, keep: bool, live_minutes: int | None = None,
        today: dt.date | None = None) -> int:
    today = today or dt.date.today()
    root = root.resolve()
    slog = root / "stress_log.jsonl"
    before = production_state()
    server = None
    results: list[dict] = []
    reason = ""

    def write(entry: dict) -> None:
        with slog.open("a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(json.dumps(entry, ensure_ascii=False), flush=True)

    try:
        try:
            t = build_scratch(root)
            server, site = serve(t["live"], root)
            profile = write_profile(root, t["clone"], site)
            env = {**os.environ, line_profile.ENV: str(profile), "PYTHONIOENCODING": "utf-8"}
            ids = seed_pieces(t["clone"], ticks, today)
            offer_and_tap(t["clone"], ids, env, root / "ledger.jsonl")
        except StressFail as e:
            write({"setup": "FAIL", "why": str(e)})
            print(f"UNKNOWN: the throwaway target could not be built: {e}", file=sys.stderr)
            return 2
        clone, live, bare = t["clone"], t["live"], t["bare"]
        write({"setup": "OK", "site": site, "clone_head": t["head"][:12], "pieces": ids,
               "remotes": git(clone, "remote", "-v").splitlines()})
        days = virtual_days(today, ticks)
        extra = ["--live-minutes", str(live_minutes)] if live_minutes is not None else []
        for k, day in enumerate(days):
            t0 = time.time()
            n0 = len(log_lines(clone))
            a = sh([sys.executable, TOOLS / "approvals.py", "apply"], cwd=clone, env=env, check=False)
            r = sh([sys.executable, TOOLS / "release.py", "--apply", "--push", "--verify-live", "--date",
                    day.isoformat(), *extra], cwd=clone, env=env, check=False)
            new = log_lines(clone)[n0:]
            content = next((e for e in reversed(new) if e.get("lane") == "content"), {})
            row = next((x for x in queue_rows(clone) if x["id"] == ids[k]), {})
            bad = pins_live(live, row)
            entry = {"tick": k + 1, "virtual_day": f"{day} {day:%a}", "expected": ids[k],
                     "piece": content.get("piece"), "outcome": content.get("outcome", "NO LOG LINE"),
                     "commit": (content.get("commit") or "")[:12],
                     "origin_main": git(bare, "rev-parse", "main")[:12],
                     "live_hash_match": not bad and bool(row.get("approved_blobs")),
                     "approvals": " | ".join(a.stdout.strip().splitlines()) or a.stderr.strip()[-300:],
                     "approvals_exit": a.returncode, "release_exit": r.returncode,
                     "elapsed_s": round(time.time() - t0, 2)}
            if content.get("patch_outcomes"):
                entry["patch_outcomes"] = content["patch_outcomes"]
            if content.get("outcome") != "PUBLISHED" or content.get("piece") != ids[k] or bad:
                entry["why"] = (content.get("why") or r.stdout.strip()[-400:] or r.stderr.strip()[-400:]
                                ) + (f"; live bytes differ for {', '.join(bad)}" if bad else "")
            results.append(entry)
            write(entry)
            if k + 1 < len(days) and every > 0:
                time.sleep(every)
        final_bad = {r["id"]: pins_live(live, r) for r in queue_rows(clone) if r["id"] in ids}
        final_bad = {k: v for k, v in final_bad.items() if v}
        published = [r["id"] for r in queue_rows(clone) if r["id"] in ids and r.get("stage") == "PUBLISHED"]
        after = production_state()
        failed = [e for e in results if "why" in e]
        if failed:
            reason = f"tick {failed[0]['tick']} was {failed[0]['outcome']}: {failed[0]['why']}"
        elif sorted(published) != sorted(ids):
            reason = f"not every piece is PUBLISHED on the queue: {sorted(set(ids) - set(published))}"
        elif final_bad:
            reason = f"the final live tree does not hash to the pins: {final_bad}"
        elif git(clone, "rev-parse", "main") != git(bare, "rev-parse", "main"):
            reason = "origin's main is not the clone's main after the last tick"
        elif after != before:
            reason = f"the production checkout changed during the run: before {before}, after {after}"
        write({"summary": "PASS" if not reason else "FAIL", "ticks": len(results),
               "published": sum(e["outcome"] == "PUBLISHED" for e in results),
               "final_live_tree_matches_every_pin": not final_bad, "production_unchanged": after == before,
               **({"why": reason} if reason else {})})
        return 0 if not reason else 1
    finally:
        if server is not None:
            server.kill()
            server.wait()
        if not keep:
            for name in ("clone", "origin.git", "live"):
                _rmtree(root / name)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ticks", type=int, required=True)
    ap.add_argument("--every", type=float, required=True, help="seconds between ticks")
    ap.add_argument("--root", help="an empty scratch directory (default: a new temp dir)")
    ap.add_argument("--keep", action="store_true", help="leave clone/, origin.git/ and live/ for inspection")
    ap.add_argument("--live-minutes", type=int, help="passed to release.py (default: release.py's own)")
    a = ap.parse_args(argv)
    if a.ticks < 1:
        ap.error("--ticks must be at least 1")
    if os.environ.get(line_profile.ENV):
        print(f"REFUSED: {line_profile.ENV} is set in this shell; the runner writes its own profile for its children",
              file=sys.stderr)
        return 2
    root = Path(a.root) if a.root else Path(tempfile.mkdtemp(prefix="b4him-stress-"))
    code = run(a.ticks, a.every, root, a.keep, a.live_minutes)
    print(f"{'PASS' if code == 0 else 'FAIL'}: stress log at {root / 'stress_log.jsonl'}")
    return code


if __name__ == "__main__":
    sys.exit(main())
