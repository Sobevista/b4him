"""The harness scope lock's cite tests for the 28 b4him maintenance-baseline rows (C1 .. A4).

Each row has a CLEAN-WORLD fixture (everything right: the row's quiet outcome) and one cite per FACET of its calendar
task (each thing the row must catch). Every cite names its row as a literal, drives the row through
`maint_run.py --row <id>` (in process: run.RUN calls the row's tool's own main(); only the network and the clock are
faked) and asserts on the receipt that run wrote to `.maint/receipts/<row>.json` under a temporary MAINT_DIR: a
path-shaped receipt produced at run time, never a committed file. Hand closes (judge, human, confirm, witness) are
asserted against the counter's HAND CLOSE rule: the close follows an awaiting SKIP, carries the same evidence, and is
written by tools/maint_watch.py.

Discrimination: tools/maint_cite_mutants.py applies one gutting mutant per facet to the row's tool in a scratch copy
and shows at least one cite of that row fails for each (the kill matrix).

The tools are imported INSIDE the test bodies, so on a tree without them (b4him main d67bd8d) every test FAILS rather
than erroring at collection. No network: sockets are refused; HTTP, DNS, TLS, RDAP and browsers are fakes.
"""
import datetime as dt
import json
import socket
import subprocess
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TZ = dt.timezone(dt.timedelta(hours=-5))
#: A pa11y-ci --json report recorded from a real run of M1 over this site (2026-10-31): 7 issues on 4 pages.
PA11Y_RECORDED = HERE / "_maint_fixtures" / "pa11y-ci" / "report-2026-10-31.json"


class Clock:
    def __init__(self, *when):
        self.set(*when)

    def set(self, *when):
        self.t = dt.datetime(*when, tzinfo=TZ)

    def __call__(self):
        return self.t.astimezone(dt.timezone.utc)


def inproc(argv, timeout):
    """maint_run's RUN, in process: the tool's own main() with its argv, stdout captured, exit code returned."""
    import contextlib
    import importlib
    import io
    import sys
    mod = importlib.import_module(Path(argv[1]).stem)
    out, err, saved = io.StringIO(), io.StringIO(), sys.argv
    sys.argv = [argv[1], *argv[2:]]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = mod.main(list(argv[2:]))
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
    except Exception as e:  # noqa: BLE001 - a tool crash is the runner's to judge, as in a real child process
        return 1, out.getvalue(), f"{type(e).__name__}: {e}"
    finally:
        sys.argv = saved
    return code, out.getvalue(), err.getvalue()


def world(monkeypatch, tmp_path, *when):
    """A temporary .maint, a fixed clock, no network, no scheduler; maint_run drives tools in process."""
    import maint_receipt as mr
    import maint_run as run
    import maint_watch as mw
    md = tmp_path / ".maint"
    monkeypatch.setenv("MAINT_DIR", str(md))
    for v in ("MAINT_RUN_ID", "MAINT_TRIGGER", "MAINT_HEARTBEAT_URL", "UPTIMEROBOT_API_KEY", "CRUX_API_KEY",
              "MAINT_OBSERVATORY_OK"):
        monkeypatch.delenv(v, raising=False)
    clock = Clock(*(when or (2026, 11, 2, 11)))
    monkeypatch.setattr(mr, "now_utc", clock)
    monkeypatch.setattr(mw, "LOCAL_TZ", TZ)
    monkeypatch.setattr(mw, "SCHEDULE_CHECK", lambda now: {"state": "ok", "problems": [], "why": "ok"})
    monkeypatch.setattr(run, "RUN", inproc)

    def no_net(*a, **k):
        raise AssertionError("a cite test opened a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", no_net)
    return md, clock


def snap(row):
    """Write the row's latest receipt to .maint/receipts/<row>.json (the run-time receipt the asserts read)."""
    import maint_receipt as mr
    mine = [e for e in mr.read_receipts() if e.get("row") == row]
    p = mr.maint_dir() / "receipts" / f"{row}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(mine[-1] if mine else {}), encoding="utf-8")
    return mine


def drive(row):
    """`maint_run.py --row <row>`, then its receipt snapshot. Returns maint_run's exit code."""
    import maint_run as run
    code = run.main(["--row", row])
    snap(row)
    return code


def close(row, *argv):
    """A person's act through maint_watch (judge / human / confirm / witness), then the row's receipt snapshot.
    Returns (exit code, the line before the close, the close) for the HAND CLOSE assertions."""
    import maint_watch as mw
    before = snap(row)
    code = mw.main(list(argv))
    after = snap(row)
    return code, (before[-1] if before else {}), (after[-1] if after else {})


def hand_close_ok(prev, rec):
    """The counter's HAND CLOSE rule: the close follows an awaiting SKIP, carries its evidence, written by maint_watch."""
    return (prev.get("outcome") == "SKIP" and str(prev.get("why", "")).startswith("awaiting ")
            and bool(rec.get("evidence")) and rec.get("evidence") == prev.get("evidence")
            and rec.get("tool") == "tools/maint_watch.py")


def load(md, rel):
    return json.loads((md / rel).read_text(encoding="utf-8"))


def findings(row):
    import maint_receipt as mr
    return [f for f in mr.read_findings() if f.get("row") == row]


