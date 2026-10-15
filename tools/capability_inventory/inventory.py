#!/usr/bin/env python3
"""
inventory.py - what can each recurring job on this machine touch?  (build: production-boundary-v1, property 4)

Read-only. For every recurring Windows scheduled task (read with `schtasks.exe /query /fo csv /v`) and every n8n
workflow export (tools/n8n/*.json in the harness), it records what the job can reach as far as it can be INSPECTED:
push, mail, network, local network, files. Anything it could not inspect is UNKNOWN. There is no "OK" status in this
file on purpose: the best a job can be is INSPECTED-NO-FLAG, which says "nothing outward was found in the text that
was read", never "this job is safe".

STATUS (per item)
  FLAGGED          an outward capability (push, mail, network) other than the allowed two was found.
  UNKNOWN          not inspected, or inspected only in part (a binary, a missing script, a spawned program, a module
                   that could not be resolved, a node type the inventory does not know).
  INSPECTED-NO-FLAG  every file it could reach was read and nothing outward but the allowed two was found.
FLAGGED wins over UNKNOWN (a found capability is a fact; the unknown part is listed beside it).

THE ALLOWED TWO (E00569, E00570)
  * the b4him release push: evidence found in b4him's tools/release.py or tools/daily.cmd. (Its read-only check that
    the live site matches is allowed with it.) Location-based: it does not prove the file is the reviewed one; the
    release itself holds that line (see tools/release.py).
  * a self-addressed notice: mail evidence in a file carrying the marker `capability: self-addressed-notice`. The
    marker is a claim, recorded as claimed; this inventory cannot verify the recipient.

LIMITS: static text scan, one pass, depth-limited following of scripts the text names. It cannot see what a program
does at run time, what a credential allows, or anything inside a binary. Vendor/OS tasks (\\Microsoft\\..., drivers,
OneDrive, Chrome) are listed and marked UNKNOWN, not inspected.

    py tools/capability_inventory/inventory.py                 # live run; writes only under ./output
    py tools/capability_inventory/inventory.py --out some\\dir
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HARNESS = Path(r"C:\Users\dansl\Claude\Projects\Data Import\Connection")
N8N_DIR = HARNESS / "tools" / "n8n"
SELF_NOTICE_MARKER = "capability: self-addressed-notice"
MAX_DEPTH = 4
MAX_FILES = 60
MAX_BYTES = 1_000_000
COMMAND_LINE = "<task command line>"
#: the real b4him release path, anchored: a copy elsewhere (a clone, a worktree named b4him) is NOT allowed.
B4HIM_TOOLS = r"c:\users\dansl\b4him\tools"

OUTWARD = ("push", "mail", "network")

PATTERNS = {
    "push": [r"\bgit\b[^\n]*\bpush\b", r"""["']push["']""", r"\bgh\s+release\s+(?:upload|create|edit|delete)\b",
             r"\bgh\s+(?:pr|issue|repo|gist|workflow|secret)\s+(?:create|edit|merge|comment|delete|fork|run|set)\b",
             r"\bgit\b[^\n]*\bsend-email\b", r"\bscp\b", r"\brsync\b", r"\bsftp\b"],
    "mail": [r"smtplib", r"Send-MailMessage", r"\bsendmail\b", r"\bsmtp\b", r"mailto:", r"MIMEText", r"messages\.send",
             r"gmail[^\n]{0,40}send", r"\bsendgrid\b", r"\bmailgun\b", r"\bsend-email\b", r"\bgit\s+send-email\b"],
    "network": [r"urllib\.request", r"\burlopen\b", r"\brequests\.(?:get|post|put|delete|request|Session)\b",
                r"^\s*import\s+requests\b", r"\bhttpx\b", r"\baiohttp\b", r"Invoke-WebRequest", r"Invoke-RestMethod",
                r"\bcurl(?:\.exe)?\b", r"\bwget\b", r"System\.Net\.WebClient", r"\bfetch\(", r"\bsocket\.socket\b",
                r"\banthropic\b", r"\bopenai\b", r"generativelanguage", r"api\.github\.com", r"\bgh\s+api\b",
                r"\bhttp\.client\b", r"\bhttplib\b", r"\bftplib\b", r"\bsmtpd?lib\b", r"\bimport\s+socket\b", r"\bsocket\.(?:create_connection|getaddrinfo)\b",
                r"\bparamiko\b", r"\bpoplib\b", r"\bimaplib\b", r"\btelnetlib\b", r"\bxmlrpc\b", r"\bssh\b", r"\birm\b", r"\biwr\b",
                r"Start-BitsTransfer", r"Net\.Sockets", r"\bTcpClient\b", r"\bHttpClient\b", r"\bnc(?:\.exe)?\s+-"],
    "files": [r"write_text", r"write_bytes", r"""open\([^)]*["'][wax]b?\+?["']""", r"Out-File", r"Set-Content",
              r"Add-Content", r"New-Item", r"Remove-Item", r"Copy-Item", r"Move-Item", r"shutil\.", r"os\.remove",
              r"\.unlink\(", r"Tee-Object", r">>", r"(?<![-=<>])\s>\s*[\w\"'%$.\\]"],
    "dynamic": [r"Invoke-Expression", r"\biex\b", r"\beval\(", r"\bexec\(", r"\bsubprocess\b", r"os\.system",
                r"Start-Process", r"\bPopen\b", r"child_process", r"\bcmd(?:\.exe)?\s+/c\b"],
}
URL = re.compile(r"https?://([A-Za-z0-9._-]+)(?::\d+)?[^\s\"'<>)]*")
LOCAL_HOSTS = {"127.0.0.1", "localhost", "0.0.0.0", "::1"}
SCRIPT_EXT = (".ps1", ".cmd", ".bat", ".py", ".js", ".sh")
ABS_SCRIPT = re.compile(r"[A-Za-z]:\\[^\"<>|*?\r\n]*?\.(?:ps1|cmd|bat|py|js|sh)\b", re.I)
REL_SCRIPT = re.compile(r"(?<![\w:.\\/])((?:\.{1,2}[\\/])?[\w.-]+(?:[\\/][\w.-]+)*\.(?:ps1|cmd|bat|py))\b", re.I)
PY_MODULE = re.compile(r"\bpy(?:thon)?(?:\.exe)?\s+(?:-\w+\s+)*-m\s+([\w.]+)")
IMPORT = re.compile(r"^\s*(?:from\s+([\w.]+)\s+import|import\s+([\w.]+))", re.M)
NETWORK_LIBS = {"requests", "httpx", "aiohttp", "urllib3", "websockets", "paramiko", "boto3", "anthropic", "openai",
                "google"}

