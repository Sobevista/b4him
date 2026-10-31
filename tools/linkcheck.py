#!/usr/bin/env python3
"""linkcheck.py: the maintenance calendar's whole-site link check (rows W1 and W1b).

W1 (weekly Mon, AUTOMATE)
  (a) INTERNAL, case-sensitive, across EVERY served page, not only the pages a release touches. Site-root links go
      through release.broken_links() unchanged (the target must be an exact path in git, because the host is
      case-sensitive even when a Windows disk is not). Three things that function does not see are checked here
      with the same rule: relative links, absolute links to b4him.com itself, and links into a path Jekyll never
      serves (a part starting with "." or "_"). A broken internal link on a LIVE page (one in the live ref's tree)
      is severity S2; any other is S3.
  (b) OUTBOUND, with a cache in .maint/linkcache.json: a link with a definite answer (alive or dead) less than
      7 days old is not fetched again. Python's stdlib only (urllib): HEAD, then GET when HEAD does not answer
      2xx/3xx; at most 1 request per second per host; a timeout; a User-Agent naming b4him-maintenance. A link is
      DEAD only on HTTP 404 or 410. A network failure (DNS, refused, TLS, timeout) or any other status (401, 403,
      429, 5xx) is UNKNOWN for that link, never broken, and an UNKNOWN is never cached.
W1b (with W1, ASSIST)
  For each dead outbound link, ask the Internet Archive's Wayback Availability API for the closest snapshot (to
  the date the link was last seen alive, when the cache knows it) and attach it to the W1 finding as a PROPOSED
  replacement. Nothing on the site changes: the Site Maintainer and Daniel decide.

Every run writes one receipt per row (tools/maint_receipt.py) and the full report to
.maint/audits/<date>_links.json. lychee and LinkChecker are not used: the calendar allowed them only if already
installed, and the report records whether they were found on PATH.

    py tools/linkcheck.py                    # the weekly run over this checkout
    py tools/linkcheck.py --repo <path>      # another checkout of b4him
Exit 0 = PASS/SKIP, 1 = FINDINGS, 2 = UNKNOWN somewhere (a check that could not run is never a pass).
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import http.client
import json
import os
import posixpath
import re
import shutil
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_receipt  # noqa: E402
import production_board as pb  # noqa: E402
import release  # noqa: E402

ROW_LINKS, ROW_WAYBACK = "W1", "W1b"
TOOL = "tools/linkcheck.py"
ROUTE = "Site Maintainer"
USER_AGENT = "b4him-maintenance/1.0 (weekly link check; +https://b4him.com/)"
SELF_HOSTS = {"b4him.com", "www.b4him.com"}
WAYBACK_API = "https://archive.org/wayback/available"
MAX_AGE = dt.timedelta(days=7)
TIMEOUT = 15
MIN_INTERVAL = 1.0
DEAD_CODES = {404, 410}
ATTR_RE = re.compile(r"""(?:href|src)\s*=\s*(?:"([^"]*)"|'([^']*)')""", re.I)
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")
IGNORED_SCHEMES = ("mailto:", "tel:", "javascript:", "data:")


def _now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _iso(t: dt.datetime) -> str:
    return t.isoformat(timespec="seconds")


def _parse(s: str | None) -> dt.datetime | None:
    try:
        return dt.datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


# ---------------------------------------------------------------- the served tree
def unserved(rel: str) -> bool:
    """Jekyll (GitHub Pages' legacy build) never serves a path with a part starting with '.' or '_'."""
    return any(part.startswith((".", "_")) for part in rel.split("/") if part)


def served_pages(root: Path) -> list[str]:
    files = [f for f in release.git("ls-files", "-z").split("\0") if f]
    return sorted(f for f in files if f.lower().endswith((".html", ".htm")) and not unserved(f))


def live_paths(ref: str) -> set[str] | None:
    """The paths in the live ref's tree (main is the live site), or None when the ref cannot be read."""
    try:
        return {f for f in release.git("ls-tree", "-r", "--name-only", "-z", ref).split("\0") if f}
    except release.ReleaseError:
        return None


def resolves(link: str, served: set[str]) -> bool:
    """The same case-sensitive rule as release.broken_links(), for a site-root path."""
    t = link.lstrip("/")
    if unserved(t):
        return False
    return (t + "index.html" in served) if link.endswith("/") else (t in served or f"{t}/index.html" in served)


