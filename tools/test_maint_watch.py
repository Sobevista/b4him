"""Tests for maint_receipt.py, maint_rows_build.py and maint_watch.py. No network: HTTP is a fake.

    py -m pytest tools/test_maint_watch.py -q

Each calendar row this builder owns (D1, D2, D3, W2, Q6, M5, H2, H3, H1/A1/A3) is shown on its PASS, FINDINGS and
UNKNOWN paths (and SKIP where the row has one).
"""
import datetime as dt
import json
import pathlib
import sys
import types

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import maint_receipt as mr  # noqa: E402
import maint_rows_build as mrb  # noqa: E402
import maint_watch as mw  # noqa: E402

TZ = dt.timezone(dt.timedelta(hours=-4))
URL = "https://hc-ping.com/00000000-test-uuid-0000-000000000000"


class Clock:
    def __init__(self):
        self.t = dt.datetime(2026, 10, 30, 11, 0, tzinfo=TZ)

    def set(self, *a):
        self.t = dt.datetime(*a, tzinfo=TZ)
        return self.t

    def __call__(self):
        return self.t.astimezone(dt.timezone.utc)


@pytest.fixture
def env(tmp_path, monkeypatch):
    md = tmp_path / ".maint"
    monkeypatch.setenv("MAINT_DIR", str(md))
    monkeypatch.delenv("MAINT_HEARTBEAT_URL", raising=False)
    monkeypatch.delenv("MAINT_CALENDAR_PATH", raising=False)
    monkeypatch.setattr(mw, "LOCAL_TZ", TZ)
    clock = Clock()
    monkeypatch.setattr(mr, "now_utc", clock)
    ns = types.SimpleNamespace(calls=[], clock=clock, md=md, tmp=tmp_path, reply=lambda url: (200, "OK"))

    def fake_get(url):
        ns.calls.append(url)
        return ns.reply(url)
    monkeypatch.setattr(mw, "HTTP_GET", fake_get)
    ns.schedule = {"state": "ok", "problems": [], "why": "b4him-maint-run last ran recently"}
    monkeypatch.setattr(mw, "SCHEDULE_CHECK", lambda now: ns.schedule)
    return ns


def now(e):
    return mw.local(e.clock())


def last(row):
    return [r for r in mr.read_receipts() if r["row"] == row][-1]


def rlog(tmp, lines):
    p = tmp / "release_log.jsonl"
    p.write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")
    return p


SKIP_LINE = {"at": "2026-10-30T12:30:01+00:00", "date": "2026-10-30", "mode": "apply", "lane": "content",
             "outcome": "SKIP", "why": "Fri is not a release day (Tuesdays only)"}


# ------------------------------------------------------------------ the shared helper
def test_receipt_shape_and_append_only(env):
    a = mr.write_receipt("D1", "PASS", why="ok", tool="t")
    b = mr.write_receipt("D1", "FINDINGS", n=2, why="x", evidence=".maint/audits/x.md", tool="t")
    assert set(a) == {"at", "row", "outcome", "n", "why", "evidence", "tool"}
    assert [r["outcome"] for r in mr.read_receipts()] == ["PASS", "FINDINGS"] and b["n"] == 2
    f = mr.write_finding("D1", "S2", "subj", "detail", "Release Manager")
    assert set(f) == {"at", "row", "severity", "subject", "detail", "route_to"} and mr.read_findings() == [f]


@pytest.mark.parametrize("kw", [dict(outcome="OK"), dict(outcome="FINDINGS"), dict(outcome="FINDINGS", n=0),
                                dict(outcome="UNKNOWN"), dict(outcome="SKIP", why=" "),
                                dict(outcome="PASS", evidence="audits/x.md"),
                                dict(outcome="PASS", evidence=".maint/../x")])
def test_receipt_refuses_a_lying_shape(env, kw):
    with pytest.raises(ValueError):
        mr.write_receipt("D1", **kw)
    assert mr.read_receipts() == []


# ------------------------------------------------------------------ the row table
CAL = """**Days.** Tuesday ... Grace periods: daily +2 h, weekly +1 day, monthly +3 days, quarterly +7 days, annual +14
days [ASSUMED].

| # | Cadence | Task | Tool | Mode | Receipt | Alarm | Goes to |
|---|---|---|---|---|---|---|---|
| D1 | daily 08:30 + 2 h | Confirm the line [S1-24] | x | AUTOMATE | line | D3 | **Release Manager** |
| H1 | every 6 months | Feels like home [6a62030979ca096c] | x | **HUMAN** | E | D2 | **Daniel** |
| E2 | each release | read verify-live | x | AUTOMATE | line | D1 | Release Manager |
"""