def pages_repo(monkeypatch, tmp_path, files=None, names=False):
    """A throwaway b4him-shaped git repo (test_maint_pages.make_repo) as the page tools' tree."""
    import maint_pages as mp
    import production_board as pb
    from test_maint_pages import local_names, make_repo
    repo = make_repo(tmp_path, files)
    if names:
        local_names(repo)
    monkeypatch.setattr(mp, "REPO", repo)
    monkeypatch.setattr(pb, "REPO", repo)
    return repo


# ================================================================== C1 uptime monitor reader
MONS = [{"friendly_name": "home", "url": "https://b4him.com/", "status": 2, "custom_uptime_ratio": "99.9"},
        {"friendly_name": "lesson", "url": "https://b4him.com/lessons/first-lap/", "status": 2,
         "custom_uptime_ratio": "100"}]


def _monitors(monkeypatch, mons):
    import headers_tls_check as h
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "ur-test")
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({"stat": "ok", "monitors": mons}).encode()))


def test_cite_C1_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, MONS)
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "PASS" and "last 7 days uptime" in rec["why"]


def test_cite_C1_home_page_must_be_monitored(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], url="https://example.org/"), MONS[1]])
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "FINDINGS" and "no monitor watches https://b4him.com/" in rec["why"]


def test_cite_C1_a_lesson_must_be_monitored(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [MONS[0], dict(MONS[1], url="https://b4him.com/about/")])
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "FINDINGS" and "no monitor watches one lesson URL" in rec["why"]


def test_cite_C1_a_down_monitor_is_s1(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], status=9), MONS[1]])
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("C1")] == ["S1"]


def test_cite_C1_no_key_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no UPTIMEROBOT_API_KEY")


# ================================================================== D1 release run watch
LINE = {"at": "2026-11-02T13:30:01+00:00", "date": "2026-11-02", "mode": "apply", "lane": "content",
        "outcome": "PUBLISHED"}


