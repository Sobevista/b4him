"""The harness scope lock's cite tests: one test per b4him maintenance row (the 28 rows of the maintenance baseline).

Each test names its row as a string literal, drives the row through `maint_run.py --row <id>` (in process: run.RUN is
replaced by an executor that calls the row's tool's own main(), with its network and clock edges faked), and asserts
the row's real outcome classes on the receipt that run produced. The receipt is written at run time to
`.maint/receipts/<row>.json` under a temporary MAINT_DIR, and that path-shaped receipt literal is what reaches each
assert: never a committed file. Where the row's own tool path is its anchor it is asserted too.

The tools are imported INSIDE the test bodies, so on a tree without them (b4him main d67bd8d) every test FAILS rather
than erroring at collection. No network: sockets are refused, HTTP / DNS / TLS / RDAP / feeds are fakes.
"""
import datetime as dt
import json
import socket
import types
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TZ = dt.timezone(dt.timedelta(hours=-5))


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


def drive(row):
    """`maint_run.py --row <row>`, then its receipt snapshot. Returns maint_run's exit code."""
    import maint_run as run
    code = run.main(["--row", row])
    snap(row)
    return code


def close(row, *argv):
    """A person's act through maint_watch (judge / human / confirm), then the row's receipt snapshot."""
    import maint_watch as mw
    code = mw.main(list(argv))
    snap(row)
    return code


def load(md, rel):
    return json.loads((md / rel).read_text(encoding="utf-8"))


# ------------------------------------------------------------------ C1 (uptime monitor reader)
def test_cite_C1_uptime_monitors_cover_home_and_a_lesson(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no UPTIMEROBOT_API_KEY")
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "ur-test")
    mons = [{"friendly_name": "home", "url": "https://b4him.com/", "status": 2, "custom_uptime_ratio": "99.9"},
            {"friendly_name": "lesson", "url": "https://b4him.com/lessons/first-lap/", "status": 2,
             "custom_uptime_ratio": "100"}]
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({"stat": "ok", "monitors": mons}).encode()))
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "PASS" and rec["tool"].startswith("tools/")
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({"stat": "ok", "monitors": mons[1:]}).encode()))
    drive("C1")
    rec = load(md, "receipts/C1.json")
    assert rec["outcome"] == "FINDINGS" and "no monitor watches https://b4him.com/" in rec["why"]


