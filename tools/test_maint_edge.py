"""Tests for tools/headers_tls_check.py (rows M3, Q4, Q5, C1) and tools/maint_receipt.py. No network: every probe is
a fake, and a guard makes any real socket connect fail the test."""
import datetime as dt
import json
import socket
import ssl

import pytest

import headers_tls_check as h
import maint_receipt

DAY = dt.date(2026, 10, 31)
NOW = dt.datetime(2026, 10, 31, 12, 0, tzinfo=dt.timezone.utc)


@pytest.fixture(autouse=True)
def sandbox(tmp_path, monkeypatch):
    d = tmp_path / ".maint"
    monkeypatch.setattr(maint_receipt, "maint_dir", lambda: d)
    monkeypatch.setattr(maint_receipt, "repo", lambda: tmp_path)

    def no_net(*a, **k):
        raise AssertionError("a test tried to open a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", no_net)
    monkeypatch.delenv("MAINT_OBSERVATORY_OK", raising=False)
    monkeypatch.delenv("UPTIMEROBOT_API_KEY", raising=False)
    return d


def receipts(d):
    return [json.loads(x) for x in (d / "maintenance_log.jsonl").read_text(encoding="utf-8").splitlines()]


def findings(d):
    p = d / "maintenance_findings.jsonl"
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------------------------------------------------------- maint_receipt

def test_receipt_shape(sandbox):
    r = maint_receipt.write_receipt("X1", "FINDINGS", n=2, why="w", evidence=".maint/a.json", tool="t.py")
    assert set(r) == {"at", "row", "outcome", "n", "why", "evidence", "tool"}
    assert receipts(sandbox) == [r]
    with pytest.raises(ValueError):
        maint_receipt.write_receipt("X1", "OK")
    with pytest.raises(ValueError):
        maint_receipt.write_receipt("X1", "FINDINGS")
    f = maint_receipt.write_finding("X1", "S2", "s", "d", "r")
    assert set(f) == {"at", "row", "severity", "subject", "detail", "route_to"}


# ---------------------------------------------------------------- M3 tls

def cert_in(days):
    t = NOW + dt.timedelta(days=days)
    return {"not_after": t.strftime("%b %d %H:%M:%S %Y GMT"), "issuer": "O=Let's Encrypt"}


def fake_http(headers=None, redirect=(301, "https://b4him.com/"), https_status=200):
    headers = headers or {"server": "GitHub.com", "content-type": "text/html; charset=utf-8",
                          "strict-transport-security": "max-age=31556952", "date": "Sat, 31 Oct 2026 12:00:00 GMT"}

    def probe(url, method="HEAD", timeout=20):
        if url.startswith("http://"):
            return {"status": redirect[0], "headers": {"location": redirect[1]}}
        return {"status": https_status, "headers": dict(headers)}
    return probe


def tls_fakes(monkeypatch, days=60, grep=(), **kw):
    monkeypatch.setattr(h, "probe_cert", lambda host: cert_in(days))
    monkeypatch.setattr(h, "probe_http", fake_http(**kw))
    monkeypatch.setattr(h, "git_grep_http", lambda root: list(grep))


def test_tls_pass_baseline_then_volatile_only_diff(sandbox, monkeypatch):
    tls_fakes(monkeypatch)
    r = h.run_tls(day=DAY, now=NOW)
    assert r["outcome"] == "PASS" and r["n"] == 0 and "60.0 days" in r["why"]
    ev = json.loads((sandbox / "audits" / "2026-10-31_tls.json").read_text(encoding="utf-8"))
    assert ev["header_diff"].startswith("no previous snapshot") and ev["threshold_assumed"] is True
    assert (sandbox / "headers" / "2026-10-31.json").exists()
    # next month, only the Date header differs: still PASS
    tls_fakes(monkeypatch, headers={"server": "GitHub.com", "content-type": "text/html; charset=utf-8",
                                    "strict-transport-security": "max-age=31556952", "date": "Mon, 30 Nov 2026"})
    r2 = h.run_tls(day=dt.date(2026, 11, 30), now=NOW)
    assert r2["outcome"] == "PASS"


def test_tls_findings_cert_headers_mixed(sandbox, monkeypatch):
    tls_fakes(monkeypatch)
    h.run_tls(day=DAY, now=NOW)
    grep = ['index.html:12:<img src="http://example.org/a.png">',
            'lessons/x.html:4:<link rel="stylesheet" href="http://cdn.example/s.css">',
            'style.css:9:  background: url("http://example.org/b.png");',
            'about/index.html:7:<a href="http://example.org/">a plain link is navigation, not a subresource</a>',
            '_drafts/y.html:1:<script src="http://never-served/x.js"></script>',
            '.maint/z.html:1:<img src="http://never-served/z.png">']
    tls_fakes(monkeypatch, days=9.5, grep=grep, headers={"server": "GitHub.com", "content-type": "text/html"})
    r = h.run_tls(day=dt.date(2026, 11, 30), now=NOW)
    assert r["outcome"] == "FINDINGS"
    fs = findings(sandbox)
    s1 = [f for f in fs if f["severity"] == "S1"]
    assert len(s1) == 1 and "expires in 9.5 days" in s1[0]["subject"] and s1[0]["route_to"] == h.ROUTE_S1
    mixed = [f for f in fs if f["severity"] == "S2"]
    assert sorted(f["subject"].split(" in ")[1] for f in mixed) == ["index.html:12", "lessons/x.html:4", "style.css:9"]
    changed = {f["subject"].split()[2] for f in fs if f["severity"] == "S3"}
    assert changed == {"content-type", "strict-transport-security"}
    assert r["n"] == len(fs)


