"""production-boundary-v1, property 4: the capability inventory says UNKNOWN and flags outward capability.

    py -m pytest tools/capability_inventory/tests -q

Fixtures only: no schtasks, no disk, no network. The live run is a separate, read-only command.
"""
import csv
import io
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import inventory as inv  # noqa: E402

HEADER = ["HostName", "TaskName", "Next Run Time", "Status", "Logon Mode", "Last Run Time", "Last Result", "Author",
          "Task To Run", "Start In", "Comment", "Scheduled Task State", "Idle Time", "Power Management",
          "Run As User", "Delete Task If Not Rescheduled", "Stop Task If Runs X Hours and X Mins", "Schedule",
          "Schedule Type"]


def tasks_csv(*rows):
    """rows: (TaskName, Task To Run, Schedule Type[, state])"""
    out = io.StringIO()
    w = csv.writer(out)
    for i, (name, cmd, sched, *state) in enumerate(rows):
        w.writerow(HEADER)                                   # schtasks repeats the header per folder
        rec = dict.fromkeys(HEADER, "N/A")
        rec.update({"HostName": "PC", "TaskName": name, "Task To Run": cmd, "Schedule Type": sched,
                    "Scheduled Task State": state[0] if state else "Enabled", "Run As User": "dansl"})
        w.writerow([rec[h] for h in HEADER])
    return out.getvalue()


B4 = r"C:\Users\dansl\b4him"
H = r"C:\Users\dansl\Harness"
FILES = {
    # the b4him release path: pushes, and re-fetches its own site. Allowed, location-based.
    B4 + r"\tools\daily.cmd": "cd /d C:\\Users\\dansl\\b4him\npy tools\\release.py --apply --push --verify-live\n",
    B4 + r"\tools\release.py": 'import subprocess\nsubprocess.run(["git","push"])\nimport urllib.request\n'
                                'urllib.request.urlopen("https://b4him.com/x")\n',
    # a job that posts to an API
    H + r"\poster.ps1": 'Invoke-RestMethod -Uri "https://api.vendor.example.org/v1/things" -Method Post\n',
    # a job that sends mail, without and with the self-notice marker
    H + r"\mailer.ps1": 'Send-MailMessage -To "someone@else.example" -Subject hi\n',
    H + r"\notice.ps1": "# capability: self-addressed-notice\nSend-MailMessage -To $env:ME -Subject 'pitches waiting'\n",
    # a wrapper that hides a push one script down
    H + r"\wrapper.ps1": '& "C:\\Users\\dansl\\Harness\\deep.ps1"\n',
    H + r"\deep.ps1": "git -C C:\\somewhere push origin main\n",
    # a quiet local job
    H + r"\quiet.ps1": 'Get-Content C:\\Users\\dansl\\Harness\\a.txt | Out-Null\n',
    # a job that starts other programs: only partly readable
    H + r"\spawner.ps1": "Start-Process -FilePath $env:SOMETHING\n",
}
TASKS = tasks_csv(
    (r"\b4him-daily-release", rf"cmd.exe /c {B4}\tools\daily.cmd >> log 2>&1", "Daily"),
    (r"\poster", rf"powershell.exe -File {H}\poster.ps1", "Daily"),
    (r"\mailer", rf"powershell.exe -File {H}\mailer.ps1", "Weekly"),
    (r"\notice", rf"powershell.exe -File {H}\notice.ps1", "Weekly"),
    (r"\wrapper", rf"powershell.exe -File {H}\wrapper.ps1", "One Time Only, Hourly"),
    (r"\quiet", rf"powershell.exe -File {H}\quiet.ps1", "Daily"),
    (r"\spawner", rf"powershell.exe -File {H}\spawner.ps1", "Daily"),
    (r"\missing-script", rf"powershell.exe -File {H}\not_there.ps1", "Daily"),
    (r"\a-binary", r"C:\Tools\thing.exe --serve", "At logon time"),
    (r"\Microsoft\Windows\Defrag\ScheduledDefrag", r"%windir%\system32\defrag.exe -c", "Daily"),
    (r"\one-shot", rf"powershell.exe -File {H}\quiet.ps1", "One Time Only"),
    (r"\on-demand", rf"powershell.exe -File {H}\quiet.ps1", "N/A"),
)