def page_dir(rel: str) -> str:
    return "/" + posixpath.dirname(rel) + "/" if posixpath.dirname(rel) else "/"


def classify(value: str) -> str:
    v = value.strip()
    if not v or v.startswith("#") or v.lower().startswith(IGNORED_SCHEMES):
        return "ignored"
    if v.startswith("//") or v.lower().startswith(("http://", "https://")):
        host = (urllib.parse.urlsplit(v if not v.startswith("//") else "https:" + v).hostname or "").lower()
        return "self" if host in SELF_HOSTS else "outbound"
    if SCHEME_RE.match(v):
        return "ignored"
    return "root" if v.startswith("/") else "relative"


def scan(root: Path, pages: list[str]) -> dict:
    """Every href/src value on every served page, sorted into the kinds the checks need."""
    out = {"root": [], "relative": [], "self": [], "outbound": {}, "ignored": 0}
    for rel in pages:
        text = (root / rel).read_text(encoding="utf-8", errors="replace")
        for m in ATTR_RE.finditer(text):
            value = html.unescape(m.group(1) if m.group(1) is not None else m.group(2)).strip()
            kind = classify(value)
            if kind == "ignored":
                out["ignored"] += 1
            elif kind == "outbound":
                url = ("https:" + value if value.startswith("//") else value).split("#", 1)[0]
                out["outbound"].setdefault(url, [])
                if rel not in out["outbound"][url]:
                    out["outbound"][url].append(rel)
            else:
                out[kind].append((rel, value))
    return out


def internal_check(root: Path, pages: list[str], found: dict, live: set[str] | None) -> list[dict]:
    """W1(a). release.broken_links() over every served page, then the three kinds it does not see."""
    served = {f for f in release.git("ls-files", "-z").split("\0") if f}
    bad, flagged = [], set()
    for item in release.broken_links([root / p for p in pages]):
        page, link = item.split(" -> ", 1)
        if (page, link) not in flagged:
            flagged.add((page, link))
            bad.append({"page": page, "link": link, "kind": "root", "why": "no such path in git (case-sensitive)"})
    # what broken_links() passes but the host will not serve (a '.'/'_' path), or never sees (a single-quoted link)
    for page, value in found["root"]:
        path = value.split("#", 1)[0].split("?", 1)[0]
        if path.startswith("//") or (page, path) in flagged or "tools" in page.split("/") or resolves(path, served):
            continue
        flagged.add((page, path))
        bad.append({"page": page, "link": value, "kind": "unserved" if unserved(path) else "root",
                    "why": "the path has a part starting with '.' or '_', which Jekyll never serves"
                    if unserved(path) else "no such path in git (case-sensitive)"})
    for page, value in found["relative"]:
        path = value.split("#", 1)[0].split("?", 1)[0]
        if not path:
            continue
        target = posixpath.normpath(posixpath.join(page_dir(page), path))
        target += "/" if path.endswith("/") and not target.endswith("/") else ""
        if not resolves(target, served):
            bad.append({"page": page, "link": value, "kind": "relative", "why": f"resolves to {target}, not served"})
    for page, value in found["self"]:
        path = urllib.parse.urlsplit(value if not value.startswith("//") else "https:" + value).path or "/"
        if not resolves(path, served):
            bad.append({"page": page, "link": value, "kind": "self", "why": f"{path} is not served"})
    for b in bad:
        b["live_page"] = None if live is None else b["page"] in live
        b["severity"] = "S3" if b["live_page"] is False else "S2"   # live unknown counts as live
    return bad


# ---------------------------------------------------------------- the network
class Fetcher:
    """Polite HTTP: one User-Agent, a timeout, and at most one request per MIN_INTERVAL seconds per host."""

    def __init__(self, opener=None, sleep=time.sleep, clock=time.monotonic, timeout=TIMEOUT,
                 min_interval=MIN_INTERVAL):
        self.open = opener or urllib.request.build_opener().open
        self.sleep, self.clock, self.timeout, self.min_interval = sleep, clock, timeout, min_interval
        self.last: dict[str, float] = {}
        self.requests = 0

    def _wait(self, host: str) -> None:
        if host in self.last:
            gap = self.min_interval - (self.clock() - self.last[host])
            if gap > 0:
                self.sleep(gap)
        self.last[host] = self.clock()

    def request(self, url: str, method: str, read: int = 0) -> dict:
        """{code, final_url, body, error}. code is None when no HTTP answer came back (a network failure)."""
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        self._wait(host)
        self.requests += 1
        req = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
        try:
            resp = self.open(req, timeout=self.timeout)
            try:
                body = resp.read(read) if read else b""
                return {"code": resp.getcode(), "final_url": resp.geturl(), "body": body, "error": None}
            finally:
                resp.close()
        except urllib.error.HTTPError as e:
            return {"code": e.code, "final_url": url, "body": b"", "error": f"HTTP {e.code}"}
        except (urllib.error.URLError, http.client.HTTPException, ValueError, OSError) as e:
            reason = getattr(e, "reason", e)
            return {"code": None, "final_url": url, "body": b"", "error": f"{type(reason).__name__}: {reason}"}