# ---- n8n node classes. Anything not named here is UNKNOWN.
N8N_BENIGN = {"manualTrigger", "scheduleTrigger", "cron", "errorTrigger", "set", "noOp", "if", "switch", "merge",
              "respondToWebhook", "splitInBatches", "wait", "stickyNote", "itemLists", "function", "functionItem",
              "executeWorkflowTrigger", "executeWorkflow", "filter", "aggregate", "splitOut", "sort", "limit"}
N8N_MAIL = {"emailSend", "gmail", "microsoftOutlook", "sendGrid", "mailgun", "slack", "telegram", "discord",
            "twilio", "whatsApp", "mattermost", "emailReadImap", "gmailTrigger"}
N8N_FILES = {"readWriteFile", "readBinaryFile", "writeBinaryFile", "readBinaryFiles", "moveBinaryData", "extractFromFile",
             "convertToFile", "localFileTrigger"}


# =============================================================== scheduled tasks
def read_schtasks() -> tuple[str | None, str]:
    """(csv text or None, note). Reading only: /query."""
    try:
        p = subprocess.run(["schtasks.exe", "/query", "/fo", "csv", "/v"], capture_output=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"schtasks could not run: {e}"
    if p.returncode:
        return None, f"schtasks exited {p.returncode}: {p.stderr.decode('mbcs', 'replace').strip()[:200]}"
    for enc in ("utf-8", "mbcs", "latin-1"):
        try:
            return p.stdout.decode(enc), ""
        except (UnicodeDecodeError, LookupError):
            continue
    return p.stdout.decode("latin-1", "replace"), ""


def parse_schtasks_csv(text: str) -> list[dict]:
    """One dict per task; a task with several triggers (several rows) gets its schedule types joined."""
    tasks: dict[str, dict] = {}
    header = None
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0] == "HostName":
            header = row
            continue
        if header is None or len(row) != len(header):
            continue
        rec = dict(zip(header, row))
        name = rec.get("TaskName", "")
        if name in tasks:
            tasks[name]["Schedule Type"] += " | " + rec.get("Schedule Type", "")
            continue
        tasks[name] = rec
    return list(tasks.values())


