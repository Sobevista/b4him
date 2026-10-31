"""Tests for linkcheck.py (maintenance rows W1 and W1b) and maint_receipt.py. No network: HTTP is a fake opener.

    py -m pytest tools/test_maint_links.py -q

Each row is shown on its PASS, FINDINGS and UNKNOWN paths (W1b also SKIP), in a throwaway git repo.
"""
import datetime as dt
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import linkcheck  # noqa: E402
import maint_receipt  # noqa: E402
import production_board as pb  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")
NOW = dt.datetime(2026, 11, 2, 9, 0, tzinfo=dt.timezone.utc)
OUT = "https://example.org/a-page"
OUT2 = "https://other.example.net/doc"


def g(root, *args):
    return subprocess.run([GIT, "-C", str(root), *args], capture_output=True, check=True,
                          encoding="utf-8").stdout.strip()


def write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


@pytest.fixture
def site(tmp_path, monkeypatch):
    """A served tree whose links all resolve; `live` is a branch at its first commit (the live site)."""
    root = tmp_path / "site"
    root.mkdir()
    g(tmp_path, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "test"), ("core.autocrlf", "false")):
        g(root, "config", k, v)
    write(root, ".gitignore", ".maint/\n")
    write(root, "index.html", '<a href="/lessons/a/">a</a> <a href="/about/">about</a> <a href="#top">t</a>\n'
                              '<a href="mailto:x@example.invalid">m</a>\n')
    write(root, "about/index.html", f'<a href="/">home</a> <a href="{OUT}#part">out</a>\n')
    write(root, "lessons/a/index.html", '<a href="../../about/">rel</a> <a href="https://b4him.com/lessons/a/">self</a>'
                                        '<img src="/img/x.png">\n')
    write(root, "img/x.png", "png")
    write(root, "_drafts/hidden.html", f'<a href="/nowhere/">never served, never scanned</a> <a href="{OUT2}">x</a>\n')
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", "site")
    g(root, "branch", "live")
    monkeypatch.setattr(pb, "REPO", root)
    monkeypatch.setenv("MAINT_DIR", str(root / ".maint"))   # watch's canonical maint_receipt reads MAINT_DIR
    return root


class Resp:
    def __init__(self, code, url, body=b""):
        self.code, self.url, self.body = code, url, body

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.body

    def close(self):
        pass


class FakeNet:
    """answers[(method, url-prefix)] = int status | bytes (a 200 with that body) | an exception to raise."""

    def __init__(self, answers):
        self.answers, self.calls, self.slept, self.t = answers, [], [], 0.0

    def open(self, req, timeout=None):
        self.calls.append((req.get_method(), req.full_url, req.get_header("User-agent"), timeout))
        for (method, prefix), ans in self.answers.items():
            if method == req.get_method() and req.full_url.startswith(prefix):
                break
        else:
            raise AssertionError(f"unexpected request {req.get_method()} {req.full_url}")
        if isinstance(ans, BaseException):
            raise ans
        if isinstance(ans, bytes):
            return Resp(200, req.full_url, ans)
        if ans >= 400:
            raise urllib.error.HTTPError(req.full_url, ans, "x", {}, None)
        return Resp(ans, req.full_url)

    def sleep(self, s):
        self.slept.append(s)
        self.t += s

    def clock(self):
        return self.t

    def fetcher(self):
        return linkcheck.Fetcher(opener=self.open, sleep=self.sleep, clock=self.clock)


def wb_json(url="http://web.archive.org/web/20250101000000/https://example.org/a-page", ts="20250101000000"):
    return json.dumps({"url": OUT, "archived_snapshots": {"closest": {"available": True, "url": url,
                                                                      "timestamp": ts, "status": "200"}}}).encode()


def lines(root, name):
    p = root / ".maint" / name
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def by_row(res):
    return {r["row"]: r for r in res["receipts"]}


# ---------------------------------------------------------------- W1 / W1b: PASS (and W1b SKIP)
def test_pass_when_every_link_resolves(site):
    net = FakeNet({("HEAD", OUT): 200})
    res = linkcheck.run(site, "live", net.fetcher(), NOW)
    r = by_row(res)
    assert r["W1"]["outcome"] == "PASS" and r["W1"]["n"] == 0
    assert r["W1b"]["outcome"] == "SKIP" and r["W1b"]["why"]
    assert linkcheck.exit_code(res["receipts"]) == 0
    rep = res["report"]
    assert "_drafts/hidden.html" not in rep["pages"] and "index.html" in rep["pages"]
    assert [o["url"] for o in rep["outbound"]] == [OUT]          # fragment stripped; _drafts never scanned
    assert rep["internal"]["counts"] == {"root": 4, "relative": 1, "self": 1}
    assert res["report_path"].name == "2026-11-02_links.json" and res["report_path"].exists()
    assert r["W1"]["evidence"] == ".maint/audits/2026-11-02_links.json" and r["W1"]["tool"] == "tools/linkcheck.py"
    assert lines(site, "maintenance_findings.jsonl") == []
    assert g(site, "status", "--porcelain") == ""                  # .maint/ is ignored: the tree stays clean


