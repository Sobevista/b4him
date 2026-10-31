#!/usr/bin/env python3
"""
standards_watch.py: calendar row E3, the standards watch ("WCAG / Pages / Actions changes", routed to the Site-Ops
Researcher). Polled weekly: it reads four official feeds once each and reports what is new since its last run.

    py tools/standards_watch.py

THE FEEDS (each URL read from the official site, and fetched once, on 2026-10-31):
  wai           https://www.w3.org/WAI/feed.xml  (Atom). "subscribe to WAI's Atom/RSS feed (/WAI/feed.xml)":
                https://www.w3.org/WAI/news/subscribe/
  gh-changelog  https://github.blog/changelog/feed/  (RSS). The changelog page's "Copy RSS feed URL" link:
                https://github.blog/changelog/  Only items whose title or category names Pages, Actions or Jekyll
                count; the rest of GitHub's changelog is not this site's business.
  docs-pages    https://github.com/github/docs/commits/main/content/pages.atom  (Atom: commits to the GitHub Pages
  docs-actions  https://github.com/github/docs/commits/main/content/actions.atom   and Actions docs). github/docs is
                "The open-source repo for docs.github.com", its articles in /content: https://github.com/github/docs
                docs.github.com itself publishes no change feed. (A changelog `label/pages/feed/` returned 404.)

OUTCOMES. FINDINGS n = n relevant items not seen by an earlier run (one S3 finding each, to the Site-Ops
Researcher). PASS = none. UNKNOWN = a feed could not be fetched or read: its items are not judged, and the receipt
says which feed; new items from the feeds that did answer are still written as findings. On a feed's first run
there is no "last run", so items dated within the last 7 days (one cadence) count as new and older ones are
recorded as seen.

STATE. .maint/standards_seen.json (git-ignored): per feed, the item ids seen and the last good fetch. Evidence:
.maint/audits/<date>_standards.json. One GET per feed, a User-Agent naming b4him, a timeout, a pause between feeds.
Exit 0 PASS, 1 FINDINGS, 2 UNKNOWN.
"""
from __future__ import annotations

import datetime as dt
import email.utils
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_input as mi  # noqa: E402
import maint_receipt as mr  # noqa: E402

ROW = "E3"
TOOL = "standards_watch.py"
ROUTE = "Site-Ops Researcher"
USER_AGENT = "b4him-maintenance/1.0 (weekly standards watch; +https://b4him.com/)"
TIMEOUT = 20
PAUSE = 1.0
FIRST_RUN_WINDOW = dt.timedelta(days=7)
KEEP = 500                                   # seen ids kept per feed
STATE = "standards_seen.json"
RELEVANT = re.compile(r"\b(pages|actions|jekyll)\b", re.I)

#: id -> (url, what it is, relevance filter or None)
FEEDS = {
    "wai": ("https://www.w3.org/WAI/feed.xml", "W3C WAI news", None),
    "gh-changelog": ("https://github.blog/changelog/feed/", "GitHub changelog (Pages / Actions / Jekyll items)",
                     RELEVANT),
    "docs-pages": ("https://github.com/github/docs/commits/main/content/pages.atom", "GitHub Pages docs changes", None),
    "docs-actions": ("https://github.com/github/docs/commits/main/content/actions.atom", "GitHub Actions docs changes",
                     None),
}
ATOM = "{http://www.w3.org/2005/Atom}"


class FeedError(Exception):
    """The feed could not be fetched or read. UNKNOWN, never PASS."""


