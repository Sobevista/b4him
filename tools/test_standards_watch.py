"""Tests for tools/standards_watch.py (row E3). No network: FETCH is a fake serving fixture feeds; a guard fails the
test if a real socket opens."""
import datetime as dt
import json
import socket

import pytest

import maint_receipt as mr
import standards_watch as sw

NOW = dt.datetime(2026, 11, 2, 15, 0, tzinfo=dt.timezone.utc)


def atom(entries):
    body = "".join(f"<entry><id>{i}</id><title>{t}</title><link href='https://example.invalid/{i}'/>"
                   f"<updated>{d}</updated></entry>" for i, t, d in entries)
    return f"<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'><title>x</title>{body}</feed>".encode()


def rss(items):
    body = "".join(f"<item><guid>{g}</guid><title>{t}</title><link>https://example.invalid/{g}</link>"
                   f"<pubDate>{d}</pubDate>" + "".join(f"<category>{c}</category>" for c in cats) + "</item>"
                   for g, t, d, cats in items)
    return f"<?xml version='1.0'?><rss version='2.0'><channel><title>c</title>{body}</channel></rss>".encode()


RECENT, OLD = "2026-10-30T10:00:00Z", "2026-09-01T10:00:00Z"
RECENT_RFC = "Fri, 30 Oct 2026 10:00:00 +0000"


@pytest.fixture
def net(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINT_DIR", str(tmp_path / ".maint"))
    monkeypatch.setattr(sw, "SLEEP", lambda s: None)

    def no_net(*a, **k):
        raise AssertionError("a test opened a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_net)
    feeds = {
        sw.FEEDS["wai"][0]: atom([("w1", "WCAG 2.2 errata", RECENT), ("w0", "old news", OLD)]),
        sw.FEEDS["gh-changelog"][0]: rss([("c1", "Actions: new runner images", RECENT_RFC, ["actions"]),
                                          ("c2", "Copilot does a thing", RECENT_RFC, ["copilot"]),
                                          ("c3", "Something", RECENT_RFC, ["Pages"])]),
        sw.FEEDS["docs-pages"][0]: atom([("p1", "Clarify CNAME", RECENT)]),
        sw.FEEDS["docs-actions"][0]: atom([]),
    }

    def fetch(url):
        v = feeds[url]
        if isinstance(v, Exception):
            raise v
        return v
    monkeypatch.setattr(sw, "FETCH", fetch)
    return feeds


def test_the_feeds_are_the_verified_official_urls():
    assert {k: v[0] for k, v in sw.FEEDS.items()} == {
        "wai": "https://www.w3.org/WAI/feed.xml",
        "gh-changelog": "https://github.blog/changelog/feed/",
        "docs-pages": "https://github.com/github/docs/commits/main/content/pages.atom",
        "docs-actions": "https://github.com/github/docs/commits/main/content/actions.atom",
    }


def test_first_run_counts_the_last_week_and_relevant_items_only(net):
    r = sw.run(NOW)
    assert r["row"] == "E3" and r["outcome"] == "FINDINGS" and r["tool"] == "tools/standards_watch.py"
    subjects = sorted(f["subject"] for f in mr.read_findings())
    # w0 is older than one cadence; c2 is not about Pages/Actions/Jekyll
    assert subjects == ["docs-pages: Clarify CNAME", "gh-changelog: Actions: new runner images",
                        "gh-changelog: Something", "wai: WCAG 2.2 errata"]
    assert r["n"] == 4 and all(f["route_to"] == "Site-Ops Researcher" and f["severity"] == "S3"
                               for f in mr.read_findings())
    assert r["evidence"] == ".maint/audits/2026-11-02_standards.json"


def test_second_run_with_nothing_new_is_pass(net):
    sw.run(NOW)
    r = sw.run(NOW + dt.timedelta(days=7))
    assert r["outcome"] == "PASS" and r["n"] == 0 and "wai 0 new of 2" in r["why"]


def test_a_new_item_since_the_last_run_is_a_finding(net):
    sw.run(NOW)
    net[sw.FEEDS["docs-actions"][0]] = atom([("a1", "Warn about rootless dind", OLD)])   # old date, but unseen
    r = sw.run(NOW + dt.timedelta(days=7))
    assert r["outcome"] == "FINDINGS" and r["n"] == 1 and mr.read_findings()[-1]["subject"].startswith("docs-actions")


def test_a_fetch_failure_is_unknown_never_pass_and_is_retried(net):
    sw.run(NOW)
    net[sw.FEEDS["wai"][0]] = sw.FeedError("HTTP 503")
    r = sw.run(NOW + dt.timedelta(days=7))
    assert r["outcome"] == "UNKNOWN" and "wai (HTTP 503)" in r["why"]
    state = json.loads((mr.maint_dir() / sw.STATE).read_text(encoding="utf-8"))
    assert state["wai"]["last_ok"] == NOW.isoformat(timespec="seconds")       # not advanced: judged again next run


def test_garbage_is_unknown(net):
    net[sw.FEEDS["docs-pages"][0]] = b"<html>not a feed</html>"
    assert sw.run(NOW)["outcome"] == "UNKNOWN"
    net[sw.FEEDS["docs-pages"][0]] = b"\x00 not xml"
    assert "docs-pages (not XML" in sw.run(NOW)["why"]


def test_an_unreadable_state_file_is_unknown_never_a_quiet_first_run(net):
    d = mr.maint_dir()
    d.mkdir(parents=True)
    (d / sw.STATE).write_text("{broken", encoding="utf-8")
    r = sw.run(NOW)
    assert r["outcome"] == "UNKNOWN" and "the seen-item state is not JSON" in r["why"]
    (d / sw.STATE).write_text("", encoding="utf-8")
    assert "the seen-item state is empty" in sw.run(NOW)["why"]
