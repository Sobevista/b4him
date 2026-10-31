"""Tests for tools/maint_schedule.py: the printed schtasks line and the read-back check. Nothing is registered: every
schtasks / where call is a fake."""
import datetime as dt
import subprocess

import pytest

import maint_schedule as ms

PY = r"C:\Windows\py.exe"
NOW = dt.datetime(2026, 11, 3, 11, 0).astimezone()


def fake(answers, calls=None):
    def run(argv):
        if calls is not None:
            calls.append(argv)
        for k, v in answers.items():
            if argv[0] == k:
                return v
        raise AssertionError(f"unexpected {argv}")
    return run


def listing(last="11/3/2026 10:35:02 AM", tr=f'"{PY}" "C:\\x y\\tools\\maint_run.py" --scheduled'):
    return (0, f"HostName: X\nTaskName: \\b4him-maint-run\nLast Run Time: {last}\nLast Result: 0\n"
               f"Task To Run: {tr}\n", "")


def test_the_line_is_list2cmdline_with_a_quoted_tr_at_10_35(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(ms, "RUN", fake({"where": (0, PY + "\r\nC:\\other\\py.exe\r\n", "")}, calls))
    repo = tmp_path / "Data Import" / "b4him"
    line = ms.command(repo)
    script = repo / "tools" / "maint_run.py"
    assert line == subprocess.list2cmdline(["schtasks.exe", "/Create", "/TN", "b4him-maint-run", "/SC", "DAILY",
                                            "/ST", "10:35", "/TR", f'"{PY}" "{script}" --scheduled', "/F"])
    assert calls == [["where", "py"]]                       # py resolved by `where py`, the first hit
    assert '/TR "\\"C:\\Windows\\py.exe\\" \\"' in line      # the stored Task To Run will begin with a quote
    assert all(a[0] != "schtasks" for a in calls)            # printing never touches the scheduler


def test_main_prints_and_registers_nothing(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(ms, "RUN", fake({"where": (0, PY, "")}, calls))
    assert ms.main([]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[1].startswith("schtasks.exe /Create /TN b4him-maint-run /SC DAILY /ST 10:35 /TR ")
    assert lines[4].endswith(" /RU %USERDOMAIN%\\%USERNAME% /F")          # the /RU variant: run while signed out
    assert "<" not in lines[4] and ">" not in lines[4]                  # nothing cmd.exe would read as a redirect
    assert lines[6] == ms.BATTERY_PS and "DisallowStartIfOnBatteries = $false" in lines[6]
    assert "Nothing above has been run or registered." in lines[-1]
    assert calls == [["where", "py"]]                                   # printing never touches the scheduler


def test_no_py_is_unknown(monkeypatch, capsys):
    monkeypatch.setattr(ms, "RUN", fake({"where": (1, "", "INFO: Could not find files")}))
    assert ms.main([]) == 2


@pytest.mark.parametrize("answer, state", [
    (listing(), "ok"),
    (listing(last="11/1/2026 10:35:02 AM"), "stale"),                      # over 26 h ago
    (listing(last="11/30/1999 12:00:00 AM"), "stale"),                     # never ran
    (listing(tr=f"{PY} C:\\x\\maint_run.py --scheduled"), "stale"),      # unquoted /TR
    (listing(tr=f'"{PY}" "C:\\x\\maint_run.py"'), "stale"),              # no --scheduled: runs look manual
    ((1, "", "ERROR: The system cannot find the file specified.\r\n"), "missing"),
    ((1, "", "ERROR: Access is denied.\r\n"), "unknown"),
    (listing(last="sometime"), "unknown"),
])
def test_check_reads_the_task_back(monkeypatch, answer, state):
    calls = []
    monkeypatch.setattr(ms, "RUN", fake({"schtasks": answer}, calls))
    r = ms.check(NOW)
    assert r["state"] == state
    assert calls == [["schtasks", "/Query", "/TN", "b4him-maint-run", "/V", "/FO", "LIST"]]   # a query, nothing else