def _fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                               "Accept": "application/atom+xml, application/rss+xml, application/xml"})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return r.read(5_000_000)
    except urllib.error.HTTPError as e:
        raise FeedError(f"HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise FeedError(f"{type(e).__name__}: {getattr(e, 'reason', e)}") from None


#: (url) -> bytes; raises FeedError. Tests replace it.
FETCH = _fetch
SLEEP = time.sleep


def _date(s: str | None) -> dt.datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = email.utils.parsedate_to_datetime(s)
        except (TypeError, ValueError):
            return None
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def parse(body: bytes) -> list[dict]:
    """Atom or RSS 2.0 -> [{id, title, link, date, categories}]. Anything else is a FeedError."""
    try:
        root = ET.fromstring(body)
    except ET.ParseError as e:
        raise FeedError(f"not XML ({e})") from None
    items = []
    if root.tag == f"{ATOM}feed":
        for e in root.findall(f"{ATOM}entry"):
            link = e.find(f"{ATOM}link")
            items.append({"id": (e.findtext(f"{ATOM}id") or "").strip(),
                          "title": (e.findtext(f"{ATOM}title") or "").strip(),
                          "link": link.get("href") if link is not None else "",
                          "date": e.findtext(f"{ATOM}updated") or e.findtext(f"{ATOM}published"),
                          "categories": [c.get("term", "") for c in e.findall(f"{ATOM}category")]})
    elif root.tag == "rss" and root.find("channel") is not None:
        for e in root.find("channel").findall("item"):
            items.append({"id": (e.findtext("guid") or e.findtext("link") or "").strip(),
                          "title": (e.findtext("title") or "").strip(),
                          "link": (e.findtext("link") or "").strip(),
                          "date": e.findtext("pubDate"),
                          "categories": [(c.text or "").strip() for c in e.findall("category")]})
    else:
        raise FeedError(f"neither Atom nor RSS (root <{root.tag}>)")
    for it in items:
        it["id"] = it["id"] or it["link"] or it["title"]
    return [it for it in items if it["id"]]


def relevant(item: dict, rule) -> bool:
    return rule is None or bool(rule.search(item["title"])) or any(rule.search(c) for c in item["categories"])


def load_state(path: Path) -> dict:
    """No state yet is a first run. A state that exists but is unreadable, empty or not a JSON object is UNKNOWN
    (the shared input layer): treating it as a first run would quietly forget which items were already reported."""
    if not path.exists():
        return {}
    data = mi.read_json(path, "the seen-item state")
    if not isinstance(data, dict):
        raise mi.InputUnknown("the seen-item state is not a JSON object")
    return data


def run(now: dt.datetime | None = None) -> dict:
    now = now or dt.datetime.now(dt.timezone.utc)
    md = mr.maint_dir()
    state_path = md / STATE
    try:
        state = load_state(state_path)
    except mi.InputUnknown as e:
        return mr.write_receipt(ROW, "UNKNOWN", why=f"could not read: {e}", tool=TOOL)
    report = {"at": now.isoformat(timespec="seconds"), "tool": TOOL, "feeds": {}}
    new_all, failed = [], []
    for i, (fid, (url, what, rule)) in enumerate(FEEDS.items()):
        if i:
            SLEEP(PAUSE)
        try:
            items = parse(FETCH(url))
        except FeedError as e:
            failed.append(f"{fid} ({e})")
            report["feeds"][fid] = {"url": url, "error": str(e)}
            continue
        prev = state.get(fid)
        seen = set(prev["seen"]) if prev else set()
        fresh = []
        for it in items:
            if it["id"] in seen or not relevant(it, rule):
                continue
            if prev is None:                   # first run: only the last cadence counts as new
                d = _date(it["date"])
                if d is None or now - d > FIRST_RUN_WINDOW:
                    continue
            fresh.append({**it, "feed": fid})
        ids = [it["id"] for it in items] + [x for x in (prev or {}).get("seen", []) if x not in {it["id"] for it in items}]
        state[fid] = {"seen": ids[:KEEP], "last_ok": now.isoformat(timespec="seconds"), "url": url}
        report["feeds"][fid] = {"url": url, "items": len(items), "new": len(fresh), "first_run": prev is None}
        new_all += fresh
    md.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    report["new"] = new_all
    ev = md / "audits" / f"{now.date().isoformat()}_standards.json"
    ev.parent.mkdir(parents=True, exist_ok=True)
    ev.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    rel = f".maint/audits/{ev.name}"
    for it in new_all:
        mr.write_finding(ROW, "S3", f"{it['feed']}: {it['title'][:100]}",
                         f"{FEEDS[it['feed']][1]}; {it['date'] or 'undated'}; {it['link']}", ROUTE,
                         link=it["link"], feed=it["feed"])
    tally = "; ".join(f"{k} {v['new']} new of {v['items']}" for k, v in report["feeds"].items() if "items" in v)
    if failed:
        return mr.write_receipt(ROW, "UNKNOWN", n=None, why=f"could not read: {', '.join(failed)}"
                                + (f"; {tally}" if tally else ""), evidence=rel, tool=TOOL)
    if new_all:
        return mr.write_receipt(ROW, "FINDINGS", n=len(new_all), why=tally, evidence=rel, tool=TOOL)
    return mr.write_receipt(ROW, "PASS", n=0, why=tally, evidence=rel, tool=TOOL)


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = run()
    print(json.dumps(r, ensure_ascii=False))
    return {"PASS": 0, "FINDINGS": 1, "UNKNOWN": 2}[r["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