def test_rows_build_reads_grace_and_strips_citations():
    d = mrb.build(CAL, "2026-10-20")
    rows = {r["id"]: r for r in d["rows"]}
    assert d["grace_hours"]["annual"] == 336 and rows["D1"]["at"] == "08:30" and rows["D1"]["grace_hours"] == 2
    assert rows["H1"]["check"] == "human" and rows["H1"]["kind"] == "semiannual" and rows["E2"]["kind"] == "event"
    assert "[S1" not in rows["D1"]["task"] and "6a62" not in rows["H1"]["task"] and "**" not in rows["H1"]["mode"]


def test_committed_row_table_is_whole():
    t = mw.load_rows()
    assert len(t["rows"]) == 31 and {"D1", "D2", "D3", "W2", "Q6", "M5", "H1", "H2", "H3", "A1", "A3"} <= set(t["rows"])
    assert all(r["grace_hours"] for r in t["rows"].values() if r["kind"] != "event")


# ------------------------------------------------------------------ D1
def test_d1_pass_on_a_skip_day(env):
    env.clock.set(2026, 10, 30, 10, 31)
    r = mw.run_d1(rlog(env.tmp, [SKIP_LINE]), dt.date(2026, 10, 30), now(env))
    assert r["outcome"] == "PASS" and "SKIP" in r["why"]


def test_d1_findings_when_missing_after_cutoff(env):
    env.clock.set(2026, 10, 31, 10, 31)
    r = mw.run_d1(rlog(env.tmp, [SKIP_LINE]), dt.date(2026, 10, 31), now(env))
    assert r["outcome"] == "FINDINGS" and "MISSING" in r["why"] and mr.read_findings()[0]["route_to"] == "Release Manager"


def test_d1_findings_on_a_fail_line(env):
    env.clock.set(2026, 10, 27, 11, 0)
    fail = {**SKIP_LINE, "at": "2026-10-27T12:30:04+00:00", "date": "2026-10-27", "outcome": "FAIL", "piece": "P"}
    r = mw.run_d1(rlog(env.tmp, [fail]), dt.date(2026, 10, 27), now(env))
    assert r["outcome"] == "FINDINGS" and "FAIL" in r["why"]


def test_d1_unknown_before_cutoff_and_without_a_log(env):
    env.clock.set(2026, 10, 31, 9, 0)
    assert mw.run_d1(rlog(env.tmp, [SKIP_LINE]), dt.date(2026, 10, 31), now(env))["outcome"] == "UNKNOWN"
    assert mw.run_d1(env.tmp / "nope.jsonl", dt.date(2026, 10, 31), now(env))["outcome"] == "UNKNOWN"
    bad = env.tmp / "bad.jsonl"
    bad.write_text("{not json\n", encoding="utf-8")
    assert mw.run_d1(bad, dt.date(2026, 10, 31), now(env))["outcome"] == "UNKNOWN"


# ------------------------------------------------------------------ D2
def small_table(tmp, rows, epoch="2026-10-20"):
    p = tmp / "rows.json"
    p.write_text(json.dumps({"epoch": epoch, "rows": rows}), encoding="utf-8")
    return p


DAILY = {"id": "D1", "kind": "daily", "at": "08:30", "grace_hours": 2, "check": "receipt", "route_to": "RM"}
WEEKLY = {"id": "W1", "kind": "weekly", "grace_hours": 24, "check": "receipt", "route_to": "SM"}
MONTHLY = {"id": "M1", "kind": "monthly", "grace_hours": 72, "check": "receipt", "route_to": "SM"}
HUMAN = {"id": "H1", "kind": "semiannual", "months": [1, 7], "grace_hours": 168, "check": "human", "route_to": "Dan"}
EVENT = {"id": "E2", "kind": "event", "grace_hours": None, "check": "event"}


def test_d2_pass_when_every_row_is_fresh_and_judged(env):
    p = small_table(env.tmp, [DAILY, WEEKLY, MONTHLY, EVENT])
    env.clock.set(2026, 10, 30, 10, 0)
    for rid in ("D1", "W1", "M1"):
        mr.write_receipt(rid, "PASS", why="ran")
    env.clock.set(2026, 10, 31, 10, 29)                 # D1 owes 10-31 08:30, grace to 10:30
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "PASS" and "E2" in r["why"] and "none UNKNOWN" in r["why"]
    env.clock.set(2026, 10, 31, 10, 31)
    assert mw.run_d2(now(env), p)["why"].startswith("overdue: D1 (last receipt 2026-10-30 10:00")