def check_url(url: str, f: Fetcher) -> dict:
    """OK, DEAD (404/410 only) or UNKNOWN. HEAD first; GET whenever HEAD does not answer 2xx/3xx."""
    if not urllib.parse.urlsplit(url).hostname:
        return {"status": "DEAD", "code": None, "method": None, "why": "malformed URL: no host"}
    h = f.request(url, "HEAD")
    if h["code"] is not None and 200 <= h["code"] < 400:
        return {"status": "OK", "code": h["code"], "method": "HEAD", "why": "", "final_url": h["final_url"]}
    g = f.request(url, "GET", read=1024)
    head_said = f"HEAD gave {h['error'] or h['code']}"
    if g["code"] is not None and 200 <= g["code"] < 400:
        return {"status": "OK", "code": g["code"], "method": "GET", "why": head_said, "final_url": g["final_url"]}
    if g["code"] in DEAD_CODES:
        return {"status": "DEAD", "code": g["code"], "method": "GET", "why": f"{head_said}; GET gave {g['code']}"}
    if g["code"] is not None:
        return {"status": "UNKNOWN", "code": g["code"], "method": "GET",
                "why": f"{head_said}; GET gave HTTP {g['code']}, which is not proof the page is gone"}
    return {"status": "UNKNOWN", "code": None, "method": "GET",
            "why": f"{head_said}; GET failed on the network ({g['error']}): never counted as broken"}


def wayback(url: str, f: Fetcher, near: dt.datetime | None = None) -> dict:
    """W1b. FOUND (with a replacement), NONE (the archive holds no usable snapshot) or UNKNOWN (the lookup failed).
    Response format per archive.org/help/wayback_api.php: {"archived_snapshots": {"closest": {"available": true,
    "url": ..., "timestamp": "YYYYMMDDhhmmss", "status": "200"}}}, or {"archived_snapshots": {}} when none."""
    q = {"url": url}
    if near:
        q["timestamp"] = near.strftime("%Y%m%d%H%M%S")
    r = f.request(WAYBACK_API + "?" + urllib.parse.urlencode(q), "GET", read=65536)
    if r["code"] != 200:
        return {"status": "UNKNOWN", "why": f"Wayback lookup failed: {r['error'] or r['code']}"}
    try:
        data = json.loads(r["body"].decode("utf-8"))
        closest = (data.get("archived_snapshots") or {}).get("closest")
    except (ValueError, AttributeError) as e:
        return {"status": "UNKNOWN", "why": f"Wayback answered something that is not its JSON: {e}"}
    if not closest:
        return {"status": "NONE", "why": "the archive holds no snapshot of this URL"}
    if closest.get("available") is not True or str(closest.get("status")) != "200" or not closest.get("url"):
        return {"status": "NONE", "why": f"the closest snapshot is not usable (status {closest.get('status')})"}
    return {"status": "FOUND", "replacement": closest["url"], "timestamp": closest.get("timestamp"),
            "why": "closest snapshot" + (f" to {q['timestamp'][:8]}, when the link was last seen alive" if near else "")}


# ---------------------------------------------------------------- the cache
def load_cache(path: Path) -> tuple[dict, str]:
    if not path.exists():
        return {"version": 1, "links": {}, "wayback": {}}, "no cache yet"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        data.setdefault("links", {})
        data.setdefault("wayback", {})
        return data, "loaded"
    except (ValueError, OSError) as e:
        return {"version": 1, "links": {}, "wayback": {}}, f"unreadable, ignored ({e})"


def save_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cache, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8",
                   newline="\n")
    tmp.replace(path)


def fresh(entry: dict | None, now: dt.datetime, definite: tuple) -> bool:
    t = _parse((entry or {}).get("checked_at"))
    return bool(entry) and entry.get("status") in definite and t is not None and now - t < MAX_AGE