# ------------------------------------------------------------------ D1, D2, D3
def test_cite_D1_release_line_present_failed_or_missing(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_watch as mw
    monkeypatch.setattr(mw, "REPO", tmp_path)
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "UNKNOWN" and rec["tool"] == "tools/maint_watch.py"
    line = {"at": "2026-11-02T13:30:01+00:00", "date": "2026-11-02", "mode": "apply", "lane": "content",
            "outcome": "PUBLISHED"}
    (tmp_path / "release_log.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "PASS"
    (tmp_path / "release_log.jsonl").write_text(json.dumps({**line, "outcome": "FAIL"}) + "\n", encoding="utf-8")
    drive("D1")
    rec = load(md, "receipts/D1.json")
    assert rec["outcome"] == "FINDINGS"


def test_cite_D2_calendar_watch_pass_and_overdue(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    import maint_watch as mw
    real = {r["id"]: r for r in json.loads(mw.ROWS_FILE.read_text(encoding="utf-8"))["rows"]}
    small = tmp_path / "rows.json"
    small.write_text(json.dumps({"epoch": "2026-10-20", "rows": [real["D1"], real["D2"]]}), encoding="utf-8")
    monkeypatch.setattr(mw, "ROWS_FILE", small)
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "FINDINGS" and "D1" in rec["why"] and rec["tool"] == "tools/maint_watch.py"
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    drive("D2")
    rec = load(md, "receipts/D2.json")
    assert rec["outcome"] == "PASS"


def test_cite_D3_heartbeat_delivered_or_unknown(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_watch as mw
    drive("D3")
    rec = load(md, "receipts/D3.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no MAINT_HEARTBEAT_URL")
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    calls = []
    monkeypatch.setattr(mw, "HTTP_GET", lambda url: (calls.append(url), (200, "OK"))[1])
    drive("D3")
    rec = load(md, "receipts/D3.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/maint_watch.py" and calls[-1].endswith("/fail")


# ------------------------------------------------------------------ W1, W1b, W2, W3
def _fetcher(monkeypatch, dead):
    import linkcheck as lc
    real = getattr(lc.Fetcher, "real", lc.Fetcher)       # a second call must wrap the class, not the first fake

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
        import urllib.error
        u = req.full_url
        if u.startswith(lc.WAYBACK_API):
            return Resp(200, u, json.dumps({"archived_snapshots": {"closest": {
                "available": True, "url": "http://web.archive.org/web/2025/x", "timestamp": "20250101000000",
                "status": "200"}}}).encode())
        if dead:
            raise urllib.error.HTTPError(u, 404, "Not Found", {}, None)
        return Resp(200, u)
    if dead:                                  # a later week: the earlier alive answers are not in the cache
        import maint_receipt as mr
        (mr.maint_dir() / "linkcache.json").unlink(missing_ok=True)

    def factory():
        return real(opener=opener, sleep=lambda s: None)
    factory.real = real
    monkeypatch.setattr(lc, "Fetcher", factory)


def test_cite_W1_whole_site_link_check(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _fetcher(monkeypatch, dead=False)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/linkcheck.py" and "23 pages" in rec["why"]
    _fetcher(monkeypatch, dead=True)
    drive("W1")
    rec = load(md, "receipts/W1.json")
    assert rec["outcome"] == "FINDINGS" and rec["n"] >= 1


def test_cite_W1b_wayback_proposals_for_dead_links(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    _fetcher(monkeypatch, dead=False)
    drive("W1b")
    rec = load(md, "receipts/W1b.json")
    assert rec["outcome"] == "SKIP" and rec["tool"].startswith("tools/")
    _fetcher(monkeypatch, dead=True)
    drive("W1b")
    rec = load(md, "receipts/W1b.json")
    assert rec["outcome"] == "FINDINGS" and "with a proposed snapshot" in rec["why"]


def test_cite_W2_weekly_digest(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("W2")
    rec = load(md, "receipts/W2.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/maint_watch.py"
    assert (md / rec["evidence"][len(".maint/"):]).is_file()


def test_cite_W3_people_scan_of_every_page(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("W3")
    rec = load(md, "receipts/W3.json")
    assert rec["outcome"] == "FINDINGS" and rec["why"].startswith("SUMMARY 23 pages") and rec["tool"].startswith("tools/")


# ------------------------------------------------------------------ M1, M1b, M2, M2b, M3, M4, M5
def test_cite_M1_accessibility_scan(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    from test_maint_quality import REP_BAD, REP_OK
    for code, rep, want in ((0, REP_OK, "PASS"), (2, REP_BAD, "FINDINGS"), (1, None, "UNKNOWN")):
        monkeypatch.setattr(mq, "run_pa11y", lambda root, rels, tag, c=code, r=rep: (c, r, {"base": "http://h",
                                                                                          "exit": c}))
        drive("M1")
        rec = load(md, "receipts/M1.json")
        assert rec["outcome"] == want and "do not cover all of WCAG 2.2 AA" in rec["why"]


def test_cite_M1b_contrast_waits_for_the_eye_then_is_judged(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    from test_maint_quality import _row
    monkeypatch.setattr(mq, "audit_contrast", lambda root, rels: {"index.html": {
        "checked": 3, "failures": [], "passingButUnverifiable": [_row("h1", 9, over="body::before")]}})
    drive("M1b")
    rec = load(md, "receipts/M1b.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting site-maintainer judgement")
    close("M1b", "judge", "M1b", "PASS", "--seat", "site-maintainer", "--note", "judged by eye on every template")
    rec = load(md, "receipts/M1b.json")
    assert rec["outcome"] == "PASS" and rec["why"].startswith("judged by site-maintainer")


def test_cite_M2_lab_performance(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    from test_maint_quality import _lhr
    paths = [mq.page_path(r) for r in mq.served_pages(REPO)]

    def lhci(lcp):
        def run_cmd(argv, cwd=None, env=None, timeout=0):
            d = Path(cwd) / ".lighthouseci"
            d.mkdir(parents=True, exist_ok=True)
            for i, p in enumerate(paths):
                for k in range(3):
                    (d / f"lhr-{i}-{k}.json").write_text(json.dumps(_lhr(p, lcp, 0.0, 10)), encoding="utf-8")
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")
        return run_cmd
    monkeypatch.setattr(mq, "find_bin", lambda name, root: "lhci")
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", lhci(1200))
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert rec["outcome"] == "PASS"
    monkeypatch.setattr(mq, "run_cmd", lhci(3000))
    drive("M2")
    rec = load(md, "receipts/M2.json")
    assert rec["outcome"] == "FINDINGS" and rec["n"] == len(paths)


def test_cite_M2b_field_performance(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    from test_maint_quality import _crux
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no CRUX_API_KEY")
    monkeypatch.setenv("CRUX_API_KEY", "test-key")
    monkeypatch.setattr(mq, "crux_query", lambda origin, key, opener=None: (200, _crux()))
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert rec["outcome"] == "PASS"
    monkeypatch.setattr(mq, "crux_query", lambda origin, key, opener=None: (200, _crux(lcp=3100)))
    drive("M2b")
    rec = load(md, "receipts/M2b.json")
    assert rec["outcome"] == "FINDINGS"


def test_cite_M3_tls_and_headers(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h

    def tls(days):
        t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=days)
        monkeypatch.setattr(h, "probe_cert", lambda host: {"not_after": t.strftime("%b %d %H:%M:%S %Y GMT"),
                                                           "issuer": "O=Let's Encrypt"})
        monkeypatch.setattr(h, "probe_http", lambda url, method="HEAD", timeout=20: (
            {"status": 301, "headers": {"location": "https://b4him.com/"}} if url.startswith("http://")
            else {"status": 200, "headers": {"server": "GitHub.com"}}))
        monkeypatch.setattr(h, "git_grep_http", lambda root: [])
    tls(60)
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"
    tls(5)
    drive("M3")
    rec = load(md, "receipts/M3.json")
    assert rec["outcome"] == "FINDINGS"


def test_cite_M4_reader_walkthrough_waits_for_the_editor(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("M4")
    rec = load(md, "receipts/M4.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    close("M4", "judge", "M4", "FINDINGS", "1", "--seat", "managing-editor", "--note", "one term needs a gloss")
    rec = load(md, "receipts/M4.json")
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and rec["evidence"].endswith("_reader.md")


def _board(monkeypatch, day):
    import maint_watch as mw
    monkeypatch.setattr(mw, "board_date", lambda repo: dt.date.fromisoformat(day))


def test_cite_M5_board_run_found_pass(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 31, 11)
    _board(monkeypatch, "2026-10-20")
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "PASS" and "next due 2026-11-02" in rec["why"]


def test_m5_board_run_due_is_awaiting(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 3, 11)
    _board(monkeypatch, "2026-10-20")
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor")


def test_m5_board_run_overdue_is_findings(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 6, 0, 1)
    _board(monkeypatch, "2026-10-20")
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "FINDINGS" and "board run overdue" in rec["why"]


def test_m5_unreadable_board_is_unknown(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    import maint_watch as mw

    def unreadable(repo):
        raise mw.Unknown("PRODUCTION_BOARD.md carries no 'Generated' line")
    monkeypatch.setattr(mw, "board_date", unreadable)
    drive("M5")
    rec = load(md, "receipts/M5.json")
    assert rec["outcome"] == "UNKNOWN" and "Generated" in rec["why"]


# ------------------------------------------------------------------ Q1 .. Q6
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


def test_cite_Q1_reread_none_due_then_awaiting_then_judged(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    _today(monkeypatch, "2026-11-02")
    drive("Q1")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("0 of 23 pages due")
    _today(monkeypatch, "2027-02-01")
    clock.set(2027, 2, 1, 11)
    drive("Q1")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    close("Q1", "judge", "Q1", "PASS", "--seat", "managing-editor", "--note", "re-read every due page; no change")
    rec = load(md, "receipts/Q1.json")
    assert rec["outcome"] == "PASS"


def test_cite_Q2_genericization_findings_then_witness(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_pages as mp
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] in ("FINDINGS", "UNKNOWN") and rec["tool"].startswith("tools/")
    monkeypatch.setattr(mp, "grep_tokens", lambda *a, **k: [])
    monkeypatch.setattr(mp, "local_tokens", lambda repo: ([], True))
    monkeypatch.setattr(mp, "people_scan", lambda repo: {"outcome": "PASS", "n": 0, "why": "clean"})
    drive("Q2")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer judgement")
    assert close("Q2", "judge", "Q2", "PASS", "--seat", "site-maintainer", "--note", "an author") == 1
    close("Q2", "judge", "Q2", "PASS", "--seat", "reviewer", "--note", "re-read the sweep; nothing leaks")
    rec = load(md, "receipts/Q2.json")
    assert rec["outcome"] == "PASS" and rec["why"].startswith("judged by reviewer")


def test_cite_Q3_patch_queue_hygiene(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("Q3")
    rec = load(md, "receipts/Q3.json")
    assert rec["outcome"] == "PASS" and "open item(s)" in rec["why"]


def test_cite_Q4_dns_and_takeover(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    from test_maint_edge import GOOD, PAGES_OK

    def dns(table):
        monkeypatch.setattr(h, "resolve", lambda name, rtype: ("nxdomain", []) if name.startswith("maint-")
                            else table.get((name, rtype), ("nxdomain", [])))
        monkeypatch.setattr(h, "gh_pages", lambda slug: ("ok", PAGES_OK))
    dns(GOOD)
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"
    dns({k: v for k, v in GOOD.items() if k[1] != "TXT"})
    drive("Q4")
    rec = load(md, "receipts/Q4.json")
    assert rec["outcome"] == "FINDINGS" and "TXT" in rec["why"]


def test_cite_Q5_observatory_needs_the_ok(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "awaiting Daniel's one-time OK")
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({
        "details_url": "https://developer.mozilla.org/x", "error": None, "grade": "A", "score": 90,
        "tests_failed": 0, "tests_passed": 10, "tests_quantity": 10}).encode()))
    drive("Q5")
    rec = load(md, "receipts/Q5.json")
    assert rec["outcome"] == "PASS" and "grade A" in rec["why"]


def test_cite_Q6_alarm_drill_armed_then_confirmed(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("Q6")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "UNKNOWN" and "no MAINT_HEARTBEAT_URL" in rec["why"]
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting alarm confirmation")
    assert rec["tool"] == "tools/maint_watch.py"
    close("Q6", "confirm", "10:30")
    rec = load(md, "receipts/Q6.json")
    assert rec["outcome"] == "PASS" and "alarm fired at 10:30" in rec["why"]


# ------------------------------------------------------------------ H1, H2, H3
def test_cite_H1_feels_like_home_pack_then_daniels_close(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    import maint_human as mh
    from test_maint_human import fake_capture
    monkeypatch.setattr(mh, "CAPTURE", fake_capture())
    drive("H1")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "SKIP" and "next due 2027-01-04" in rec["why"]
    clock.set(2027, 1, 4, 11)
    drive("H1")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: H1 pack")
    close("H1", "human", "H1", "E01234")
    rec = load(md, "receipts/H1.json")
    assert rec["outcome"] == "PASS" and "E01234" in rec["why"]


def _note(md, row, day, text):
    (md / "notes").mkdir(parents=True, exist_ok=True)
    (md / "notes" / f"{row}_{day}.md").write_text(text, encoding="utf-8")


GOOD_NOTE = "Date: {d}\nReviewer: reviewer\nReviewed: the publication gate\nVerdict: no change\nFindings: none\n"


def test_cite_H2_publication_gate_note(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer")
    _note(md, "H2", "2027-01-05", "Date: 2027-01-05\nReviewer: <seat>\n")
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "UNKNOWN" and "Verdict" in rec["why"]
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H2")
    rec = load(md, "receipts/H2.json")
    assert rec["outcome"] == "PASS"


def test_cite_H3_calendar_reread_note(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 5, 11)
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting publisher")
    _note(md, "H3", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "PASS"
    clock.set(2027, 1, 13, 0, 1)
    _note(md, "H3", "2027-01-13", "")                                        # a newer, empty note
    drive("H3")
    rec = load(md, "receipts/H3.json")
    assert rec["outcome"] == "UNKNOWN"


# ------------------------------------------------------------------ A1, A2, A3, A4
def test_cite_A1_wcag_em_pack_then_daniels_sign_off(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    drive("A1")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: A1 WCAG-EM pack")
    close("A1", "human", "A1", "E04321")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "PASS" and "E04321" in rec["why"]


def test_a1_without_a_page_list_is_unknown(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    import site_pages

    def no_git(*a, **k):
        raise site_pages.GitError("git could not start")
    monkeypatch.setattr(site_pages, "served_pages", no_git)
    drive("A1")
    rec = load(md, "receipts/A1.json")
    assert rec["outcome"] == "UNKNOWN" and "no page list" in rec["why"]


def test_cite_A2_content_inventory_waits_for_the_editor(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    drive("A2")
    rec = load(md, "receipts/A2.json")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement: 23 pages")
    close("A2", "judge", "A2", "PASS", "--seat", "managing-editor", "--note", "no redundant or outdated page")
    rec = load(md, "receipts/A2.json")
    assert rec["outcome"] == "PASS"


def test_cite_A3_rdap_window_then_daniels_close(monkeypatch, tmp_path):
    md, clock = world(monkeypatch, tmp_path)
    import maint_human as mh

    def rdap(expires):
        boot = {"services": [[["com"], ["https://rdap.example.invalid/com/v1/"]]]}
        dom = {"status": ["client transfer prohibited"],
               "events": [{"eventAction": "expiration", "eventDate": expires}]}
        monkeypatch.setattr(mh, "GET_JSON", lambda url: boot if url == mh.BOOTSTRAP else dom)
    rdap("2027-07-19T00:00:00Z")
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "SKIP" and "expires 2027-07-19" in rec["why"]
    rdap("2026-12-20T00:00:00Z")
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "FINDINGS" and "the 60-day window is open" in rec["why"]
    close("A3", "human", "A3", "E05555")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "PASS"
    drive("A3")
    rec = load(md, "receipts/A3.json")
    assert rec["outcome"] == "SKIP" and "closed for this window" in rec["why"]


def test_cite_A4_scanner_calibration(monkeypatch, tmp_path):
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    from test_maint_quality import _scanners
    monkeypatch.setattr(mq, "default_scanners", lambda root: _scanners())
    drive("A4")
    rec = load(md, "receipts/A4.json")
    assert rec["outcome"] == "PASS" and "all 5 planted faults" in rec["why"]
    monkeypatch.setattr(mq, "default_scanners", lambda root: _scanners(
        **{"contrast-audit.js": lambda: {"low-contrast/index.html": []}}))
    drive("A4")
    rec = load(md, "receipts/A4.json")
    assert rec["outcome"] == "FINDINGS" and "contrast-audit.js missed low-contrast" in rec["why"]