def _release(monkeypatch, tmp_path, *lines):
    import maint_watch as mw
    monkeypatch.setattr(mw, "REPO", tmp_path)
    (tmp_path / "release_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def test_cite_D1_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _release(monkeypatch, tmp_path, LINE)
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/maint_watch.py"


def test_cite_D1_no_line_by_10_30_is_missing(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _release(monkeypatch, tmp_path, dict(LINE, date="2026-11-01"))
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "FINDINGS" and "MISSING" in rec["why"]


def test_cite_D1_a_failed_release_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _release(monkeypatch, tmp_path, dict(LINE, outcome="FAIL"))
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "FINDINGS" and "FAIL" in rec["why"]


def test_cite_D1_before_the_cutoff_is_pending(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 2, 9)
    _release(monkeypatch, tmp_path, dict(LINE, date="2026-11-01"))
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "UNKNOWN" and "10:30 has not passed" in rec["why"]


# ================================================================== D2 calendar watch
def _table(monkeypatch, tmp_path, *ids):
    import maint_watch as mw
    real = {r["id"]: r for r in json.loads(mw.ROWS_FILE.read_text(encoding="utf-8"))["rows"]}
    small = tmp_path / "rows.json"
    small.write_text(json.dumps({"epoch": "2026-10-20", "rows": [real[i] for i in ids]}), encoding="utf-8")
    monkeypatch.setattr(mw, "ROWS_FILE", small)


def test_cite_D2_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2", "M4")
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    mr.write_receipt("M4", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "PASS" and "none UNKNOWN" in rec["why"]


def test_cite_D2_an_overdue_row_is_listed(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _table(monkeypatch, tmp_path, "D1", "D2")
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "FINDINGS" and "D1 (no receipt ever" in rec["why"]


def test_cite_D2_a_stuck_unknown_is_an_alarm(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 2, 7)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2")
    mr.write_receipt("D1", "UNKNOWN", why="no release log", tool="maint_watch.py")
    clock.set(2026, 11, 2, 9, 30)
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "FINDINGS" and "D1 STUCK" in rec["why"]


def test_cite_D2_an_unjudged_assist_row_goes_overdue(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D2", "M4")
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: pack", tool="maint_pages.py")
    clock.set(2026, 12, 7, 11)
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: pack", tool="maint_pages.py")
    clock.set(2026, 12, 11, 0, 1)
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "FINDINGS" and "M4 (awaiting judgement since 2026-11-02" in rec["why"]


# ================================================================== D3 heartbeat
def _hb(monkeypatch):
    import maint_watch as mw
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    calls = []
    monkeypatch.setattr(mw, "HTTP_GET", lambda url: (calls.append(url), (200, "OK"))[1])
    return calls


def _d1d2(outcome2="PASS", why2="ok"):
    import maint_receipt as mr
    mr.write_receipt("D1", "PASS", why="ok", tool="maint_watch.py")
    mr.write_receipt("D2", outcome2, n=1 if outcome2 == "FINDINGS" else None, why=why2, tool="maint_watch.py")


def test_cite_D3_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    calls = _hb(monkeypatch)
    _d1d2()
    drive("D3")
    rec = load(md, "receipts/D3.json")
    assert rec["outcome"] == "PASS" and calls == ["https://hc-ping.example.invalid/x"]


def test_cite_D3_an_unknown_watch_pings_fail(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    calls = _hb(monkeypatch)
    _d1d2("UNKNOWN", "cannot judge")
    drive("D3")
    rec = load(md, "receipts/D3.json")
    assert rec["outcome"] == "PASS" and calls[-1].endswith("/fail") and "D2 UNKNOWN" in rec["why"]


def test_cite_D3_a_new_alarm_fails_once_then_stands(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    import maint_watch as mw
    calls = _hb(monkeypatch)
    _table(monkeypatch, tmp_path, "D1", "D2", "W1")
    for day in (2, 3):
        clock.set(2026, 11, day, 10)
        import maint_receipt as mr
        mr.write_receipt("D1", "PASS", why="ok", tool="maint_watch.py")
        clock.set(2026, 11, day, 10, 35)
        mw.run_d2(mw.local(clock()))
        drive("D3")
        rec = load(md, "receipts/D3.json")
        assert rec["outcome"] == "PASS" and calls[-1].endswith("/fail") == (day == 2)


def test_cite_D3_no_url_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _d1d2()
    drive("D3")
    rec = load(md, "receipts/D3.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no MAINT_HEARTBEAT_URL")


# ================================================================== W1 / W1b link check, Wayback
def _net(monkeypatch, dead=(), wayback=True):
    import urllib.error

    import linkcheck as lc
    import maint_receipt as mr
    real = getattr(lc.Fetcher, "real", lc.Fetcher)
    calls = []

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

    def opener(req, timeout=None):
        u = req.full_url
        calls.append(u)
        if u.startswith(lc.WAYBACK_API):
            if not wayback:
                raise urllib.error.URLError("archive unreachable")
            return Resp(200, u, json.dumps({"archived_snapshots": {"closest": {
                "available": True, "url": "http://web.archive.org/web/2025/x", "timestamp": "20250101000000",
                "status": "200"}}}).encode())
        if any(u.startswith(d) for d in dead):
            raise urllib.error.HTTPError(u, 404, "Not Found", {}, None)
        return Resp(200, u)

    def factory():
        return real(opener=opener, sleep=lambda s: None)
    factory.real = real
    monkeypatch.setattr(lc, "Fetcher", factory)
    (mr.maint_dir() / "linkcache.json").unlink(missing_ok=True)
    return calls


OUT = "https://example.org/a-page"


def test_cite_W1_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/linkcheck.py" and "23 pages" in rec["why"]


def test_cite_W1_internal_link_case_sensitive(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": '<a href="../Lessons/alpha/">x</a>'})
    _net(monkeypatch)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "FINDINGS" and "1 broken internal" in rec["why"]


def test_cite_W1_every_page_not_only_touched(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"zz/deep/index.html": '<a href="../nowhere/">x</a>'})
    _net(monkeypatch)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "FINDINGS" and "1 broken internal" in rec["why"]


def test_cite_W1_dead_outbound_link(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "FINDINGS" and "1 dead" in rec["why"]


def test_cite_W1_outbound_answers_are_cached(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    calls = _net(monkeypatch)
    drive("W1")
    first = len(calls)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "PASS" and first >= 1 and len(calls) == first      # the second week fetched nothing


def test_cite_W1b_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch)
    drive("W1b")
    rec = load(md, "receipts/W1b.json")
    assert rec["outcome"] == "SKIP" and rec["why"] == "no dead outbound links this run"


def test_cite_W1b_dead_link_gets_a_proposed_snapshot(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    drive("W1b")
    rec = load(md, "receipts/W1b.json")
    prop = [f.get("proposal") for f in findings("W1") if f.get("proposal")]
    assert rec["outcome"] == "FINDINGS" and prop and prop[0]["status"] == "PROPOSED, not applied"


def test_cite_W1b_a_failed_lookup_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,), wayback=False)
    drive("W1b")
    rec = load(md, "receipts/W1b.json")
    assert rec["outcome"] == "UNKNOWN" and "Wayback lookups failed" in rec["why"]


# ================================================================== W2 weekly digest
def _digest(md, rec):
    return (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")


def test_cite_W2_clean_world_says_0_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("W2")
    rec = load(md, "receipts/W2.json")
    assert rec["outcome"] == "PASS" and "0 findings" in _digest(md, rec)


def test_cite_W2_lists_open_findings_by_age(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 28, 9)
    import maint_receipt as mr
    mr.write_finding("W1", "S2", "internal link about -> /gone/", "x", "Site Maintainer")
    mr.write_receipt("W1", "FINDINGS", n=1, why="1 broken", tool="linkcheck.py")
    clock.set(2026, 11, 2, 11)
    drive("W2")
    rec = load(md, "receipts/W2.json")
    assert rec["outcome"] == "PASS" and "5 d · W1 S2 internal link about -> /gone/" in _digest(md, rec)


def test_cite_W2_lists_unknowns_by_age(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 30, 11)
    import maint_receipt as mr
    mr.write_receipt("M2b", "UNKNOWN", why="no CRUX_API_KEY", tool="maint_quality.py")
    clock.set(2026, 11, 2, 11)
    drive("W2")
    rec = load(md, "receipts/W2.json")
    assert rec["outcome"] == "PASS" and "3 d · M2b: no CRUX_API_KEY" in _digest(md, rec)


def test_cite_W2_carries_the_monitor_line(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    mr.write_receipt("C1", "PASS", n=0, why="home: up, last 7 days uptime 99.9%", tool="headers_tls_check.py")
    drive("W2")
    rec = load(md, "receipts/W2.json")
    assert rec["outcome"] == "PASS" and "C1 uptime monitor: PASS home: up, last 7 days uptime 99.9%" in _digest(md, rec)


# ================================================================== W3 people scan
def test_cite_W3_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, names=True)
    drive("W3")
    rec = load(md, "receipts/W3.json")
    assert rec["outcome"] == "PASS" and "with the known-names list loaded" in rec["why"]


def test_cite_W3_a_planted_name_is_s1(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"about/index.html": "<p>i met Quillon there.</p>"}, names=True)
    drive("W3")
    rec = load(md, "receipts/W3.json")
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("W3")] == ["S1"]
    assert findings("W3")[0]["subject"] == "about/index.html: known-outside-rule"


def test_cite_W3_every_published_page(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, {"zz/deep/index.html": "<p>i met Quillon there.</p>"}, names=True)
    drive("W3")
    rec = load(md, "receipts/W3.json")
    assert rec["outcome"] == "FINDINGS" and findings("W3")[0]["subject"].startswith("zz/deep/index.html")


def test_cite_W3_no_names_file_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path)
    drive("W3")
    rec = load(md, "receipts/W3.json")
    assert rec["outcome"] == "UNKNOWN" and "people_names.local.json absent" in rec["why"]


# ================================================================== M1 accessibility scan (real parser, recorded run)
def _pa11y(monkeypatch, code, stdout):
    import maint_quality as mq
    monkeypatch.setattr(mq, "find_bin", lambda name, root: name)
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", lambda argv, cwd=None, env=None, timeout=0: types.SimpleNamespace(
        returncode=code, stdout=stdout, stderr=""))


def test_cite_M1_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 0, json.dumps({"total": 23, "passes": 23, "errors": 0, "results": {"http://h/": []}}))
    drive("M1")
    rec = load(md, "receipts/M1.json")
    assert rec["outcome"] == "PASS" and "0 WCAG2AA issues" in rec["why"]


def test_cite_M1_recorded_report_is_parsed_into_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 2, "pa11y-ci noise line\n" + PA11Y_RECORDED.read_text(encoding="utf-8"))
    drive("M1")
    rec = load(md, "receipts/M1.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 7) and "on 4 page(s)" in rec["why"]
    assert "do not cover all of WCAG 2.2 AA" in rec["why"]


def test_cite_M1_a_technical_fault_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 1, "Error: browser failed to launch")
    drive("M1")
    rec = load(md, "receipts/M1.json")
    assert rec["outcome"] == "UNKNOWN" and "technical fault" in rec["why"]


# ================================================================== M1b contrast audit
def _contrast(monkeypatch, failures=(), unverifiable=()):
    import maint_quality as mq
    from test_maint_quality import _row
    monkeypatch.setattr(mq, "audit_contrast", lambda root, rels: {"index.html": {
        "checked": 5, "failures": [_row(*f) for f in failures],
        "passingButUnverifiable": [_row("h1", 9, over=o) for o in unverifiable]}})


def test_cite_M1b_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch)
    drive("M1b")
    rec = load(md, "receipts/M1b.json")
    assert rec["outcome"] == "PASS" and "nothing painted over" in rec["why"]


