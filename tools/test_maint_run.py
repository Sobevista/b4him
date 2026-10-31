"""Tests for tools/maint_run.py: which rows are due on a date, the run order, and crash isolation. No network: the
crash tests run tiny fake tools written into tmp_path; the order tests replace the process runner."""
import datetime as dt
import json
import sys
import textwrap
from pathlib import Path

import pytest

import maint_receipt as mr
import maint_run as run

HERE = Path(__file__).resolve().parent
ROWS = run.load_table()
IDS = [r["id"] for r in ROWS]
BY_ID = {r["id"]: r for r in ROWS}
DAILY = {"D1", "D2", "D3"}
WEEKLY = {"C1", "W1", "W1b", "W2", "W3"}
MONTHLY = {"M1", "M1b", "M2", "M2b", "M3", "M4", "M5"}
QUARTERLY = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}
SEMI = {"H1", "H2", "H3"}
ANNUAL = {"A1", "A2", "A3", "A4"}
EVENTS = {"E1", "E2", "E3"}


@pytest.fixture
def md(tmp_path, monkeypatch):
    d = tmp_path / ".maint"
    monkeypatch.setenv("MAINT_DIR", str(d))
    return d


# ------------------------------------------------------------------ scheduling
def test_the_table_is_the_calendar_we_think_it_is():
    assert set(IDS) == DAILY | WEEKLY | MONTHLY | QUARTERLY | SEMI | ANNUAL | EVENTS


@pytest.mark.parametrize("day, want", [
    (dt.date(2026, 11, 3), DAILY),                                          # a Tuesday
    (dt.date(2026, 10, 31), DAILY),                                         # a Saturday
    (dt.date(2026, 11, 9), DAILY | WEEKLY),                                 # a Monday, not the first
    (dt.date(2026, 11, 2), DAILY | WEEKLY | MONTHLY),                       # first Monday of November
    (dt.date(2026, 10, 5), DAILY | WEEKLY | MONTHLY | QUARTERLY),           # first Monday of October (a quarter)
    (dt.date(2026, 12, 7), DAILY | WEEKLY | MONTHLY),                       # first Monday of a non-quarter month
    (dt.date(2027, 7, 5), DAILY | WEEKLY | MONTHLY | QUARTERLY | SEMI),     # first Monday of July
    (dt.date(2027, 1, 4), DAILY | WEEKLY | MONTHLY | QUARTERLY | SEMI | ANNUAL),  # first Monday of January
    (dt.date(2027, 1, 11), DAILY | WEEKLY),                                 # second Monday of January
])
def test_due_rows_follow_the_days_paragraph(day, want):
    assert set(run.due_rows(ROWS, day)) == want


def test_event_rows_are_never_due():
    for n in range(400):
        d = dt.date(2026, 10, 1) + dt.timedelta(days=n)
        assert not EVENTS & set(run.due_rows(ROWS, d))


def test_first_monday():
    assert run.first_monday(2026, 11) == dt.date(2026, 11, 2)
    assert run.first_monday(2027, 2) == dt.date(2027, 2, 1)          # the 1st is itself a Monday


def test_order_puts_the_watcher_after_the_rest_and_d1_d2_d3_last():
    o = run.ordered(IDS)
    assert o[-3:] == ["D1", "D2", "D3"]
    assert o.index("W2") > max(o.index(r) for r in ("C1", "W1", "W1b", "W3", "M1", "A4"))


def test_every_clock_row_has_a_runner_whose_tool_is_here_and_a_timeout():
    for rid in IDS:
        if rid in EVENTS:
            assert rid in run.EVENT_RECEIPTS
            continue
        tool, args, timeout = run.RUNNERS[rid]
        assert (HERE / tool).is_file(), f"{rid}: {tool} missing"
        assert isinstance(timeout, int) and 0 < timeout <= 4 * 3600


# ------------------------------------------------------------------ order and sharing (fake runner, no processes)
def test_all_runs_each_tool_once_per_args_and_heartbeat_last(md, monkeypatch):
    calls = []

    def fake(argv, timeout):
        tool, args = Path(argv[1]).name, tuple(argv[2:])
        calls.append((tool, args))
        rows = [r for r, (t, a, _) in run.RUNNERS.items() if (t, a) == (tool, args)]
        if (tool, args) == ("maint_watch.py", ("digest",)):
            rows = ["M5", "H2", "H3", "W2"]                      # the digest writes the receipts-only checks too
        for r in rows:
            mr.write_receipt(r, "PASS", n=0, why="fake", tool=tool)
        return 0, "", ""
    monkeypatch.setattr(run, "RUN", fake)
    res = run.run(IDS, BY_ID)
    assert [e["row"] for e in res["receipts"]] and {e["row"] for e in res["receipts"]} == set(IDS)
    assert res["could_not_start"] == []
    assert calls.count(("linkcheck.py", ())) == 1                         # W1 and W1b share one run
    assert ("maint_watch.py", ("check", "M5")) not in calls               # already receipted by the digest
    assert calls[-3:] == [("maint_watch.py", ("one", "D1")), ("maint_watch.py", ("one", "D2")),
                          ("maint_watch.py", ("one", "D3"))]
    ev = {e["row"]: e for e in res["receipts"]}
    assert ev["E1"]["outcome"] == "SKIP" and ev["E3"]["outcome"] == "UNKNOWN"