N8N = {
    "local_only.json": json.dumps({"name": "local", "active": False, "nodes": [
        {"name": "Run", "type": "n8n-nodes-base.manualTrigger", "parameters": {}},
        {"name": "Ask", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "http://127.0.0.1:8787/job/x"}},
        {"name": "Report", "type": "n8n-nodes-base.code", "parameters": {"jsCode": "return [{json:{ok:true}}];"}}]}),
    "outward.json": json.dumps({"name": "out", "active": True, "nodes": [
        {"name": "Run", "type": "n8n-nodes-base.scheduleTrigger", "parameters": {}},
        {"name": "Post", "type": "n8n-nodes-base.httpRequest", "parameters": {"url": "https://hooks.vendor.example.org/abc"}}]}),
    "mailing.json": json.dumps({"name": "mail", "active": True, "nodes": [
        {"name": "Send", "type": "n8n-nodes-base.emailSend", "parameters": {}}]}),
    "novel.json": json.dumps({"name": "novel", "active": True, "nodes": [
        {"name": "Mystery", "type": "n8n-nodes-base.somethingNew", "parameters": {}}]}),
    "shell.json": json.dumps({"name": "sh", "active": True, "nodes": [
        {"name": "Do", "type": "n8n-nodes-base.executeCommand", "parameters": {"command": "echo hi"}}]}),
    "broken.json": "{ not json",
}


def run():
    return inv.build(TASKS, "", N8N, "", inv.Reader(FILES))


def by_name(result):
    return {i["name"]: i for i in result["items"]}


def test_uninspected_is_unknown_and_outward_capabilities_are_flagged():
    r = run()
    it = by_name(r)

    # ---- only recurring tasks are inventoried; the rest are listed as excluded, not silently dropped
    assert r["sources"]["scheduled_tasks"]["tasks_seen"] == 12
    assert set(r["not_recurring_excluded"]) == {r"\one-shot", r"\on-demand"}
    assert r"\wrapper" in it                                    # "One Time Only, Hourly" repeats, so it counts

    # ---- nothing is ever called OK; the only statuses are the three
    assert {i["status"] for i in r["items"]} <= {"FLAGGED", "UNKNOWN", "INSPECTED-NO-FLAG"}

    # ---- not inspected means UNKNOWN: a missing script, a binary, an OS task, a bad export, an unknown node type
    for name in (r"\missing-script", r"\a-binary", r"\Microsoft\Windows\Defrag\ScheduledDefrag", "broken.json",
                 "novel.json", "shell.json"):
        assert it[name]["status"] == "UNKNOWN", (name, it[name]["status"], it[name]["unknown"])
        assert it[name]["unknown"]
    assert not it[r"\missing-script"]["inspected"] and not it[r"\a-binary"]["inspected"]
    # a program that starts other programs is only partly read
    assert it[r"\spawner"]["status"] == "UNKNOWN" and it[r"\spawner"]["inspected"]
    # an n8n export that does not say whether it is active is UNKNOWN on that point, even if its nodes are local
    assert it["local_only.json"]["status"] == "UNKNOWN" or it["local_only.json"]["enabled"] is False

    # ---- outward capabilities other than the allowed two are flagged
    assert it[r"\poster"]["status"] == "FLAGGED" and it[r"\poster"]["flags"][0]["capability"] == "network"
    assert it[r"\mailer"]["status"] == "FLAGGED" and it[r"\mailer"]["flags"][0]["capability"] == "mail"
    assert it["outward.json"]["status"] == "FLAGGED"
    assert it["mailing.json"]["status"] == "FLAGGED"
    # a push hidden one script down is found by following the script
    wrapper = it[r"\wrapper"]
    assert wrapper["status"] == "FLAGGED" and wrapper["flags"][0]["capability"] == "push"
    assert wrapper["flags"][0]["file"].endswith("deep.ps1")

    # ---- the allowed two are recorded as allowed, not flagged, and say why
    b4 = it[r"\b4him-daily-release"]
    assert b4["flags"] == [] and b4["status"] != "FLAGGED"
    assert {a["capability"] for a in b4["allowed"]} == {"push", "network"}
    assert all(a["allowed_as"] == "b4him release path" for a in b4["allowed"])
    notice = it[r"\notice"]
    assert notice["flags"] == [] and notice["allowed"][0]["allowed_as"].startswith("self-addressed notice")
    assert "claimed" in notice["allowed"][0]["allowed_as"]          # a claim, not a verification
    # the same capability from a file outside b4him's release path is not allowed
    assert it[r"\wrapper"]["allowed"] == []

    # ---- a quiet, fully-read job is INSPECTED-NO-FLAG, which is not "safe"
    assert it[r"\quiet"]["status"] == "INSPECTED-NO-FLAG" and it[r"\quiet"]["unknown"] == []
    # local-only network is recorded but not outward
    assert it["local_only.json"]["capabilities"]["local_network"] and not it["local_only.json"]["flags"]

    # ---- the summary counts add up and name the flagged and unknown
    s = r["summary"]
    assert s["items"] == len(r["items"]) == sum(s["by_status"].values())
    assert set(s["flagged"]) == {n for n, i in it.items() if i["status"] == "FLAGGED"}
    assert r"\poster" in s["flagged"] and r"\b4him-daily-release" not in s["flagged"]
    assert r"\a-binary" in s["unknown"]


