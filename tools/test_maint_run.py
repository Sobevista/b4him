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
WEEKLY = {"C1", "W1", "W1b", "W2", "W3", "E3", "A3"}          # E3 polls its feeds; A3 polls RDAP (expiry - 60 d)
MONTHLY = {"M1", "M1b", "M2", "M2b", "M3", "M4", "M5"}
QUARTERLY = {"Q1", "Q2", "Q3", "Q4", "Q5", "Q6"}
SEMI = {"H1", "H2", "H3"}
ANNUAL = {"A1", "A2", "A3", "A4"}
EVENTS = {"E1", "E2"}


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
    assert ev["E1"]["outcome"] == "SKIP" and ev["E2"]["outcome"] == "SKIP"
    assert ("standards_watch.py", ()) in calls and ev["E3"]["tool"] == "tools/standards_watch.py"   # E3 has a tool now


# ------------------------------------------------------------------ crash isolation (real processes, fake tools)
FAKE = {
    "ok.py": "write(sys.argv[1], 'PASS')",
    "partial.py": "write(sys.argv[1], 'PASS'); sys.exit(3)",          # the review's repro: PASS, then a crash exit
    "pass1.py": "write(sys.argv[1], 'PASS'); sys.exit(1)",            # exit 1 that no FINDINGS explains
    "skip2.py": "write(sys.argv[1], 'SKIP'); sys.exit(2)",            # exit 2 explained by its SKIP
    "pages.py": "[write('W3.page', 'UNKNOWN') for _ in range(3)]; write('W3', 'FINDINGS', 4)",
    "boom.py": "raise RuntimeError('scanner fell over')",
    "hang.py": "import time; time.sleep(60)",
    "quiet.py": "print('did nothing')",
    "weird.py": "sys.exit(7)",
}
PRELUDE = textwrap.dedent("""\
    import datetime, json, os, sys
    def write(row, outcome, n=0):
        d = os.environ['MAINT_DIR']; os.makedirs(d, exist_ok=True)
        e = {'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds'), 'row': row,
             'outcome': outcome, 'n': n, 'why': 'fake', 'evidence': None, 'tool': 'tools/' + os.path.basename(sys.argv[0]),
             'run_id': os.environ.get('MAINT_RUN_ID')}
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
    assert all(e["tool"] == "tools/maint_run.py" for r, e in got.items() if r in ("R2", "R3", "R4", "R5", "R6"))


def test_exit_code_is_non_zero_on_any_runner_failure(fakes, monkeypatch, capsys):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    assert run.main(["--row", "R1"]) == 0                                    # a clean runner
    assert run.main(["--row", "R1", "--row", "R2", "--row", "R3"]) == 2     # a crash and a timeout: non-zero
    assert run.main(["--row", "R4"]) == 2                                    # exited 0 with no receipt
    assert run.main(["--row", "R6"]) == 2                                    # could not start
    assert run.main(["--row", "NOPE"]) == 2
    out = capsys.readouterr().out
    assert "3 receipt(s) for 3 row(s)" in out and "runner failed for R2, R3" in out
    assert "runner could not start for R6" in out


# ------------------------------------------------------------------ run records (the harness counter's spec)
def raw_log(md):
    import json as _j
    return [_j.loads(x) for x in (md / "maintenance_log.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]


def test_run_records_bracket_every_receipt_of_the_run(fakes, md, monkeypatch):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    monkeypatch.delenv("MAINT_TRIGGER", raising=False)
    monkeypatch.delenv("MAINT_RUN_ID", raising=False)
    monkeypatch.setattr(run, "launched_process", lambda: {"pid": 4242, "proc_started": "2026-10-31T09:00:00+00:00"})
    assert run.main(["--row", "R1", "--row", "D2"]) == 0
    log = raw_log(md)
    start, end, body = log[0], log[-1], log[1:-1]
    assert list(start) == ["at", "kind", "run_id", "runner", "pid", "proc_started", "trigger"]
    assert start["pid"] == 4242
    assert start["kind"] == "run_start" and start["runner"] == "tools/maint_run.py" and start["trigger"] == "manual"
    assert list(end) == ["at", "kind", "run_id", "runner", "exit", "rows_failed"] and end["kind"] == "run_end"
    assert end["exit"] == 0 and end["rows_failed"] == [] and start["proc_started"] == "2026-10-31T09:00:00+00:00"
    assert end["run_id"] == start["run_id"] and "row" not in start and "row" not in end
    assert [e["row"] for e in body] == ["R1", "D2"]
    assert all(e["run_id"] == start["run_id"] and e["tool"] == "tools/ok.py" for e in body)   # set by the CHILD
    assert "MAINT_RUN_ID" not in __import__("os").environ               # the id dies with the run
    assert mr.read_receipts() == body                                   # readers never see the run records


def test_proc_started_is_the_child_process_creation_time():
    """A fresh process's GetProcessTimes creation time, read in that process: within seconds of now, with an offset.
    (Asserting it in-process would measure pytest's own start, the round-5 review's red run.)"""
    import datetime as _dt
    import subprocess as _sp
    import sys as _sys
    before = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0)
    out = _sp.run([_sys.executable, "-c", "import sys; sys.path.insert(0, sys.argv[1]); import maint_run; "
                   "print(maint_run.proc_started())", str(HERE)], capture_output=True, encoding="utf-8",
                  check=True).stdout.strip()
    ps = _dt.datetime.fromisoformat(out)
    assert ps.utcoffset() is not None and before - _dt.timedelta(seconds=2) <= ps <= before + _dt.timedelta(seconds=60)


def test_choose_launch_picks_the_py_launcher_when_it_started_us():
    own = (200, r"C:\Py\Python314\python.exe", "2026-10-31T10:35:01+00:00")
    launcher = (100, r"C:\Windows\py.exe", "2026-10-31T10:35:00+00:00")
    shell = (50, r"C:\Windows\System32\cmd.exe", "2026-10-31T09:00:00+00:00")
    assert run.choose_launch(own, launcher) == {"pid": 100, "proc_started": "2026-10-31T10:35:00+00:00"}
    assert run.choose_launch(own, shell) == {"pid": 200, "proc_started": "2026-10-31T10:35:01+00:00"}
    assert run.choose_launch(own, (100, r"C:\Windows\PYW.EXE", "x"))["pid"] == 100
    assert run.choose_launch(own, (100, None, None))["pid"] == 200          # an unreadable parent is not a launcher


def _child_launch(argv):
    import json as _j
    import subprocess as _sp
    code = ("import sys, os, json; sys.path.insert(0, sys.argv[1]); import maint_run; "
            "print(json.dumps({'me': os.getpid(), 'parent': os.getppid(), **maint_run.launched_process()}))")
    out = _sp.run([*argv, "-c", code, str(HERE)], capture_output=True, encoding="utf-8", check=True).stdout
    return _j.loads(out.strip().splitlines()[-1])


def test_pid_is_the_process_task_scheduler_would_create():
    """Run directly with python.exe (what maint_schedule.py prints), pid is the process itself; run through the py
    launcher, pid is the launcher, which is what Task Scheduler would have created (its event 129 ProcessID)."""
    import shutil as _sh
    import sys as _sys
    direct = _child_launch([_sys.executable])
    assert direct["pid"] == direct["me"] and direct["proc_started"]
    py = _sh.which("py")
    if py is None:
        pytest.skip("no py launcher on PATH")
    via = _child_launch([py])
    assert via["pid"] == via["parent"] != via["me"] and via["proc_started"]


def test_run_end_names_the_rows_whose_runner_failed(fakes, md, monkeypatch):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    assert run.main(["--row", "R1", "--row", "R2", "--row", "R3", "--row", "R6"]) == 2
    end = raw_log(md)[-1]
    assert end["kind"] == "run_end" and end["exit"] == 2 and end["rows_failed"] == ["R2", "R3", "R6"]


def test_run_ids_are_unique_and_scheduled_is_recorded(fakes, md, monkeypatch):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    monkeypatch.delenv("MAINT_TRIGGER", raising=False)
    run.main(["--row", "R1"])
    monkeypatch.setenv("MAINT_TRIGGER", "x")                             # cleaned by monkeypatch after the test
    run.main(["--row", "R1", "--scheduled"])
    starts = [e for e in raw_log(md) if e.get("kind") == "run_start"]
    assert len({s["run_id"] for s in starts}) == 2
    assert [s["trigger"] for s in starts] == ["manual", "scheduled"]


def test_a_crash_still_writes_run_end_and_exits_non_zero(fakes, md, monkeypatch):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))

    def boom(*a, **k):
        raise RuntimeError("runner bug")
    monkeypatch.setattr(run, "run", boom)
    with pytest.raises(RuntimeError):
        run.main(["--row", "R1"])
    log = raw_log(md)
    assert [e["kind"] for e in log] == ["run_start", "run_end"] and log[0]["run_id"] == log[1]["run_id"]
    assert log[1]["exit"] == 1 and log[1]["rows_failed"] == []          # the crash is recorded as a non-zero exit


def test_a_tool_run_by_hand_writes_run_id_null_and_a_repo_relative_tool(md, monkeypatch):
    monkeypatch.delenv("MAINT_RUN_ID", raising=False)
    r = mr.write_receipt("W1", "PASS", n=0, why="by hand", tool="linkcheck.py")
    assert r["run_id"] is None and r["tool"] == "tools/linkcheck.py"
    assert mr.write_receipt("W1", "PASS", why="x", tool=str(HERE / "linkcheck.py"))["tool"] == "tools/linkcheck.py"
    assert mr.write_receipt("W1", "PASS", why="x", tool="tools/linkcheck.py")["tool"] == "tools/linkcheck.py"
    monkeypatch.setenv("MAINT_RUN_ID", "abc")
    assert mr.write_receipt("W1", "PASS", why="x", tool="linkcheck.py")["run_id"] == "abc"


def test_a_partial_run_never_reads_as_pass(fakes, monkeypatch):
    monkeypatch.setattr(run, "RUNNERS", {"P1": ("partial.py", ("P1",), 30), "P2": ("pass1.py", ("P2",), 30),
                                         "P3": ("skip2.py", ("P3",), 30), "P4": ("ok.py", ("P4",), 30)})
    rows = {r: {"id": r, "kind": "daily"} for r in ("P1", "P2", "P3", "P4")}
    got = {e["row"]: e for e in run.run(list(rows), rows)["receipts"]}
    assert got["P1"]["outcome"] == "UNKNOWN" and "exited 3 after writing P1 PASS" in got["P1"]["why"]
    assert got["P2"]["outcome"] == "UNKNOWN" and "exited 1 after writing P2 PASS" in got["P2"]["why"]
    assert got["P3"]["outcome"] == "SKIP" and got["P4"]["outcome"] == "PASS"


def test_only_this_runs_receipt_from_this_tool_counts(fakes, monkeypatch):
    mr.write_receipt("R4", "PASS", why="yesterday's pass", tool="quiet.py")           # before the run: never counts
    monkeypatch.setattr(run, "RUNNERS", {"R4": ("quiet.py", (), 30), "R7": ("ok.py", ("R8",), 30),
                                         "W3": ("pages.py", (), 30)})
    rows = {r: {"id": r, "kind": "daily"} for r in ("R4", "R7", "W3")}
    got = {e["row"]: e for e in run.run(list(rows), rows)["receipts"]}
    assert got["R4"]["outcome"] == "UNKNOWN"                       # quiet.py wrote nothing this run
    assert got["R7"]["outcome"] == "UNKNOWN"                       # ok.py wrote R8, not R7
    assert got["W3"]["outcome"] == "FINDINGS" and got["W3"]["n"] == 4   # the summary, never a W3.page line


def test_patch_proof_runs_the_four_checks_and_keeps_their_receipts_out_of_the_calendar(md, tmp_path, monkeypatch):
    tree = tmp_path / "patched"
    tree.mkdir()
    import subprocess as sp
    sp.run(["git", "init", "-q", str(tree)], check=True)
    sp.run(["git", "-C", str(tree), "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q",
            "--allow-empty", "-m", "x"], check=True)
    calls = []

    def fake(argv, timeout):
        tool, args = Path(argv[1]).name, argv[2:]
        calls.append((tool, args))
        row = {"a11y": "M1", "contrast": "M1b", "perf": "M2"}.get(args[0], "W1")
        out = "FINDINGS" if row == "M2" else "PASS"
        mr.write_receipt(row, out, n=2 if out == "FINDINGS" else 0, why="fake", tool=tool)
        return (1 if out == "FINDINGS" else 0), "", ""
    monkeypatch.setattr(run, "RUN", fake)
    r = run.patch_proof(tree)
    assert [c[1][0] for c in calls] == ["a11y", "contrast", "--repo", "perf"]
    assert ("linkcheck.py", ["--repo", str(tree.resolve()), "--internal-only"]) in calls          # W1(a) only
    assert r["row"] == "E1" and r["outcome"] == "FINDINGS" and r["n"] == 2 and "M2 FINDINGS 2" in r["why"]
    assert [e["row"] for e in mr.read_receipts()] == ["E1"]       # M1/M1b/W1/M2 of a patch are not calendar runs
    proof = md / r["evidence"][len(".maint/"):]
    assert json.loads(proof.read_text(encoding="utf-8"))["outcome"] == "FINDINGS"
    owed = [f for f in mr.read_findings() if f["subject"] == run.OWED]
    run.patch_proof(tree)
    assert len(owed) == 1 and len([f for f in mr.read_findings() if f["subject"] == run.OWED]) == 1   # filed once
    assert run.patch_proof(tmp_path / "nope")["outcome"] == "UNKNOWN"


def test_list_runs_nothing(fakes, monkeypatch, capsys, md):
    monkeypatch.setattr(run, "load_table", lambda path=None: list(fakes.values()))
    assert run.main(["--all", "--list"]) == 0
    assert capsys.readouterr().out.split()[-1] == "D2" and not (md / "maintenance_log.jsonl").exists()