def test_cite_M1b_a_failing_pair_is_findings_by_cause(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch, failures=[("p.a", 1.2), ("p.b", 1.3)])
    drive("M1b")
    rec = load(md, "receipts/M1b.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and "2 el" in rec["why"]


def test_cite_M1b_a_pseudo_element_waits_for_the_eye(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch, unverifiable=["body::before"])
    drive("M1b")
    rec = load(md, "receipts/M1b.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting site-maintainer judgement")
    code, prev, close_rec = close("M1b", "judge", "M1b", "PASS", "--seat", "site-maintainer", "--note",
                                  "judged by eye on every template")
    rec = load(md, "receipts/M1b.json")
    assert rec["outcome"] == "PASS" and hand_close_ok(prev, rec)


# ================================================================== M2 lab performance
def _lighthouse(monkeypatch, lcp, runs=3, outlier=None):
    import maint_quality as mq
    from test_maint_quality import _lhr
    paths = [mq.page_path(r) for r in mq.served_pages(REPO)]

    def run_cmd(argv, cwd=None, env=None, timeout=0):
        d = Path(cwd) / ".lighthouseci"
        d.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(paths):
            for k in range(runs):
                v = outlier if (outlier and k == 0) else lcp
                (d / f"lhr-{i}-{k}.json").write_text(json.dumps(_lhr(p, v, 0.0, 10)), encoding="utf-8")
        return types.SimpleNamespace(returncode=0, stdout="", stderr="")
    monkeypatch.setattr(mq, "find_bin", lambda name, root: "lhci")
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", run_cmd)
    return paths


def test_cite_M2_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200)
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert rec["outcome"] == "PASS" and "on the median of 3 runs" in rec["why"]


def test_cite_M2_the_median_not_the_worst_run(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200, outlier=9000)
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert rec["outcome"] == "PASS"


def test_cite_M2_a_budget_miss_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    paths = _lighthouse(monkeypatch, 3000)
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", len(paths))


def test_cite_M2_a_missing_run_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200, runs=2)
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert rec["outcome"] == "UNKNOWN" and "2/3 runs" in rec["why"]


# ================================================================== M2b field performance
def _crux(monkeypatch, status, body):
    import maint_quality as mq
    monkeypatch.setenv("CRUX_API_KEY", "test-key")
    monkeypatch.setattr(mq, "crux_query", lambda origin, key, opener=None: (status, body))


def test_cite_M2b_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_quality import _crux as crux_body
    _crux(monkeypatch, 200, crux_body())
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert rec["outcome"] == "PASS" and rec["why"].startswith("p75 ")