def is_recurring(schedule: str) -> bool:
    """Recurring: any trigger that fires again. A plain 'One Time Only' fires once; 'One Time Only, Hourly' is a
    one-time start that repeats, so it counts. 'N/A', 'Undefined' and 'On demand' do not."""
    for part in (p.strip() for p in schedule.split("|")):
        low = part.lower()
        if not low or low.startswith(("n/a", "undefined", "on demand")):
            continue
        if low.startswith("one time only"):
            if "," in low:
                return True
            continue
        return True
    return False


def is_vendor(name: str, command: str) -> bool:
    low = command.lower()
    # Name prefixes of OS/vendor tasks only. A user task that launches an installed program (git, python, curl) by its
    # full path is NOT vendor: its command line and the scripts it names are read like any other.
    return (name.lower().startswith(("\\microsoft\\", "\\googleuserpeh", "\\softlanding", "\\onedrive", "\\nv",
                                     "\\nvidia", "\\apple", "\\adobe", "\\google"))
            or "com handler" in low)


class Reader:
    """File access for the scan; a test supplies a dict instead of a disk."""
    def __init__(self, files: dict[str, str] | None = None):
        self.files = None if files is None else {os.path.normcase(os.path.normpath(k)): v for k, v in files.items()}

    def read(self, path: str) -> str | None:
        key = os.path.normcase(os.path.normpath(path))
        if self.files is not None:
            return self.files.get(key)
        try:
            p = Path(os.path.expandvars(path))
            if p.is_file() and p.stat().st_size <= MAX_BYTES:
                return p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            pass
        return None

    def exists(self, path: str) -> bool:
        key = os.path.normcase(os.path.normpath(path))
        return key in self.files if self.files is not None else Path(os.path.expandvars(path)).is_file()


def scan_text(text: str, path: str) -> dict:
    """What one file's text shows. Each hit: {file, line, text}. Comments are not stripped: a mention counts (an
    over-report is safer than a miss)."""
    found: dict[str, list] = {k: [] for k in (*PATTERNS, "local_network")}
    for n, line in enumerate(text.splitlines(), 1):
        for kind, pats in PATTERNS.items():
            if any(re.search(p, line, re.I) for p in pats):
                found[kind].append({"file": path, "line": n, "text": line.strip()[:160]})
        for m in URL.finditer(line):
            host = m.group(1).lower()
            if host in LOCAL_HOSTS:
                found["local_network"].append({"file": path, "line": n, "text": m.group(0)[:160]})
            elif host not in ("schemas.microsoft.com", "www.w3.org", "example.com", "example.invalid"):
                found["network"].append({"file": path, "line": n, "text": m.group(0)[:160]})
    return found


def _stdlib(name: str) -> bool:
    top = name.split(".")[0]
    return top in getattr(sys, "stdlib_module_names", set()) or top in {"__future__"}


def _resolve(ref: str, bases: list[str], reader: Reader) -> str | None:
    ref = os.path.expandvars(ref)
    cands = [ref] if os.path.isabs(ref) else [os.path.join(b, ref) for b in bases if b]
    for c in cands:
        if reader.exists(c):
            return os.path.normpath(c)
    return None