# ---------------------------------------------------------------- W1(a): FINDINGS, severity by live page
def test_internal_findings_case_sensitive_every_page_and_severity(site):
    write(site, "index.html", '<a href="/Lessons/a/">wrong case</a> <a href="/about/">ok</a>\n')
    write(site, "lessons/a/index.html", '<a href="../b/">rel</a> <a href="https://b4him.com/missing/">self</a>'
                                        "<a href='/about/nope'>single quoted</a> <a href=\"/_drafts/hidden.html\">u</a>\n")
    write(site, "new/index.html", '<a href="/gone/">a page not yet live</a>\n')
    g(site, "add", "-A")
    g(site, "commit", "-q", "-m", "drift")
    res = linkcheck.run(site, "live", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW)
    bad = {(b["page"], b["link"]): b for b in res["report"]["internal"]["broken"]}
    assert set(bad) == {("index.html", "/Lessons/a/"), ("lessons/a/index.html", "../b/"),
                        ("lessons/a/index.html", "https://b4him.com/missing/"),
                        ("lessons/a/index.html", "/about/nope"), ("lessons/a/index.html", "/_drafts/hidden.html"),
                        ("new/index.html", "/gone/")}
    assert bad[("index.html", "/Lessons/a/")]["severity"] == "S2"          # live page
    assert bad[("new/index.html", "/gone/")]["severity"] == "S3"           # not in the live tree
    assert bad[("lessons/a/index.html", "/_drafts/hidden.html")]["kind"] == "unserved"
    r = by_row(res)
    assert r["W1"]["outcome"] == "FINDINGS" and r["W1"]["n"] == 6 and "(5 S2)" in r["W1"]["why"]
    assert linkcheck.exit_code(res["receipts"]) == 1
    f = lines(site, "maintenance_findings.jsonl")
    assert len(f) == 6 and {x["route_to"] for x in f} == {"Site Maintainer"} and all(x["row"] == "W1" for x in f)


def test_unreadable_live_ref_counts_every_broken_link_as_live(site):
    write(site, "index.html", '<a href="/nope/">x</a>\n')
    res = linkcheck.run(site, "no-such-ref", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW)
    assert [b["severity"] for b in res["report"]["internal"]["broken"]] == ["S2"]
    assert "no-such-ref" in res["report"]["internal"]["note"]


# ---------------------------------------------------------------- W1(a): UNKNOWN
def test_internal_check_that_cannot_run_is_unknown(tmp_path, monkeypatch):
    root = tmp_path / "not-a-repo"
    root.mkdir()
    monkeypatch.setattr(pb, "REPO", root)
    res = linkcheck.run(root, "live", FakeNet({}).fetcher(), NOW)
    r = by_row(res)
    assert r["W1"]["outcome"] == "UNKNOWN" and "could not run" in r["W1"]["why"]
    assert r["W1b"]["outcome"] == "UNKNOWN"
    assert linkcheck.exit_code(res["receipts"]) == 2


# ---------------------------------------------------------------- W1(b) + W1b: FINDINGS with a proposal
def test_dead_outbound_gets_a_wayback_proposal(site):
    net = FakeNet({("HEAD", OUT): 404, ("GET", OUT): 404, ("GET", linkcheck.WAYBACK_API): wb_json()})
    res = linkcheck.run(site, "live", net.fetcher(), NOW)
    r = by_row(res)
    assert r["W1"]["outcome"] == "FINDINGS" and r["W1"]["n"] == 1
    assert r["W1b"]["outcome"] == "FINDINGS" and r["W1b"]["n"] == 1 and "1 with a proposed snapshot" in r["W1b"]["why"]
    (f,) = lines(site, "maintenance_findings.jsonl")
    assert f["severity"] == "S3" and f["pages"] == ["about/index.html"]
    assert f["proposal"]["replacement"].startswith("http://web.archive.org/web/20250101000000/")
    assert f["proposal"]["status"] == "PROPOSED, not applied"
    wb_call = [c for c in net.calls if c[1].startswith(linkcheck.WAYBACK_API)][0]
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(wb_call[1]).query)["url"] == [OUT]


def test_dead_link_with_no_snapshot_is_reported_without_a_proposal(site):
    net = FakeNet({("HEAD", OUT): 410, ("GET", OUT): 410,
                   ("GET", linkcheck.WAYBACK_API): b'{"url": "x", "archived_snapshots": {}}'})
    res = linkcheck.run(site, "live", net.fetcher(), NOW)
    assert by_row(res)["W1b"]["outcome"] == "FINDINGS" and "1 with none" in by_row(res)["W1b"]["why"]
    (f,) = lines(site, "maintenance_findings.jsonl")
    assert f["proposal"] is None and f["wayback_status"] == "NONE"


def test_wayback_asks_near_the_date_the_link_was_last_alive(site):
    linkcheck.run(site, "live", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW - dt.timedelta(days=30))
    net = FakeNet({("HEAD", OUT): 404, ("GET", OUT): 404, ("GET", linkcheck.WAYBACK_API): wb_json()})
    linkcheck.run(site, "live", net.fetcher(), NOW)
    wb_call = [c for c in net.calls if c[1].startswith(linkcheck.WAYBACK_API)][0]
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(wb_call[1]).query)["timestamp"] == ["20261003090000"]


