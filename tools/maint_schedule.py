#!/usr/bin/env python3
"""
maint_schedule.py: the maintenance calendar's schedule line. It PRINTS the command a human pastes to run
tools/maint_run.py every day at 10:35 local (after D1's 08:30 + 2 h cutoff, so D2 and D3 see the release line); it
never registers, changes or deletes a task. `--check` reads the task back and says whether it exists and ran lately;
D2 (tools/maint_watch.py) calls the same check, so a missing or stalled schedule is a D2 alarm.

    py tools/maint_schedule.py                 print the schtasks /Create line (paste it into cmd.exe), the /RU
                                               variant, and the PowerShell that lets it start on battery
    py tools/maint_schedule.py --repo <path>   ... for another checkout (default: this one)
    py tools/maint_schedule.py --check         read `schtasks /Query /TN b4him-maint-run /V /FO LIST`

HOW THE LINE IS BUILT (harness LESSONS, "A path containing spaces inside schtasks /TR"): the interpreter is the full
path of python.exe itself, resolved with `py -c "import sys;print(sys.executable)"`, not the py.exe launcher, so the
process Task Scheduler creates (its event 129 ProcessID) IS maint_run's process and run_start's pid / proc_started
are its own (tools/maint_run.py). The /TR value is quoted ("<python>" "<script>" --scheduled) so the stored Task To
Run begins with a quote, and the whole
argv is joined by subprocess.list2cmdline, never by PowerShell string-building. After pasting, read it back:
`schtasks /Query /TN b4him-maint-run /V /FO LIST` must show "Task To Run:" beginning with ".

--check: exit 0 the task exists, its Task To Run is quoted and it last ran under 26 hours ago (one day + 2 h slack);
1 the task is missing, never ran, ran too long ago, or is unquoted; 2 schtasks could not be read (UNKNOWN).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
TASK = "b4him-maint-run"
AT = "10:35"
STALE = dt.timedelta(hours=26)
NEVER = ("N/A", "11/30/1999 12:00:00 AM", "Never")
TIME_FORMATS = ("%m/%d/%Y %I:%M:%S %p", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S",
                "%d.%m.%Y %H:%M:%S")


class Unreadable(Exception):
    pass


def _run(argv: list[str]) -> tuple[int, str, str]:
    try:
        p = subprocess.run(argv, capture_output=True, encoding="utf-8", errors="replace")
    except OSError as e:
        raise Unreadable(f"{argv[0]} could not start: {e}") from None
    return p.returncode, p.stdout, p.stderr


#: (argv) -> (code, stdout, stderr). Tests replace it.
RUN = _run


def python_exe() -> str:
    """The full path of python.exe, as the py launcher resolves it (never py.exe itself: see the docstring)."""
    code, out, err = RUN(["py", "-c", "import sys;print(sys.executable)"])
    lines = [x.strip() for x in out.splitlines() if x.strip()]
    if code != 0 or not lines or not lines[-1].lower().endswith("python.exe"):
        raise Unreadable(f"`py -c sys.executable` gave no python.exe: {(err or out).strip()[:200]}")
    return lines[-1]


where_py = python_exe                          # the old name; the line no longer runs the launcher


def create_argv(repo: Path = REPO, py: str | None = None, ru: str | None = None) -> list[str]:
    script = Path(repo) / "tools" / "maint_run.py"
    tr = f'"{py or python_exe()}" "{script}" --scheduled'   # run_start records trigger=scheduled (maint_run.py)
    if len(tr) > 261:
        raise Unreadable(f"the /TR value is {len(tr)} chars; schtasks allows 262")
    return (["schtasks.exe", "/Create", "/TN", TASK, "/SC", "DAILY", "/ST", AT, "/TR", tr]
            + (["/RU", ru] if ru else []) + ["/F"])


def command(repo: Path = REPO, py: str | None = None, ru: str | None = None) -> str:
    return subprocess.list2cmdline(create_argv(repo, py, ru))


#: Printed, never run. Task Scheduler's DisallowStartIfOnBatteries defaults to True ("the task will not be started if
#: the computer is running on batteries", learn.microsoft.com/.../taskschd/tasksettings-disallowstartifonbatteries),
#: and a task made by schtasks /Create gets that default, so on a laptop unplugged at 10:35 the run would not start.
#: And (CAL-4, 2026-11-07) StartWhenAvailable + WakeToRun: on 2026-11-07 the PC slept through 10:35 with
#: StartWhenAvailable off, Windows logged event 153 "missed its schedule", Last Result read 0x800710E0 and no row ran.
BATTERY_PS = (f"$t = Get-ScheduledTask -TaskName '{TASK}'; $t.Settings.DisallowStartIfOnBatteries = $false; "
              f"$t.Settings.StopIfGoingOnBatteries = $false; $t.Settings.StartWhenAvailable = $true; "
              f"$t.Settings.WakeToRun = $true; Set-ScheduledTask -InputObject $t")


HISTORY_LOG = "Microsoft-Windows-TaskScheduler/Operational"
HISTORY_ON = f"wevtutil sl {HISTORY_LOG} /e:true"
HISTORY_READBACK = f"wevtutil gl {HISTORY_LOG}"


def guidance(repo: Path = REPO, py: str | None = None, ru: str | None = None) -> list[str]:
    """Every line a human pastes, in order, as text. Nothing here runs any of them."""
    py = py or python_exe()
    return [
        "# 1. Create the task (cmd.exe). Without /RU it runs as you, only while you are signed in:",
        command(repo, py),
        "#    Or, to run whether or not you are signed in, name your account with /RU; schtasks then prompts for its",
        "#    password (learn.microsoft.com/windows-server/administration/windows-commands/schtasks-create, /ru /rp):",
        command(repo, py, ru or r"%USERDOMAIN%\%USERNAME%"),     # cmd.exe expands these to your own account
        "# 2. Let it start on battery (PowerShell; Task Scheduler's default is not to start on batteries):",
        BATTERY_PS,
        f"# 3. Read it back: schtasks /Query /TN {TASK} /V /FO LIST  ('Task To Run:' must begin with a quote;",
        "#    'Power Management:' must not say 'No Start On Batteries'). Then: py tools/maint_schedule.py --check",
        "# 4. Once, ELEVATED (Run as administrator), Daniel: turn on Task Scheduler history. It is off on this",
        "#    machine, so the harness counter cannot see event 129 (the ProcessID it matches to run_start's pid)",
        "#    and reads UNKNOWN until it is on:",
        HISTORY_ON,
        "#    Read it back (expect the line 'enabled: true'):",
        HISTORY_READBACK,
    ]


def _field(text: str, name: str) -> str | None:
    for line in text.splitlines():
        if line.strip().startswith(name + ":"):
            return line.split(":", 1)[1].strip()
    return None


def _parse_time(s: str) -> dt.datetime | None:
    for f in TIME_FORMATS:
        try:
            return dt.datetime.strptime(s, f)
        except ValueError:
            pass
    return None


def check(now: dt.datetime | None = None) -> dict:
    """{"state": ok|missing|stale|unknown, "problems": [...], "why": str}. Read-only."""
    now = (now or dt.datetime.now().astimezone()).astimezone().replace(tzinfo=None)   # schtasks prints local time
    try:
        code, out, err = RUN(["schtasks", "/Query", "/TN", TASK, "/V", "/FO", "LIST"])
    except Unreadable as e:
        return {"state": "unknown", "problems": [], "why": str(e)}
    if code != 0:
        msg = (err or out).strip()
        if "cannot find" in msg.lower() or "does not exist" in msg.lower():
            return {"state": "missing", "problems": [f"scheduled task {TASK} is missing (paste the line from "
                                                      f"`py tools/maint_schedule.py`)"], "why": msg[:200]}
        return {"state": "unknown", "problems": [], "why": f"schtasks /Query exit {code}: {msg[:200]}"}
    problems = []
    tr = _field(out, "Task To Run") or ""
    if not tr.startswith('"'):
        problems.append(f"{TASK}: Task To Run is not quoted ({tr[:80]!r}); a path with spaces will break")
    if not tr.rstrip().endswith("--scheduled"):
        problems.append(f"{TASK}: Task To Run lacks --scheduled, so its runs record trigger=manual")
    last = _field(out, "Last Run Time")
    if last is None:
        return {"state": "unknown", "problems": problems, "why": "schtasks printed no 'Last Run Time' field"}
    if last in NEVER:
        problems.append(f"{TASK} has never run")
    else:
        t = _parse_time(last)
        if t is None:
            return {"state": "unknown", "problems": problems, "why": f"cannot read Last Run Time {last!r}"}
        if now - t > STALE:
            problems.append(f"{TASK} last ran {t:%Y-%m-%d %H:%M}, over {int(STALE.total_seconds() // 3600)} h ago")
    return {"state": "ok" if not problems else "stale", "problems": problems, "why": "; ".join(problems) or f"{TASK} last ran {last}"}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="read the task back; never change it")
    ap.add_argument("--repo", default=str(REPO), help="the checkout whose tools/maint_run.py the task runs")
    a = ap.parse_args(argv)
    if a.check:
        r = check()
        print(json.dumps(r, ensure_ascii=False))
        return {"ok": 0, "missing": 1, "stale": 1, "unknown": 2}[r["state"]]
    try:
        lines = guidance(Path(a.repo))
    except Unreadable as e:
        print(f"UNKNOWN: {e}")
        return 2
    print("\n".join(lines))
    print("# Nothing above has been run or registered.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