def inspect_command(command: str, start_in: str, reader: Reader) -> dict:
    """Follow the command to its script text(s). Returns {capabilities, files_scanned, unknown}."""
    caps: dict[str, list] = {k: [] for k in (*PATTERNS, "local_network")}
    scanned: list[str] = []
    unknown: list[str] = []
    queue: list[tuple[str, int]] = []
    seen: set[str] = set()
    # the command line is text the inventory read: scan it too (FLAGGED wins over UNKNOWN)
    for kind, hits in scan_text(command, COMMAND_LINE).items():
        caps[kind].extend(hits)
    for m in ABS_SCRIPT.finditer(command):
        queue.append((m.group(0), 0))
    for m in PY_MODULE.finditer(command):
        unknown.append(f"python -m {m.group(1)}: module source not located by this inventory")
    if not queue and not unknown:
        exe = command.strip().split(" ")[0].strip('"') if command.strip() else ""
        if exe.lower().endswith((".exe", ".com")) or not exe:
            unknown.append(f"a program ({exe or 'none named'}), not a script: its text was not inspected")
        else:
            unknown.append("the command names no script this inventory could read")
        return {"capabilities": caps, "files_scanned": scanned, "unknown": unknown}
    while queue:
        path, depth = queue.pop(0)
        norm = os.path.normcase(os.path.normpath(path))
        if norm in seen:
            continue
        seen.add(norm)
        if len(scanned) >= MAX_FILES:
            unknown.append(f"stopped after {MAX_FILES} files: the rest were not read")
            break
        text = reader.read(path)
        if text is None:
            unknown.append(f"script not readable: {path}")
            continue
        scanned.append(path)
        for kind, hits in scan_text(text, path).items():
            caps[kind].extend(hits)
        if caps["dynamic"] and any(h["file"] == path for h in caps["dynamic"]):
            unknown.append(f"{Path(path).name} starts other programs or evaluates text: what they do was not read")
        if depth >= MAX_DEPTH:
            unknown.append(f"depth {MAX_DEPTH} reached at {path}: scripts it names were not followed")
            continue
        here = str(Path(path).parent)
        bases = [here, start_in, str(Path(here).parent), str(HARNESS) if "Connection" in path else ""]
        refs = [m.group(0) for m in ABS_SCRIPT.finditer(text)] + [m.group(1) for m in REL_SCRIPT.finditer(text)]
        for ref in refs:
            got = _resolve(ref, bases, reader)
            if got:
                queue.append((got, depth + 1))
            elif os.path.isabs(os.path.expandvars(ref)):
                unknown.append(f"{Path(path).name} names {ref}, which is not readable")
        if path.lower().endswith(".py"):
            for m in IMPORT.finditer(text):
                mod = m.group(1) or m.group(2)
                top = mod.split(".")[0]
                if _stdlib(mod):
                    continue
                local = _resolve(f"{top}.py", [here], reader) or _resolve(os.path.join(top, "__init__.py"), [here], reader)
                if local:
                    queue.append((local, depth + 1))
                elif top in NETWORK_LIBS:
                    caps["network"].append({"file": path, "line": 0, "text": f"imports {top} (network library)"})
                else:
                    unknown.append(f"{Path(path).name} imports {top}, which was not resolved to a file")
    return {"capabilities": caps, "files_scanned": scanned, "unknown": sorted(set(unknown))}


# =============================================================== judging
def allowed_for(kind: str, hit: dict, texts: dict[str, str] | None = None) -> str | None:
    """Which of the allowed two covers this hit, or None."""
    f = hit["file"].replace("/", "\\").lower()
    if kind in ("push", "network") and re.fullmatch(re.escape(B4HIM_TOOLS) + r"\\(?:release\.py|daily\.cmd)", os.path.normpath(f).lower()):
        return "b4him release path"
    if kind == "mail" and texts and SELF_NOTICE_MARKER in texts.get(hit["file"], ""):
        return "self-addressed notice (claimed by marker, recipient not verified)"
    return None


def judge(item: dict, texts: dict[str, str] | None = None) -> dict:
    caps = item["capabilities"]
    flags, allowed = [], []
    for kind in OUTWARD:
        for hit in caps.get(kind, []):
            why = allowed_for(kind, hit, texts)
            (allowed if why else flags).append({"capability": kind, "allowed_as": why, **hit} if why else
                                               {"capability": kind, **hit})
    item["flags"], item["allowed"] = flags, allowed
    if flags:
        item["status"] = "FLAGGED"
    elif item["unknown"] or not item["inspected"]:
        item["status"] = "UNKNOWN"
    else:
        item["status"] = "INSPECTED-NO-FLAG"
    return item