def test_cite_M2b_a_p75_miss_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_quality import _crux as crux_body
    _crux(monkeypatch, 200, crux_body(lcp=3100))
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert rec["outcome"] == "FINDINGS" and "largest_contentful_paint p75 3100" in rec["why"]


def test_cite_M2b_no_field_data_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 404, {"error": {"code": 404, "message": "chrome ux report data not found"}})
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("UNKNOWN-field")


def test_cite_M2b_no_key_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no CRUX_API_KEY")


# ================================================================== M3 TLS and headers
def _tls(monkeypatch, days=60, redirect=301, headers=None, grep=()):
    import headers_tls_check as h
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
    monkeypatch.setattr(h, "probe_cert", lambda host: {"not_after": t.strftime("%b %d %H:%M:%S %Y GMT"),
                                                       "issuer": "O=Let's Encrypt"})
    hdr = headers or {"server": "GitHub.com"}
    monkeypatch.setattr(h, "probe_http", lambda url, method="HEAD", timeout=20: (
        {"status": redirect, "headers": {"location": "https://b4him.com/"}} if url.startswith("http://")
        else {"status": 200, "headers": dict(hdr)}))
    monkeypatch.setattr(h, "git_grep_http", lambda root: list(grep))


def test_cite_M3_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch)
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"


def test_cite_M3_a_certificate_near_expiry_is_s1(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, days=5)
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "FINDINGS" and "certificate expires in" in rec["why"]


def test_cite_M3_http_must_redirect_to_https(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, redirect=200)
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "FINDINGS" and "does not redirect permanently" in rec["why"]