def test_d2_never_rounds_unknown_to_pass(env):
    """The review's repro: fresh UNKNOWN receipts for every row gave D2 PASS and a success heartbeat."""
    p = small_table(env.tmp, [DAILY, WEEKLY, MONTHLY, EVENT])
    env.clock.set(2026, 10, 31, 10, 0)
    for rid in ("D1", "W1", "M1"):
        mr.write_receipt(rid, "UNKNOWN", why="could not run")
    env.clock.set(2026, 10, 31, 11, 0)                  # inside every grace: named, never PASS
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "UNKNOWN" and "D1 (until" in r["why"] and "W1" in r["why"] and "M1" in r["why"]
    env.clock.set(2026, 10, 31, 12, 1)                  # D1's UNKNOWN is past its own 2 h grace: STUCK, an alarm
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and r["n"] == 1 and "D1 STUCK" in r["why"] and "in grace: W1, M1" in r["why"]
    assert "STUCK UNKNOWN D1" in {f["subject"] for f in mr.read_findings()}
    env.clock.set(2026, 11, 1, 11, 1)                   # W1 past 24 h too
    assert mw.run_d2(now(env), p)["n"] >= 2
    mr.write_receipt("D1", "PASS", why="ok")            # a judged receipt ends the streak
    assert "D1 STUCK" not in mw.run_d2(now(env), p)["why"]


def test_d2_and_d3_alarm_on_a_missing_or_stale_schedule(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/abc")
    p = small_table(env.tmp, [DAILY])
    env.clock.set(2026, 11, 3, 10, 35)
    mr.write_receipt("D1", "PASS", why="ok")
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"
    env.schedule = {"state": "missing", "problems": ["scheduled task b4him-maint-run is missing"], "why": "x"}
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and "SCHEDULE (scheduled task b4him-maint-run is missing)" in r["why"]
    monkeypatch.setattr(mw, "ROWS_FILE", p)
    mw.main(["--now", "2026-11-03T10:35:00-05:00", "one", "D3"])
    assert env.calls[-1].endswith("/fail")              # the heartbeat says so out of band
    env.schedule = {"state": "unknown", "problems": [], "why": "schtasks could not start"}
    assert mw.run_d2(now(env), p)["outcome"] == "UNKNOWN"


def test_d2_overdue_from_first_scheduled_date_when_no_receipt_ever(env):
    p = small_table(env.tmp, [DAILY, WEEKLY, MONTHLY])
    env.clock.set(2026, 10, 27, 23, 0)                  # first Monday 10-26: weekly grace runs to Wed 10-28 00:00
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and r["n"] == 1 and r["why"].startswith("overdue: D1")
    env.clock.set(2026, 10, 28, 0, 1)
    r = mw.run_d2(now(env), p)
    assert r["n"] == 2 and "W1 (no receipt ever, due 2026-10-26" in r["why"] and "M1" not in r["why"]
    assert {f["subject"] for f in mr.read_findings()} == {"OVERDUE D1", "OVERDUE W1"}


def test_d2_monthly_waits_for_its_first_monday(env):
    p = small_table(env.tmp, [MONTHLY])
    env.clock.set(2026, 11, 2, 9)
    mr.write_receipt("M1", "PASS")
    env.clock.set(2026, 12, 10, 23, 59)                 # next first Monday 12-07, +1 day +3 days -> 12-11 00:00
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"
    env.clock.set(2026, 12, 11, 0, 1)
    assert mw.run_d2(now(env), p)["outcome"] == "FINDINGS"


def test_d2_human_row_counts_only_a_close(env):
    p = small_table(env.tmp, [HUMAN])
    env.clock.set(2027, 1, 4, 9)
    mr.write_receipt("H1", "UNKNOWN", why="reminder fired")
    env.clock.set(2027, 1, 12, 0, 1)                    # 01-04 + 1 day + 7 days
    assert mw.run_d2(now(env), p)["outcome"] == "FINDINGS"
    mr.write_receipt("H1", "PASS", why="closed by E01234")
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"


def test_d2_unknown_when_the_table_cannot_be_read(env):
    bad = env.tmp / "rows.json"
    bad.write_text("{", encoding="utf-8")
    assert mw.run_d2(now(env), bad)["outcome"] == "UNKNOWN"


# ------------------------------------------------------------------ D3
def test_d3_pass_success_ping_and_url_never_logged(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)
    r = mw.run_d3(False, "", now(env))
    assert r["outcome"] == "PASS" and env.calls == [URL]
    assert "test-uuid" not in (env.md / "maintenance_log.jsonl").read_text(encoding="utf-8")


def test_d3_appends_fail_when_d1_or_d2_is_not_pass(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL + "/")
    r = mw.run_d3(True, "D2 FINDINGS", now(env))
    assert env.calls == [URL + "/fail"] and r["outcome"] == "PASS" and "fail signal" in r["why"]


def test_d3_unknown_without_env_and_on_network_error(env, monkeypatch):
    assert mw.run_d3(False, "", now(env))["why"] == "no MAINT_HEARTBEAT_URL" and env.calls == []
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)

    def boom(url):
        raise OSError(f"cannot reach {url}")
    env.reply = boom
    r = mw.run_d3(False, "", now(env))
    assert r["outcome"] == "UNKNOWN" and "test-uuid" not in r["why"] and "<MAINT_HEARTBEAT_URL>" in r["why"]