# ------------------------------------------------------------------ crash isolation (real processes, fake tools)
FAKE = {
    "ok.py": "write(sys.argv[1], 'PASS')",
    "boom.py": "raise RuntimeError('scanner fell over')",
    "hang.py": "import time; time.sleep(60)",
    "quiet.py": "print('did nothing')",
    "weird.py": "sys.exit(7)",
}
PRELUDE = textwrap.dedent("""\
    import datetime, json, os, sys
    def write(row, outcome):
        d = os.environ['MAINT_DIR']; os.makedirs(d, exist_ok=True)
        e = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'row': row,
             'outcome': outcome, 'n': 0, 'why': 'fake', 'evidence': None, 'tool': 'ok.py'}
        open(os.path.join(d, 'maintenance_log.jsonl'), 'a', encoding='utf-8').write(json.dumps(e) + '\\n')
    """)


@pytest.fixture
def fakes(tmp_path, md, monkeypatch):
    tools = tmp_path / "faketools"
    tools.mkdir()
    for name, body in FAKE.items():
        (tools / name).write_text(PRELUDE + body + "\n", encoding="utf-8")
    monkeypatch.setattr(run, "TOOLS_DIR", tools)
    monkeypatch.setattr(run, "RUNNERS", {
        "R1": ("ok.py", ("R1",), 30), "R2": ("boom.py", (), 30), "R3": ("hang.py", (), 2),
        "R4": ("quiet.py", (), 30), "R5": ("weird.py", (), 30), "R6": ("gone.py", (), 30),
        "D2": ("ok.py", ("D2",), 30),
    })
    monkeypatch.setattr(run, "LAST_ROWS", ("D2",))
    return {r: {"id": r, "kind": "daily"} for r in ("R1", "R2", "R3", "R4", "R5", "R6", "D2")}


def test_a_crash_is_an_unknown_for_that_row_and_the_run_goes_on(fakes):
    res = run.run(list(fakes), fakes)
    got = {e["row"]: e for e in res["receipts"]}
    assert set(got) == set(fakes)                                    # every row has a receipt
    assert got["R1"]["outcome"] == "PASS" and got["D2"]["outcome"] == "PASS"   # rows after the crashes still ran
    assert got["R2"]["outcome"] == "UNKNOWN" and "scanner fell over" in got["R2"]["why"]
    assert got["R3"]["outcome"] == "UNKNOWN" and "timed out after 2 s" in got["R3"]["why"]
    assert got["R4"]["outcome"] == "UNKNOWN" and "without a R4 receipt: did nothing" in got["R4"]["why"]
    assert got["R5"]["outcome"] == "UNKNOWN" and "exited 7" in got["R5"]["why"]
    assert got["R6"]["outcome"] == "UNKNOWN" and "could not start" in got["R6"]["why"]
    assert res["could_not_start"] == ["R6"]                          # only a runner that never started counts
    assert [e["row"] for e in mr.read_receipts()][-1] == "D2"        # the watch row was last
    assert all(e["tool"] == "maint_run.py" for r, e in got.items() if r in ("R2", "R3", "R4", "R5", "R6"))


def test_exit_code_is_2_only_when_a_runner_could_not_start(fakes, monkeypatch, capsys):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    assert run.main(["--row", "R1", "--row", "R2", "--row", "R3"]) == 0     # crashes and timeouts still exit 0
    assert run.main(["--row", "R6"]) == 2
    assert run.main(["--row", "NOPE"]) == 2
    out = capsys.readouterr().out
    assert "3 receipt(s) for 3 row(s)" in out and "runner could not start for R6" in out


def test_list_runs_nothing(fakes, monkeypatch, capsys, md):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    assert run.main(["--all", "--list"]) == 0
    assert capsys.readouterr().out.split()[-1] == "D2" and not (md / "maintenance_log.jsonl").exists()