def test_cite_M3_a_changed_header_is_diffed(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    _tls(monkeypatch)
    snaps = md / "headers"
    snaps.mkdir(parents=True)
    (snaps / "2026-10-01.json").write_text(json.dumps({"headers": {"server": "nginx"}}), encoding="utf-8")
    monkeypatch.setattr(h, "today", lambda: dt.date(2026, 11, 2))
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "FINDINGS" and "response header server changed" in rec["why"]


def test_cite_M3_a_mixed_content_subresource(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, grep=['index.html:12:<img src="http://example.org/a.png">'])
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "FINDINGS" and "http:// subresource in index.html:12" in rec["why"]


# ================================================================== M4 reader walkthrough
JARGON = "<p>then i open the harness again later today and go home to rest for a while now.</p>"


def test_cite_M4_clean_world_awaits_the_editor(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path)
    drive("M4")
    rec = load(md, "receipts/M4.json")
    assert rec["outcome"] == "SKIP" and "no mechanical finding" in rec["why"] and not findings("M4")


def test_cite_M4_unglossed_jargon_on_the_route(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import page
    pages_repo(monkeypatch, tmp_path, {"lessons/alpha/index.html": page("Alpha", JARGON)})
    drive("M4")
    rec = load(md, "receipts/M4.json")
    assert rec["outcome"] == "SKIP" and "scanner found 1 unglossed jargon" in rec["why"]
    assert findings("M4")[0]["subject"] == "lessons/alpha/index.html: unglossed jargon"


def test_cite_M4_a_broken_reader_path(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import page
    pages_repo(monkeypatch, tmp_path, {"lessons/index.html": page("Lessons", "<p>no links</p>")})
    drive("M4")
    rec = load(md, "receipts/M4.json")
    assert rec["outcome"] == "SKIP" and "1 broken path segment" in rec["why"]
    assert findings("M4")[0]["severity"] == "S2"


def test_cite_M4_the_editors_judgement_closes_it(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path)
    drive("M4")
    code, prev, _ = close("M4", "judge", "M4", "FINDINGS", "1", "--seat", "managing-editor", "--note",
                          "one term needs a gloss")
    rec = load(md, "receipts/M4.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and hand_close_ok(prev, rec)


# ================================================================== M5 board run (a test per outcome)
def _board(monkeypatch, tmp_path, stamp=True):
    import maint_watch as mw
    head = (REPO / "PRODUCTION_BOARD.md").read_text(encoding="utf-8").splitlines()[:6]
    if not stamp:
        head = [x for x in head if "Generated" not in x]
    (tmp_path / "PRODUCTION_BOARD.md").write_text("\n".join(head) + "\n", encoding="utf-8")
    monkeypatch.setattr(mw, "REPO", tmp_path)


def test_cite_M5_clean_world_board_run_found(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2026, 10, 31, 11)
    _board(monkeypatch, tmp_path)
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "PASS" and "board run 2026-10-20 found" in rec["why"]


def test_m5_board_run_due_is_awaiting(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 3, 11)
    _board(monkeypatch, tmp_path)
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor")


def test_m5_board_run_overdue_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 6, 0, 1)
    _board(monkeypatch, tmp_path)
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "FINDINGS" and "board run overdue" in rec["why"]


def test_m5_unreadable_board_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _board(monkeypatch, tmp_path, stamp=False)
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "UNKNOWN" and "carries no '*Generated" in rec["why"]


# ================================================================== Q1 quarterly re-read
def _today(monkeypatch, day):
    import datetime as _d

    import maint_pages as mp

    class Day(_d.date):
        @classmethod
        def today(cls):
            return _d.date.fromisoformat(day)
    shim = types.SimpleNamespace(**{k: getattr(_d, k) for k in dir(_d) if not k.startswith("__")})
    shim.date = Day
    monkeypatch.setattr(mp, "dt", shim)


def test_cite_Q1_clean_world_none_due(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _today(monkeypatch, "2026-11-02")
    drive("Q1")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("0 of 23 pages due")


def test_cite_Q1_pages_past_90_days_await_the_editor(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2027, 2, 1, 11)
    _today(monkeypatch, "2027-02-01")
    drive("Q1")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    code, prev, _ = close("Q1", "judge", "Q1", "PASS", "--seat", "managing-editor", "--note", "re-read; no change")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "PASS" and hand_close_ok(prev, rec)


# ================================================================== Q2 genericization sweep
def _client(repo, tokens=("Brindlecorp",)):
    (repo / "data" / "forbidden_tokens.local.json").write_text(json.dumps({"tokens": list(tokens)}), encoding="utf-8")


def test_cite_Q2_clean_world_awaits_a_witness(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, tmp_path, names=True)
    _client(repo)
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer judgement: 0 forbidden tokens")


def test_cite_Q2_a_planted_token_in_a_named_lesson(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import page
    repo = pages_repo(monkeypatch, tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>i built zorblax.</p>")},
                      names=True)
    _client(repo)
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and "1 in lessons/ (S1)" in rec["why"]
    assert [(f["subject"], f["severity"]) for f in findings("Q2")] == [
        ("lessons/alpha/index.html: forbidden token", "S1")]


def test_cite_Q2_every_served_file_type(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, tmp_path, {"assets/app.js": "const c = 'Quendrith';\n"}, names=True)
    _client(repo)
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "FINDINGS" and findings("Q2")[0]["subject"] == "assets/app.js: forbidden token"


def test_cite_Q2_the_client_token_from_the_local_list(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import page
    repo = pages_repo(monkeypatch, tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>for brindlecorp.</p>")},
                      names=True)
    _client(repo)
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "FINDINGS" and "brindlecorp" not in rec["why"].lower()
    assert findings("Q2")[0]["subject"] == "lessons/alpha/index.html: forbidden token"


def test_cite_Q2_the_witness_closes_it_through_maint_watch(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, tmp_path, names=True)
    _client(repo)
    drive("Q2")
    code, _, _ = close("Q2", "witness", "site-maintainer")                  # an author may not witness
    assert code == 1
    code, prev, _ = close("Q2", "witness", "privacy-safety")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "PASS" and "witnessed by privacy-safety" in rec["why"] and hand_close_ok(prev, rec)


# ================================================================== Q3 patch-queue hygiene
def test_cite_Q3_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, tmp_path, names=True)
    drive("Q3")
    rec = load(md, "receipts/Q3.json")
    assert rec["outcome"] == "PASS" and "none older than 90 days" in rec["why"]


def test_cite_Q3_a_stale_finding_is_flagged(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 1, 5, 9)
    import maint_receipt as mr
    pages_repo(monkeypatch, tmp_path, names=True)
    mr.write_finding("W1", "S3", "dead outbound link https://example.org/old", "x", "Site Maintainer")
    clock.set(2026, 11, 2, 11)
    drive("Q3")
    rec = load(md, "receipts/Q3.json")
    assert rec["outcome"] == "FINDINGS" and rec["n"] == 1 and "older than 90 days" in rec["why"]


def test_cite_Q3_a_stale_patch_is_flagged(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import make_repo
    import maint_pages as mp
    repo = make_repo(tmp_path, queue=[{"id": "P-9", "title": "Old patch", "stage": "DRAFTED", "kind": "patch",
                                       "drafted": "2026-01-02", "since": "2026-01-02"}])
    monkeypatch.setattr(mp, "REPO", repo)
    drive("Q3")
    rec = load(md, "receipts/Q3.json")
    assert rec["outcome"] == "FINDINGS" and rec["n"] == 1


# ================================================================== Q4 DNS and takeover
def _dns(monkeypatch, drop=(), extra=None, wildcard=False):
    import headers_tls_check as h
    from test_maint_edge import GOOD, PAGES_OK
    table = {k: v for k, v in GOOD.items() if k not in drop}
    table.update(extra or {})
    monkeypatch.setattr(h, "resolve", lambda name, rtype: (("ok", ["185.199.108.153"]) if wildcard else
                                                          ("nxdomain", [])) if name.startswith("maint-")
                        else table.get((name, rtype), ("nxdomain", [])))
    monkeypatch.setattr(h, "gh_pages", lambda slug: ("ok", PAGES_OK))


def test_cite_Q4_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch)
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"


def test_cite_Q4_an_a_record_outside_pages(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, extra={("b4him.com", "A"): ("ok", ["185.199.108.153", "203.0.113.9"])})
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "FINDINGS" and "A points outside GitHub Pages: 203.0.113.9" in rec["why"]


def test_cite_Q4_the_verification_txt(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, drop=(("_github-pages-challenge-sobevista.b4him.com", "TXT"),))
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "FINDINGS" and "verification TXT" in rec["why"]


def test_cite_Q4_a_wildcard_record(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, wildcard=True)
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "FINDINGS" and "wildcard record" in rec["why"]


# ================================================================== Q5 security-header grade
def _observatory(monkeypatch, failed=0, tests=None):
    import headers_tls_check as h
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({
        "details_url": "https://developer.mozilla.org/x", "error": None, "grade": "B", "score": 70,
        "tests_failed": failed, "tests_passed": 10 - failed, "tests_quantity": 10}).encode()))
    monkeypatch.setattr(h, "http_get", lambda *a, **k: (200, json.dumps({"tests": tests or {}}).encode()))


XFO = {"x-frame-options": {"pass": False}}


def test_cite_Q5_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch)
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert rec["outcome"] == "PASS" and "tests_failed 0/10" in rec["why"]


def test_cite_Q5_needs_daniels_ok(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "awaiting Daniel's one-time OK")


def test_cite_Q5_a_failing_test_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch, 1, {"strict-transport-security": {"pass": False}})
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert rec["outcome"] == "FINDINGS" and "strict-transport-security" in rec["why"]


def test_cite_Q5_the_frame_ancestors_limit_is_filed_once(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch, 1, XFO)
    drive("Q5")
    first = load(md, "receipts/Q5.json")
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert first["outcome"] == "FINDINGS" and rec["outcome"] == "PASS" and "not re-filed" in rec["why"]


# ================================================================== Q6 alarm fire drill
def test_cite_Q6_clean_world_drill_confirmed(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6")
    code, prev, _ = close("Q6", "confirm", "10:30")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "PASS" and "alarm fired at 10:30" in rec["why"] and hand_close_ok(prev, rec)


def test_cite_Q6_an_armed_drill_awaits_confirmation(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting alarm confirmation")
    assert rec["evidence"].endswith("_drill.md") and rec["tool"] == "tools/maint_watch.py"


def test_cite_Q6_no_alarm_is_an_s1_failure(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6")
    code, prev, _ = close("Q6", "confirm", "never")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("Q6")] == ["S1"]
    assert hand_close_ok(prev, rec)


def test_cite_Q6_no_heartbeat_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("Q6")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "UNKNOWN" and "no MAINT_HEARTBEAT_URL" in rec["why"]


# ================================================================== H1 "feels like home"
def _capture(monkeypatch, problems=()):
    import maint_human as mh
    from test_maint_human import fake_capture
    monkeypatch.setattr(mh, "CAPTURE", fake_capture(problems))


def test_cite_H1_clean_world_not_due(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _capture(monkeypatch)
    drive("H1")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "SKIP" and "next due 2027-01-04" in rec["why"]


def test_cite_H1_the_pack_sits_beside_the_d9_reference(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch)
    drive("H1")
    rec = load(md, "receipts/H1.json")
    pack = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: H1 pack")
    assert "reference_logo.png" in pack and "`--navy-800`" in pack and pack.count("### ") == 4


def test_cite_H1_a_failed_capture_check_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch, ["t.png: 2560x10 px, expected 2560x4000"])
    drive("H1")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "UNKNOWN" and "capture check failed" in rec["why"]


def test_cite_H1_daniels_close(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch)
    drive("H1")
    code, prev, _ = close("H1", "human", "H1", "E01234")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "PASS" and "E01234" in rec["why"] and hand_close_ok(prev, rec)


# ================================================================== H2 / H3 review notes
GOOD_NOTE = "Date: {d}\nReviewer: reviewer\nReviewed: the publication gate\nVerdict: no change\nFindings: none\n"


def _note(md, row, day, text):
    (md / "notes").mkdir(parents=True, exist_ok=True)
    (md / "notes" / f"{row}_{day}.md").write_text(text, encoding="utf-8")


def test_cite_H2_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "PASS" and "review note 2027-01-05 found" in rec["why"]


def test_cite_H2_due_without_a_note_awaits_the_reviewer(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer")


def test_cite_H2_a_template_note_is_read_and_refused(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H2", "2027-01-05", "Date: 2027-01-05\nReviewer: <seat>\nReviewed: ...\nVerdict: ___\nFinding: n/a\n")
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "UNKNOWN" and "Verdict" in rec["why"]


def test_cite_H2_an_author_cannot_review(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05").replace("reviewer", "managing-editor"))
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "UNKNOWN" and "independent Reviewer for H2" in rec["why"]


def test_cite_H2_the_date_line_must_match_the_filename(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2026-01-05"))
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "UNKNOWN" and "equal to the filename's date" in rec["why"]


def test_cite_H3_clean_world(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H3", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "PASS" and "re-read note 2027-01-05 found" in rec["why"]


def test_cite_H3_due_without_a_note_awaits_daniel(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting publisher")


def test_cite_H3_an_empty_note_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H3", "2027-01-05", "")
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "UNKNOWN" and "Date: YYYY-MM-DD" in rec["why"]


def test_cite_H3_a_future_dated_note_is_refused(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    _note(md, "H3", "2099-01-01", GOOD_NOTE.format(d="2099-01-01"))
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "UNKNOWN" and "not in the future" in rec["why"]


# ================================================================== A1 WCAG-EM
def test_cite_A1_clean_world_not_due(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("A1")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "SKIP" and "next due 2027-01-04" in rec["why"]


def test_cite_A1_the_pack_has_every_page_and_the_easy_checks(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    (md).mkdir(parents=True, exist_ok=True)
    (md / "2027-01-03_a11y.json").write_text('{"results": {}}', encoding="utf-8")
    drive("A1")
    rec = load(md, "receipts/A1.json")
    pack = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: A1 WCAG-EM pack (23 pages")
    assert pack.count("| `") == 23 and "Visible Keyboard Focus" in pack and "2.5.8 Target Size (Minimum)" in pack
    assert "automated_axe_pa11y.json (copied from" in pack


def test_a1_without_a_page_list_is_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    import site_pages

    def no_git(*a, **k):
        raise site_pages.GitError("git could not start")
    monkeypatch.setattr(site_pages, "served_pages", no_git)
    drive("A1")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "UNKNOWN" and "no page list" in rec["why"]


def test_cite_A1_daniels_sign_off(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    drive("A1")
    code, prev, _ = close("A1", "human", "A1", "E04321")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "PASS" and hand_close_ok(prev, rec)


# ================================================================== A2 content inventory
def test_cite_A2_clean_world_awaits_the_editor(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("A2")
    rec = load(md, "receipts/A2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement: 23 pages") \
        and "no duplicate" in rec["why"]


def test_cite_A2_true_duplicates_are_found(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    from test_maint_pages import page
    pages_repo(monkeypatch, tmp_path, {"blog/index.html": page("Same", "<p>coming soon</p>"),
                                       "videos/index.html": page("Same", "<p>coming soon</p>")})
    drive("A2")
    rec = load(md, "receipts/A2.json")
    assert rec["outcome"] == "SKIP" and "1 duplicate group(s), filed as A2 findings" in rec["why"]
    assert findings("A2")[0]["subject"] == "duplicate visible text: blog/index.html = videos/index.html"


def test_cite_A2_the_editors_rot_judgement_closes_it(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("A2")
    code, prev, _ = close("A2", "judge", "A2", "PASS", "--seat", "managing-editor", "--note", "nothing redundant")
    rec = load(md, "receipts/A2.json")
    assert rec["outcome"] == "PASS" and hand_close_ok(prev, rec)


# ================================================================== A3 domain registration
def _rdap(monkeypatch, expires, status=("client transfer prohibited",)):
    import maint_human as mh
    boot = {"services": [[["com"], ["https://rdap.example.invalid/com/v1/"]]]}
    dom = {"status": list(status), "events": [{"eventAction": "expiration", "eventDate": expires}]}
    monkeypatch.setattr(mh, "GET_JSON", lambda url: boot if url == mh.BOOTSTRAP else dom)


def test_cite_A3_clean_world_far_from_expiry(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2027-07-19T00:00:00Z")
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "SKIP" and "expires 2027-07-19" in rec["why"] and "window opens 2027-05-20" in rec["why"]


def test_cite_A3_the_60_day_window_awaits_daniel(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: expires 2026-12-20")
    assert rec["evidence"].endswith("_rdap.json") and [f["severity"] for f in findings("A3")] == ["S2"]


def test_cite_A3_a_hold_status_is_s1(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2027-07-19T00:00:00Z", status=("client hold",))
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("A3")] == ["S1"]


def test_cite_A3_daniels_close_ends_the_window(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")
    drive("A3")
    code, prev, _ = close("A3", "human", "A3", "E05555")
    closed = load(md, "receipts/A3.json")
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert closed["outcome"] == "PASS" and hand_close_ok(prev, closed)
    assert rec["outcome"] == "SKIP" and "closed for this window" in rec["why"]


# ================================================================== A4 scanner calibration (the real scanners)
def _real_scanners(monkeypatch, **override):
    """The real no-network scanners (release.broken_links, people_registry, linkcheck's internal pass, the
    headers_tls mixed-content grep, maint_pages' people scan) against the real tools/_maint_fixtures/; the two browser
    scanners (pa11y-ci, contrast-audit.js) are recorded answers."""
    import maint_quality as mq
    from test_maint_quality import _scanners
    canned = _scanners()
    default = mq.default_scanners

    def scanners(root):
        real = default(root)
        s = {k: real[k] for k in ("release.broken_links", "people_registry", "linkcheck.py", "headers_tls_check.py",
                                  "maint_pages.py")}
        s.update({k: canned[k] for k in ("pa11y-ci", "contrast-audit.js")})
        s.update(override)
        return s
    monkeypatch.setattr(mq, "default_scanners", scanners)


def _matrix(md, rec):
    return json.loads((md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8"))["matrix"]


def test_cite_A4_clean_world_every_planted_fault_seen(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch)
    drive("A4")
    rec = load(md, "receipts/A4.json")
    m = _matrix(md, rec)
    assert rec["outcome"] == "PASS" and m["broken-internal-link"] == {"release.broken_links": "SEEN",
                                                                       "linkcheck.py": "SEEN"}
    assert m["forbidden-token"] == {"people_registry": "SEEN", "maint_pages.py": "SEEN"}
    assert m["mixed-content"] == {"headers_tls_check.py": "SEEN"}


def test_cite_A4_a_blind_scanner_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch, **{"contrast-audit.js": lambda: {"low-contrast/index.html": [], "index.html": []}})
    drive("A4")
    rec = load(md, "receipts/A4.json")
    assert rec["outcome"] == "FINDINGS" and "contrast-audit.js missed low-contrast" in rec["why"]


def test_cite_A4_a_noisy_scanner_is_findings(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch, **{"pa11y-ci": lambda: {"missing-alt/index.html": ["pa11y:image-alt"],
                                                        "low-contrast/index.html": ["pa11y:G18"],
                                                        "index.html": ["pa11y:region"]}})
    drive("A4")
    rec = load(md, "receipts/A4.json")
    assert rec["outcome"] == "FINDINGS" and "pa11y-ci flagged the clean control page" in rec["why"]