def test_a_source_that_could_not_be_read_is_unknown_as_a_whole_never_an_empty_ok():
    r = inv.build(None, "schtasks could not run: access denied", None, "no such directory", inv.Reader({}))
    assert r["items"] == []
    assert r["sources"]["scheduled_tasks"]["status"] == "UNKNOWN" and r["sources"]["n8n"]["status"] == "UNKNOWN"
    assert r["summary"]["sources_unread"] == ["scheduled_tasks", "n8n"]
    assert "OK" not in json.dumps(r["summary"]["by_status"])


def test_recurring_rules_and_csv_parsing():
    assert inv.is_recurring("Daily") and inv.is_recurring("At logon time") and inv.is_recurring("One Time Only, Minute")
    assert inv.is_recurring("One Time Only | Weekly")
    assert not inv.is_recurring("One Time Only") and not inv.is_recurring("N/A") and not inv.is_recurring("Undefined")
    two = tasks_csv(("\\t", "x.cmd", "Daily"), ("\\t", "x.cmd", "At logon time"))
    parsed = inv.parse_schtasks_csv(two)
    assert len(parsed) == 1 and "Daily" in parsed[0]["Schedule Type"] and "At logon" in parsed[0]["Schedule Type"]


def test_the_inventory_writes_nothing_but_its_own_output(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(inv, "live", lambda: run())
    assert inv.main(["--out", str(tmp_path / "out")]) == 0
    assert sorted(p.name for p in (tmp_path / "out").iterdir()) == ["INVENTORY.md", "inventory.json"]
    assert "flagged" in capsys.readouterr().out


def test_second_release_copy_command_line_and_stdlib_siblings():
    """D1/D2/D3: a copy of the release path is flagged, the task command line is scanned, and the stdlib/CLI
    network siblings are flagged."""
    D = r"C:\Users\dansl\Downloads\b4him\tools"
    real = r"C:\Users\dansl\b4him\tools"
    assert inv.allowed_for("push", {"file": real + r"\release.py"}) == "b4him release path"
    assert inv.allowed_for("push", {"file": real.upper() + "\\DAILY.CMD"}) == "b4him release path"
    assert inv.allowed_for("push", {"file": D + r"\release.py"}) is None
    assert inv.allowed_for("push", {"file": r"C:\x" + real[2:] + r"\release.py"}) is None
    r = inv.inspect_command('powershell.exe -Command "git push origin main"', "", inv.Reader({}))
    assert r["capabilities"]["push"] and r["unknown"]
    for text in ("import http.client", "import ftplib", "gh release upload v1 x.zip", "git send-email HEAD~1",
                 "import socket", "scp a b:c", "rsync -a x y", "import paramiko", "Invoke-WebRequest http://x.invalid",
                 "gh pr create"):
        caps = inv.scan_text(text, "f")
        assert any(caps[k] for k in inv.OUTWARD), text