def inventory_task(rec: dict, reader: Reader) -> dict:
    name, command = rec.get("TaskName", "?"), rec.get("Task To Run", "")
    item = {"kind": "scheduled_task", "name": name, "command": command,
            "enabled": rec.get("Scheduled Task State", "?") == "Enabled", "schedule": rec.get("Schedule Type", ""),
            "run_as": rec.get("Run As User", ""), "inspected": False, "files_scanned": [], "unknown": [],
            "capabilities": {k: [] for k in (*PATTERNS, "local_network")}}
    if is_vendor(name, command):
        item["unknown"].append("OS or vendor task: not inspected (what it can reach is not known to this inventory)")
        # ...but whatever its command line or named scripts show is still scanned, and FLAGGED wins.
        r = inspect_command(command, rec.get("Start In", "") if rec.get("Start In", "N/A") != "N/A" else "", reader)
        item.update(capabilities=r["capabilities"], files_scanned=r["files_scanned"],
                    unknown=sorted(set(item["unknown"] + r["unknown"])))
        return judge(item, {p: reader.read(p) or "" for p in r["files_scanned"]})
    r = inspect_command(command, rec.get("Start In", "") if rec.get("Start In", "N/A") != "N/A" else "", reader)
    item.update(capabilities=r["capabilities"], files_scanned=r["files_scanned"], unknown=r["unknown"],
                inspected=bool(r["files_scanned"]))
    texts = {p: reader.read(p) or "" for p in r["files_scanned"]}
    return judge(item, texts)


# =============================================================== n8n
def inventory_n8n(name: str, raw: str) -> dict:
    item = {"kind": "n8n_workflow", "name": name, "enabled": None, "schedule": "", "inspected": False,
            "files_scanned": [name], "unknown": [], "nodes": 0,
            "capabilities": {k: [] for k in (*PATTERNS, "local_network")}}
    try:
        wf = json.loads(raw)
    except ValueError as e:
        item["unknown"].append(f"export is not valid JSON: {e}")
        return judge(item)
    nodes = wf.get("nodes")
    if not isinstance(nodes, list):
        item["unknown"].append("export has no nodes list")
        return judge(item)
    item["inspected"] = True
    item["nodes"] = len(nodes)
    item["enabled"] = wf.get("active") if "active" in wf else None
    if item["enabled"] is None:
        item["unknown"].append("the export does not say whether the workflow is active")
    caps = item["capabilities"]
    triggers = []
    for node in nodes:
        t = str(node.get("type", ""))
        short = t.split(".")[-1]
        where = f"{name}::{node.get('name', '?')}"
        params = node.get("parameters") or {}
        hit = lambda text: {"file": where, "line": 0, "text": str(text)[:160]}          # noqa: E731
        if node.get("credentials"):
            item["unknown"].append(f"{node.get('name')}: uses stored credentials ({', '.join(node['credentials'])}); "
                                   f"what they allow was not inspected")
        if short in ("scheduleTrigger", "cron", "manualTrigger", "webhook", "errorTrigger"):
            triggers.append(short)
        if short == "webhook":
            caps["local_network"].append(hit(f"inbound webhook {params.get('path', '')}"))
        elif short == "httpRequest":
            url = str(params.get("url", ""))
            m = URL.search(url)
            if url.startswith("=") and not m:
                caps["network"].append(hit(f"HTTP request to a computed address: {url}"))
                item["unknown"].append(f"{node.get('name')}: the request address is computed at run time")
            elif m and m.group(1).lower() in LOCAL_HOSTS:
                caps["local_network"].append(hit(url))
            else:
                caps["network"].append(hit(url or "HTTP request with no address"))
        elif short in N8N_MAIL:
            caps["mail"].append(hit(f"{short} node"))
        elif short in N8N_FILES:
            caps["files"].append(hit(f"{short} node"))
        elif short == "executeCommand":
            caps["files"].append(hit("executeCommand node"))
            caps["dynamic"].append(hit(params.get("command", "")))
            item["unknown"].append(f"{node.get('name')}: runs a shell command; its effects were not read")
            for kind, hits in scan_text(str(params.get("command", "")), where).items():
                caps[kind].extend(hits)
        elif short in ("code", "function", "functionItem"):
            js = str(params.get("jsCode") or params.get("functionCode") or params.get("pythonCode") or "")
            for kind, hits in scan_text(js, where).items():
                caps[kind].extend(hits)
            if re.search(r"require\(|child_process|\beval\(|new Function\(|\$helpers\.httpRequest|fetch\(|import ", js):
                item["unknown"].append(f"{node.get('name')}: code node reaches modules or the network; not fully read")
        elif short in N8N_BENIGN:
            pass
        else:
            item["unknown"].append(f"{node.get('name')}: node type {t!r} is not known to this inventory")
    item["schedule"] = ", ".join(sorted(set(triggers))) or "no trigger found"
    item["unknown"] = sorted(set(item["unknown"]))
    return judge(item)