def test_tls_https_failing_is_s1(sandbox, monkeypatch):
    def bad_cert(host):
        raise ssl.SSLCertVerificationError("certificate verify failed: certificate has expired")
    tls_fakes(monkeypatch)
    monkeypatch.setattr(h, "probe_cert", bad_cert)
    monkeypatch.setattr(h, "probe_http", fake_http(redirect=(200, ""), https_status=404))
    r = h.run_tls(day=DAY, now=NOW)
    assert r["outcome"] == "FINDINGS"
    subjects = [f["subject"] for f in findings(sandbox) if f["severity"] == "S1"]
    assert any(s.startswith("HTTPS failing") for s in subjects)
    assert any("does not redirect" in s for s in subjects)
    assert any("returns 404" in s for s in subjects)


def test_tls_unknown_when_local_network_down(sandbox, monkeypatch):
    def offline(*a, **k):
        raise h.LocalNetworkError("cannot resolve b4him.com: getaddrinfo failed")

    def grep_broken(root):
        raise RuntimeError("git grep exit 128: not a git repository")
    monkeypatch.setattr(h, "probe_cert", offline)
    monkeypatch.setattr(h, "probe_http", offline)
    monkeypatch.setattr(h, "git_grep_http", grep_broken)
    r = h.run_tls(day=DAY, now=NOW)
    assert r["outcome"] == "UNKNOWN" and r["n"] is None
    assert "cannot resolve" in r["why"] and "git grep" in r["why"]
    assert findings(sandbox) == []
    assert not (sandbox / "headers").exists()


# ---------------------------------------------------------------- Q4 dns

GOOD = {
    ("b4him.com", "A"): ("ok", sorted(h.PAGES_A)),
    ("b4him.com", "AAAA"): ("ok", sorted(h.PAGES_AAAA)),
    ("b4him.com", "CNAME"): ("noanswer", []),
    ("www.b4him.com", "CNAME"): ("ok", ["sobevista.github.io."]),
    ("_github-pages-challenge-sobevista.b4him.com", "TXT"): ("ok", ["s3cr3t-looking-value"]),
}
PAGES_OK = {"cname": "b4him.com", "https_enforced": True, "status": "built", "build_type": "legacy"}


def dns_fakes(monkeypatch, table=None, wildcard=("nxdomain", []), pages=("ok", PAGES_OK)):
    table = {**GOOD, **(table or {})}

    def fake(name, rtype):
        if name.startswith("maint-"):
            return wildcard
        return table.get((name, rtype), ("nxdomain", []))
    monkeypatch.setattr(h, "resolve", fake)
    monkeypatch.setattr(h, "gh_pages", lambda slug: pages)


def test_dns_pass(sandbox, monkeypatch):
    dns_fakes(monkeypatch)
    r = h.run_dns(day=DAY)
    assert r["outcome"] == "PASS", r["why"]
    ev = (sandbox / "audits" / "2026-10-31_dns.json").read_text(encoding="utf-8")
    assert "s3cr3t-looking-value" not in ev  # TXT presence only, never its value


def test_dns_findings(sandbox, monkeypatch):
    dns_fakes(monkeypatch,
              table={("b4him.com", "A"): ("ok", ["185.199.108.153", "203.0.113.9"]),
                     ("www.b4him.com", "CNAME"): ("ok", ["someone-else.github.io."]),
                     ("_github-pages-challenge-sobevista.b4him.com", "TXT"): ("nxdomain", [])},
              wildcard=("ok", ["185.199.108.153"]),
              pages=("ok", {**PAGES_OK, "https_enforced": False}))
    r = h.run_dns(day=DAY)
    assert r["outcome"] == "FINDINGS" and r["n"] == 5
    by = {f["severity"]: [] for f in findings(sandbox)}
    for f in findings(sandbox):
        by[f["severity"]].append(f["subject"])
    assert any("203.0.113.9" in s for s in by["S1"])
    assert any("wildcard" in s for s in by["S1"])
    assert any("someone-else" in s for s in by["S1"])
    assert any("verification TXT" in s for s in by["S2"]) and any("Enforce HTTPS" in s for s in by["S2"])


def test_dns_unknown_without_gh_or_resolver(sandbox, monkeypatch):
    dns_fakes(monkeypatch, pages=("unknown", "gh api exit 1: not logged in"))
    r = h.run_dns(day=DAY)
    assert r["outcome"] == "UNKNOWN" and "Enforce HTTPS" in r["why"]
    dns_fakes(monkeypatch, table={("b4him.com", "A"): ("error", ["LifetimeTimeout: no answer"])},
              wildcard=("error", ["LifetimeTimeout"]))
    r2 = h.run_dns(day=DAY)
    assert r2["outcome"] == "UNKNOWN" and "LifetimeTimeout" in r2["why"]