@pytest.mark.parametrize("reply", [(404, "not found"), (500, "err"), (200, "OK (not found)"),
                                   (200, "OK (rate limited)"), (301, "")])
def test_d3_findings_when_the_ping_is_not_recorded(env, monkeypatch, reply):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)
    env.reply = lambda url: reply
    assert mw.run_d3(False, "", now(env))["outcome"] == "FINDINGS"


def test_daily_cli_runs_d1_d2_d3_in_order(env, monkeypatch, capsys):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)
    code = mw.main(["--now", "2026-10-30T10:45:00-04:00", "daily", "--release-log",
                    str(rlog(env.tmp, [SKIP_LINE]))])
    rows = [r["row"] for r in mr.read_receipts()]
    assert rows == ["D1", "D2", "D3"] and last("D1")["outcome"] == "PASS"
    assert last("D2")["outcome"] == "FINDINGS" and env.calls == [URL + "/fail"] and code == 1


# ------------------------------------------------------------------ M5, H2, H3
def board(tmp, day):
    (tmp / "PRODUCTION_BOARD.md").write_text(f"# PRODUCTION BOARD\n\n*Generated {day} by `tools/production_board.py` "
                                             "from `production_queue.jsonl`.*\n", encoding="utf-8")


def test_m5_board_receipt_pass_unknown_findings(env):
    t = mw.load_rows()
    board(env.tmp, "2026-10-20")
    env.clock.set(2026, 10, 31, 9)
    assert mw.run_check("M5", now(env), repo=env.tmp, table=t)["outcome"] == "PASS"
    env.clock.set(2026, 11, 3, 9)                        # due 11-02, grace to 11-06 00:00
    r = mw.run_check("M5", now(env), repo=env.tmp, table=t)
    assert r["outcome"] == "SKIP" and mr.is_awaiting(r) and "the board run due" in r["why"]   # waiting, not failing
    env.clock.set(2026, 11, 6, 0, 1)
    assert mw.run_check("M5", now(env), repo=env.tmp, table=t)["outcome"] == "FINDINGS"
    assert mr.read_findings()[-1]["route_to"] == "Editor"
    (env.tmp / "PRODUCTION_BOARD.md").write_text("# no stamp\n", encoding="utf-8")
    assert mw.run_check("M5", now(env), repo=env.tmp, table=t)["outcome"] == "UNKNOWN"


def note(e, row, day):
    (e.md / "notes").mkdir(parents=True, exist_ok=True)
    (e.md / "notes" / f"{row}_{day}.md").write_text("no change\n", encoding="utf-8")


def test_h2_note_skip_unknown_findings_pass(env):
    t = mw.load_rows()
    env.clock.set(2026, 12, 1, 9)
    assert mw.run_check("H2", now(env), table=t)["outcome"] == "SKIP"         # first due 2027-01-04
    env.clock.set(2027, 1, 6, 9)
    assert mr.is_awaiting(mw.run_check("H2", now(env), table=t))             # in grace to 01-12: awaiting
    env.clock.set(2027, 1, 12, 0, 1)
    assert mw.run_check("H2", now(env), table=t)["outcome"] == "FINDINGS"
    note(env, "H2", "2027-01-12")
    r = mw.run_check("H2", now(env), table=t)
    assert r["outcome"] == "PASS" and r["evidence"] == ".maint/notes/H2_2027-01-12.md"


def test_digest_empty_week_says_0_findings(env):
    env.clock.set(2026, 11, 2, 9)
    code = mw.main(["--now", "2026-11-02T09:00:00-04:00", "digest"])
    text = (env.md / "audits" / "2026-11-02_weekly.md").read_text(encoding="utf-8")
    assert "0 findings" in text and "## Monitor status" in text and "C1 uptime monitor: UNKNOWN" in text
    assert "## UNKNOWNs by age" in text and "nothing due for Daniel" in text
    assert last("W2")["outcome"] == "PASS" and last("W2")["evidence"] == ".maint/audits/2026-11-02_weekly.md"
    assert code == 2                                     # C1 UNKNOWN is never rounded away