# ---------------------------------------------------------------- W1(b) + W1b: UNKNOWN, never broken
@pytest.mark.parametrize("answer", [urllib.error.URLError(OSError(11001, "getaddrinfo failed")), TimeoutError("t"),
                                    ConnectionResetError("reset"), 403, 429, 503])
def test_network_failure_or_ambiguous_status_is_unknown_never_dead(site, answer):
    net = FakeNet({("HEAD", OUT): answer, ("GET", OUT): answer})
    res = linkcheck.run(site, "live", net.fetcher(), NOW)
    r = by_row(res)
    assert r["W1"]["outcome"] == "UNKNOWN" and OUT in r["W1"]["why"]
    assert r["W1b"]["outcome"] == "UNKNOWN"                          # the dead set may be incomplete
    assert lines(site, "maintenance_findings.jsonl") == []           # nothing reported as broken
    assert OUT not in json.loads((site / ".maint" / "linkcache.json").read_text())["links"]   # UNKNOWN not cached
    assert linkcheck.exit_code(res["receipts"]) == 2


def test_failed_wayback_lookup_is_unknown(site):
    net = FakeNet({("HEAD", OUT): 404, ("GET", OUT): 404,
                   ("GET", linkcheck.WAYBACK_API): urllib.error.URLError("down")})
    res = linkcheck.run(site, "live", net.fetcher(), NOW)
    r = by_row(res)
    assert r["W1"]["outcome"] == "FINDINGS"                           # the dead link is still a finding
    assert r["W1b"]["outcome"] == "UNKNOWN" and "1 of 1 Wayback lookups failed" in r["W1b"]["why"]
    assert OUT not in json.loads((site / ".maint" / "linkcache.json").read_text())["wayback"]


# ---------------------------------------------------------------- the cache, the manners
def test_cache_skips_a_link_checked_within_7_days_and_refetches_after(site):
    linkcheck.run(site, "live", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW)
    again = FakeNet({})
    res = linkcheck.run(site, "live", again.fetcher(), NOW + dt.timedelta(days=6))
    assert again.calls == [] and res["report"]["outbound"][0]["source"] == "cache"
    assert by_row(res)["W1"]["outcome"] == "PASS"
    assert res["report_path"].name == "2026-11-08_links.json"
    later = FakeNet({("HEAD", OUT): 200})
    linkcheck.run(site, "live", later.fetcher(), NOW + dt.timedelta(days=8))
    assert len(later.calls) == 1


def test_same_day_rerun_keeps_the_first_report(site):
    a = linkcheck.run(site, "live", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW)
    b = linkcheck.run(site, "live", FakeNet({}).fetcher(), NOW)
    assert a["report_path"].exists() and b["report_path"].name == "2026-11-02_links-2.json"
    assert len(lines(site, "maintenance_log.jsonl")) == 4


def test_head_refused_falls_back_to_get_with_polite_rate_and_user_agent():
    net = FakeNet({("HEAD", OUT): 405, ("GET", OUT): 200, ("HEAD", OUT2): 200})
    f = net.fetcher()
    assert linkcheck.check_url(OUT, f)["status"] == "OK"
    assert linkcheck.check_url(OUT2, f)["status"] == "OK"
    assert [c[0] for c in net.calls] == ["HEAD", "GET", "HEAD"]
    assert net.slept == [1.0]                      # HEAD then GET on one host waits; another host does not
    assert all(c[2].startswith("b4him-maintenance/") and c[3] == linkcheck.TIMEOUT for c in net.calls)


def test_corrupt_cache_is_ignored_not_fatal(site):
    (site / ".maint").mkdir()
    (site / ".maint" / "linkcache.json").write_text("{not json", encoding="utf-8")
    res = linkcheck.run(site, "live", FakeNet({("HEAD", OUT): 200}).fetcher(), NOW)
    assert res["report"]["cache"]["state"].startswith("unreadable") and by_row(res)["W1"]["outcome"] == "PASS"


# ---------------------------------------------------------------- maint_receipt
def test_receipt_shape_and_refusals(site):
    r = maint_receipt.write_receipt("W1", "PASS", n=0, why="ok", evidence=None, tool="x.py")
    assert set(r) == {"at", "row", "outcome", "n", "why", "evidence", "tool"}
    with pytest.raises(ValueError):
        maint_receipt.write_receipt("W1", "OK")
    with pytest.raises(ValueError):
        maint_receipt.write_receipt("W1", "FINDINGS")
    with pytest.raises(ValueError):
        maint_receipt.write_receipt("W1", "UNKNOWN")
    with pytest.raises(ValueError):
        maint_receipt.write_finding("W1", "S9", "s", "d", "r")
    f = maint_receipt.write_finding("W1", "S3", "s", "d", "Site Maintainer", proposal=None, at="ignored")
    assert list(f)[:6] == ["at", "row", "severity", "subject", "detail", "route_to"] and f["at"] != "ignored" and "proposal" in f