def outbound_check(urls: dict, cache: dict, f: Fetcher, now: dt.datetime) -> list[dict]:
    """W1(b). One result per distinct URL, from the cache when it holds a definite answer under 7 days old."""
    out = []
    for url in sorted(urls):
        prev = cache["links"].get(url)
        if fresh(prev, now, ("OK", "DEAD")):
            res, source = {k: v for k, v in prev.items()}, "cache"
        else:
            res, source = check_url(url, f), "fetched"
            res["checked_at"] = _iso(now)
            res["last_ok_at"] = _iso(now) if res["status"] == "OK" else (prev or {}).get("last_ok_at")
            if res["status"] in ("OK", "DEAD"):
                cache["links"][url] = res
        out.append({"url": url, "pages": urls[url], "source": source, **res})
    return out


def wayback_check(dead: list[dict], cache: dict, f: Fetcher, now: dt.datetime) -> None:
    """W1b. Attach a proposal (or the reason there is none) to every dead outbound result, in place."""
    for d in dead:
        prev = cache["wayback"].get(d["url"])
        if fresh(prev, now, ("FOUND", "NONE")):
            wb, source = dict(prev), "cache"
        else:
            wb, source = wayback(d["url"], f, _parse(d.get("last_ok_at"))), "fetched"
            wb["checked_at"] = _iso(now)
            if wb["status"] in ("FOUND", "NONE"):
                cache["wayback"][d["url"]] = wb
        d["wayback"] = {**wb, "source": source}


# ---------------------------------------------------------------- the run
def external_checkers() -> dict:
    return {name: shutil.which(name) is not None for name in ("lychee", "linkchecker")}


def report_path(day: dt.date) -> Path:
    d = maint_receipt.maint_dir() / "audits"
    d.mkdir(parents=True, exist_ok=True)
    p, i = d / f"{day.isoformat()}_links.json", 2
    while p.exists():                     # a second run the same day keeps the first run's evidence
        p, i = d / f"{day.isoformat()}_links-{i}.json", i + 1
    return p


def run(root: Path, live_ref: str = "origin/main", fetcher: Fetcher | None = None,
        now: dt.datetime | None = None) -> dict:
    """Check `root`, write its receipts, findings, cache and report under root/.maint/. Module roots restored."""
    saved, saved_dir = pb.REPO, os.environ.get("MAINT_DIR")
    pb.REPO = root
    os.environ["MAINT_DIR"] = str(root / ".maint")     # maint_receipt writes to MAINT_DIR or its own repo's .maint/
    try:
        return _run(root, live_ref, fetcher, now)
    finally:
        pb.REPO = saved
        if saved_dir is None:
            os.environ.pop("MAINT_DIR", None)
        else:
            os.environ["MAINT_DIR"] = saved_dir