def test_one_d3_fails_when_d1_or_d2_is_missing_or_unknown(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/abc")
    env.clock.set(2026, 11, 3, 10, 35)
    mw.main(["--now", "2026-11-03T10:35:00-05:00", "one", "D3"])            # no D1/D2 today -> fail signal
    assert env.calls[-1].endswith("/fail") and "D1 no receipt today" in last("D3")["why"]
    mr.write_receipt("D1", "PASS", why="ok", tool="t")
    mr.write_receipt("D2", "PASS", why="ok", tool="t")
    mw.main(["--now", "2026-11-03T10:35:00-05:00", "one", "D3"])
    assert not env.calls[-1].endswith("/fail") and last("D3")["outcome"] == "PASS"
    mr.write_receipt("D2", "UNKNOWN", why="cannot judge", tool="t")
    mw.main(["--now", "2026-11-03T10:35:00-05:00", "one", "D3"])
    assert env.calls[-1].endswith("/fail") and "D2 UNKNOWN" in last("D3")["why"]


def test_d3_pings_fail_only_for_a_new_alarm(env, monkeypatch):
    """The re-review: a standing alarm on day 1 sends /fail, day 2 sends success, a new alarm on day 3 sends /fail."""
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/abc")
    p = small_table(env.tmp, [DAILY, WEEKLY])
    monkeypatch.setattr(mw, "ROWS_FILE", p)

    def day(d, w1_pass):
        env.clock.set(2026, 11, d, 10, 0)
        mr.write_receipt("D1", "PASS", why="ok", tool="t")
        if w1_pass:
            mr.write_receipt("W1", "PASS", why="ok", tool="t")
        env.clock.set(2026, 11, d, 10, 35)
        mw.run_d2(now(env))
        mw.run_d3_watch(now(env))                    # what `one D3` runs (main --now would pin the clock)
        return env.calls[-1].endswith("/fail"), last("D3")["why"]
    env.clock.set(2026, 11, 1, 9)
    mr.write_receipt("W1", "PASS", why="ok", tool="t")
    env.schedule = {"state": "missing", "problems": ["scheduled task b4him-maint-run is missing"], "why": "x"}
    fail1, why1 = day(3, True)
    assert fail1 and "NEW SCHEDULE missing" in why1                  # day 1: the alarm is new
    fail2, why2 = day(4, True)
    assert not fail2 and "standing alarm(s) already reported" in why2   # day 2: same alarm, success ping
    fail3, why3 = day(10, False)                                       # W1 missed its Monday 11-09 + 1 d + 24 h? not yet
    assert not fail3
    fail4, why4 = day(12, False)                                       # day 3: OVERDUE W1 is new -> /fail
    assert fail4 and "NEW W1 overdue" in why4 and "SCHEDULE" not in why4


def test_judge_closes_an_assist_row_and_refuses_an_author_where_independence_is_required(env, capsys):
    env.clock.set(2026, 11, 2, 12)
    mr.write_receipt("M4", "SKIP", why=mr.awaiting_why("M4", "managing-editor", "pack assembled"),
                     evidence=".maint/audits/2026-11-02_reader.md", tool="maint_pages.py")
    mr.write_receipt("Q2", "SKIP", why=mr.awaiting_why("Q2", "reviewer", "sweep"),
                     evidence=".maint/audits/2026-11-02_genericize.md", tool="maint_pages.py")
    assert mw.main(["judge", "M4", "PASS", "--seat", "managing-editor",
                    "--note", "walked the path; all four questions answered"]) == 0
    assert last("M4")["outcome"] == "PASS" and last("M4")["why"].startswith("judged by managing-editor")
    assert last("M4")["evidence"] == ".maint/audits/2026-11-02_reader.md"     # the pack it judged rides along
    assert mw.main(["judge", "Q2", "PASS", "--seat", "site-maintainer", "--note", "x"]) == 1      # an author
    assert mw.main(["judge", "Q2", "PASS", "--seat", "maintenance-auditor", "--note", "x"]) == 1  # ran the sweep
    assert mw.main(["judge", "Q2", "FINDINGS", "--seat", "reviewer", "--note", "x"]) == 1        # no n
    assert mw.main(["judge", "H1", "PASS", "--seat", "publisher", "--note", "x"]) == 1           # HUMAN: E-number
    assert mw.main(["judge", "M4", "PASS", "--seat", "nobody", "--note", "x"]) == 1
    assert mw.main(["judge", "Q2", "FINDINGS", "2", "--seat", "reviewer",
                    "--note", "two non-lesson pages need a look"]) == 1
    assert last("Q2")["outcome"] == "FINDINGS" and last("Q2")["n"] == 2
    assert last("Q2")["evidence"] == ".maint/audits/2026-11-02_genericize.md"
    assert "REFUSED" in capsys.readouterr().out


# ------------------------------------------------------------------ round 3 (exp5): judge only what awaits a person
def test_judge_refuses_automate_rows_and_the_watch_rows(env, capsys):
    """exp5 A: a STUCK scanner row (W3, no names file) and D1/D3 were closable by any seat."""
    env.clock.set(2026, 11, 3, 10, 50)
    mr.write_receipt("W3", "UNKNOWN", why="names file absent", tool="maint_pages.py")
    mr.write_receipt("D1", "FINDINGS", n=1, why="MISSING: no line", tool="maint_watch.py")
    for rid in ("W3", "D1", "D2", "D3", "M1", "Q5", "C1"):
        assert mw.main(["judge", rid, "PASS", "--seat", "reviewer", "--note", "fine"]) == 1, rid
    assert last("W3")["outcome"] == "UNKNOWN" and last("D1")["outcome"] == "FINDINGS"     # nothing was written
    assert "AUTOMATE row" in capsys.readouterr().out


def test_judge_refuses_a_row_that_is_not_awaiting(env, capsys):
    """exp5 B3/B4: Q2 and A2 were judged with no evidence pack behind them."""
    env.clock.set(2026, 11, 3, 10, 50)
    assert mw.main(["judge", "Q2", "PASS", "--seat", "reviewer", "--note", "ok"]) == 1          # no receipt at all
    mr.write_receipt("A2", "SKIP", why=mr.awaiting_why("A2", "managing-editor", "pack"), tool="maint_pages.py")
    mr.write_receipt("A2", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")
    assert mw.main(["judge", "A2", "PASS", "--seat", "reviewer", "--note", "again"]) == 1      # already judged
    assert "latest receipt is not `awaiting" in capsys.readouterr().out
    assert [r["row"] for r in mr.read_receipts()] == ["A2", "A2"]


def test_judge_and_human_refuse_a_back_dated_clock(env, capsys):
    """exp5 C: `--now 2026-01-01 judge M1b` wrote a receipt dated in the past."""
    env.clock.set(2026, 11, 3, 10, 50)
    mr.write_receipt("M1b", "SKIP", why=mr.awaiting_why("M1b", "site-maintainer", "eye"), tool="maint_quality.py")
    assert mw.main(["--now", "2026-01-01T09:00:00-05:00", "judge", "M1b", "PASS", "--seat", "site-maintainer",
                    "--note", "old"]) == 1
    assert mw.main(["--now", "2026-01-01T09:00:00-05:00", "human", "H1", "E01234"]) == 1
    assert mr.is_awaiting(last("M1b")) and not [r for r in mr.read_receipts() if r["row"] == "H1"]
    assert "real clock only" in capsys.readouterr().out


def test_d3_a_stuck_row_whose_cause_changes_is_a_new_alarm(env, monkeypatch):
    """exp5 E: W1 STUCK for 'no network' was reported; it then crashed with KeyError, and D3 said nothing new."""
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/abc")
    p = small_table(env.tmp, [DAILY, WEEKLY])
    monkeypatch.setattr(mw, "ROWS_FILE", p)

    def day(d, why):
        env.clock.set(2026, 12, d, 9, 0)
        mr.write_receipt("W1", "UNKNOWN", why=why, tool="linkcheck.py")
        mr.write_receipt("D1", "PASS", why="ok", tool="t")
        env.clock.set(2026, 12, d, 10, 40)
        mw.run_d2(now(env))
        mw.run_d3_watch(now(env))
        return env.calls[-1].endswith("/fail"), last("D3")["why"]
    env.clock.set(2026, 12, 6, 9)
    mr.write_receipt("W1", "UNKNOWN", why="no network", tool="linkcheck.py")
    fail, why = day(8, "no network")                     # stuck: past W1's 24 h grace
    assert fail and "NEW W1 stuck-unknown: no network" in why
    fail, why = day(9, "no network")                     # same cause: standing, success ping
    assert not fail
    fail, why = day(10, "linkcheck crashed: KeyError 'pages'")   # a new cause on the same stuck row
    assert fail and "NEW W1 stuck-unknown: linkcheck crashed" in why


def test_cause_class_blurs_numbers_and_keeps_the_first_clause():
    assert mw.cause_class("expires 2027-09-01 (58 days): the window") == mw.cause_class("expires 2027-09-01 (57 days)")
    assert mw.cause_class("no network") != mw.cause_class("linkcheck crashed: KeyError")
    assert mw.alarm_key("W1", "stuck-unknown", "linkcheck crashed: KeyError") == "W1 stuck-unknown: linkcheck crashed"


def test_d2_alarms_an_assist_row_only_when_no_judgement_arrives_in_cadence_plus_grace(env):
    """The re-review's repro: M4 waiting on its seat must not be STUCK four days later; it is overdue only when a
    whole cadence + grace passes without a judgement, and re-runs that still wait do not buy more time."""
    p = small_table(env.tmp, [{**MONTHLY, "id": "M4"}])
    env.clock.set(2026, 11, 2, 11)
    mr.write_receipt("M4", "SKIP", why=mr.awaiting_why("M4", "managing-editor", "pack"), tool="maint_pages.py")
    env.clock.set(2026, 11, 6, 11)
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"               # waiting is not stuck
    env.clock.set(2026, 12, 7, 11)
    mr.write_receipt("M4", "SKIP", why=mr.awaiting_why("M4", "managing-editor", "pack"), tool="maint_pages.py")
    env.clock.set(2026, 12, 11, 0, 1)                                # next first Monday 12-07 + 1 d + 72 h
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and "M4 (awaiting judgement since 2026-11-02" in r["why"]
    mr.write_receipt("M4", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"


def test_d2_judges_a3_on_the_rdap_clock(env):
    """The re-review's repro: weekly SKIPs far from expiry are on time; there is no January false alarm."""
    a3 = {"id": "A3", "kind": "annual", "months": [1], "grace_hours": 336, "check": "human", "route_to": "Daniel"}
    p = small_table(env.tmp, [a3])
    for d in (4, 11, 18, 25):
        env.clock.set(2027, 1, d, 11)
        mr.write_receipt("A3", "SKIP", why="not due: expires 2027-09-01 (240 days)", tool="maint_human.py")
    env.clock.set(2027, 1, 26, 11)
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"
    env.clock.set(2027, 2, 3, 11)                                    # no poll since 01-25: Monday 02-01 + 1 d + 24 h
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and "RDAP poll stopped" in r["why"]
    for d in (5, 12, 19):                                            # window opens 2027-07-03; grace 14 d
        env.clock.set(2027, 7, d, 11)
        mr.write_receipt("A3", "FINDINGS", n=1, why="expires 2027-09-01 (58 days): the 60-day window is open",
                         tool="maint_human.py")
    env.clock.set(2027, 7, 16, 11)
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"               # inside the 14-day grace (to 07-17 00:00)
    env.clock.set(2027, 7, 20, 11)
    r = mw.run_d2(now(env), p)
    assert r["outcome"] == "FINDINGS" and "window opened 2027-07-03" in r["why"]
    mr.write_receipt("A3", "PASS", why="closed by Daniel's ledger E01234", tool="maint_watch.py")
    assert mw.run_d2(now(env), p)["outcome"] == "PASS"


def test_one_human_row_is_skip_when_not_due_and_a_reminder_when_due(env):
    env.clock.set(2026, 11, 3, 9)
    mw.main(["--now", "2026-11-03T09:00:00-05:00", "one", "H1"])
    assert last("H1")["outcome"] == "SKIP" and "next due 2027-01-04" in last("H1")["why"]
    env.clock.set(2027, 1, 4, 9)
    mw.main(["--now", "2027-01-04T09:00:00-05:00", "one", "H1"])
    assert mr.is_awaiting(last("H1")) and "reminder fired 2027-01-04" in last("H1")["why"]
    mw.main(["--now", "2027-01-04T09:00:00-05:00", "one", "H1"])
    assert mr.is_awaiting(last("H1")) and "awaiting Daniel" in last("H1")["why"]


def test_digest_uses_the_c1_readers_receipt_when_there_is_one(env):
    env.clock.set(2026, 11, 2, 8)
    mr.write_receipt("C1", "PASS", n=0, why="b4him: up, last 7 days uptime 100.000%", tool="headers_tls_check.py")
    env.clock.set(2026, 11, 2, 9)
    mw.main(["--now", "2026-11-02T09:00:00-04:00", "digest"])
    text = (env.md / "audits" / "2026-11-02_weekly.md").read_text(encoding="utf-8")
    assert "C1 uptime monitor: PASS b4him: up" in text
    assert [r["tool"] for r in mr.read_receipts() if r["row"] == "C1"] == ["headers_tls_check.py"]


def test_digest_lists_open_findings_and_unknowns_by_age(env):
    env.clock.set(2026, 10, 28, 9)
    mr.write_finding("D2", "S2", "OVERDUE W1", "x", "SM")
    mr.write_receipt("D2", "FINDINGS", n=1, why="overdue: W1")
    mr.write_receipt("W3", "UNKNOWN", why="no names file")
    env.clock.set(2026, 10, 29, 9)
    mr.write_finding("D2", "S2", "OVERDUE W1", "x", "SM")
    mr.write_receipt("D2", "FINDINGS", n=1, why="overdue: W1")
    mr.write_receipt("W3", "UNKNOWN", why="no names file")
    mw.main(["--now", "2026-11-02T09:00:00-04:00", "digest"])
    text = (env.md / "audits" / "2026-11-02_weekly.md").read_text(encoding="utf-8")
    assert "## Open findings by age (1)" in text and "5 d · D2 S2 OVERDUE W1" in text
    assert "5 d · W3: no names file" in text


def test_digest_h3_reminder_with_evidence_pack_and_due_for_daniel(env, monkeypatch):
    monkeypatch.setenv("MAINT_CALENDAR_PATH", "seat/CALENDAR.md")
    mw.main(["--now", "2027-01-04T09:00:00-05:00", "digest"])
    text = (env.md / "audits" / "2027-01-04_weekly.md").read_text(encoding="utf-8")
    assert "REMINDER: the re-read is due" in text and "seat/CALENDAR.md" in text and "PRODUCTION_PLAN.md" in text
    assert "**H1** due 2027-01-04" in text and "**A1** due 2027-01-04" in text and "**A3**" in text
    assert "screenshots" in text                         # H1's "what to look at" comes from the row table
    h1 = last("H1")
    assert mr.is_awaiting(h1) and "(on time)" in h1["why"]


# ------------------------------------------------------------------ HUMAN rows
def test_human_reminder_fires_once_late_is_recorded_and_e_number_closes(env, capsys):
    mw.main(["--now", "2027-01-06T09:00:00-05:00", "digest"])
    mw.main(["--now", "2027-01-07T09:00:00-05:00", "digest"])
    fired = [r for r in mr.read_receipts() if r["row"] == "A3"]
    assert len(fired) == 1 and "late by 2 day(s)" in fired[0]["why"]
    assert mw.main(["--now", "2027-01-07T10:00:00-05:00", "human", "A3", "E00999"]) == 1    # never back-dated
    assert mw.main(["human", "A3", "E00999"]) == 0                                           # the clock's own time
    assert last("A3")["outcome"] == "PASS" and "E00999" in last("A3")["why"]
    mw.main(["--now", "2027-01-11T09:00:00-05:00", "digest"])
    text = (env.md / "audits" / "2027-01-11_weekly.md").read_text(encoding="utf-8")
    assert "A3: not due; next 2028-01-03" in text
    assert mw.main(["human", "W1", "E00999"]) == 1 and mw.main(["human", "A1", "00999"]) == 1


# ------------------------------------------------------------------ Q6
def test_drill_unknown_without_a_heartbeat(env):
    assert mw.main(["--now", "2027-01-04T09:00:00-05:00", "drill"]) == 2
    assert last("Q6")["outcome"] == "UNKNOWN" and "no MAINT_HEARTBEAT_URL" in last("Q6")["why"]
    assert (env.md / "audits" / "2027-01-04_drill.md").is_file()


def test_drill_skips_one_heartbeat_then_confirm_pass(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)
    mw.main(["--now", "2027-01-04T09:00:00-05:00", "drill"])
    q = last("Q6")
    assert mr.is_awaiting(q) and q["why"].startswith("awaiting alarm confirmation")
    mw.main(["--now", "2027-01-04T10:40:00-05:00", "daily", "--release-log", str(env.tmp / "none.jsonl")])
    assert last("D3")["outcome"] == "SKIP" and env.calls == []                 # the heartbeat really was withheld
    assert mw.main(["--now", "2027-01-05T13:00:00-05:00", "confirm", "2027-01-05T12:31:00-04:00"]) == 0
    assert last("Q6")["outcome"] == "PASS" and "alarm fired at 12:31" in last("Q6")["why"]
    assert mw.main(["--now", "2027-01-05T13:00:00-05:00", "confirm", "12:00"]) == 1   # nothing armed any more
    mw.main(["--now", "2027-01-06T10:40:00-05:00", "daily", "--release-log", str(env.tmp / "none.jsonl")])
    assert env.calls == [URL + "/fail"]                                         # pings resume after the drill


def test_drill_confirm_never_is_a_fail_finding(env, monkeypatch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", URL)
    mw.main(["--now", "2027-01-04T09:00:00-05:00", "drill"])
    assert mw.main(["--now", "2027-01-06T09:00:00-05:00", "confirm", "never"]) == 1
    assert last("Q6")["outcome"] == "FINDINGS" and mr.read_findings()[-1]["severity"] == "S1"


def test_drill_lists_rows_quiet_for_four_quarters(env, monkeypatch):
    t = mw.load_rows()
    env.clock.set(2025, 12, 29, 9)
    mr.write_receipt("W1", "PASS")
    mr.write_receipt("M3", "PASS")
    env.clock.set(2026, 6, 1, 9)
    mr.write_receipt("M3", "FINDINGS", n=1, why="cert")
    mr.write_receipt("Q4", "PASS")
    env.clock.set(2027, 1, 4, 9)
    out = "\n".join(mw.retire_candidates(t, mr.read_receipts(), mr.read_findings(), now(env)))
    assert "**W1**: zero findings and zero alarms in 4 quarters" in out
    assert "M3" not in out and "Q4: zero findings and zero alarms so far" in out and "D1: no receipt ever" in out