# ---------------------------------------------------------------- Q5 observatory

def test_observatory_refuses_without_ok(sandbox, monkeypatch):
    def must_not_call(*a, **k):
        raise AssertionError("scanned without Daniel's OK")
    monkeypatch.setattr(h, "http_post", must_not_call)
    r = h.run_observatory(day=DAY)
    assert r["outcome"] == "UNKNOWN" and r["why"] == "awaiting Daniel's one-time OK"
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "yes")  # only the exact value 1 counts
    assert h.run_observatory(day=DAY)["outcome"] == "UNKNOWN"


def obs(monkeypatch, status, payload):
    calls = []

    def fake(url, data, headers, timeout=60):
        calls.append(url)
        return status, json.dumps(payload).encode()
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")
    monkeypatch.setattr(h, "http_post", fake)
    return calls


def test_observatory_pass_findings_unknown(sandbox, monkeypatch):
    base = {"id": 1, "details_url": "https://developer.mozilla.org/en-US/observatory/analyze?host=b4him.com",
            "algorithm_version": 4, "scanned_at": "2026-10-31T00:00:00Z", "error": None, "grade": "A+", "score": 105,
            "status_code": 200, "tests_failed": 0, "tests_passed": 10, "tests_quantity": 10}
    calls = obs(monkeypatch, 200, base)
    r = h.run_observatory(day=DAY)
    assert r["outcome"] == "PASS" and "grade A+" in r["why"]
    assert calls == ["https://observatory-api.mdn.mozilla.net/api/v2/scan?host=b4him.com"]
    obs(monkeypatch, 200, {**base, "grade": "D", "score": 30, "tests_failed": 4, "tests_passed": 6})
    r = h.run_observatory(day=DAY)
    assert r["outcome"] == "FINDINGS" and r["n"] == 1 and "tests_failed 4/10" in r["why"]
    obs(monkeypatch, 422, {"error": "invalid-hostname-lookup", "message": "b4him.com cannot be resolved"})
    r = h.run_observatory(day=DAY)
    assert r["outcome"] == "UNKNOWN" and "invalid-hostname-lookup" in r["why"]


# ---------------------------------------------------------------- C1 uptime

def test_uptime_unknown_without_key(sandbox, monkeypatch):
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (_ for _ in ()).throw(AssertionError("called without key")))
    r = h.run_uptime(day=DAY)
    assert r["outcome"] == "UNKNOWN" and r["why"] == "no UPTIMEROBOT_API_KEY"


def ur(monkeypatch, status, payload):
    seen = {}

    def fake(url, data, headers, timeout=60):
        seen["url"], seen["data"] = url, data
        return status, json.dumps(payload).encode()
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "ur-readonly-SECRET")
    monkeypatch.setattr(h, "http_post", fake)
    return seen


def mon(status, ratio="99.981"):
    return {"id": 1, "friendly_name": "b4him home", "url": "https://b4him.com/", "status": status,
            "custom_uptime_ratio": ratio}


def test_uptime_pass_findings_unknown(sandbox, monkeypatch):
    seen = ur(monkeypatch, 200, {"stat": "ok", "monitors": [mon(2)]})
    r = h.run_uptime(day=DAY)
    assert r["outcome"] == "PASS" and "b4him home: up, last 7 days uptime 99.981%" in r["why"]
    assert seen["url"] == "https://api.uptimerobot.com/v2/getMonitors"
    assert b"custom_uptime_ratios=7" in seen["data"] and b"api_key=ur-readonly-SECRET" in seen["data"]
    ur(monkeypatch, 200, {"stat": "ok", "monitors": [mon(9, "97.2")]})
    r = h.run_uptime(day=DAY)
    assert r["outcome"] == "FINDINGS" and findings(sandbox)[-1]["severity"] == "S1"
    ur(monkeypatch, 200, {"stat": "ok", "monitors": [mon(0)]})
    assert h.run_uptime(day=DAY)["outcome"] == "UNKNOWN"  # a paused monitor is UNKNOWN, never up
    ur(monkeypatch, 200, {"stat": "fail", "error": {"type": "invalid_parameter", "message": "api_key is wrong"}})
    r = h.run_uptime(day=DAY)
    assert r["outcome"] == "UNKNOWN" and "invalid_parameter" in r["why"]
    ur(monkeypatch, 200, {"stat": "ok", "monitors": []})
    assert h.run_uptime(day=DAY)["outcome"] == "UNKNOWN"
    for p in sandbox.rglob("*"):
        if p.is_file():
            assert "SECRET" not in p.read_text(encoding="utf-8"), p


def test_cli_exit_codes(sandbox, monkeypatch, capsys):
    assert h.main(["observatory"]) == 2
    assert json.loads(capsys.readouterr().out)["row"] == "Q5"
    dns_fakes(monkeypatch)
    assert h.main(["dns"]) == 0