def _run(root: Path, live_ref: str, fetcher: Fetcher | None, now: dt.datetime | None) -> dict:
    now = now or _now()
    f = fetcher or Fetcher()
    cache_file = maint_receipt.maint_dir() / "linkcache.json"
    cache, cache_state = load_cache(cache_file)
    rep = {"at": _iso(now), "tool": TOOL, "repo_head": None, "live_ref": live_ref, "live_ref_sha": None,
           "engine": "python-stdlib urllib", "external_checkers_on_path": external_checkers(),
           "user_agent": USER_AGENT, "cache": {"path": ".maint/linkcache.json", "state": cache_state},
           "pages": [], "internal": {"error": None, "broken": []}, "outbound": [], "ignored_links": 0}
    internal_error = None
    try:
        rep["repo_head"] = release.git("rev-parse", "HEAD").strip()
        pages = served_pages(root)
        live = live_paths(live_ref)
        if live is not None:
            rep["live_ref_sha"] = release.git("rev-parse", live_ref).strip()
        rep["pages"] = pages
        rep["skipped_by_broken_links"] = [p for p in pages if "tools" in p.split("/")]
        found = scan(root, pages)
        rep["ignored_links"] = found["ignored"]
        rep["internal"]["counts"] = {k: len(found[k]) for k in ("root", "relative", "self")}
        rep["internal"]["broken"] = internal_check(root, pages, found, live)
        if live is None:
            rep["internal"]["note"] = f"live ref {live_ref} unreadable: every broken link is treated as live (S2)"
    except (release.ReleaseError, OSError) as e:
        internal_error = f"{type(e).__name__}: {e}"
        rep["internal"]["error"] = internal_error
        found = {"outbound": {}}

    outbound = outbound_check(found["outbound"], cache, f, now)
    dead = [o for o in outbound if o["status"] == "DEAD"]
    unknown = [o for o in outbound if o["status"] == "UNKNOWN"]
    wayback_check(dead, cache, f, now)
    rep["outbound"] = outbound
    rep["requests_made"] = f.requests
    save_cache(cache_file, cache)

    path = report_path(now.date())
    rel_ev = path.relative_to(root).as_posix()
    path.write_text(json.dumps(rep, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")

    # ---- findings: every broken internal link, every dead outbound link (with its W1b proposal)
    for b in rep["internal"]["broken"]:
        maint_receipt.write_finding(
            ROW_LINKS, b["severity"], f"internal link {b['page']} -> {b['link']}",
            f"{b['why']}; " + ("live page" if b["live_page"] else "live state UNKNOWN, treated as live"
                               if b["live_page"] is None else "not a live page"),
            ROUTE, kind=b["kind"], evidence=rel_ev)
    for d in dead:
        wb = d["wayback"]
        proposal = ({"replacement": wb["replacement"], "snapshot_timestamp": wb.get("timestamp"),
                     "source": "Wayback Availability API", "status": "PROPOSED, not applied"}
                    if wb["status"] == "FOUND" else None)
        maint_receipt.write_finding(
            ROW_LINKS, "S3", f"dead outbound link {d['url']}",
            f"{d['why']}; on {', '.join(d['pages'])}; W1b: {wb['why']}", ROUTE,
            pages=d["pages"], proposal=proposal, wayback_status=wb["status"], evidence=rel_ev)

    # ---- receipts
    n_int, n_s2 = len(rep["internal"]["broken"]), sum(b["severity"] == "S2" for b in rep["internal"]["broken"])
    n = n_int + len(dead)
    tally = (f"{len(rep['pages'])} pages; {n_int} broken internal ({n_s2} S2); {len(outbound)} outbound: "
             f"{len(dead)} dead, {len(unknown)} UNKNOWN, {len(outbound) - len(dead) - len(unknown)} alive")
    if internal_error:
        w1 = ("UNKNOWN", None, f"internal check could not run ({internal_error}); {tally}")
    elif n:
        w1 = ("FINDINGS", n, tally)
    elif unknown:
        w1 = ("UNKNOWN", None, f"{tally}; could not check: " + "; ".join(f"{u['url']} ({u['why']})" for u in unknown))
    else:
        w1 = ("PASS", 0, tally)
    lookups_failed = [d for d in dead if d["wayback"]["status"] == "UNKNOWN"]
    proposals = sum(d["wayback"]["status"] == "FOUND" for d in dead)
    if lookups_failed:
        w1b = ("UNKNOWN", None, f"{len(lookups_failed)} of {len(dead)} Wayback lookups failed: "
                                + "; ".join(d["wayback"]["why"] for d in lookups_failed))
    elif dead:
        w1b = ("FINDINGS", len(dead), f"{len(dead)} dead outbound: {proposals} with a proposed snapshot, "
                                      f"{len(dead) - proposals} with none in the archive")
    elif unknown or internal_error:
        w1b = ("UNKNOWN", None, f"{len(unknown)} outbound links UNKNOWN, so the dead set may be incomplete")
    else:
        w1b = ("SKIP", None, "no dead outbound links this run")
    receipts = [maint_receipt.write_receipt(ROW_LINKS, w1[0], n=w1[1], why=w1[2], evidence=rel_ev, tool=TOOL),
                maint_receipt.write_receipt(ROW_WAYBACK, w1b[0], n=w1b[1], why=w1b[2], evidence=rel_ev, tool=TOOL)]
    return {"report": rep, "report_path": path, "receipts": receipts}


def exit_code(receipts: list[dict]) -> int:
    outcomes = {r["outcome"] for r in receipts}
    return 2 if "UNKNOWN" in outcomes else 1 if "FINDINGS" in outcomes else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--repo", type=Path, default=pb.REPO, help="the b4him checkout to check (default: this one)")
    ap.add_argument("--live-ref", default="origin/main", help="the ref whose tree is the live site")
    a = ap.parse_args(argv)
    res = run(a.repo.resolve(), a.live_ref)
    for r in res["receipts"]:
        print(json.dumps(r, ensure_ascii=False))
    print(f"report: {res['report_path']}")
    return exit_code(res["receipts"])


if __name__ == "__main__":
    sys.exit(main())