# =============================================================== the whole inventory
def build(schtasks_text: str | None, schtasks_note: str, n8n: dict[str, str] | None, n8n_note: str,
          reader: Reader) -> dict:
    """The inventory. A source that could not be read is recorded as UNKNOWN as a whole, never as zero items."""
    sources, items, not_recurring = {}, [], []
    if schtasks_text is None:
        sources["scheduled_tasks"] = {"status": "UNKNOWN", "note": schtasks_note or "not read"}
    else:
        tasks = parse_schtasks_csv(schtasks_text)
        for rec in tasks:
            if is_recurring(rec.get("Schedule Type", "")):
                items.append(inventory_task(rec, reader))
            else:
                not_recurring.append(rec.get("TaskName", "?"))
        sources["scheduled_tasks"] = {"status": "READ", "tasks_seen": len(tasks),
                                      "recurring": sum(i["kind"] == "scheduled_task" for i in items),
                                      "not_recurring_excluded": len(not_recurring)}
    if n8n is None:
        sources["n8n"] = {"status": "UNKNOWN", "note": n8n_note or "not read"}
    else:
        for fname in sorted(n8n):
            items.append(inventory_n8n(fname, n8n[fname]))
        sources["n8n"] = {"status": "READ", "exports": len(n8n)}
    by_status: dict[str, int] = {}
    for i in items:
        by_status[i["status"]] = by_status.get(i["status"], 0) + 1
    return {"sources": sources, "items": items, "not_recurring_excluded": not_recurring,
            "summary": {"items": len(items), "by_status": dict(sorted(by_status.items())),
                        "flagged": [i["name"] for i in items if i["status"] == "FLAGGED"],
                        "unknown": [i["name"] for i in items if i["status"] == "UNKNOWN"],
                        "sources_unread": [k for k, v in sources.items() if v["status"] != "READ"]}}


def live(n8n_dir: Path = N8N_DIR) -> dict:
    text, note = read_schtasks()
    exports, n8n_note = None, ""
    if n8n_dir.is_dir():
        exports = {p.name: p.read_text(encoding="utf-8", errors="replace") for p in sorted(n8n_dir.glob("*.json"))}
    else:
        n8n_note = f"{n8n_dir} is not a directory"
    return build(text, note, exports, n8n_note, Reader())


def render_md(inv: dict) -> str:
    s = inv["summary"]
    L = ["# Capability inventory", "",
         "Read-only static inventory. Statuses: FLAGGED, UNKNOWN, INSPECTED-NO-FLAG. There is no OK: "
         "INSPECTED-NO-FLAG means nothing outward was found in the text that was read.", "",
         f"- items: {s['items']}  by status: {s['by_status']}",
         f"- sources: {json.dumps(inv['sources'])}", "", "## Flagged", ""]
    for i in inv["items"]:
        if i["status"] == "FLAGGED":
            kinds = sorted({f['capability'] for f in i['flags']})
            L.append(f"- **{i['name']}** ({i['kind']}): {', '.join(kinds)}; e.g. {i['flags'][0]['file']}:{i['flags'][0]['line']}")
    L += ["", "## Unknown", ""] + [f"- {i['name']}: {(i['unknown'] or ['not inspected'])[0]}"
                                  for i in inv["items"] if i["status"] == "UNKNOWN"]
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(HERE / "output"), help="directory for inventory.json and INVENTORY.md")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    inv = live()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "inventory.json").write_text(json.dumps(inv, indent=1, ensure_ascii=False), encoding="utf-8", newline="\n")
    (out / "INVENTORY.md").write_text(render_md(inv), encoding="utf-8", newline="\n")
    s = inv["summary"]
    print(f"items {s['items']}  by status {s['by_status']}")
    print(f"sources {json.dumps(inv['sources'])}")
    print(f"flagged ({len(s['flagged'])}): {s['flagged']}")
    print(f"unknown ({len(s['unknown'])})")
    print(f"wrote {out}")
    return 1 if s["sources_unread"] else 0


if __name__ == "__main__":
    sys.exit(main())
