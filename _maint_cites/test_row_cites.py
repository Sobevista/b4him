"""The harness scope lock's cite tests for the 28 b4him maintenance-baseline rows (C1 .. A4).

This file lives in _maint_cites/, not tools/: the gate lints every conftest.py on a cite's directory chain, whole, and
tools/conftest.py is the release tests' (it imports release and binding). The tools are imported by module name (the
gate's broker serves them; run locally with PYTHONPATH=tools). Jekyll never serves a folder that starts with "_".

Each row has a CLEAN-WORLD fixture (everything right: the row's quiet outcome) and one cite per FACET of its calendar
task (each thing the row must catch). Every cite names its row as a literal, drives the row through
`maint_run.py --row <id>` (in process: run.RUN calls the row's tool's own main(); only the network and the clock are
faked) and asserts on the receipt that run wrote to the receipt log under a temporary MAINT_DIR: produced at run time
by the tools, never written by the test and never a committed file. Each cite imports its row's tool inside the body
and `receipt()` checks that module is the one maint_run.py runs for the row. Hand closes (judge, human, confirm, witness) are
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
from pathlib import Path

TZ = dt.timezone(dt.timedelta(hours=-5))


def tools_dir():
    """The b4him tools/ directory, as maint_run.py (a shared tool) knows it."""
    import maint_run as run
    return run.TOOLS_DIR


def repo_root():
    return tools_dir().parent


def pa11y_recorded():
    """A pa11y-ci --json report recorded from a real run of M1 over this site (2026-10-31): 7 issues on 4 pages."""
    return (tools_dir() / "_maint_fixtures" / "pa11y-ci" / "report-2026-10-31.json").read_text(encoding="utf-8")


class Clock:
    """The fake clock: `set(...)` a local wall time (TZ), `now()` the UTC instant maint_receipt.now_utc returns."""
    t = None

    def set(self, *when):
        self.t = dt.datetime(*when, tzinfo=TZ)
        return self

    def now(self):
        return self.t.astimezone(dt.timezone.utc)


def world(monkeypatch, tmp_path, *when, watch=None):
    """A temporary .maint, a fixed clock and zone, no network. `watch` (maint_watch, for its own rows) gets a
    scheduler stub: the real one asks Task Scheduler."""
    import maint_receipt as mr
    md = tmp_path / ".maint"
    monkeypatch.setenv("MAINT_DIR", str(md))
    for v in ("MAINT_RUN_ID", "MAINT_TRIGGER", "MAINT_HEARTBEAT_URL", "UPTIMEROBOT_API_KEY", "CRUX_API_KEY",
              "MAINT_OBSERVATORY_OK"):
        monkeypatch.delenv(v, raising=False)
    clock = Clock().set(*(when or (2026, 11, 2, 11)))
    monkeypatch.setattr(mr, "now_utc", clock.now)
    monkeypatch.setattr(mr, "LOCAL_TZ", TZ)
    if watch is not None:
        monkeypatch.setattr(watch, "SCHEDULE_CHECK", lambda now: {"state": "ok", "problems": [], "why": "ok"})

    def no_net(*a, **k):
        raise AssertionError("a cite test opened a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_net)
    monkeypatch.setattr(socket, "getaddrinfo", no_net)
    return md, clock


def log_lines():
    """Every readable line of the receipt log (receipts and run markers), even when the log also holds corrupt lines a
    test planted on purpose. Read only."""
    import maint_receipt as mr
    p = mr.maint_dir() / mr.LOG_NAME
    out = []
    if p.exists():
        for raw in p.read_bytes().decode("utf-8", "replace").split("\n"):
            try:
                e = json.loads(raw)
            except ValueError:
                continue
            if isinstance(e, dict):
                out.append(e)
    return out


def receipts_any():
    """Every readable receipt line (run markers are not receipts)."""
    return [e for e in log_lines() if "kind" not in e]


def snap(row):
    """The row's receipt lines, as the tools wrote them to the receipt log (read only: the test writes no receipt)."""
    return [e for e in receipts_any() if e.get("row") == row]


#: row -> {"run_id", "start"} of the LAST drive of that row: receipt() accepts only that run's lines.
DRIVES: dict = {}


def drive(row, tool, *pre):
    """`maint_run.py --row <row>`, with maint_run's child run in process (in_process: `tool`, with `pre` args first,
    unless the test already replaced RUN). Returns maint_run's exit code. Records the run this drive started (its
    run_start marker's run_id, and the clock before it began), so receipt() reads only what THIS run wrote."""
    import maint_receipt as mr
    import maint_run as run
    start = mr.now_utc().replace(microsecond=0)
    seen = {e.get("run_id") for e in log_lines() if e.get("kind") == "run_start"}
    saved = run.RUN
    if saved is run.run_process:
        run.RUN = run.in_process(tool, *pre)          # maint_run checks `tool` IS the script it runs for the row
    try:
        code = run.main(["--row", row])
    finally:
        run.RUN = saved
    new = [e.get("run_id") for e in log_lines() if e.get("kind") == "run_start" and e.get("run_id") not in seen]
    if len(new) != 1 or not new[0]:
        raise AssertionError(f"drive({row}): expected one new run_start marker, found {len(new)}")
    DRIVES[row] = {"run_id": new[0], "start": start}
    return code


def close(row, watch, *argv):
    """A person's act through maint_watch (`watch`, imported by a maint_watch row's test): judge / human / confirm /
    witness. Returns (exit code, the row's last line before the close, its last line after) from the receipt log."""
    before = snap(row)
    code = watch.main(list(argv))
    after = snap(row)
    return code, (before[-1] if before else {}), (after[-1] if after else {})


def hand_close_ok(prev, rec):
    """The counter's HAND CLOSE rule: the close follows an awaiting SKIP, carries its evidence, written by maint_watch."""
    return (prev.get("outcome") == "SKIP" and str(prev.get("why", "")).startswith("awaiting ")
            and bool(rec.get("evidence")) and rec.get("evidence") == prev.get("evidence")
            and rec.get("tool") == "tools/maint_watch.py")


def runner_identity(row, tool):
    """Check `tool` (the module the test imported) declares as its TOOL exactly maint_run's RUNNERS script for the row
    (maint_run.in_process then refuses any module whose FILE is not that script). -> the receipt `tool` field that
    module writes (tools/<script>)."""
    import maint_receipt as mr
    import maint_run as run
    want = "tools/" + run.RUNNERS[row][0]
    got = mr.tool_path(tool.TOOL)
    if got != want:
        raise AssertionError(f"row {row} is run by {want}, not {got}")
    return want


def receipt(row, tool):
    """The row's LAST receipt of the row's LAST drive ({} when that run wrote none): a line carrying that drive's
    run_id, stamped at or after the drive's start, and written by the row's own runner module (`tool`, checked by
    runner_identity) or by maint_run.py itself (the UNKNOWN it writes when the runner gave no usable receipt).
    A line from another run, an older line, or a line from any other tool is never this row's answer. Nothing here
    writes; the log is maint_receipt's, written by the run."""
    import maint_run as run
    own = runner_identity(row, tool)
    d = DRIVES.get(row)
    if d is None:
        raise AssertionError(f"receipt({row}): the row was never driven through maint_run.py in this test")

    def this_run(e):
        try:
            at = dt.datetime.fromisoformat(str(e.get("at")))
        except ValueError:
            return False
        return (e.get("row") == row and e.get("run_id") == d["run_id"] and at.tzinfo is not None
                and at >= d["start"] and e.get("tool") in (own, run.RUNNER))
    mine = [e for e in receipts_any() if this_run(e)]
    return mine[-1] if mine else {}


def run_end(row):
    """The run_end marker of the row's last drive (maint_run's last write: its exit code and rows_failed)."""
    d = DRIVES.get(row)
    ends = [e for e in log_lines() if e.get("kind") == "run_end" and d and e.get("run_id") == d["run_id"]]
    return ends[-1] if ends else {}


def drive_real(row):
    """`maint_run.py --row <row>` with maint_run's REAL RUN (run_process: a child process). Records the drive."""
    import maint_receipt as mr
    import maint_run as run
    start = mr.now_utc().replace(microsecond=0)
    seen = {e.get("run_id") for e in log_lines() if e.get("kind") == "run_start"}
    code = run.main(["--row", row])
    new = [e.get("run_id") for e in log_lines() if e.get("kind") == "run_start" and e.get("run_id") not in seen]
    if len(new) != 1 or not new[0]:
        raise AssertionError(f"drive_real({row}): expected one new run_start marker, found {len(new)}")
    DRIVES[row] = {"run_id": new[0], "start": start}
    return code


def closed(row, tool):
    """The row's LAST line after a person's close through maint_watch ({} when none): stamped at or after the row's
    last drive, written by tools/maint_watch.py, outside any run (a hand act carries run_id null). `tool` is checked
    to be the row's own runner module, so the cite names the row's tool."""
    runner_identity(row, tool)
    d = DRIVES.get(row)
    if d is None:
        raise AssertionError(f"closed({row}): the row was never driven through maint_run.py in this test")

    def hand(e):
        try:
            at = dt.datetime.fromisoformat(str(e.get("at")))
        except ValueError:
            return False
        return (e.get("row") == row and e.get("run_id") is None and at.tzinfo is not None and at >= d["start"]
                and e.get("tool") == "tools/maint_watch.py")
    mine = [e for e in receipts_any() if hand(e)]
    return mine[-1] if mine else {}


def evidence(rec):
    """The evidence file a receipt names (`.maint/...`), as the tool wrote it, parsed as JSON."""
    import maint_receipt as mr
    rel = str(rec["evidence"])
    return json.loads((mr.maint_dir() / rel[len(".maint/"):]).read_text(encoding="utf-8"))


def evidence_text(rec):
    """The evidence file a receipt names, as the tool wrote it, as text."""
    import maint_receipt as mr
    rel = str(rec["evidence"])
    return (mr.maint_dir() / rel[len(".maint/"):]).read_text(encoding="utf-8")


def findings(row):
    import maint_receipt as mr
    return [f for f in mr.read_findings() if f.get("row") == row]


# ------------------------------------------------------------------ small fixtures (no test_maint_* import)
class Proc:
    """What a tool's run_cmd returns: returncode, stdout, stderr."""
    returncode, stdout, stderr = 0, "", ""


def proc(returncode=0, stdout="", stderr=""):
    p = Proc()
    p.returncode, p.stdout, p.stderr = returncode, stdout, stderr
    return p


def contrast_row(sel, ratio, color="rgb(119, 119, 119)", bg="rgb(136, 136, 136)", over=None):
    """One contrast-audit.js row (as tools/test_maint_quality._row)."""
    return {"selector": sel, "ratio": ratio, "color": color, "background": bg, "large": False,
            "overlaySource": over, "overImage": bool(over), "translucentText": False}


def lhr(path, lcp, cls, tbt):
    """One Lighthouse result (as tools/test_maint_quality._lhr)."""
    return {"requestedUrl": f"http://localhost:5555{path}", "audits": {
        "largest-contentful-paint": {"numericValue": lcp}, "cumulative-layout-shift": {"numericValue": cls},
        "total-blocking-time": {"numericValue": tbt}}}


def crux_body(lcp=1800, inp=150, cls="0.05"):
    """A CrUX record answer (as tools/test_maint_quality._crux)."""
    m = {}
    for k, v in (("largest_contentful_paint", lcp), ("interaction_to_next_paint", inp), ("cumulative_layout_shift", cls)):
        if v is not None:
            m[k] = {"percentiles": {"p75": v}}
    return {"record": {"key": {"origin": "https://b4him.com"}, "metrics": m,
                       "collectionPeriod": {"lastDate": {"year": 2026, "month": 10, "day": 29}}}}


def canned_scanners():
    """The calibration scanners' recorded answers (as tools/test_maint_quality._scanners)."""
    return {
        "release.broken_links": lambda: {"broken-link/index.html": ["broken-link"], "index.html": []},
        "linkcheck.py": lambda: {"broken-link/index.html": ["x"]},
        "pa11y-ci": lambda: {"missing-alt/index.html": ["pa11y:image-alt"], "low-contrast/index.html": ["pa11y:G18"],
                             "index.html": []},
        "contrast-audit.js": lambda: {"low-contrast/index.html": ["contrast:p.planted-low-contrast:1.2"], "index.html": []},
        "headers_tls_check.py": lambda: {"mixed-content/index.html": ["m"]},
        "people_registry": lambda: {"forbidden-token/index.html": ["known-outside-rule:FIXTURE-CLIENT:Zorblax"],
                                    "index.html": []},
        "maint_pages.py": lambda: {"forbidden-token/index.html": ["maint_pages.py:Zorblax"]},
    }


def good_dns(h):
    """The DNS answers of a correctly pointed b4him.com (`h` is headers_tls_check; as tools/test_maint_edge.GOOD)."""
    return {
        ("b4him.com", "A"): ("ok", sorted(h.PAGES_A)),
        ("b4him.com", "AAAA"): ("ok", sorted(h.PAGES_AAAA)),
        ("b4him.com", "CNAME"): ("noanswer", []),
        ("www.b4him.com", "CNAME"): ("ok", ["sobevista.github.io."]),
        ("_github-pages-challenge-sobevista.b4him.com", "TXT"): ("ok", ["s3cr3t-looking-value"]),
    }


PAGES_OK = {"cname": "b4him.com", "https_enforced": True, "status": "built", "build_type": "legacy"}


def crc32(data):
    """CRC-32 (the PNG chunk check), in plain Python."""
    c = 0xFFFFFFFF
    for b in data:
        c ^= b
        for _ in range(8):
            c = (c >> 1) ^ (0xEDB88320 if c & 1 else 0)
    return c ^ 0xFFFFFFFF


def png(path, w, h):
    """A PNG signature + IHDR of w x h (all maint_human.check_tiles reads), as tools/test_maint_human.png."""
    import struct
    raw = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + raw
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(raw)) + chunk + struct.pack(">I", crc32(chunk)))
    return path


def fake_capture(mh, problems=()):
    """maint_human's CAPTURE, faked: right-sized tiles for every page and width (`mh` is maint_human)."""
    def cap(repo, rels, out):
        res = {}
        for r in rels:
            for w in mh.WIDTHS:
                plan = mh.tile_plan(2500)
                names = [png(out / f"{r.replace('/', '-')}_{w}_{i}.png", w * 2, h * 2).name
                         for i, (_, h) in enumerate(plan)]
                res.setdefault(r, {})[w] = {"tiles": names, "height": 2500, "problems": list(problems)}
        return res
    return cap


# ------------------------------------------------------------------ a throwaway b4him-shaped site (maint_pages rows)
D11 = ("## D11 \u2014 Publishing the Lessons: curated + genericized. LOCKED 2026-07-21\n\n"
       "- **Genericization is a hard rule, applied consistently.** Product/project names \u2192 generic: Zorblax \u2192 \"a tool "
       "I built\". Collaborator \u2192 generic: Quendrith \u2192 \"a teammate\". `Vexmoor-rig` \u2192 \"a machine\".\n\n"
       "## D12 \u2014 Later. LOCKED 2026-09-01\n\nText.\n\n## D13 \u2014 End\n")
CLEAN = ("<html><head><title>{t}</title></head><body><main><p>i write here about my work and what i learn.</p>{b}"
         "</main></body></html>")


def page(title, body=""):
    return CLEAN.format(t=title, b=body)


def local_names(repo, names=("Quillon",), role="client"):
    (repo / "data" / "people_names.local.json").write_text(
        json.dumps({"people": [{"label": "PERSON-X", "role": role, "names": list(names)}]}), encoding="utf-8")


def site_repo(tool, tmp_path, files=None, queue=None, decisions=None):
    """A throwaway b4him-shaped git repo, committed with the row's own tool's public `git(repo, *args)` (maint_pages
    and linkcheck each define one: the test starts no process itself). Same shape as tools/test_maint_pages.make_repo."""
    repo = tmp_path / "site"
    (repo / "data").mkdir(parents=True)
    for f in ("people_registry.json", "common_first_names.txt"):
        (repo / "data" / f).write_bytes((repo_root() / "data" / f).read_bytes())
    base = {
        ".gitignore": ".maint/\ndata/people_names.local.json\ndata/forbidden_tokens.local.json\n",
        "CNAME": "example.invalid\n",
        "DECISIONS.md": decisions or D11,
        "index.html": page("Home", '<a href="/lessons/">Lessons</a>'),
        "lessons/index.html": page("Lessons", '<a href="/lessons/find-your-door/">Take the quiz</a>'
                                   '<h2 id="lessons-list">Tier One</h2><a class="mod" href="/lessons/alpha/">Alpha</a>'),
        "lessons/find-your-door/index.html": page("Door", "<script>x='<a href=\"/lessons/#lessons-list\">Start</a>'"
                                                  "</script>"),
        "lessons/alpha/index.html": page("Alpha", "<p>a plain lesson about checking the work, by hand, each time.</p>"),
        "_hidden/secret.html": page("Hidden", "<p>Zorblax</p>"),
    }
    base.update(files or {})
    for rel, text in base.items():
        if text is None:
            continue
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    rows = queue if queue is not None else [
        {"id": "C-1", "title": "Alpha", "stage": "PUBLISHED", "page": "lessons/alpha/index.html",
         "published": "2026-10-20"},
        {"id": "P-1", "title": "Headings", "stage": "PUBLISHED", "kind": "patch", "published": "2026-10-20",
         "files": ["index.html", "lessons/index.html", "lessons/find-your-door/index.html"]},
        {"id": "P-2", "title": "Shelf", "stage": "DRAFTED", "kind": "patch", "drafted": "2026-10-20",
         "since": "2026-10-20", "drafted_by": "site maintainer agent"},
    ]
    (repo / "production_queue.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8",
                                                 newline="\n")
    who = ("-c", "user.name=t", "-c", "user.email=t@example.invalid")
    for args in (("init", "-q"), ("add", "-A"), (*who, "commit", "-q", "-m", "fixture")):
        code, out = tool.git(repo, *args)
        if code:
            raise AssertionError(f"git {args[-1]} failed in the fixture repo: {out}")
    return repo


def pages_repo(monkeypatch, mp, tmp_path, files=None, names=False, queue=None, decisions=None):
    """The fixture site as maint_pages' tree (`mp` is maint_pages, imported by the test)."""
    repo = site_repo(mp, tmp_path, files, queue, decisions)
    if names:
        local_names(repo)
    monkeypatch.setattr(mp, "REPO", repo)
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
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, MONS)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "PASS" and "last 7 days uptime" in rec["why"]


def test_cite_C1_home_page_must_be_monitored(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], url="https://example.org/"), MONS[1]])
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "no monitor watches https://b4him.com/" in rec["why"]


def test_cite_C1_a_lesson_must_be_monitored(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [MONS[0], dict(MONS[1], url="https://b4him.com/about/")])
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "no monitor watches one lesson URL" in rec["why"]


def test_cite_C1_a_down_monitor_is_s1(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], status=9), MONS[1]])
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("C1")] == ["S1"]


def test_cite_C1_no_key_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no UPTIMEROBOT_API_KEY")


# ================================================================== D1 release run watch
LINE = {"at": "2026-11-02T13:30:01+00:00", "date": "2026-11-02", "mode": "apply", "lane": "content",
        "outcome": "PUBLISHED"}


def _release(monkeypatch, tmp_path, *lines):
    import maint_watch as mw
    monkeypatch.setattr(mw, "REPO", tmp_path)
    (tmp_path / "release_log.jsonl").write_text("".join(json.dumps(x) + "\n" for x in lines), encoding="utf-8")


def test_cite_D1_clean_world(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, LINE)
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/maint_watch.py"


def test_cite_D1_no_line_by_10_30_is_missing(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, date="2026-11-01"))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "MISSING" in rec["why"]


def test_cite_D1_a_failed_release_is_findings(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, outcome="FAIL"))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "FAIL" in rec["why"]


def test_cite_D1_before_the_cutoff_is_pending(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 2, 9, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, date="2026-11-01"))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "10:30 has not passed" in rec["why"]


# ================================================================== D2 calendar watch
def _table(monkeypatch, tmp_path, *ids):
    import maint_watch as mw
    real = {r["id"]: r for r in json.loads((tools_dir() / "maint_rows.json").read_text(encoding="utf-8"))["rows"]}
    small = tmp_path / "rows.json"
    small.write_text(json.dumps({"epoch": "2026-10-20", "rows": [real[i] for i in ids]}), encoding="utf-8")
    monkeypatch.setattr(mw, "ROWS_FILE", small)


def test_cite_D2_clean_world(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2", "M4")
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    mr.write_receipt("M4", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "PASS" and "none UNKNOWN" in rec["why"]


def test_cite_D2_an_overdue_row_is_listed(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D1", "D2")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "D1 (no receipt ever" in rec["why"]


def test_cite_D2_a_stuck_unknown_is_an_alarm(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 2, 7, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2")
    mr.write_receipt("D1", "UNKNOWN", why="no release log", tool="maint_watch.py")
    clock.set(2026, 11, 2, 9, 30)
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "D1 STUCK" in rec["why"]


def test_cite_D2_an_unjudged_assist_row_goes_overdue(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D2", "M4")
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: pack", tool="maint_pages.py")
    clock.set(2026, 12, 7, 11)
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: pack", tool="maint_pages.py")
    clock.set(2026, 12, 11, 0, 1)
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
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
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    calls = _hb(monkeypatch)
    _d1d2()
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "PASS" and calls == ["https://hc-ping.example.invalid/x"]


def test_cite_D3_an_unknown_watch_pings_fail(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    calls = _hb(monkeypatch)
    _d1d2("UNKNOWN", "cannot judge")
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "PASS" and calls[-1].endswith("/fail") and "D2 UNKNOWN" in rec["why"]


def test_cite_D3_a_new_alarm_fails_once_then_stands(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    calls = _hb(monkeypatch)
    _table(monkeypatch, tmp_path, "D1", "D2", "W1")
    for day in (2, 3):
        clock.set(2026, 11, day, 10)
        import maint_receipt as mr
        mr.write_receipt("D1", "PASS", why="ok", tool="maint_watch.py")
        clock.set(2026, 11, day, 10, 35)
        mw.run_d2(mw.local(clock.now()))
        drive("D3", maint_watch)
        rec = receipt("D3", maint_watch)
        assert rec["outcome"] == "PASS" and calls[-1].endswith("/fail") == (day == 2)


def test_cite_D3_no_url_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _d1d2()
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "no MAINT_HEARTBEAT_URL")


# ================================================================== W1 / W1b link check, Wayback
#: The real linkcheck.Fetcher class, kept once (a test replaces linkcheck.Fetcher with a factory).
REAL: dict = {}


class Answer:
    """A urllib response, faked: code, url, body."""
    code, url, body = 200, "", b""

    def getcode(self):
        return self.code

    def geturl(self):
        return self.url

    def read(self, n=-1):
        return self.body

    def close(self):
        return None


def _net(monkeypatch, dead=(), wayback=True):
    import urllib.error

    import linkcheck as lc
    import maint_receipt as mr
    real = REAL.setdefault("Fetcher", lc.Fetcher)            # the class itself, never a factory an earlier call set
    calls = []

    def Resp(code, url, body=b""):                            # noqa: N802 - reads like the class it fakes
        r = Answer()
        r.code, r.url, r.body = code, url, body
        return r

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
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/linkcheck.py" and "23 pages" in rec["why"]


def test_cite_W1_internal_link_case_sensitive(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": '<a href="../Lessons/alpha/">x</a>'})
    _net(monkeypatch)
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "FINDINGS" and "1 broken internal" in rec["why"]


def test_cite_W1_every_page_not_only_touched(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"zz/deep/index.html": '<a href="../nowhere/">x</a>'})
    _net(monkeypatch)
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "FINDINGS" and "1 broken internal" in rec["why"]


def test_cite_W1_dead_outbound_link(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "FINDINGS" and "1 dead" in rec["why"]


def test_cite_W1_outbound_answers_are_cached(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    calls = _net(monkeypatch)
    drive("W1", linkcheck, "--repo", str(repo))
    first = len(calls)
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "PASS" and first >= 1 and len(calls) == first      # the second week fetched nothing


def test_cite_W1b_clean_world(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch)
    drive("W1b", linkcheck, "--repo", str(repo))
    rec = receipt("W1b", linkcheck)
    assert rec["outcome"] == "SKIP" and rec["why"] == "no dead outbound links this run"


def test_cite_W1b_dead_link_gets_a_proposed_snapshot(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    drive("W1b", linkcheck, "--repo", str(repo))
    rec = receipt("W1b", linkcheck)
    prop = [f.get("proposal") for f in findings("W1") if f.get("proposal")]
    assert rec["outcome"] == "FINDINGS" and prop and prop[0]["status"] == "PROPOSED, not applied"


def test_cite_W1b_a_failed_lookup_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,), wayback=False)
    drive("W1b", linkcheck, "--repo", str(repo))
    rec = receipt("W1b", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "Wayback lookups failed" in rec["why"]


# ================================================================== W2 weekly digest
def _digest(md, rec):
    return (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")


def test_cite_W2_clean_world_says_0_findings(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "PASS" and "0 findings" in _digest(md, rec)


def test_cite_W2_lists_open_findings_by_age(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 28, 9, watch=maint_watch)
    import maint_receipt as mr
    mr.write_finding("W1", "S2", "internal link about -> /gone/", "x", "Site Maintainer")
    mr.write_receipt("W1", "FINDINGS", n=1, why="1 broken", tool="linkcheck.py")
    clock.set(2026, 11, 2, 11)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "PASS" and "5 d · W1 S2 internal link about -> /gone/" in _digest(md, rec)


def test_cite_W2_lists_unknowns_by_age(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 30, 11, watch=maint_watch)
    import maint_receipt as mr
    mr.write_receipt("M2b", "UNKNOWN", why="no CRUX_API_KEY", tool="maint_quality.py")
    clock.set(2026, 11, 2, 11)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "PASS" and "3 d · M2b: no CRUX_API_KEY" in _digest(md, rec)


def test_cite_W2_carries_the_monitor_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    mr.write_receipt("C1", "PASS", n=0, why="home: up, last 7 days uptime 99.9%", tool="headers_tls_check.py")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "PASS" and "C1 uptime monitor: PASS home: up, last 7 days uptime 99.9%" in _digest(md, rec)


# ================================================================== W3 people scan
def test_cite_W3_clean_world(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "PASS" and "with the known-names list loaded" in rec["why"]


def test_cite_W3_a_planted_name_is_s1(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"about/index.html": "<p>i met Quillon there.</p>"}, names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("W3")] == ["S1"]
    assert findings("W3")[0]["subject"] == "about/index.html: known-outside-rule"


def test_cite_W3_every_published_page(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"zz/deep/index.html": "<p>i met Quillon there.</p>"}, names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "FINDINGS" and findings("W3")[0]["subject"].startswith("zz/deep/index.html")


def test_cite_W3_no_names_file_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and "people_names.local.json absent" in rec["why"]


# ================================================================== M1 accessibility scan (real parser, recorded run)
def _pa11y(monkeypatch, code, stdout):
    import maint_quality as mq
    monkeypatch.setattr(mq, "find_bin", lambda name, root: name)
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", lambda argv, cwd=None, env=None, timeout=0: proc(code, stdout))


def test_cite_M1_clean_world(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 0, json.dumps({"total": 23, "passes": 23, "errors": 0, "results": {"http://h/": []}}))
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec["outcome"] == "PASS" and "0 WCAG2AA issues" in rec["why"]


def test_cite_M1_recorded_report_is_parsed_into_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 2, "pa11y-ci noise line\n" + pa11y_recorded())
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 7) and "on 4 page(s)" in rec["why"]
    assert "do not cover all of WCAG 2.2 AA" in rec["why"]


def test_cite_M1_a_technical_fault_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 1, "Error: browser failed to launch")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and "technical fault" in rec["why"]


# ================================================================== M1b contrast audit
def _contrast(monkeypatch, failures=(), unverifiable=()):
    import maint_quality as mq
    monkeypatch.setattr(mq, "audit_contrast", lambda root, rels: {"index.html": {
        "checked": 5, "failures": [contrast_row(*f) for f in failures],
        "passingButUnverifiable": [contrast_row("h1", 9, over=o) for o in unverifiable]}})


def test_cite_M1b_clean_world(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch)
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec["outcome"] == "PASS" and "nothing painted over" in rec["why"]


def test_cite_M1b_a_failing_pair_is_findings_by_cause(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch, failures=[("p.a", 1.2), ("p.b", 1.3)])
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and "2 el" in rec["why"]


def test_cite_M1b_a_pseudo_element_waits_for_the_eye(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _contrast(monkeypatch, unverifiable=["body::before"])
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting site-maintainer judgement")
    assert evidence(rec)                                     # the pack a judge closes from (the close: a D2 cite)


# ================================================================== M2 lab performance
def _lighthouse(monkeypatch, lcp, runs=3, outlier=None):
    import maint_quality as mq
    paths = [mq.page_path(r) for r in mq.served_pages(repo_root())]

    def run_cmd(argv, cwd=None, env=None, timeout=0):
        d = Path(cwd) / ".lighthouseci"
        d.mkdir(parents=True, exist_ok=True)
        for i, p in enumerate(paths):
            for k in range(runs):
                v = outlier if (outlier and k == 0) else lcp
                (d / f"lhr-{i}-{k}.json").write_text(json.dumps(lhr(p, v, 0.0, 10)), encoding="utf-8")
        return proc(0, "")
    monkeypatch.setattr(mq, "find_bin", lambda name, root: "lhci")
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", run_cmd)
    return paths


def test_cite_M2_clean_world(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec["outcome"] == "PASS" and "on the median of 3 runs" in rec["why"]


def test_cite_M2_the_median_not_the_worst_run(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200, outlier=9000)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec["outcome"] == "PASS"


def test_cite_M2_a_budget_miss_is_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    paths = _lighthouse(monkeypatch, 3000)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", len(paths))


def test_cite_M2_a_missing_run_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 1200, runs=2)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and "2/3 runs" in rec["why"]


# ================================================================== M2b field performance
def _crux(monkeypatch, status, body):
    import maint_quality as mq
    monkeypatch.setenv("CRUX_API_KEY", "test-key")
    monkeypatch.setattr(mq, "crux_query", lambda origin, key, opener=None: (status, body))


def test_cite_M2b_clean_world(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 200, crux_body())
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec["outcome"] == "PASS" and rec["why"].startswith("p75 ")


def test_cite_M2b_a_p75_miss_is_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 200, crux_body(lcp=3100))
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec["outcome"] == "FINDINGS" and "largest_contentful_paint p75 3100" in rec["why"]


def test_cite_M2b_no_field_data_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 404, {"error": {"code": 404, "message": "chrome ux report data not found"}})
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("UNKNOWN-field")


def test_cite_M2b_no_key_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
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
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"


def test_cite_M3_a_certificate_near_expiry_is_s1(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, days=5)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "certificate expires in" in rec["why"]


def test_cite_M3_http_must_redirect_to_https(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, redirect=200)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "does not redirect permanently" in rec["why"]


def test_cite_M3_a_changed_header_is_diffed(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    _tls(monkeypatch)
    snaps = md / "headers"
    snaps.mkdir(parents=True)
    (snaps / "2026-10-01.json").write_text(json.dumps({"headers": {"server": "nginx"}}), encoding="utf-8")
    monkeypatch.setattr(h, "today", lambda: dt.date(2026, 11, 2))
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "response header server changed" in rec["why"]


def test_cite_M3_a_mixed_content_subresource(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, grep=['index.html:12:<img src="http://example.org/a.png">'])
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "http:// subresource in index.html:12" in rec["why"]


# ================================================================== M4 reader walkthrough
JARGON = "<p>then i open the harness again later today and go home to rest for a while now.</p>"


def test_cite_M4_clean_world_awaits_the_editor(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec["outcome"] == "SKIP" and "no mechanical finding" in rec["why"] and not findings("M4")


def test_cite_M4_unglossed_jargon_on_the_route(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"lessons/alpha/index.html": page("Alpha", JARGON)})
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec["outcome"] == "SKIP" and "scanner found 1 unglossed jargon" in rec["why"]
    assert findings("M4")[0]["subject"] == "lessons/alpha/index.html: unglossed jargon"


def test_cite_M4_a_broken_reader_path(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"lessons/index.html": page("Lessons", "<p>no links</p>")})
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec["outcome"] == "SKIP" and "1 broken path segment" in rec["why"]
    assert findings("M4")[0]["severity"] == "S2"


def test_cite_M4_the_walkthrough_awaits_the_editor_with_its_pack(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    assert evidence_text(rec)                                # the pack a judge closes from (the close: a D2 cite)


# ================================================================== M5 board run (a test per outcome)
def _board(monkeypatch, tmp_path, stamp=True):
    import maint_watch as mw
    head = (repo_root() / "PRODUCTION_BOARD.md").read_text(encoding="utf-8").splitlines()[:6]
    if not stamp:
        head = [x for x in head if "Generated" not in x]
    (tmp_path / "PRODUCTION_BOARD.md").write_text("\n".join(head) + "\n", encoding="utf-8")
    monkeypatch.setattr(mw, "REPO", tmp_path)


def test_cite_M5_clean_world_board_run_found(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2026, 10, 31, 11, watch=maint_watch)
    _board(monkeypatch, tmp_path)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec["outcome"] == "PASS" and "board run 2026-10-20 found" in rec["why"]


def test_m5_board_run_due_is_awaiting(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 3, 11, watch=maint_watch)
    _board(monkeypatch, tmp_path)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor")


def test_m5_board_run_overdue_is_findings(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2026, 11, 6, 0, 1, watch=maint_watch)
    _board(monkeypatch, tmp_path)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "board run overdue" in rec["why"]


def test_m5_unreadable_board_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _board(monkeypatch, tmp_path, stamp=False)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "carries no '*Generated" in rec["why"]


# ================================================================== Q1 quarterly re-read
def _today(monkeypatch, day):
    import datetime as _d

    import maint_pages as mp

    class Day(_d.date):
        @classmethod
        def today(cls):
            return _d.date.fromisoformat(day)

    class Shim:
        """maint_pages' `dt`, with today() pinned: the datetime names it uses."""
        date, datetime, timedelta, timezone, time = Day, _d.datetime, _d.timedelta, _d.timezone, _d.time
    monkeypatch.setattr(mp, "dt", Shim)


def test_cite_Q1_clean_world_none_due(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    _today(monkeypatch, "2026-11-02")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("0 of 23 pages due")


def test_cite_Q1_pages_past_90_days_await_the_editor(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path, 2027, 2, 1, 11)
    _today(monkeypatch, "2027-02-01")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    assert rec["evidence"]                                   # the list a judge closes from (the close: a D2 cite)


# ================================================================== Q2 genericization sweep
def _client(repo, tokens=("Brindlecorp",)):
    (repo / "data" / "forbidden_tokens.local.json").write_text(json.dumps({"tokens": list(tokens)}), encoding="utf-8")


def test_cite_Q2_clean_world_awaits_a_witness(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer judgement: 0 forbidden tokens")


def test_cite_Q2_a_planted_token_in_a_named_lesson(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>i built zorblax.</p>")},
                      names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and "1 in lessons/ (S1)" in rec["why"]
    assert [(f["subject"], f["severity"]) for f in findings("Q2")] == [
        ("lessons/alpha/index.html: forbidden token", "S1")]


def test_cite_Q2_every_served_file_type(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, {"assets/app.js": "const c = 'Quendrith';\n"}, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec["outcome"] == "FINDINGS" and findings("Q2")[0]["subject"] == "assets/app.js: forbidden token"


def test_cite_Q2_the_client_token_from_the_local_list(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>for brindlecorp.</p>")},
                      names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec["outcome"] == "FINDINGS" and "brindlecorp" not in rec["why"].lower()
    assert findings("Q2")[0]["subject"] == "lessons/alpha/index.html: forbidden token"


def test_cite_Q2_the_witness_rules(monkeypatch, tmp_path):
    import maint_pages
    import pytest
    md, clock = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    prev = receipt("Q2", maint_pages)
    day = clock.now().date()
    with pytest.raises(maint_pages.CouldNotRun):                                        # an author may not witness
        maint_pages.cmd_witness(repo, day, "site-maintainer", tool="maint_watch.py", evidence=prev["evidence"])
    rec = maint_pages.cmd_witness(repo, day, "privacy-safety", tool="maint_watch.py", evidence=prev["evidence"])[0]
    assert rec["outcome"] == "PASS" and "witnessed by privacy-safety" in rec["why"] and hand_close_ok(prev, rec)


# ================================================================== Q3 patch-queue hygiene
def test_cite_Q3_clean_world(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec["outcome"] == "PASS" and "none older than 90 days" in rec["why"]


def test_cite_Q3_a_stale_finding_is_flagged(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path, 2026, 1, 5, 9)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    mr.write_finding("W1", "S3", "dead outbound link https://example.org/old", "x", "Site Maintainer")
    clock.set(2026, 11, 2, 11)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec["outcome"] == "FINDINGS" and rec["n"] == 1 and "older than 90 days" in rec["why"]


def test_cite_Q3_a_stale_patch_is_flagged(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    import maint_pages as mp
    repo = site_repo(mp, tmp_path, queue=[{"id": "P-9", "title": "Old patch", "stage": "DRAFTED", "kind": "patch",
                                       "drafted": "2026-01-02", "since": "2026-01-02"}])
    monkeypatch.setattr(mp, "REPO", repo)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec["outcome"] == "FINDINGS" and rec["n"] == 1


# ================================================================== Q4 DNS and takeover
def _dns(monkeypatch, drop=(), extra=None, wildcard=False):
    import headers_tls_check as h
    table = {k: v for k, v in good_dns(h).items() if k not in drop}
    table.update(extra or {})
    monkeypatch.setattr(h, "resolve", lambda name, rtype: (("ok", ["185.199.108.153"]) if wildcard else
                                                          ("nxdomain", [])) if name.startswith("maint-")
                        else table.get((name, rtype), ("nxdomain", [])))
    monkeypatch.setattr(h, "gh_pages", lambda slug: ("ok", PAGES_OK))


def test_cite_Q4_clean_world(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch)
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/headers_tls_check.py"


def test_cite_Q4_an_a_record_outside_pages(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, extra={("b4him.com", "A"): ("ok", ["185.199.108.153", "203.0.113.9"])})
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "A points outside GitHub Pages: 203.0.113.9" in rec["why"]


def test_cite_Q4_the_verification_txt(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, drop=(("_github-pages-challenge-sobevista.b4him.com", "TXT"),))
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "verification TXT" in rec["why"]


def test_cite_Q4_a_wildcard_record(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch, wildcard=True)
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
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
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch)
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec["outcome"] == "PASS" and "tests_failed 0/10" in rec["why"]


def test_cite_Q5_needs_daniels_ok(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "awaiting Daniel's one-time OK")


def test_cite_Q5_a_failing_test_is_findings(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch, 1, {"strict-transport-security": {"pass": False}})
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "strict-transport-security" in rec["why"]


def test_cite_Q5_the_frame_ancestors_limit_is_filed_once(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _observatory(monkeypatch, 1, XFO)
    drive("Q5", headers_tls_check)
    first = receipt("Q5", headers_tls_check)
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert first["outcome"] == "FINDINGS" and rec["outcome"] == "PASS" and "not re-filed" in rec["why"]


# ================================================================== Q6 alarm fire drill
def test_cite_Q6_clean_world_drill_confirmed(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    code, prev, _ = close("Q6", maint_watch, "confirm", "10:30")
    rec = closed("Q6", maint_watch)
    assert rec["outcome"] == "PASS" and "alarm fired at 10:30" in rec["why"] and hand_close_ok(prev, rec)


def test_cite_Q6_an_armed_drill_awaits_confirmation(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting alarm confirmation")
    assert rec["evidence"].endswith("_drill.md") and rec["tool"] == "tools/maint_watch.py"


def test_cite_Q6_no_alarm_is_an_s1_failure(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    code, prev, _ = close("Q6", maint_watch, "confirm", "never")
    rec = closed("Q6", maint_watch)
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("Q6")] == ["S1"]
    assert hand_close_ok(prev, rec)


def test_cite_Q6_no_heartbeat_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "no MAINT_HEARTBEAT_URL" in rec["why"]


# ================================================================== H1 "feels like home"
def _capture(monkeypatch, problems=()):
    import maint_human as mh
    monkeypatch.setattr(mh, "CAPTURE", fake_capture(mh, problems))


def test_cite_H1_clean_world_not_due(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    _capture(monkeypatch)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec["outcome"] == "SKIP" and "next due 2027-01-04" in rec["why"]


def test_cite_H1_the_pack_sits_beside_the_d9_reference(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    pack = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: H1 pack")
    assert "reference_logo.png" in pack and "`--navy-800`" in pack and pack.count("### ") == 4


def test_cite_H1_a_failed_capture_check_is_unknown(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch, ["t.png: 2560x10 px, expected 2560x4000"])
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec["outcome"] == "UNKNOWN" and "capture check failed" in rec["why"]


def test_cite_H1_when_due_the_pack_awaits_daniel(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    _capture(monkeypatch)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: H1 pack")
    assert evidence_text(rec)                                # the pack Daniel closes from (the close: a D2 cite)


# ================================================================== H2 / H3 review notes
GOOD_NOTE = "Date: {d}\nReviewer: reviewer\nReviewed: the publication gate\nVerdict: no change\nFindings: none\n"


def _note(md, row, day, text):
    (md / "notes").mkdir(parents=True, exist_ok=True)
    (md / "notes" / f"{row}_{day}.md").write_text(text, encoding="utf-8")


def test_cite_H2_clean_world(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "PASS" and "review note 2027-01-05 found" in rec["why"]


def test_cite_H2_due_without_a_note_awaits_the_reviewer(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting reviewer")


def test_cite_H2_a_template_note_is_read_and_refused(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H2", "2027-01-05", "Date: 2027-01-05\nReviewer: <seat>\nReviewed: ...\nVerdict: ___\nFinding: n/a\n")
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "Verdict" in rec["why"]


def test_cite_H2_an_author_cannot_review(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05").replace("reviewer", "managing-editor"))
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "independent Reviewer for H2" in rec["why"]


def test_cite_H2_the_date_line_must_match_the_filename(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2026-01-05"))
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "equal to the filename's date" in rec["why"]


def test_cite_H3_clean_world(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H3", "2027-01-05", GOOD_NOTE.format(d="2027-01-05"))
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec["outcome"] == "PASS" and "re-read note 2027-01-05 found" in rec["why"]


def test_cite_H3_due_without_a_note_awaits_daniel(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting publisher")


def test_cite_H3_an_empty_note_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H3", "2027-01-05", "")
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "the note is empty" in rec["why"]


def test_cite_H3_a_future_dated_note_is_refused(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H3", "2099-01-01", GOOD_NOTE.format(d="2099-01-01"))
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "not in the future" in rec["why"]


# ================================================================== A1 WCAG-EM
def test_cite_A1_clean_world_not_due(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec["outcome"] == "SKIP" and "next due 2027-01-04" in rec["why"]


def test_cite_A1_the_pack_has_every_page_and_the_easy_checks(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    (md).mkdir(parents=True, exist_ok=True)
    (md / "2027-01-03_a11y.json").write_text('{"results": {}}', encoding="utf-8")
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    pack = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: A1 WCAG-EM pack (23 pages")
    assert pack.count("| `") == 23 and "Visible Keyboard Focus" in pack and "2.5.8 Target Size (Minimum)" in pack
    copied = (md / rec["evidence"][len(".maint/"):]).parent / "automated_axe_pa11y.json"
    assert "automated_axe_pa11y.json (copied from" in pack and copied.read_text(encoding="utf-8") == '{"results": {}}'


def test_a1_without_a_page_list_is_unknown(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    tree = tmp_path / "not-a-checkout"
    tree.mkdir()
    (tree / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")   # not a checkout, even inside one
    drive("A1", maint_human, "--repo", str(tree))
    rec = receipt("A1", maint_human)
    assert rec["outcome"] == "UNKNOWN" and "no page list" in rec["why"]


def test_cite_A1_when_due_the_pack_awaits_daniel(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling")
    assert evidence_text(rec)                                # the pack Daniel signs off (the close: a D2 cite)


# ================================================================== A2 content inventory
def test_cite_A2_clean_world_awaits_the_editor(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement: 23 pages") \
        and "no duplicate" in rec["why"]


def test_cite_A2_true_duplicates_are_found(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"blog/index.html": page("Same", "<p>coming soon</p>"),
                                       "videos/index.html": page("Same", "<p>coming soon</p>")})
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec["outcome"] == "SKIP" and "1 duplicate group(s), filed as A2 findings" in rec["why"]
    assert findings("A2")[0]["subject"] == "duplicate visible text: blog/index.html = videos/index.html"


def test_cite_A2_the_inventory_awaits_the_editors_rot_judgement(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting managing-editor judgement")
    assert evidence_text(rec)                                # the inventory a judge closes from (the close: a D2 cite)


# ================================================================== A3 domain registration
def _rdap(monkeypatch, expires, status=("client transfer prohibited",)):
    import maint_human as mh
    boot = {"services": [[["com"], ["https://rdap.example.invalid/com/v1/"]]]}
    dom = {"status": list(status), "events": [{"eventAction": "expiration", "eventDate": expires}]}
    monkeypatch.setattr(mh, "GET_JSON", lambda url: boot if url == mh.BOOTSTRAP else dom)


def test_cite_A3_clean_world_far_from_expiry(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2027-07-19T00:00:00Z")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec["outcome"] == "SKIP" and "expires 2027-07-19" in rec["why"] and "window opens 2027-05-20" in rec["why"]


def test_cite_A3_the_60_day_window_awaits_daniel(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: expires 2026-12-20")
    assert rec["evidence"].endswith("_rdap.json") and [f["severity"] for f in findings("A3")] == ["S2"]


def test_cite_A3_a_hold_status_is_s1(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2027-07-19T00:00:00Z", status=("client hold",))
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec["outcome"] == "FINDINGS" and [f["severity"] for f in findings("A3")] == ["S1"]


def test_cite_A3_daniels_close_ends_the_window(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")
    drive("A3", maint_human)
    prev = receipt("A3", maint_human)
    mr.write_receipt("A3", "PASS", why="closed by Daniel's ledger E05555 (recorded here; the ledger itself is not read "
                     "by this tool)", evidence=prev["evidence"], tool="maint_watch.py")   # the close, as maint_watch writes it
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert prev["outcome"] == "SKIP" and rec["outcome"] == "SKIP" and "closed for this window" in rec["why"]


# ================================================================== A4 scanner calibration (the real scanners)
def _real_scanners(monkeypatch, **override):
    """The real no-network scanners (release.broken_links, people_registry, linkcheck's internal pass, the
    headers_tls mixed-content grep, maint_pages' people scan) against the real tools/_maint_fixtures/; the two browser
    scanners (pa11y-ci, contrast-audit.js) are recorded answers."""
    import maint_quality as mq
    canned = canned_scanners()
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
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch)
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    m = _matrix(md, rec)
    assert rec["outcome"] == "PASS" and m["broken-internal-link"] == {"release.broken_links": "SEEN",
                                                                       "linkcheck.py": "SEEN"}
    assert m["forbidden-token"] == {"people_registry": "SEEN", "maint_pages.py": "SEEN"}
    assert m["mixed-content"] == {"headers_tls_check.py": "SEEN"}


def test_cite_A4_a_blind_scanner_is_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch, **{"contrast-audit.js": lambda: {"low-contrast/index.html": [], "index.html": []}})
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec["outcome"] == "FINDINGS" and "contrast-audit.js missed low-contrast" in rec["why"]


def test_cite_A4_a_noisy_scanner_is_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch, **{"pa11y-ci": lambda: {"missing-alt/index.html": ["pa11y:image-alt"],
                                                        "low-contrast/index.html": ["pa11y:G18"],
                                                        "index.html": ["pa11y:region"]}})
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec["outcome"] == "FINDINGS" and "pa11y-ci flagged the clean control page" in rec["why"]


# ================================================================== round 7: every facet the reviewer's mutants found
# (C1, Q5, M1, M1b, D1, D2 first: a could-not-run case must never read as PASS)
def test_cite_C1_a_missing_7_day_ratio_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], custom_uptime_ratio=None), MONS[1]])
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "returned no 7-day ratio" in rec["why"]


def test_cite_C1_a_paused_monitor_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, [dict(MONS[0], status=0), MONS[1]])
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "is paused" in rec["why"]


def test_cite_Q5_no_tests_failed_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, json.dumps({
        "details_url": "x", "error": None, "grade": "A", "score": 90}).encode()))
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "has no tests_failed" in rec["why"]


def test_cite_M1_exit_0_with_issues_in_the_report_is_findings(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 0, pa11y_recorded())
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 7) and "exit 0 but its report holds 7" in rec["why"]


def test_cite_M1_every_served_page_is_in_the_scan(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    seen = []

    def run_cmd(argv, cwd=None, env=None, timeout=0):
        seen.append(json.loads(Path(argv[argv.index("--config") + 1]).read_text(encoding="utf-8"))["urls"])
        return proc(0, json.dumps({"total": 23, "passes": 23, "errors": 0, "results": {}}))
    monkeypatch.setattr(mq, "find_bin", lambda name, root: name)
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", run_cmd)
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec["outcome"] == "PASS" and len(seen[0]) == 23 and seen[0][0].endswith("/about/")


def test_cite_M1b_a_page_that_could_not_be_audited_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    import maint_quality as mq
    monkeypatch.setattr(mq, "audit_contrast", lambda root, rels: {
        "index.html": {"checked": 5, "failures": [], "passingButUnverifiable": []},
        "about/index.html": {"error": "TimeoutError: page did not load"}})
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and "1 page(s) could not be audited: about/index.html" in rec["why"]


def test_cite_D1_a_failed_patch_in_the_release_is_a_finding(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, patch_outcomes=[{"piece": "P-7", "outcome": "FAIL"}]))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "patch P-7 FAIL" in rec["why"]


def test_cite_D1_the_10_30_cutoff(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 2, 10, 29, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, date="2026-11-01"))
    drive("D1", maint_watch)
    before = receipt("D1", maint_watch)
    clock.set(2026, 11, 2, 10, 31)
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert before["outcome"] == "UNKNOWN" and rec["outcome"] == "FINDINGS" and "MISSING" in rec["why"]


def test_cite_D2_a_stale_schedule_alarms(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    import maint_watch as mw
    _table(monkeypatch, tmp_path, "D1", "D2")
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    monkeypatch.setattr(mw, "SCHEDULE_CHECK", lambda now: {
        "state": "stale", "problems": ["b4him-maint-run last ran 2026-10-30 10:35, over 26 h ago"], "why": "x"})
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "SCHEDULE (b4him-maint-run last ran 2026-10-30" in rec["why"]


def test_cite_D2_a_human_row_closes_only_on_daniels_pass(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 4, 11, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D2", "H1")
    mr.write_receipt("H1", "SKIP", why="awaiting Daniel's ruling: H1 pack", tool="maint_human.py")
    clock.set(2027, 1, 12, 0, 1)                         # 01-04 + 1 d + 7 d, and still no E-number
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "H1 (no receipt ever, due 2027-01-04" in rec["why"]


# ------------------------------------------------------------------ D3
def test_cite_D3_a_changed_cause_after_the_colon_is_a_new_alarm(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    import maint_watch as mw
    calls = _hb(monkeypatch)
    fails = []
    for day, why in ((2, "linkcheck crashed: KeyError 'pages'"), (3, "linkcheck crashed: TimeoutError")):
        clock.set(2026, 11, day, 10, 35)
        mr.write_receipt("D1", "PASS", why="ok", tool="maint_watch.py")
        r = mr.write_receipt("D2", "FINDINGS", n=1, why="overdue: W1 STUCK", tool="maint_watch.py")
        (md / mw.D2_ALARMS).write_text(json.dumps({"at": r["at"], "alarms": [mw.alarm_key("W1", "stuck-unknown", why)]}),
                                       encoding="utf-8")
        drive("D3", maint_watch)
        fails.append(calls[-1].endswith("/fail"))
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "PASS" and fails == [True, True] and "linkcheck crashed: timeouterror" in rec["why"]


def test_cite_D3_a_drill_withholds_the_ping(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    calls = _hb(monkeypatch)
    _d1d2()
    mw.main(["drill"])
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("drill (Q6)") and calls == []


def test_cite_D3_ok_not_found_is_not_a_delivered_ping(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    _hb(monkeypatch)
    monkeypatch.setattr(mw, "HTTP_GET", lambda url: (200, "OK (not found)"))
    _d1d2()
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "not recorded by the service" in rec["why"]


# ------------------------------------------------------------------ W1, W1b
def test_cite_W1_a_broken_link_with_unknown_live_state_is_s2(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": '<a href="../Lessons/alpha/">x</a>'})
    _net(monkeypatch)
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "FINDINGS" and "(1 S2)" in rec["why"] and findings("W1")[0]["severity"] == "S2"


def test_cite_W1_an_unknown_answer_is_never_cached(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    import urllib.error

    import linkcheck as lc
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch)
    real = lc.Fetcher.real

    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 503, "Unavailable", {}, None)
    monkeypatch.setattr(lc, "Fetcher", lambda: real(opener=opener, sleep=lambda s: None))
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    cache = json.loads((md / "linkcache.json").read_text(encoding="utf-8"))
    assert rec["outcome"] == "UNKNOWN" and OUT not in cache["links"]


def test_cite_W1b_the_snapshot_is_asked_for_near_the_last_alive_date(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    import linkcheck as lc
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": f'<a href="{OUT}">out</a>'})
    dead = []
    calls = _net(monkeypatch, dead=dead)
    drive("W1b", linkcheck, "--repo", str(repo))                                             # 2026-11-02: alive, last_ok_at recorded
    dead.append(OUT)
    clock.set(2026, 11, 10, 11)                              # 8 days on: the cache is stale, the link is dead
    drive("W1b", linkcheck, "--repo", str(repo))
    rec = receipt("W1b", linkcheck)
    asked = [u for u in calls if u.startswith(lc.WAYBACK_API)]
    assert rec["outcome"] == "FINDINGS" and asked and "timestamp=20261102" in asked[-1]


# ------------------------------------------------------------------ W2, W3
def test_cite_W2_lists_the_receipts_of_the_week(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 10, 30, 11, watch=maint_watch)
    import maint_receipt as mr
    mr.write_receipt("Q3", "PASS", n=0, why="4 open item(s), none older than 90 days", tool="maint_pages.py")
    clock.set(2026, 11, 2, 11)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    text = _digest(md, rec)
    assert rec["outcome"] == "PASS" and "2026-10-30T16:00:00+00:00 Q3 PASS: 4 open item(s)" in text.split(
        "## Receipts of the week")[1]


def test_cite_W3_title_words_are_exempt_only_on_their_own_page(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"games/index.html": page("Gentle Harbor", "<h1>Gentle Harbor</h1>"),
                                       "about/index.html": page("About", "<p>i played Gentle Harbor once.</p>")},
               names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "FINDINGS" and [f["subject"] for f in findings("W3")] == [
        "about/index.html: unknown-name (needs review)"]


def test_cite_W3_a_capitalised_pair_in_the_names_file_is_never_exempt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, {"about/index.html": page(
        "Corvane Mistlewood", "<h1>Corvane Mistlewood</h1><p>i met Corvane Mistlewood.</p>")})
    local_names(repo, names=("Quillon Mistlewood",))     # a pair sharing a word with a known name: heuristic hit
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    ev = json.loads((md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8"))
    exempted = [e["text"] for pg in ev["pages"].values() for e in pg["exempted"]]   # the one planted page
    assert rec["outcome"] == "FINDINGS" and len(ev["pages"]) >= 1 and not any("Mistlewood" in t for t in exempted)


# ------------------------------------------------------------------ M2, M2b, M3: thresholds either side of the line
def test_cite_M2_the_lcp_budget_either_side_of_2500(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _lighthouse(monkeypatch, 2499)
    drive("M2", maint_quality)
    under = receipt("M2", maint_quality)
    _lighthouse(monkeypatch, 2501)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert under["outcome"] == "PASS" and rec["outcome"] == "FINDINGS" and "2501 > 2500" in rec["why"]


def test_cite_M2b_lcp_p75_either_side_of_2500(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 200, crux_body(lcp=2500))
    drive("M2b", maint_quality)
    at = receipt("M2b", maint_quality)
    _crux(monkeypatch, 200, crux_body(lcp=2501))
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert at["outcome"] == "PASS" and rec["outcome"] == "FINDINGS" and "p75 2501 > 2500" in rec["why"]


def test_cite_M2b_inp_p75_either_side_of_200(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _crux(monkeypatch, 200, crux_body(inp=200))
    drive("M2b", maint_quality)
    at = receipt("M2b", maint_quality)
    _crux(monkeypatch, 200, crux_body(inp=201))
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert at["outcome"] == "PASS" and rec["outcome"] == "FINDINGS" and "interaction_to_next_paint p75 201" in rec["why"]


def test_cite_M3_the_certificate_line_at_13_and_14_days(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch, days=14.5)
    drive("M3", headers_tls_check)
    over = receipt("M3", headers_tls_check)
    _tls(monkeypatch, days=13.5)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert over["outcome"] == "PASS" and rec["outcome"] == "FINDINGS" and "certificate expires in 13." in rec["why"]


# ------------------------------------------------------------------ M4, Q1, Q2, Q3
def test_cite_M4_the_route_goes_through_find_your_door(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    walk = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and "-> /lessons/find-your-door/ ->" in walk.split("shortest click route found:")[1]


def test_cite_Q1_due_at_exactly_90_days(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 17, 11)
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)          # every page published 2026-10-20
    _today(monkeypatch, "2027-01-17")                      # 89 days
    drive("Q1", maint_pages)
    before = receipt("Q1", maint_pages)
    _today(monkeypatch, "2027-01-18")                      # 90 days
    clock.set(2027, 1, 18, 11)
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert before["why"].startswith("0 of 4 pages due") and rec["why"].startswith(
        "awaiting managing-editor judgement: 4 of 4 pages due")


def test_cite_Q2_the_voice_token_is_still_swept_in_the_lessons(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    d11 = D11.replace("`Vexmoor-rig` → \"a machine\".", "`Vexmoor-rig` → \"a machine\", Halvard → first person.")
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, {"DECISIONS.md": d11,
                                              "lessons/alpha/index.html": page("Alpha", "<p>Halvard built it.</p>"),
                                              "notes/plan.md": "Halvard rules this.\n"}, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and [f["subject"] for f in findings("Q2")] == [
        "lessons/alpha/index.html: forbidden token"]


def test_cite_Q3_a_closed_finding_is_not_stale(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path, 2026, 1, 5, 9)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    mr.write_finding("W1", "S3", "dead outbound link https://example.org/old", "x", "Site Maintainer")
    mr.write_finding("W1", "S3", "dead outbound link https://example.org/old", "fixed", "Site Maintainer",
                     status="closed")
    clock.set(2026, 11, 2, 11)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec["outcome"] == "PASS" and "0 finding" in rec["why"]


def test_cite_Q3_stale_either_side_of_90_days(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path, 2026, 8, 4, 9)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _today(monkeypatch, "2026-11-02")
    mr.write_finding("W1", "S3", "ninety days old", "x", "Site Maintainer")           # 2026-08-04: 90 days
    clock.set(2026, 11, 2, 11)
    drive("Q3", maint_pages)
    at_90 = receipt("Q3", maint_pages)
    clock.set(2026, 8, 3, 9)
    mr.write_finding("W1", "S3", "ninety-one days old", "x", "Site Maintainer")      # 2026-08-03: 91 days
    clock.set(2026, 11, 2, 11)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert at_90["outcome"] == "PASS" and (rec["outcome"], rec["n"]) == ("FINDINGS", 1)


# ------------------------------------------------------------------ Q4, Q6
def test_cite_Q4_an_aaaa_record_outside_pages(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    _dns(monkeypatch, extra={("b4him.com", "AAAA"): ("ok", sorted(h.PAGES_AAAA) + ["2001:db8::1"])})
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "AAAA points outside GitHub Pages: 2001:db8::1" in rec["why"]


def test_cite_Q4_enforce_https_must_be_on(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    _dns(monkeypatch)
    monkeypatch.setattr(h, "gh_pages", lambda slug: ("ok", dict(PAGES_OK, https_enforced=False)))
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "FINDINGS" and "Enforce HTTPS is off" in rec["why"]


def test_cite_Q6_no_row_is_a_retire_candidate_before_4_quarters(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 1, 9, watch=maint_watch)
    import maint_receipt as mr
    mr.write_receipt("W1", "PASS", n=0, why="ok", tool="linkcheck.py")
    clock.set(2026, 11, 2, 11)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    drill = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and "W1: zero findings and zero alarms so far, but history only since" in drill
    assert "candidate to retire" not in drill


def test_cite_Q6_an_alarm_time_must_belong_to_the_drill(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    code, prev, _ = close("Q6", maint_watch, "confirm", "23:00")                       # later than now: not this drill's alarm
    rec = receipt("Q6", maint_watch)                                       # the drill's own line still stands
    assert code == 1 and closed("Q6", maint_watch) == {}                   # and no close was written
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting alarm confirmation")


# ------------------------------------------------------------------ H1, H2, H3, A1, A2, A3, A4
def test_cite_H1_every_tile_is_measured(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    import maint_human as mh

    def capture(repo, rels, out):
        res = {}
        for r in rels:
            plan = mh.tile_plan(2500)
            paths = [png(out / f"{r.replace('/', '-')}_{i}.png", 2560, 10) for i, _ in enumerate(plan)]   # wrong size
            res[r] = {1280: {"tiles": [p.name for p in paths], "height": 2500,
                             "problems": mh.check_tiles(paths, plan, 1280, 2500)}}
        return res
    monkeypatch.setattr(mh, "CAPTURE", capture)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec["outcome"] == "UNKNOWN" and "capture check failed" in rec["why"] and "expected 2560x4000" in rec["why"]


def test_cite_H2_a_value_needs_real_content(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H2", "2027-01-05", GOOD_NOTE.format(d="2027-01-05").replace("the publication gate", "ok"))
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "Reviewed: <what was reviewed>" in rec["why"]


def test_cite_H3_a_finding_line_is_required(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    _note(md, "H3", "2027-01-05", GOOD_NOTE.format(d="2027-01-05").replace("Findings: none\n", ""))
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "at least one 'Finding: ...' line" in rec["why"]


def test_cite_A1_the_new_wcag_22_criteria_are_in_the_pack(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    pack = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and "- [ ] 2.4.11 Focus Not Obscured (Minimum), AA" in pack


def test_cite_A2_the_inventory_names_each_page_url(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    audit = (md / rec["evidence"][len(".maint/"):]).read_text(encoding="utf-8")
    assert rec["outcome"] == "SKIP" and "https://example.invalid/lessons/alpha/" in audit


def test_cite_A3_the_window_opens_60_days_before_expiry(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")                # 47 days out: inside the 60-day window
    drive("A3", maint_human)
    a3 = receipt("A3", maint_human)                          # D2's view of the same window: a D2 cite below
    assert a3["outcome"] == "SKIP" and a3["why"].startswith("awaiting Daniel's ruling: expires 2026-12-20 (47 days)")


def test_cite_D2_an_a3_window_left_open_goes_overdue(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "A3")
    plant_awaiting("A3", "maint_human.py", "awaiting Daniel's ruling: expires 2026-12-20 (47 days), the 60-day window "
                   "is open; confirm auto-renew and the registrar contact, then close with maint_watch.py human A3 "
                   "<E-number>", "audits/2026-11-02_rdap.json")
    clock.set(2026, 11, 4, 1)                                # the window opened 2026-10-21; grace 14 d to 11-04
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "the 60-day window opened 2026-10-21" in rec["why"]


def test_cite_A3_the_60_day_line(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    _rdap(monkeypatch, "2027-01-02T16:00:00Z")                # 61 days after 2026-11-02 16:00Z: not yet
    drive("A3", maint_human)
    before = receipt("A3", maint_human)
    _rdap(monkeypatch, "2027-01-01T16:00:00Z")                # exactly 60 days: the window is open
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert before["why"].startswith("not due: expires 2027-01-02 (61 days)")
    assert rec["outcome"] == "SKIP" and rec["why"].startswith("awaiting Daniel's ruling: expires 2027-01-01 (60 days)")


def test_cite_A4_the_contrast_hit_must_be_the_planted_one(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _real_scanners(monkeypatch, **{"contrast-audit.js": lambda: {
        "low-contrast/index.html": ["contrast:p.some-other-paragraph:1.4"], "index.html": []}})
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec["outcome"] == "FINDINGS" and "contrast-audit.js missed low-contrast" in rec["why"]


# ================================================================== property cites: empty, unreadable, future-dated and
# foreign-timezone inputs must never give PASS (the shared input layer, tools/maint_input.py, as a class)
from hypothesis import HealthCheck, given, settings  # noqa: E402
from hypothesis import strategies as st  # noqa: E402

PROPS = settings(max_examples=6, deadline=None, derandomize=True, database=None,   # writes nothing
                
                 suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow])
KINDS = st.sampled_from(["empty", "garbage", "not_json", "future", "foreign_tz"])
GARBAGE = st.binary(min_size=1, max_size=24).filter(lambda b: b.strip() and not b.strip().startswith((b"{", b"[")))
FOREIGN = st.sampled_from([9, 10, 12, 13, 14])         # hours east of UTC: a wall clock that reads right, a wrong instant


def fresh(monkeypatch, tmp_path, *when, watch=None):
    import uuid
    d = tmp_path / uuid.uuid4().hex
    d.mkdir(parents=True)
    return world(monkeypatch, d, *when, watch=watch)


def bad_bytes(kind, garbage):
    return {"empty": b"", "garbage": b"\xff\xfe" + garbage, "not_json": b"{not json"}.get(kind, b"{not json")


def _use_opener(monkeypatch, real, opener):
    import linkcheck as lc

    def factory():
        return real(opener=opener, sleep=lambda s: None)
    factory.real = real
    monkeypatch.setattr(lc, "Fetcher", factory)


def never_pass(rec):
    return rec.get("outcome") in ("UNKNOWN", "FINDINGS")


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_C1_corrupt_monitor_answers_never_pass(monkeypatch, tmp_path, kind, garbage):
    import headers_tls_check
    md, _ = fresh(monkeypatch, tmp_path)
    import headers_tls_check as h
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "ur-test")
    body = {"future": json.dumps({"stat": "ok", "monitors": [dict(MONS[0], custom_uptime_ratio=""), MONS[1]]}).encode(),
            "foreign_tz": json.dumps({"stat": "ok", "monitors": []}).encode()}.get(kind) or bad_bytes(kind, garbage)
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, body))
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE, east=FOREIGN)
def test_cite_D1_corrupt_release_logs_never_pass(monkeypatch, tmp_path, kind, garbage, east):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    log = md.parent / "release_log.jsonl"
    md.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(mw, "REPO", md.parent)
    if kind == "future":
        log.write_text(json.dumps(dict(LINE, at="2026-11-02T18:00:00+00:00")) + "\n", encoding="utf-8")
    elif kind == "foreign_tz":                         # 08:30 on a foreign wall clock is the night before, here
        log.write_text(json.dumps(dict(LINE, at=f"2026-11-02T08:30:00+{east:02d}:00")) + "\n", encoding="utf-8")
    else:
        log.write_bytes(bad_bytes(kind, garbage))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE, east=FOREIGN)
def test_cite_D2_corrupt_inputs_never_pass(monkeypatch, tmp_path, kind, garbage, east):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    _table(monkeypatch, md.parent, "D1", "D2")
    md.mkdir(parents=True, exist_ok=True)
    line = {"row": "D1", "outcome": "PASS", "n": None, "why": "ok", "evidence": None, "tool": "tools/maint_watch.py"}
    if kind in ("empty", "not_json"):
        mw.ROWS_FILE.write_bytes(bad_bytes(kind, garbage))
    elif kind == "garbage":
        (md / "maintenance_log.jsonl").write_bytes(b"{" + garbage + b"\n")
    elif kind == "future":
        (md / "maintenance_log.jsonl").write_text(json.dumps(dict(line, at="2026-11-03T16:00:00+00:00")) + "\n",
                                                  encoding="utf-8")
    else:                                              # 10:00 today on a foreign clock is yesterday evening here
        (md / "maintenance_log.jsonl").write_text(json.dumps(dict(line, at=f"2026-11-02T10:00:00+{east:02d}:00"))
                                                  + "\n", encoding="utf-8")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=st.text(min_size=1, max_size=20).filter(lambda s: s.strip() != "OK"))
def test_cite_D3_unproven_pings_never_pass_as_success(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    calls = _hb(monkeypatch)
    _d1d2()
    if kind in ("empty", "garbage", "not_json"):
        body = {"empty": "", "garbage": garbage, "not_json": "OK (not found)"}[kind]
        monkeypatch.setattr(mw, "HTTP_GET", lambda url: (200, body))
    elif kind == "future":
        (md / mw.DRILLS).write_text("{not json\n", encoding="utf-8")      # an unreadable drill log
    else:
        (md / mw.DRILLS).write_text("", encoding="utf-8")                 # an empty drill log
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert not (rec.get("outcome") == "PASS" and "success signal" in rec.get("why", "")), rec


@PROPS
@given(kind=KINDS, code=st.sampled_from([401, 403, 429, 500, 502, 503]))
def test_cite_W1_unproven_links_never_pass(monkeypatch, tmp_path, kind, code):
    import linkcheck
    md, _ = fresh(monkeypatch, tmp_path)
    import urllib.error

    import linkcheck as lc
    repo = site_repo(linkcheck, md.parent, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    if kind in ("future", "foreign_tz"):              # a cached "alive" from the future must not stand in for a fetch
        # foreign_tz: 12:00 at -08:00 is 20:00Z, four hours ahead of the 16:00Z clock, though its digits read as past
        at = "2026-11-09T16:00:00+00:00" if kind == "future" else "2026-11-02T12:00:00-08:00"
        md.mkdir(parents=True, exist_ok=True)
        (md / "linkcache.json").write_text(json.dumps({"version": 1, "wayback": {}, "links": {
            OUT: {"status": "OK", "checked_at": at, "last_ok_at": at}}}), encoding="utf-8")
    else:
        real = lc.Fetcher.real

        def opener(req, timeout=None):
            if kind == "empty":
                raise urllib.error.URLError("no route")
            raise urllib.error.HTTPError(req.full_url, code, "x", {}, None)
        _use_opener(monkeypatch, real, opener)
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_W1b_corrupt_archive_answers_never_pass(monkeypatch, tmp_path, kind, garbage):
    import linkcheck
    md, _ = fresh(monkeypatch, tmp_path)
    import urllib.error

    import linkcheck as lc
    repo = site_repo(linkcheck, md.parent, {"about/index.html": f'<a href="{OUT}">out</a>'})
    _net(monkeypatch, dead=(OUT,))
    real = lc.Fetcher.real
    body = bad_bytes(kind, garbage) if kind in ("empty", "garbage", "not_json") else b'{"archived_snapshots": 7}'

    class R:
        def __init__(self, u, b, c=200):
            self.url, self.body, self.code = u, b, c

        def getcode(self):
            return self.code

        def geturl(self):
            return self.url

        def read(self, n=-1):
            return self.body

        def close(self):
            pass

    def opener(req, timeout=None):
        if req.full_url.startswith(lc.WAYBACK_API):
            return R(req.full_url, body)
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
    _use_opener(monkeypatch, real, opener)
    drive("W1b", linkcheck, "--repo", str(repo))
    rec = receipt("W1b", linkcheck)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_W2_corrupt_receipt_logs_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, watch=maint_watch)
    md.mkdir(parents=True, exist_ok=True)
    line = {"row": "W1", "outcome": "PASS", "n": 0, "why": "ok", "evidence": None, "tool": "tools/linkcheck.py"}
    if kind == "future":
        text = json.dumps(dict(line, at="2026-11-05T16:00:00+00:00")) + "\n"
    elif kind == "foreign_tz":
        text = json.dumps(dict(line, at="2026-11-03T12:00:00+14:00")) + "\n"     # = 11-02 22:00Z: hours ahead
    else:
        (md / "maintenance_log.jsonl").write_bytes(b"{" + bad_bytes(kind, garbage) + b"\n")
        text = None
    if text:
        (md / "maintenance_log.jsonl").write_text(text, encoding="utf-8")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_W3_a_corrupt_names_file_never_passes(monkeypatch, tmp_path, kind, garbage):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, md.parent)
    names = repo / "data" / "people_names.local.json"
    names.write_bytes(bad_bytes(kind, garbage) if kind != "future" else b'{"people": "nobody"}')
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE, code=st.sampled_from([0, 2]))
def test_cite_M1_unreadable_reports_never_pass(monkeypatch, tmp_path, kind, garbage, code):
    import maint_quality
    md, _ = fresh(monkeypatch, tmp_path)
    out = {"empty": "", "garbage": garbage.decode("latin-1"), "not_json": "{not json",
           "future": json.dumps({"total": 1, "results": "x"}), "foreign_tz": json.dumps([1, 2])}[kind]
    _pa11y(monkeypatch, code, out)
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS)
def test_cite_M1b_unreadable_audits_never_pass(monkeypatch, tmp_path, kind):
    import maint_quality
    md, _ = fresh(monkeypatch, tmp_path)
    import maint_quality as mq
    res = {"empty": {}, "garbage": {"index.html": {"error": "garbage"}}, "not_json": {"index.html": "x"},
           "future": {"index.html": {"checked": 0, "failures": [], "passingButUnverifiable": []}},
           "foreign_tz": {"index.html": {}}}[kind]
    monkeypatch.setattr(mq, "audit_contrast", lambda root, rels: res)
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_M2_unreadable_lighthouse_results_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_quality
    md, _ = fresh(monkeypatch, tmp_path)
    import maint_quality as mq

    def run_cmd(argv, cwd=None, env=None, timeout=0):
        d = Path(cwd) / ".lighthouseci"
        d.mkdir(parents=True, exist_ok=True)
        if kind != "future":                           # "future" here: lhci wrote nothing at all
            (d / "lhr-0.json").write_bytes(bad_bytes(kind, garbage) if kind != "foreign_tz" else b"[]")
        return proc(0, "")
    monkeypatch.setattr(mq, "find_bin", lambda name, root: "lhci")
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "run_cmd", run_cmd)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS)
def test_cite_M2b_unreadable_field_data_never_passes(monkeypatch, tmp_path, kind):
    import maint_quality
    md, _ = fresh(monkeypatch, tmp_path)
    body = {"empty": None, "garbage": {"record": "x"}, "not_json": {}, "future": {"record": {"metrics": {}}},
            "foreign_tz": {"record": {"metrics": {"largest_contentful_paint": {"percentiles": {"p75": "fast"}}}}}}[kind]
    _crux(monkeypatch, 200, body)
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_M3_unreadable_tls_inputs_never_pass(monkeypatch, tmp_path, kind, garbage):
    import headers_tls_check
    md, _ = fresh(monkeypatch, tmp_path)
    import headers_tls_check as h
    _tls(monkeypatch)
    if kind in ("empty", "garbage", "not_json"):     # the previous header snapshot cannot be read
        (md / "headers").mkdir(parents=True, exist_ok=True)
        (md / "headers" / "2026-10-01.json").write_bytes(bad_bytes(kind, garbage))
        monkeypatch.setattr(h, "today", lambda: dt.date(2026, 11, 2))
    else:                                            # the certificate's expiry cannot be read
        monkeypatch.setattr(h, "probe_cert", lambda host: {"not_after": "2027-01-01T00:00:00" if kind == "future"
                                                           else "Jan 1 00:00:00 2027 JST+9", "issuer": "x"})
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS)
def test_cite_M4_an_unreadable_tree_never_passes(monkeypatch, tmp_path, kind):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    import maint_pages as mp
    d = md.parent / "not-a-repo"
    d.mkdir(parents=True)
    (d / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")      # not a checkout, even inside one
    monkeypatch.setattr(mp, "REPO", d)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_M5_corrupt_boards_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, 2026, 10, 31, 11, watch=maint_watch)
    import maint_watch as mw
    d = md.parent
    d.mkdir(parents=True, exist_ok=True)
    board = {"future": "*Generated 2027-03-01 by `tools/production_board.py` from x.*\n",
             "foreign_tz": "# PRODUCTION BOARD\nno stamp here\n"}
    if kind in board:
        (d / "PRODUCTION_BOARD.md").write_text(board[kind], encoding="utf-8")
    else:
        (d / "PRODUCTION_BOARD.md").write_bytes(bad_bytes(kind, garbage))
    monkeypatch.setattr(mw, "REPO", d)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert never_pass(rec), rec


def _corrupt_queue(repo, kind, garbage):
    q = repo / "production_queue.jsonl"
    if kind == "future":
        q.write_text("\n\n", encoding="utf-8")                   # zero records where records are expected
    elif kind == "foreign_tz":
        q.unlink()                                                # missing
    else:
        q.write_bytes(bad_bytes(kind, garbage))


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_Q1_a_corrupt_queue_is_unknown_not_none_due(monkeypatch, tmp_path, kind, garbage):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, md.parent)
    _corrupt_queue(repo, kind, garbage)
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec.get("outcome") in ("UNKNOWN", "FINDINGS"), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_Q2_a_corrupt_client_list_never_passes(monkeypatch, tmp_path, kind, garbage):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, md.parent, names=True)
    f = repo / "data" / "forbidden_tokens.local.json"
    f.write_bytes(bad_bytes(kind, garbage) if kind not in ("future", "foreign_tz") else
                  (b'{"tokens": []}' if kind == "future" else b'["Brindlecorp"]'))
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec.get("outcome") in ("UNKNOWN", "FINDINGS"), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_Q3_corrupt_queues_and_findings_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, md.parent, names=True)
    if kind == "garbage":
        md.mkdir(parents=True, exist_ok=True)
        (md / "maintenance_findings.jsonl").write_bytes(b"{" + garbage + b"\n")
    else:
        _corrupt_queue(repo, kind, garbage)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS)
def test_cite_Q4_unanswered_dns_never_passes(monkeypatch, tmp_path, kind):
    import headers_tls_check
    md, _ = fresh(monkeypatch, tmp_path)
    import headers_tls_check as h
    _dns(monkeypatch)
    if kind in ("empty", "garbage"):
        monkeypatch.setattr(h, "resolve", lambda name, rtype: ("error", ["LifetimeTimeout"]))
    else:
        monkeypatch.setattr(h, "gh_pages", lambda slug: ("unknown", "gh api exit 1"))
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_Q5_unreadable_grades_never_pass(monkeypatch, tmp_path, kind, garbage):
    import headers_tls_check
    md, _ = fresh(monkeypatch, tmp_path)
    import headers_tls_check as h
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")
    body = {"future": json.dumps({"grade": "A", "tests_failed": "0"}).encode(),
            "foreign_tz": json.dumps({"error": "rate-limited", "message": "slow down"}).encode()}.get(kind) or \
        bad_bytes(kind, garbage)
    monkeypatch.setattr(h, "http_post", lambda *a, **k: (200, body))
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_Q6_a_corrupt_drill_log_never_passes(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, watch=maint_watch)
    import maint_watch as mw
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    md.mkdir(parents=True, exist_ok=True)
    (md / mw.DRILLS).write_bytes(bad_bytes(kind, garbage))
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_H1_unreadable_captures_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_human
    md, _ = fresh(monkeypatch, tmp_path, 2027, 1, 4, 11)
    import maint_human as mh

    def capture(repo, rels, out):
        plan = mh.tile_plan(2500)
        paths = []
        for i, _ in enumerate(plan):
            p = out / f"t{i}.png"
            p.write_bytes(bad_bytes(kind, garbage))
            paths.append(p)
        return {rels[0]: {1280: {"tiles": [p.name for p in paths], "height": 2500,
                                 "problems": mh.check_tiles(paths, plan, 1280, 2500)}}}
    monkeypatch.setattr(mh, "CAPTURE", capture)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_H2_unreadable_notes_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    (md / "notes").mkdir(parents=True, exist_ok=True)
    if kind == "future":
        (md / "notes" / "H2_2027-02-01.md").write_text(GOOD_NOTE.format(d="2027-02-01"), encoding="utf-8")
    elif kind == "foreign_tz":
        (md / "notes" / "H2_2027-01-05.md").write_text(GOOD_NOTE.format(d="2027-01-05T09:00+14:00"), encoding="utf-8")
    else:
        (md / "notes" / "H2_2027-01-05.md").write_bytes(bad_bytes(kind, garbage))
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert never_pass(rec), rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_H3_unreadable_notes_never_pass(monkeypatch, tmp_path, kind, garbage):
    import maint_watch
    md, _ = fresh(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    (md / "notes").mkdir(parents=True, exist_ok=True)
    if kind == "future":
        (md / "notes" / "H3_2027-02-01.md").write_text(GOOD_NOTE.format(d="2027-02-01"), encoding="utf-8")
    elif kind == "foreign_tz":
        (md / "notes" / "H3_2027-01-05.md").write_text(GOOD_NOTE.format(d="2027-01-04"), encoding="utf-8")
    else:
        (md / "notes" / "H3_2027-01-05.md").write_bytes(bad_bytes(kind, garbage))
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert never_pass(rec), rec


@PROPS
@given(why=st.text(min_size=1, max_size=30))
def test_cite_A1_no_page_list_never_passes(monkeypatch, tmp_path, why):
    import maint_human
    md, _ = fresh(monkeypatch, tmp_path, 2027, 1, 4, 11)
    tree = md.parent / "no-checkout"                          # `why` names what sits there instead of a git checkout
    tree.mkdir()
    (tree / ".git").write_text(why, encoding="utf-8")         # a .git FILE pointing nowhere: git cannot list it
    drive("A1", maint_human, "--repo", str(tree))
    rec = receipt("A1", maint_human)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=GARBAGE)
def test_cite_A2_a_corrupt_queue_never_passes(monkeypatch, tmp_path, kind, garbage):
    import maint_pages
    md, _ = fresh(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, md.parent)
    _corrupt_queue(repo, kind, garbage)
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS, garbage=st.text(min_size=1, max_size=20))
def test_cite_A3_unreadable_rdap_never_passes(monkeypatch, tmp_path, kind, garbage):
    import maint_human
    md, _ = fresh(monkeypatch, tmp_path)
    import maint_human as mh
    boot = {"services": [[["com"], ["https://rdap.example.invalid/com/v1/"]]]}
    dom = {"empty": {}, "garbage": {"events": [{"eventAction": "expiration", "eventDate": garbage}]},
           "not_json": ["not", "a", "record"], "future": {"events": [{"eventAction": "expiration",
                                                                      "eventDate": "2027-07-19T00:00:00"}]},
           "foreign_tz": {"events": "x"}}[kind]
    monkeypatch.setattr(mh, "GET_JSON", lambda url: boot if url == mh.BOOTSTRAP else dom)
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec.get("outcome") == "UNKNOWN", rec


@PROPS
@given(kind=KINDS)
def test_cite_A4_broken_scanners_never_pass(monkeypatch, tmp_path, kind):
    import maint_quality
    md, _ = fresh(monkeypatch, tmp_path)
    import maint_quality as mq

    def broken():
        raise mq.Unavailable(f"scanner broken ({kind})")
    bad = {"empty": lambda: {}, "garbage": broken, "not_json": lambda: {"x": ["y"]},
           "future": broken, "foreign_tz": lambda: {}}[kind]
    _real_scanners(monkeypatch, **{"pa11y-ci": bad})
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert never_pass(rec), rec


# ================================================================== round 8: a check that could not run is never PASS
# (the reviewer's mut10 batch: the shared input layer, maint_run's receipt intake, and each tool's UNKNOWN exits)
def test_cite_D1_a_release_time_with_no_zone_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, at="2026-11-02T13:30:01"))          # no zone: which 13:30?
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "has no timezone" in rec["why"]


def test_cite_D1_a_release_line_with_no_time_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, at=None))
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "no time" in rec["why"]


def test_cite_D1_a_missing_release_log_is_unknown_as_missing(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setattr(maint_watch, "REPO", tmp_path)                             # no release_log.jsonl at all
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "the release log is missing" in rec["why"]


def test_cite_D1_a_line_break_inside_a_value_is_not_a_new_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setattr(maint_watch, "REPO", tmp_path)
    line = json.dumps(dict(LINE, note="checked \u0085 twice"), ensure_ascii=False)    # U+0085 raw inside a value
    (tmp_path / "release_log.jsonl").write_text(line + "\n", encoding="utf-8")
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "PASS" and rec["tool"] == "tools/maint_watch.py"     # one line, read whole


def test_cite_D1_a_release_line_stamped_past_the_clock_skew_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 2, 10, watch=maint_watch)   # 10:00 local = 15:00Z
    _release(monkeypatch, tmp_path, dict(LINE, at="2026-11-02T15:09:00+00:00"))    # 9 min ahead: clock skew, fine
    drive("D1", maint_watch)
    near = receipt("D1", maint_watch)
    _release(monkeypatch, tmp_path, dict(LINE, at="2026-11-02T15:11:00+00:00"))    # 11 min ahead: a future line
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert near["outcome"] == "PASS"
    assert rec["outcome"] == "UNKNOWN" and "is in the future" in rec["why"]


def test_cite_D2_an_empty_row_table_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    t = tmp_path / "rows.json"
    t.write_text(json.dumps({"epoch": "2026-10-20", "rows": []}), encoding="utf-8")
    monkeypatch.setattr(maint_watch, "ROWS_FILE", t)
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "zero records" in rec["why"]


def test_cite_D2_a_schedule_that_cannot_be_read_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2", "M4")
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    mr.write_receipt("M4", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")
    monkeypatch.setattr(maint_watch, "SCHEDULE_CHECK",
                        lambda now: {"state": "unknown", "problems": [], "why": "schtasks /Query exit 1"})
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "schedule UNKNOWN: schtasks /Query exit 1" in rec["why"]


def _stray_run(monkeypatch, write):
    """maint_run's RUN replaced by one that only calls `write(row_tool_receipt)` and exits 0: the row's tool wrote no
    receipt of its own in this run."""
    import maint_run as run

    def fake(argv, timeout):
        write()
        return 0, "", ""
    monkeypatch.setattr(run, "RUN", fake)


def test_cite_C1_a_receipt_from_another_run_is_not_this_runs(monkeypatch, tmp_path):
    import headers_tls_check
    import os
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr

    def other_run():
        saved = os.environ.get(mr.RUN_ENV)
        os.environ[mr.RUN_ENV] = "another-run"
        try:
            mr.write_receipt("C1", "PASS", n=0, why="from another run", tool="headers_tls_check.py")
        finally:
            os.environ[mr.RUN_ENV] = saved
    _stray_run(monkeypatch, other_run)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a C1 receipt" in rec["why"]


def test_cite_C1_a_receipt_from_before_the_run_is_stale(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    import maint_receipt as mr

    def stale():
        clock.set(2026, 11, 2, 10)                                     # an hour before the run began
        mr.write_receipt("C1", "PASS", n=0, why="stale", tool="headers_tls_check.py")
        clock.set(2026, 11, 2, 11, 1)
    _stray_run(monkeypatch, stale)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a C1 receipt" in rec["why"]


def test_cite_C1_a_receipt_from_a_foreign_tool_is_not_the_rows(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    _stray_run(monkeypatch, lambda: mr.write_receipt("C1", "PASS", n=0, why="not my tool", tool="maint_pages.py"))
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a C1 receipt" in rec["why"]


def test_cite_C1_a_pass_with_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    _monitors(monkeypatch, MONS)

    def exits_2(argv, timeout):
        code, out, err = run.in_process(headers_tls_check)(argv, timeout)                         # the tool writes its PASS ...
        return 2, out, err + "\nthen died"                             # ... and the process exits 2
    monkeypatch.setattr(run, "RUN", exits_2)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]


def test_cite_W1_an_internal_check_that_could_not_run_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)

    def no_tree(root):
        raise OSError("the served tree is unreadable")
    monkeypatch.setattr(linkcheck, "served_pages", no_tree)
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "internal check could not run" in rec["why"]


def test_cite_M1_exit_0_with_an_unreadable_report_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 0, "pa11y-ci printed no JSON at all")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and "pa11y-ci exit 0 but its JSON report could not be read" in rec["why"]


def test_cite_A4_a_scanner_that_could_not_run_is_not_calibrated(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)

    def down():
        raise maint_quality.Unavailable("linkcheck could not start")
    _real_scanners(monkeypatch, **{"linkcheck.py": down})   # broken-internal-link is still SEEN by release.broken_links
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec["outcome"] == "UNKNOWN" and "Scanners that could not run: linkcheck.py" in rec["why"]


def test_cite_W3_no_served_page_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"index.html": None, "lessons/index.html": None,
                                       "lessons/find-your-door/index.html": None, "lessons/alpha/index.html": None},
               names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and "no served HTML page found at HEAD" in rec["why"]


def test_cite_M3_a_mixed_content_grep_that_fails_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch)

    def grep_fails(root):
        raise RuntimeError("git grep exit 128")
    monkeypatch.setattr(headers_tls_check, "git_grep_http", grep_fails)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "mixed content: git grep exit 128" in rec["why"]


def test_cite_Q4_a_dns_lookup_error_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _dns(monkeypatch)
    table = headers_tls_check.resolve
    monkeypatch.setattr(headers_tls_check, "resolve", lambda name, rtype: ("error", ["LifetimeTimeout"])
                        if rtype == "TXT" else table(name, rtype))
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "TXT: LifetimeTimeout" in rec["why"]

# ================================================================== round 8: maint_run's receipt intake, row by row
# Every row is driven through tools/maint_run.py, so every row's cites must refuse what the runner must refuse: a
# receipt from another run, one from before the run, one from another tool, and a PASS whose process then exits
# unexplained. Each attack replaces only maint_run's RUN (the child process) for the row.
def _intake_attack(monkeypatch, clock, row, kind):
    import os

    import maint_receipt as mr
    import maint_run as run
    own = run.RUNNERS[row][0]
    other = "maint_pages.py" if own != "maint_pages.py" else "linkcheck.py"

    def fake(argv, timeout):
        if kind == "another_run":
            saved = os.environ.get(mr.RUN_ENV)
            os.environ[mr.RUN_ENV] = "another-run"
            try:
                mr.write_receipt(row, "PASS", n=0, why="from another run", tool=own)
            finally:
                os.environ[mr.RUN_ENV] = saved
            return 0, "", ""
        if kind == "stale":
            t = clock.t
            clock.t = t - dt.timedelta(hours=1)
            mr.write_receipt(row, "PASS", n=0, why="written an hour before the run", tool=own)
            clock.t = t + dt.timedelta(minutes=1)
            return 0, "", ""
        if kind == "foreign":
            mr.write_receipt(row, "PASS", n=0, why="written by another tool", tool=other)
            return 0, "", ""
        if kind == "crash":                                                             # no receipt at all
            return 3, "", "Traceback: the runner died before writing anything"
        mr.write_receipt(row, "PASS", n=0, why="then the process died", tool=own)       # unexplained exit
        return 2, "", "Traceback: then the process died"
    monkeypatch.setattr(run, "RUN", fake)


def test_cite_W1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1", "another_run")
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1 receipt" in rec["why"]


def test_cite_W1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1", "stale")
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1 receipt" in rec["why"]


def test_cite_W1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1", "foreign")
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1 receipt" in rec["why"]


def test_cite_W1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1", "unexplained")
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_W1b_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1b", "another_run")
    drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1b receipt" in rec["why"]


def test_cite_W1b_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1b", "stale")
    drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1b receipt" in rec["why"]


def test_cite_W1b_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1b", "foreign")
    drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "without a W1b receipt" in rec["why"]


def test_cite_W1b_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1b", "unexplained")
    drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_W2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "W2", "another_run")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a W2 receipt" in rec["why"]


def test_cite_W2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "W2", "stale")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a W2 receipt" in rec["why"]


def test_cite_W2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "W2", "foreign")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a W2 receipt" in rec["why"]


def test_cite_W2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "W2", "unexplained")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_W3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W3", "another_run")
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a W3 receipt" in rec["why"]


def test_cite_W3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W3", "stale")
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a W3 receipt" in rec["why"]


def test_cite_W3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W3", "foreign")
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a W3 receipt" in rec["why"]


def test_cite_W3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W3", "unexplained")
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_D1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D1", "another_run")
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D1 receipt" in rec["why"]


def test_cite_D1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D1", "stale")
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D1 receipt" in rec["why"]


def test_cite_D1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D1", "foreign")
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D1 receipt" in rec["why"]


def test_cite_D1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D1", "unexplained")
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_D2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D2", "another_run")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D2 receipt" in rec["why"]


def test_cite_D2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D2", "stale")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D2 receipt" in rec["why"]


def test_cite_D2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D2", "foreign")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D2 receipt" in rec["why"]


def test_cite_D2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D2", "unexplained")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_D3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D3", "another_run")
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D3 receipt" in rec["why"]


def test_cite_D3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D3", "stale")
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D3 receipt" in rec["why"]


def test_cite_D3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D3", "foreign")
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a D3 receipt" in rec["why"]


def test_cite_D3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "D3", "unexplained")
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1", "another_run")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1 receipt" in rec["why"]


def test_cite_M1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1", "stale")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1 receipt" in rec["why"]


def test_cite_M1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1", "foreign")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1 receipt" in rec["why"]


def test_cite_M1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1", "unexplained")
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M1b_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1b", "another_run")
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1b receipt" in rec["why"]


def test_cite_M1b_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1b", "stale")
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1b receipt" in rec["why"]


def test_cite_M1b_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1b", "foreign")
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M1b receipt" in rec["why"]


def test_cite_M1b_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1b", "unexplained")
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2", "another_run")
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2 receipt" in rec["why"]


def test_cite_M2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2", "stale")
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2 receipt" in rec["why"]


def test_cite_M2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2", "foreign")
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2 receipt" in rec["why"]


def test_cite_M2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2", "unexplained")
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M2b_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2b", "another_run")
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2b receipt" in rec["why"]


def test_cite_M2b_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2b", "stale")
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2b receipt" in rec["why"]


def test_cite_M2b_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2b", "foreign")
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a M2b receipt" in rec["why"]


def test_cite_M2b_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2b", "unexplained")
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M3", "another_run")
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a M3 receipt" in rec["why"]


def test_cite_M3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M3", "stale")
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a M3 receipt" in rec["why"]


def test_cite_M3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M3", "foreign")
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a M3 receipt" in rec["why"]


def test_cite_M3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M3", "unexplained")
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M4_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M4", "another_run")
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a M4 receipt" in rec["why"]


def test_cite_M4_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M4", "stale")
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a M4 receipt" in rec["why"]


def test_cite_M4_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M4", "foreign")
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a M4 receipt" in rec["why"]


def test_cite_M4_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M4", "unexplained")
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_M5_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "M5", "another_run")
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a M5 receipt" in rec["why"]


def test_cite_M5_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "M5", "stale")
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a M5 receipt" in rec["why"]


def test_cite_M5_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "M5", "foreign")
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a M5 receipt" in rec["why"]


def test_cite_M5_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "M5", "unexplained")
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q1", "another_run")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q1 receipt" in rec["why"]


def test_cite_Q1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q1", "stale")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q1 receipt" in rec["why"]


def test_cite_Q1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q1", "foreign")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q1 receipt" in rec["why"]


def test_cite_Q1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q1", "unexplained")
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q2", "another_run")
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q2 receipt" in rec["why"]


def test_cite_Q2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q2", "stale")
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q2 receipt" in rec["why"]


def test_cite_Q2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q2", "foreign")
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q2 receipt" in rec["why"]


def test_cite_Q2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q2", "unexplained")
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q3", "another_run")
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q3 receipt" in rec["why"]


def test_cite_Q3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q3", "stale")
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q3 receipt" in rec["why"]


def test_cite_Q3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q3", "foreign")
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q3 receipt" in rec["why"]


def test_cite_Q3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q3", "unexplained")
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q4_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q4", "another_run")
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q4 receipt" in rec["why"]


def test_cite_Q4_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q4", "stale")
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q4 receipt" in rec["why"]


def test_cite_Q4_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q4", "foreign")
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q4 receipt" in rec["why"]


def test_cite_Q4_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q4", "unexplained")
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q5_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q5", "another_run")
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q5 receipt" in rec["why"]


def test_cite_Q5_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q5", "stale")
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q5 receipt" in rec["why"]


def test_cite_Q5_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q5", "foreign")
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q5 receipt" in rec["why"]


def test_cite_Q5_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q5", "unexplained")
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_Q6_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "Q6", "another_run")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q6 receipt" in rec["why"]


def test_cite_Q6_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "Q6", "stale")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q6 receipt" in rec["why"]


def test_cite_Q6_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "Q6", "foreign")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a Q6 receipt" in rec["why"]


def test_cite_Q6_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "Q6", "unexplained")
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_H1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H1", "another_run")
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a H1 receipt" in rec["why"]


def test_cite_H1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H1", "stale")
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a H1 receipt" in rec["why"]


def test_cite_H1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H1", "foreign")
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a H1 receipt" in rec["why"]


def test_cite_H1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H1", "unexplained")
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_H2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H2", "another_run")
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H2 receipt" in rec["why"]


def test_cite_H2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H2", "stale")
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H2 receipt" in rec["why"]


def test_cite_H2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H2", "foreign")
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H2 receipt" in rec["why"]


def test_cite_H2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H2", "unexplained")
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_H3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H3", "another_run")
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H3 receipt" in rec["why"]


def test_cite_H3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H3", "stale")
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H3 receipt" in rec["why"]


def test_cite_H3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H3", "foreign")
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "without a H3 receipt" in rec["why"]


def test_cite_H3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _intake_attack(monkeypatch, clock, "H3", "unexplained")
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_A1_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A1", "another_run")
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A1 receipt" in rec["why"]


def test_cite_A1_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A1", "stale")
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A1 receipt" in rec["why"]


def test_cite_A1_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A1", "foreign")
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A1 receipt" in rec["why"]


def test_cite_A1_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A1", "unexplained")
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_A2_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A2", "another_run")
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a A2 receipt" in rec["why"]


def test_cite_A2_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A2", "stale")
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a A2 receipt" in rec["why"]


def test_cite_A2_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A2", "foreign")
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "without a A2 receipt" in rec["why"]


def test_cite_A2_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A2", "unexplained")
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_A3_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A3", "another_run")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A3 receipt" in rec["why"]


def test_cite_A3_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A3", "stale")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A3 receipt" in rec["why"]


def test_cite_A3_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A3", "foreign")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "without a A3 receipt" in rec["why"]


def test_cite_A3_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A3", "unexplained")
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]

def test_cite_A4_maint_run_refuses_a_receipt_from_another_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A4", "another_run")
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a A4 receipt" in rec["why"]


def test_cite_A4_maint_run_refuses_a_receipt_from_before_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A4", "stale")
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a A4 receipt" in rec["why"]


def test_cite_A4_maint_run_refuses_a_receipt_from_another_tool(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A4", "foreign")
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "without a A4 receipt" in rec["why"]


def test_cite_A4_maint_run_a_pass_then_an_unexplained_exit_is_unknown(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A4", "unexplained")
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert rec.get("outcome") == "UNKNOWN" and "a non-zero exit is not a pass" in rec["why"]


# ================================================================== D2: a hand close (maint_watch judge / human)
def plant_awaiting(row, script, why, ev_rel):
    """An `awaiting ...` SKIP for `row` as its runner `script` writes it, with its evidence file under .maint/: the
    input a hand close needs (written through maint_receipt, the shared writer)."""
    import maint_receipt as mr
    p = mr.maint_dir() / ev_rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("# the evidence pack\n", encoding="utf-8")
    return mr.write_receipt(row, "SKIP", why=why, evidence=".maint/" + ev_rel, tool=script)


def test_cite_D2_a_hand_close_of_M1b_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "M1b")
    plant_awaiting("M1b", "maint_quality.py", 'awaiting site-maintainer judgement: 1 element(s) painted over by body::before', "packs/M1b/index.md")
    code, prev, shut = close("M1b", maint_watch, *('judge', 'M1b', 'PASS', '--seat', 'site-maintainer', '--note', 'judged by eye on every template'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "M1b" not in rec["why"]

def test_cite_D2_a_hand_close_of_M4_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "M4")
    plant_awaiting("M4", "maint_pages.py", 'awaiting managing-editor judgement: the walkthrough pack', "packs/M4/index.md")
    code, prev, shut = close("M4", maint_watch, *('judge', 'M4', 'FINDINGS', '1', '--seat', 'managing-editor', '--note', 'one term needs a gloss'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 1 and shut["outcome"] == "FINDINGS" and shut["n"] == 1 and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "M4" not in rec["why"]

def test_cite_D2_a_hand_close_of_Q1_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "Q1")
    plant_awaiting("Q1", "maint_pages.py", 'awaiting managing-editor judgement: 23 pages due', "packs/Q1/index.md")
    code, prev, shut = close("Q1", maint_watch, *('judge', 'Q1', 'PASS', '--seat', 'managing-editor', '--note', 're-read; no change'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "Q1" not in rec["why"]

def test_cite_D2_a_hand_close_of_A2_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "A2")
    plant_awaiting("A2", "maint_pages.py", 'awaiting managing-editor judgement: the inventory', "packs/A2/index.md")
    code, prev, shut = close("A2", maint_watch, *('judge', 'A2', 'PASS', '--seat', 'managing-editor', '--note', 'nothing redundant'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "A2" not in rec["why"]

def test_cite_D2_a_hand_close_of_H1_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "H1")
    plant_awaiting("H1", "maint_human.py", "awaiting Daniel's ruling: H1 pack", "packs/H1/index.md")
    code, prev, shut = close("H1", maint_watch, *('human', 'H1', 'E01234'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "H1" not in rec["why"]

def test_cite_D2_a_hand_close_of_A1_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "A1")
    plant_awaiting("A1", "maint_human.py", "awaiting Daniel's ruling: A1 pack", "packs/A1/index.md")
    code, prev, shut = close("A1", maint_watch, *('human', 'A1', 'E04321'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "A1" not in rec["why"]

def test_cite_D2_a_hand_close_of_A3_follows_its_awaiting_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "A3")
    plant_awaiting("A3", "maint_human.py", "awaiting Daniel's ruling: expires 2026-12-20 (47 days), the 60-day window is open", "packs/A3/index.md")
    code, prev, shut = close("A3", maint_watch, *('human', 'A3', 'E05555'))
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert code == 0 and shut["outcome"] == "PASS" and hand_close_ok(prev, shut)
    assert rec["outcome"] == "PASS" and "A3" not in rec["why"]

# ================================================================== round 9: maint_run's exit code and run_end, row by row
# A runner that dies without a receipt is the RUN's failure: maint_run exits 2 and run_end names the row in rows_failed.

def test_cite_C1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "C1", "crash")
    code = drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    end = run_end("C1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a C1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["C1"]

def test_cite_W1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1", "crash")
    code = drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    end = run_end("W1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a W1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["W1"]

def test_cite_W1b_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import linkcheck
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W1b", "crash")
    code = drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    end = run_end("W1b")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a W1b receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["W1b"]

def test_cite_W3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W3", "crash")
    code = drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    end = run_end("W3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a W3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["W3"]

def test_cite_M1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1", "crash")
    code = drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    end = run_end("M1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M1"]

def test_cite_M1b_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M1b", "crash")
    code = drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    end = run_end("M1b")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M1b receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M1b"]

def test_cite_M2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2", "crash")
    code = drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    end = run_end("M2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M2"]

def test_cite_M2b_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M2b", "crash")
    code = drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    end = run_end("M2b")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M2b receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M2b"]

def test_cite_M3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M3", "crash")
    code = drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    end = run_end("M3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M3"]

def test_cite_M4_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M4", "crash")
    code = drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    end = run_end("M4")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M4 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M4"]

def test_cite_Q1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q1", "crash")
    code = drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    end = run_end("Q1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q1"]

def test_cite_Q2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q2", "crash")
    code = drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    end = run_end("Q2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q2"]

def test_cite_Q3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q3", "crash")
    code = drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    end = run_end("Q3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q3"]

def test_cite_Q4_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q4", "crash")
    code = drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    end = run_end("Q4")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q4 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q4"]

def test_cite_Q5_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q5", "crash")
    code = drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    end = run_end("Q5")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q5 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q5"]

def test_cite_A2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A2", "crash")
    code = drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    end = run_end("A2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a A2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["A2"]

def test_cite_A4_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_quality
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A4", "crash")
    code = drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    end = run_end("A4")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a A4 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["A4"]

def test_cite_W2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "W2", "crash")
    code = drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    end = run_end("W2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a W2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["W2"]

def test_cite_M5_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "M5", "crash")
    code = drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    end = run_end("M5")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a M5 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["M5"]

def test_cite_H2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H2", "crash")
    code = drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    end = run_end("H2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a H2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["H2"]

def test_cite_H3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H3", "crash")
    code = drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    end = run_end("H3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a H3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["H3"]

def test_cite_H1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "H1", "crash")
    code = drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    end = run_end("H1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a H1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["H1"]

def test_cite_A1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A1", "crash")
    code = drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    end = run_end("A1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a A1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["A1"]

def test_cite_A3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_human
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "A3", "crash")
    code = drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    end = run_end("A3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a A3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["A3"]

def test_cite_Q6_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "Q6", "crash")
    code = drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    end = run_end("Q6")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a Q6 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["Q6"]

def test_cite_D1_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "D1", "crash")
    code = drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    end = run_end("D1")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a D1 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["D1"]

def test_cite_D2_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "D2", "crash")
    code = drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    end = run_end("D2")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a D2 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["D2"]

def test_cite_D3_a_runner_that_dies_fails_the_run(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path)
    _intake_attack(monkeypatch, clock, "D3", "crash")
    code = drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    end = run_end("D3")
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a D3 receipt" in rec["why"]
    assert code == 2 and end.get("exit") == 2 and end.get("rows_failed") == ["D3"]


# ================================================================== round 9: maint_run's REAL child process (run_process)
CHILD_EXIT_3 = "import sys\nsys.exit(3)\n"
CHILD_SLEEPS = "import time\ntime.sleep(60)\n"
CHILD_CWD = "import os, sys\nprint('cwd=' + os.path.basename(os.getcwd()), file=sys.stderr)\nsys.exit(3)\n"


def child_tool(monkeypatch, tmp_path, row, body, timeout=None):
    """maint_run's runner script for `row`, replaced by a tiny child script under tmp_path (TOOLS_DIR is maint_run's
    public seam for this): maint_run then launches it for real with run_process. -> the scripts folder."""
    import maint_run as run
    d = tmp_path / "child-tools"
    d.mkdir(parents=True, exist_ok=True)
    script, args, t = run.RUNNERS[row]
    (d / script).write_text(body, encoding="utf-8")
    monkeypatch.setattr(run, "TOOLS_DIR", d)
    if timeout is not None:
        monkeypatch.setitem(run.RUNNERS, row, (script, args, timeout))
    return d


def test_cite_W1_a_child_s_exit_code_is_read(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    child_tool(monkeypatch, tmp_path, "W1", CHILD_EXIT_3)
    code = drive_real("W1")
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "exited 3 without a W1 receipt" in rec["why"]
    assert code == 2 and run_end("W1").get("rows_failed") == ["W1"]


def test_cite_W1_a_child_past_its_timeout_is_stopped(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    child_tool(monkeypatch, tmp_path, "W1", CHILD_SLEEPS, timeout=2)
    code = drive_real("W1")
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "timed out after 2 s and was stopped" in rec["why"] and code == 2


def test_cite_W1_a_child_that_cannot_launch_could_not_start(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    child_tool(monkeypatch, tmp_path, "W1", CHILD_EXIT_3)
    monkeypatch.setattr(run, "REPO", tmp_path / "no-such-folder")         # the child's working folder is gone
    code = drive_real("W1")
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and rec["why"].startswith("runner could not start") and code == 2


def test_cite_W1_the_child_runs_in_the_repo_root(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    child_tool(monkeypatch, tmp_path, "W1", CHILD_CWD)
    root = tmp_path / "repo-root-w1"
    root.mkdir()
    monkeypatch.setattr(run, "REPO", root)
    drive_real("W1")
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "cwd=repo-root-w1" in rec["why"]


def test_cite_M2_the_row_s_timeout_reaches_the_child(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    asked = []

    def records(argv, timeout):
        asked.append(timeout)
        return 3, "", "stopped by the test"
    monkeypatch.setattr(run, "RUN", records)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert asked == [run.RUNNERS["M2"][2]] and rec.get("outcome") == "UNKNOWN"


def test_cite_W1_a_foreign_module_with_the_same_tool_is_refused(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)

    class LookAlike:
        """Declares linkcheck's TOOL; is not linkcheck."""
        TOOL = linkcheck.TOOL

        def main(self, argv):
            import maint_receipt as mr
            mr.write_receipt("W1", "PASS", n=0, why="a look-alike's PASS", tool=self.TOOL)
            return 0
    code = drive("W1", LookAlike())
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and rec["why"].startswith("runner could not start") and code == 2


def test_cite_W1_another_real_module_is_refused(monkeypatch, tmp_path):
    import linkcheck
    import maint_run
    md, _ = world(monkeypatch, tmp_path)
    code = drive("W1", maint_run)                                        # a real module, but not linkcheck.py
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "the module handed in is not this script" in rec["why"] and code == 2


# ================================================================== round 9: git that fails inside the scanned tree
def test_cite_W1_a_head_that_cannot_be_resolved_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    repo = site_repo(linkcheck, tmp_path)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/no-such-branch\n", encoding="utf-8")
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "git rev-parse HEAD failed" in rec["why"]


def test_cite_W1_git_that_cannot_start_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    repo = site_repo(linkcheck, tmp_path)
    empty = tmp_path / "no-git-here"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))                              # no git binary on the path
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "git rev-parse HEAD failed" in rec["why"] and "exit 127" in rec["why"]


def test_cite_W3_a_page_git_cannot_read_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    code, sha = maint_pages.git(repo, "rev-parse", "HEAD:lessons/alpha/index.html")
    blob = repo / ".git" / "objects" / sha.strip()[:2] / sha.strip()[2:]
    blob.chmod(0o666)                                                   # git writes its objects read-only
    blob.unlink()                                                       # the page's object is gone from the tree
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert code == 0 and rec["outcome"] == "UNKNOWN" and "could not run: git show" in rec["why"]


def test_cite_W3_git_that_cannot_start_mid_scan_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    listed = maint_pages.served_files
    empty = tmp_path / "no-git-here"
    empty.mkdir()

    def list_then_lose_git(repo, exts=(".html",)):
        pages = listed(repo, exts)
        monkeypatch.setenv("PATH", str(empty))                          # git is gone once the page list is read
        return pages
    monkeypatch.setattr(maint_pages, "served_files", list_then_lose_git)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and "could not run: git could not start" in rec["why"]


# ================================================================== round 9: a zone that is not the machine's (A07)
FAR_EAST = dt.timezone(dt.timedelta(hours=9))


def test_cite_D1_the_release_day_is_the_calendar_zone_s(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    monkeypatch.setattr(mr, "LOCAL_TZ", FAR_EAST)                       # +09:00: never this machine's zone
    clock.t = dt.datetime(2026, 11, 2, 11, 0, tzinfo=FAR_EAST)          # 02:00Z; the US day is still 11-01
    _release(monkeypatch, tmp_path, dict(LINE, at="2026-11-01T23:35:00+00:00"))   # 08:35 on 11-02 at +09:00
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert rec["outcome"] == "PASS" and rec["why"].startswith("2026-11-02: 08:35 PUBLISHED")


def far_east(monkeypatch, clock, *when):
    """The calendar's zone pinned to +09:00 (never this machine's), and the clock set to a wall time there."""
    import maint_receipt as mr
    monkeypatch.setattr(mr, "LOCAL_TZ", FAR_EAST)
    clock.t = dt.datetime(*when, tzinfo=FAR_EAST)


def test_cite_D2_cadence_runs_on_the_calendar_zone_s_days(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D2", "D1")
    far_east(monkeypatch, clock, 2026, 11, 2, 8, 40)                    # 08:40 on 11-02 here = 11-01 23:40Z
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    far_east(monkeypatch, clock, 2026, 11, 3, 5, 0)                     # D1's next 10:30 here is still ahead
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "PASS" and "none UNKNOWN" in rec["why"]


def test_cite_W2_the_digest_s_week_ends_on_the_calendar_zone_s_day(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    far_east(monkeypatch, clock, 2026, 11, 2, 11, 0)                    # 02:00Z: the US day is still 11-01
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "PASS" and "week to 2026-11-02" in _digest(md, rec)


def test_cite_Q6_the_drill_withholds_the_calendar_zone_s_today(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    far_east(monkeypatch, clock, 2026, 11, 2, 11, 0)                    # 02:00Z: the US day is still 11-01
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert rec["outcome"] == "SKIP" and "the 2026-11-02 heartbeat is withheld" in rec["why"]


# ================================================================== round 9: D2's owed-judgement clock (A17, A18)
def _owed_m4(clock, later_outcome, later_why):
    """M4 awaiting a judgement since 2026-11-02, then (on 2027-01-05) a line that is NOT a close; D2 runs 2027-01-06."""
    import maint_receipt as mr
    plant_awaiting("M4", "maint_pages.py", "awaiting managing-editor judgement: the walkthrough pack",
                   "packs/M4/index.md")
    clock.set(2027, 1, 5, 11)
    mr.write_receipt("M4", later_outcome, n=1 if later_outcome == "FINDINGS" else None, why=later_why,
                     tool="maint_pages.py")
    clock.set(2027, 1, 6, 11)


def test_cite_D2_a_line_that_is_not_a_close_leaves_the_judgement_owed(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "M4")
    _owed_m4(clock, "SKIP", "walkthrough re-run: nothing new")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "M4" in rec["why"] and "awaiting judgement since 2026-11-02" in rec["why"]


def test_cite_D2_scanner_findings_are_not_a_judgement(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    _table(monkeypatch, tmp_path, "D2", "M4")
    _owed_m4(clock, "FINDINGS", "1 unglossed term on the route")
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "M4" in rec["why"] and "awaiting judgement since 2026-11-02" in rec["why"]


# ================================================================== round 9: the judge's precondition (A19, A20)
def test_cite_M4_a_judge_close_needs_the_row_s_own_awaiting_line(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: a pack from another tool",
                     evidence=rec["evidence"], tool="maint_quality.py")             # not M4's runner
    code, prev, after = close("M4", maint_watch, "judge", "M4", "PASS", "--seat", "managing-editor", "--note", "ok")
    assert rec["outcome"] == "SKIP" and code == 1 and after == prev           # refused: nothing written


def test_cite_M4_a_judge_close_needs_its_evidence_on_disk(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: the walkthrough pack",
                     evidence=".maint/packs/M4/gone.md", tool="maint_pages.py")      # names a pack that is not there
    code, prev, after = close("M4", maint_watch, "judge", "M4", "PASS", "--seat", "managing-editor", "--note", "ok")
    assert rec["outcome"] == "SKIP" and code == 1 and after == prev


def test_cite_M4_the_editors_judgement_closes_it(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    code, prev, shut = close("M4", maint_watch, "judge", "M4", "FINDINGS", "1", "--seat", "managing-editor", "--note",
                             "one term needs a gloss")
    rec = receipt("M4", maint_pages)
    assert rec == prev and code == 1 and (shut["outcome"], shut["n"]) == ("FINDINGS", 1) and hand_close_ok(prev, shut)


# ================================================================== round 10: the reviewer's mut12 survivors
def fatal_git_during(fn, tmp_path):
    """`fn` (a tool's own public function), wrapped so git fails FATALLY (exit 128: GIT_DIR points nowhere) for
    exactly that call, and works again after it."""
    import os
    nowhere = str(tmp_path / "no-repository-here")

    def wrapped(*args, **kwargs):
        saved = os.environ.get("GIT_DIR")
        os.environ["GIT_DIR"] = nowhere                     # every git command now dies with exit 128
        try:
            return fn(*args, **kwargs)
        finally:
            if saved is None:
                os.environ.pop("GIT_DIR", None)
            else:
                os.environ["GIT_DIR"] = saved
    return wrapped


def test_cite_W1_a_same_named_script_in_another_folder_is_refused(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "linkcheck.py").write_text("raise SystemExit(0)\n", encoding="utf-8")   # same name, other file
    monkeypatch.setattr(run, "TOOLS_DIR", elsewhere)
    code = drive("W1", linkcheck)                       # the real linkcheck module is not THAT linkcheck.py
    rec = receipt("W1", linkcheck)
    assert rec.get("outcome") == "UNKNOWN" and "the module handed in is not this script" in rec["why"] and code == 2


def test_cite_Q2_a_git_grep_that_dies_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    monkeypatch.setattr(maint_pages, "grep_tokens", fatal_git_during(maint_pages.grep_tokens, tmp_path))
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert rec["outcome"] == "UNKNOWN", rec


def test_cite_A2_a_git_log_that_dies_is_unknown(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setattr(maint_pages, "git_dates", fatal_git_during(maint_pages.git_dates, tmp_path))
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and "could not run: git log" in rec["why"]


def test_cite_M3_a_mixed_content_grep_that_dies_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import headers_tls_check as h
    real_grep = h.git_grep_http                             # the real grep, before _tls fakes it
    _tls(monkeypatch)
    monkeypatch.setattr(h, "git_grep_http", fatal_git_during(real_grep, tmp_path))
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "mixed content: git grep exit 128" in rec["why"]


def test_cite_M1_an_automate_row_cannot_be_judged(monkeypatch, tmp_path):
    import maint_quality
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _pa11y(monkeypatch, 0, json.dumps({"total": 23, "passes": 23, "errors": 0, "results": {"http://h/": []}}))
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    plant_awaiting("M1", "maint_quality.py", "awaiting site-maintainer judgement: a pack", "packs/M1/index.md")
    code, prev, after = close("M1", maint_watch, "judge", "M1", "PASS", "--seat", "site-maintainer", "--note", "ok")
    assert rec["outcome"] == "PASS" and code == 1 and after == prev     # M1 is AUTOMATE: its tool judges it


def test_cite_Q2_an_author_cannot_judge_the_sweep(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    code, prev, after = close("Q2", maint_watch, "judge", "Q2", "PASS", "--seat", "site-maintainer", "--note", "fine")
    assert rec["outcome"] == "SKIP" and code == 1 and after == prev     # Q2 needs a seat that did not write the pages


def test_cite_H1_a_close_needs_a_real_ledger_e_number(monkeypatch, tmp_path):
    import maint_human
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11, watch=maint_watch)
    _capture(monkeypatch)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    code, prev, after = close("H1", maint_watch, "human", "H1", "Eh, looks fine")
    assert rec["outcome"] == "SKIP" and code == 1 and after == prev


def test_cite_D3_a_4xx_from_the_heartbeat_is_not_delivered(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _hb(monkeypatch)
    monkeypatch.setattr(maint_watch, "HTTP_GET", lambda url: (404, "not found"))
    _d1d2()
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "FINDINGS" and "HTTP 404" in rec["why"]


def test_cite_M4_a_close_needs_the_latest_line_to_be_awaiting(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    pages_repo(monkeypatch, maint_pages, tmp_path)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    mr.write_receipt("M4", "SKIP", why="walkthrough not due", evidence=rec["evidence"], tool="maint_pages.py")
    code, prev, after = close("M4", maint_watch, "judge", "M4", "PASS", "--seat", "managing-editor", "--note", "ok")
    assert rec["outcome"] == "SKIP" and code == 1 and after == prev


def test_cite_D3_a_missing_d2_receipt_pings_fail(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    calls = _hb(monkeypatch)
    mr.write_receipt("D1", "PASS", why="ok", tool="maint_watch.py")          # D1 today, D2 never
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "PASS" and calls[-1].endswith("/fail") and "D2 no receipt today" in rec["why"]


def test_cite_D2_a_schedule_check_that_raises_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    _table(monkeypatch, tmp_path, "D1", "D2", "M4")
    mr.write_receipt("D1", "PASS", why="released", tool="maint_watch.py")
    mr.write_receipt("M4", "PASS", why="judged by managing-editor: ok", tool="maint_watch.py")

    def broken(now):
        raise RuntimeError("Task Scheduler did not answer")
    monkeypatch.setattr(maint_watch, "SCHEDULE_CHECK", broken)
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "schedule UNKNOWN: RuntimeError: Task Scheduler did not answer" in rec["why"]


#: A child that starts a grandchild (no pipes shared) and then outlives its timeout.
CHILD_WITH_GRANDCHILD = ("import pathlib, subprocess, sys, time\n"
                         "here = pathlib.Path(sys.argv[0]).parent\n"
                         "subprocess.Popen([sys.executable, str(here / 'grandchild.py')], stdin=subprocess.DEVNULL,\n"
                         "                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)\n"
                         "time.sleep(60)\n")
#: The grandchild: appends a byte to ../beats/heartbeat.txt every 0.05 s for 20 s, while it lives.
GRANDCHILD = ("import pathlib, sys, time\n"
              "beat = pathlib.Path(sys.argv[0]).parent.parent / 'beats' / 'heartbeat.txt'\n"
              "beat.parent.mkdir(exist_ok=True)\n"
              "for i in range(400):\n"
              "    with open(beat, 'a') as f:\n"
              "        f.write('x')\n"
              "    time.sleep(0.05)\n")


def test_cite_W1_a_timed_out_child_is_stopped_with_its_children(monkeypatch, tmp_path):
    import linkcheck
    import time
    md, _ = world(monkeypatch, tmp_path)
    d = child_tool(monkeypatch, tmp_path, "W1", CHILD_WITH_GRANDCHILD, timeout=3)
    (d / "grandchild.py").write_text(GRANDCHILD, encoding="utf-8")
    drive_real("W1")
    rec = receipt("W1", linkcheck)
    beat = tmp_path / "beats" / "heartbeat.txt"          # written by the grandchild alone
    time.sleep(0.5)
    before = beat.stat().st_size if beat.exists() else 0
    time.sleep(1.5)                                      # a live grandchild writes a byte every 0.05 s
    after = beat.stat().st_size if beat.exists() else 0
    assert rec.get("outcome") == "UNKNOWN" and "timed out after 3 s" in rec["why"]
    assert before > 0 and after == before                # it ran, and it was stopped with its parent


# ================================================================== round 10 sweep: every refusal is exit 1 and writes nothing
def refused(row, watch, *argv):
    """A hand act that must be REFUSED: exit 1, and the row's receipt log unchanged."""
    code, prev, after = close(row, watch, *argv)
    return code == 1 and after == prev


def _awaiting_m4(tmp_path):
    plant_awaiting("M4", "maint_pages.py", "awaiting managing-editor judgement: the walkthrough pack",
                   "packs/M4/index.md")


def test_cite_D2_a_judge_refuses_when_the_row_table_cannot_be_read(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    bad = tmp_path / "rows.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(maint_watch, "ROWS_FILE", bad)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "judge", "M4", "PASS", "--seat", "managing-editor", "--note", "ok")
    drive("D2", maint_watch)
    assert receipt("D2", maint_watch)["outcome"] == "UNKNOWN"


def test_cite_D2_a_judge_refuses_an_event_row(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    plant_awaiting("E1", "maint_run.py", "awaiting site-maintainer judgement: x", "packs/E1/index.md")
    assert refused("E1", maint_watch, "judge", "E1", "PASS", "--seat", "site-maintainer", "--note", "ok")
    assert refused("Z9", maint_watch, "judge", "Z9", "PASS", "--seat", "site-maintainer", "--note", "ok")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_a_judge_refuses_a_human_row(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    plant_awaiting("H1", "maint_human.py", "awaiting Daniel's ruling: H1 pack", "packs/H1/index.md")
    assert refused("H1", maint_watch, "judge", "H1", "PASS", "--seat", "managing-editor", "--note", "ok")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_a_judge_refuses_a_seat_that_is_not_a_seat(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "judge", "M4", "PASS", "--seat", "the-intern", "--note", "ok")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_a_judge_refuses_an_empty_note(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "judge", "M4", "PASS", "--seat", "managing-editor", "--note", "   ")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_a_judge_refuses_findings_without_a_count(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "judge", "M4", "FINDINGS", "--seat", "managing-editor", "--note", "x")
    assert refused("M4", maint_watch, "judge", "M4", "FINDINGS", "0", "--seat", "managing-editor", "--note", "x")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_a_hand_act_refuses_a_fixed_clock(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "--now", "2026-11-02T10:00:00+00:00", "judge", "M4", "PASS", "--seat",
                   "managing-editor", "--note", "ok")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_human_refuses_a_row_that_is_not_human(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _awaiting_m4(tmp_path)
    assert refused("M4", maint_watch, "human", "M4", "E01234")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_human_refuses_when_nothing_awaits(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    mr.write_receipt("H1", "SKIP", why="HUMAN row not due: next due 2027-01-04", tool="maint_human.py")
    assert refused("H1", maint_watch, "human", "H1", "E01234")
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_D2_human_takes_a_real_e_number_only(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    plant_awaiting("H1", "maint_human.py", "awaiting Daniel's ruling: H1 pack", "packs/H1/index.md")
    for bad in ("E12", "E1234567", "E01234x", "xE01234", "E0123a"):
        assert refused("H1", maint_watch, "human", "H1", bad), bad
    code, prev, shut = close("H1", maint_watch, "human", "H1", "e01234")       # lower case is upper-cased, then good
    assert code == 0 and shut["outcome"] == "PASS" and "E01234" in shut["why"]
    assert snap("D2") == []                        # a refused hand act runs no watch either


def test_cite_Q2_a_witness_refuses_when_nothing_awaits(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    assert refused("Q2", maint_watch, "witness", "privacy-safety", "--repo", str(repo))
    assert repo.is_dir()


def test_cite_Q2_a_witness_refuses_when_there_is_no_sweep(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    plant_awaiting("Q2", "maint_pages.py", "awaiting a witness: the sweep", "audits/q2.md")
    assert refused("Q2", maint_watch, "witness", "privacy-safety", "--repo", str(repo))
    assert repo.is_dir()


def _armed_q6(monkeypatch, maint_watch):
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    drive("Q6", maint_watch)
    return receipt("Q6", maint_watch)


def test_cite_Q6_a_second_drill_is_refused_while_one_is_armed(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    first = _armed_q6(monkeypatch, maint_watch)
    assert first["outcome"] == "SKIP" and refused("Q6", maint_watch, "drill")


def test_cite_Q6_a_drill_for_a_past_day_is_refused(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    assert refused("Q6", maint_watch, "drill", "--date", "2026-10-01")
    drive("Q6", maint_watch)
    assert receipt("Q6", maint_watch)["outcome"] == "SKIP"


def test_cite_Q6_confirm_refuses_without_an_armed_drill(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    assert refused("Q6", maint_watch, "confirm", "10:30")
    drive("Q6", maint_watch)
    assert receipt("Q6", maint_watch)["outcome"] == "UNKNOWN"


def test_cite_Q6_confirm_refuses_when_the_drill_line_is_not_awaiting(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    first = _armed_q6(monkeypatch, maint_watch)
    mr.write_receipt("Q6", "SKIP", why="not this quarter", evidence=first["evidence"], tool="maint_watch.py")
    assert first["outcome"] == "SKIP" and refused("Q6", maint_watch, "confirm", "10:30")


def test_cite_Q6_confirm_refuses_a_time_it_cannot_read(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    first = _armed_q6(monkeypatch, maint_watch)
    assert first["outcome"] == "SKIP"
    assert refused("Q6", maint_watch, "confirm", "25:99")
    assert refused("Q6", maint_watch, "confirm", "teatime")


# ================================================================== round 10 sweep: maint_run's run, exit by exit, row by row
def fake_runner(monkeypatch, row, outcome, code, asked=None):
    """maint_run's RUN replaced by a child that writes the row's `outcome` receipt (as the row's own tool) and exits
    `code`; `asked` collects the timeout maint_run passed."""
    import maint_receipt as mr
    import maint_run as run
    own = run.RUNNERS[row][0]

    def fake(argv, timeout):
        if asked is not None:
            asked.append(timeout)
        if outcome:
            mr.write_receipt(row, outcome, n=1 if outcome == "FINDINGS" else None, why=f"a {outcome} from the child",
                             tool=own)
        return code, "", ""
    monkeypatch.setattr(run, "RUN", fake)


def exit_case(monkeypatch, row, tool, outcome, code):
    """One maint_run run of `row` whose child wrote `outcome` and exited `code` -> (receipt, run_end, exit code)."""
    fake_runner(monkeypatch, row, outcome, code)
    rc = drive(row, tool)
    return receipt(row, tool), run_end(row), rc


def test_cite_C1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "C1", None, 3, asked)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for C1: 120 s


def test_cite_C1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "C1", headers_tls_check, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "C1", headers_tls_check, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["C1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "C1", headers_tls_check, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["C1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "C1", headers_tls_check, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["C1"] and rc == 2


def test_cite_W1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "W1", None, 3, asked)
    drive("W1", linkcheck)
    rec = receipt("W1", linkcheck)
    assert asked == [3600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for W1: 3600 s


def test_cite_W1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "W1", linkcheck, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "W1", linkcheck, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W1", linkcheck, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["W1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W1", linkcheck, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W1"] and rc == 2


def test_cite_W1b_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "W1b", None, 3, asked)
    drive("W1b", linkcheck)
    rec = receipt("W1b", linkcheck)
    assert asked == [3600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for W1b: 3600 s


def test_cite_W1b_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "W1b", linkcheck, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "W1b", linkcheck, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W1b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W1b", linkcheck, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["W1b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W1b", linkcheck, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W1b"] and rc == 2


def test_cite_W3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "W3", None, 3, asked)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert asked == [900] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for W3: 900 s


def test_cite_W3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "W3", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "W3", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W3", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["W3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W3", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W3"] and rc == 2


def test_cite_M1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M1", None, 3, asked)
    drive("M1", maint_quality)
    rec = receipt("M1", maint_quality)
    assert asked == [7200] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M1: 7200 s


def test_cite_M1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M1", maint_quality, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M1", maint_quality, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M1", maint_quality, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M1", maint_quality, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M1"] and rc == 2


def test_cite_M1b_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M1b", None, 3, asked)
    drive("M1b", maint_quality)
    rec = receipt("M1b", maint_quality)
    assert asked == [3600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M1b: 3600 s


def test_cite_M1b_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M1b", maint_quality, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M1b", maint_quality, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M1b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M1b", maint_quality, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M1b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M1b", maint_quality, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M1b"] and rc == 2


def test_cite_M2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M2", None, 3, asked)
    drive("M2", maint_quality)
    rec = receipt("M2", maint_quality)
    assert asked == [7200] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M2: 7200 s


def test_cite_M2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M2", maint_quality, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M2", maint_quality, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M2", maint_quality, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M2", maint_quality, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M2"] and rc == 2


def test_cite_M2b_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M2b", None, 3, asked)
    drive("M2b", maint_quality)
    rec = receipt("M2b", maint_quality)
    assert asked == [300] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M2b: 300 s


def test_cite_M2b_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M2b", maint_quality, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M2b", maint_quality, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M2b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M2b", maint_quality, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M2b"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M2b", maint_quality, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M2b"] and rc == 2


def test_cite_M3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M3", None, 3, asked)
    drive("M3", headers_tls_check)
    rec = receipt("M3", headers_tls_check)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M3: 600 s


def test_cite_M3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M3", headers_tls_check, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M3", headers_tls_check, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M3", headers_tls_check, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M3", headers_tls_check, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M3"] and rc == 2


def test_cite_M4_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M4", None, 3, asked)
    drive("M4", maint_pages)
    rec = receipt("M4", maint_pages)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M4: 600 s


def test_cite_M4_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M4", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M4", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M4", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M4", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M4"] and rc == 2


def test_cite_Q1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q1", None, 3, asked)
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q1: 600 s


def test_cite_Q1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q1", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q1", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q1", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q1", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q1"] and rc == 2


def test_cite_Q2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q2", None, 3, asked)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    assert asked == [900] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q2: 900 s


def test_cite_Q2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q2", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q2", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q2", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q2", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q2"] and rc == 2


def test_cite_Q3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q3", None, 3, asked)
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q3: 600 s


def test_cite_Q3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q3", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q3", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q3", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q3", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q3"] and rc == 2


def test_cite_Q4_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q4", None, 3, asked)
    drive("Q4", headers_tls_check)
    rec = receipt("Q4", headers_tls_check)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q4: 600 s


def test_cite_Q4_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q4", headers_tls_check, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q4", headers_tls_check, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q4", headers_tls_check, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q4", headers_tls_check, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q4"] and rc == 2


def test_cite_Q5_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q5", None, 3, asked)
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert asked == [600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q5: 600 s


def test_cite_Q5_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q5", headers_tls_check, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q5", headers_tls_check, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q5"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q5", headers_tls_check, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q5"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q5", headers_tls_check, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q5"] and rc == 2


def test_cite_A2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "A2", None, 3, asked)
    drive("A2", maint_pages)
    rec = receipt("A2", maint_pages)
    assert asked == [900] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for A2: 900 s


def test_cite_A2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "A2", maint_pages, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "A2", maint_pages, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A2", maint_pages, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["A2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A2", maint_pages, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A2"] and rc == 2


def test_cite_A4_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "A4", None, 3, asked)
    drive("A4", maint_quality)
    rec = receipt("A4", maint_quality)
    assert asked == [3600] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for A4: 3600 s


def test_cite_A4_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "A4", maint_quality, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "A4", maint_quality, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A4", maint_quality, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["A4"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A4", maint_quality, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A4"] and rc == 2


def test_cite_W2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "W2", None, 3, asked)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert asked == [300] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for W2: 300 s


def test_cite_W2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "W2", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "W2", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W2", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["W2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "W2", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["W2"] and rc == 2


def test_cite_M5_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "M5", None, 3, asked)
    drive("M5", maint_watch)
    rec = receipt("M5", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for M5: 120 s


def test_cite_M5_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "M5", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "M5", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M5"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M5", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["M5"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "M5", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["M5"] and rc == 2


def test_cite_H2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "H2", None, 3, asked)
    drive("H2", maint_watch)
    rec = receipt("H2", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for H2: 120 s


def test_cite_H2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "H2", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "H2", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H2", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["H2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H2", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H2"] and rc == 2


def test_cite_H3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "H3", None, 3, asked)
    drive("H3", maint_watch)
    rec = receipt("H3", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for H3: 120 s


def test_cite_H3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "H3", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "H3", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H3", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["H3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H3", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H3"] and rc == 2


def test_cite_H1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "H1", None, 3, asked)
    drive("H1", maint_human)
    rec = receipt("H1", maint_human)
    assert asked == [1200] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for H1: 1200 s


def test_cite_H1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "H1", maint_human, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "H1", maint_human, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H1", maint_human, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["H1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "H1", maint_human, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["H1"] and rc == 2


def test_cite_A1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "A1", None, 3, asked)
    drive("A1", maint_human)
    rec = receipt("A1", maint_human)
    assert asked == [300] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for A1: 300 s


def test_cite_A1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "A1", maint_human, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "A1", maint_human, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A1", maint_human, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["A1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A1", maint_human, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A1"] and rc == 2


def test_cite_A3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "A3", None, 3, asked)
    drive("A3", maint_human)
    rec = receipt("A3", maint_human)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for A3: 120 s


def test_cite_A3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_human
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "A3", maint_human, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "A3", maint_human, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A3", maint_human, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["A3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "A3", maint_human, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["A3"] and rc == 2


def test_cite_Q6_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "Q6", None, 3, asked)
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for Q6: 120 s


def test_cite_Q6_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "Q6", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "Q6", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q6"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q6", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["Q6"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "Q6", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["Q6"] and rc == 2


def test_cite_D1_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "D1", None, 3, asked)
    drive("D1", maint_watch)
    rec = receipt("D1", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for D1: 120 s


def test_cite_D1_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "D1", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "D1", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D1", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["D1"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D1", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D1"] and rc == 2


def test_cite_D2_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "D2", None, 3, asked)
    drive("D2", maint_watch)
    rec = receipt("D2", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for D2: 120 s


def test_cite_D2_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "D2", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "D2", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D2", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["D2"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D2", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D2"] and rc == 2


def test_cite_D3_maint_run_gives_the_row_its_own_timeout(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    asked = []
    fake_runner(monkeypatch, "D3", None, 3, asked)
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert asked == [120] and rec.get("outcome") == "UNKNOWN"          # the calendar's timeout for D3: 120 s


def test_cite_D3_maint_run_explains_each_exit_by_its_receipt(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path)
    for outcome, code in (("PASS", 0), ("FINDINGS", 1), ("UNKNOWN", 2), ("SKIP", 2)):     # explained: the run is fine
        rec, end, rc = exit_case(monkeypatch, "D3", maint_watch, outcome, code)
        assert rec.get("outcome") == outcome and end.get("rows_failed") == [] and rc == 0 == end.get("exit"), outcome
    rec, end, rc = exit_case(monkeypatch, "D3", maint_watch, "PASS", 1)                       # a PASS that exits 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D3", maint_watch, "FINDINGS", 2)                   # FINDINGS do not explain 2
    assert rec.get("outcome") == "FINDINGS" and end.get("rows_failed") == ["D3"] and rc == 2
    rec, end, rc = exit_case(monkeypatch, "D3", maint_watch, "UNKNOWN", 1)                    # nor UNKNOWN 1
    assert rec.get("outcome") == "UNKNOWN" and end.get("rows_failed") == ["D3"] and rc == 2


def test_cite_C1_the_runner_quotes_the_last_160_characters_of_a_failure(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    monkeypatch.setattr(run, "RUN", lambda argv, timeout: (3, "", "first line\n" + "x" * 200))
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec.get("outcome") == "UNKNOWN" and rec["why"].endswith(": " + "x" * 160)


def test_cite_C1_the_run_start_marker_says_who_triggered_it(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, MONS)
    drive("C1", headers_tls_check)
    manual = [e for e in log_lines() if e.get("kind") == "run_start" and e.get("run_id") == DRIVES["C1"]["run_id"]]
    monkeypatch.setenv("MAINT_TRIGGER", "scheduled")
    drive("C1", headers_tls_check)
    sched = [e for e in log_lines() if e.get("kind") == "run_start" and e.get("run_id") == DRIVES["C1"]["run_id"]]
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "PASS" and manual[0]["trigger"] == "manual" and sched[0]["trigger"] == "scheduled"


def test_cite_C1_a_runner_that_raises_closes_the_run_with_exit_1(monkeypatch, tmp_path):
    import headers_tls_check
    import pytest
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run

    def explodes(argv, timeout):
        raise RuntimeError("the runner itself broke")
    monkeypatch.setattr(run, "RUN", explodes)
    with pytest.raises(RuntimeError):
        run.main(["--row", "C1"])
    ends = [e for e in log_lines() if e.get("kind") == "run_end"]
    assert ends and ends[-1]["exit"] == 1 and headers_tls_check.TOOL == "headers_tls_check.py"


def test_cite_C1_the_launch_is_the_py_launcher_s_when_it_started_the_run(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import maint_run as run
    own = (11, r"C:\\Python\\python.exe", "2026-11-02T16:00:00+00:00")
    for launcher in ("py.exe", "pyw.exe", "PY.EXE"):
        parent = (22, "C:\\Windows\\" + launcher, "2026-11-02T15:59:59+00:00")
        assert run.choose_launch(own, parent) == {"pid": 22, "proc_started": "2026-11-02T15:59:59+00:00"}, launcher
    for other in ("python.exe", "cmd.exe", "__sweep__", "py.exe.bak"):
        parent = (22, "C:\\Windows\\" + other, "2026-11-02T15:59:59+00:00")
        assert run.choose_launch(own, parent) == {"pid": 11, "proc_started": "2026-11-02T16:00:00+00:00"}, other
    assert run.choose_launch(own, (22, None, None))["pid"] == 11
    assert run.RUNNERS["C1"][0] == headers_tls_check.TOOL                      # C1's runs carry this launch record


# ================================================================== sweep: maint_watch's clock, line by line
def owns(row, tool):
    """`tool` (the module a cite imported) is the script maint_run.py runs for `row`."""
    import maint_receipt as mr
    import maint_run as run
    return mr.tool_path(tool.TOOL) == "tools/" + run.RUNNERS[row][0]


def local_at(*when):
    """A wall time in the cites' calendar zone (TZ)."""
    return dt.datetime(*when, tzinfo=TZ)


def real_row(watch, rid):
    """The calendar's own row `rid` (tools/maint_rows.json, through maint_watch's public load_rows)."""
    return watch.load_rows()["rows"][rid]


def one_row_table(watch, *rids):
    return {"rows": {r: real_row(watch, r) for r in rids}, "epoch_date": dt.date(2026, 10, 20)}


def rec_at(row, outcome, when, why="x", tool="maint_watch.py", **kw):
    """A receipt line as a tool writes it, stamped `when` (aware)."""
    return {"at": when.isoformat(timespec="seconds"), "row": row, "outcome": outcome,
            "n": 1 if outcome == "FINDINGS" else None, "why": why, "evidence": None, "tool": f"tools/{tool}",
            "run_id": None, **kw}


def test_cite_D1_the_release_window_is_08_25_to_10_30_inclusive(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    day, now = dt.date(2026, 11, 2), local_at(2026, 11, 2, 11, 0)

    def judged(*at):
        return maint_watch.judge_release_day([dict(LINE, at=local_at(*at).isoformat())], day, now)
    for at, inside in (((2026, 11, 2, 8, 25, 0), True), ((2026, 11, 2, 8, 24, 59), False),
                       ((2026, 11, 2, 10, 30, 0), True), ((2026, 11, 2, 10, 30, 1), False)):
        v = judged(*at)
        assert bool(v["scheduled"]) is inside and (v["problems"] == []) is inside, at
        if not inside:
            assert v["problems"][0].startswith("MISSING: no line from the 08:30 run by 10:30"), at
    skip = maint_watch.judge_release_day([dict(LINE, outcome="SKIP")], day, now)
    assert skip["problems"] == [] and skip["scheduled"]                  # a SKIP release is a fine day
    assert owns("D1", maint_watch)                           # this is D1's runner's logic


def test_cite_D1_pending_until_10_30_exactly(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    day = dt.date(2026, 11, 2)
    before = maint_watch.judge_release_day([], day, local_at(2026, 11, 2, 10, 29, 59))
    at = maint_watch.judge_release_day([], day, local_at(2026, 11, 2, 10, 30, 0))
    assert before["pending"] and before["problems"] == []
    assert not at["pending"] and at["problems"][0].startswith("MISSING")
    fail = maint_watch.judge_release_day([dict(LINE, outcome="FAIL", at=local_at(2026, 11, 2, 12, 0).isoformat())],
                                         day, local_at(2026, 11, 2, 13, 0))
    assert fail["problems"][0].startswith("MISSING") and "FAIL" in fail["problems"][1]   # MISSING comes first
    assert owns("D1", maint_watch)                           # this is D1's runner's logic


def test_cite_D1_a_release_day_in_the_future_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    import pytest
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    with pytest.raises(maint_watch.Unknown, match="is in the future"):
        maint_watch.judge_release_day([], dt.date(2026, 11, 3), local_at(2026, 11, 2, 11, 0))
    assert maint_watch.RELEASE_RUN_AT == dt.time(8, 30) and "D1" in maint_watch.ONE_ROWS


def test_cite_D2_each_kind_s_next_occurrence(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    occ = maint_watch.occ_on_or_after
    d1, w2, m4, q6, h1, a2 = (real_row(maint_watch, r) for r in ("D1", "W2", "M4", "Q6", "H1", "A2"))
    assert occ(d1, local_at(2026, 11, 2, 8, 0)) == local_at(2026, 11, 2, 8, 30)
    assert occ(d1, local_at(2026, 11, 2, 8, 30)) == local_at(2026, 11, 2, 8, 30)          # on the minute: that one
    assert occ(d1, local_at(2026, 11, 2, 8, 31)) == local_at(2026, 11, 3, 8, 30)
    assert occ(w2, local_at(2026, 11, 4, 0, 0)) == local_at(2026, 11, 9)                 # Wednesday -> Monday
    assert occ(w2, local_at(2026, 11, 9, 0, 0)) == local_at(2026, 11, 9)                 # Monday midnight itself
    assert occ(w2, local_at(2026, 11, 9, 0, 1)) == local_at(2026, 11, 16)
    assert occ(m4, local_at(2026, 11, 2, 0, 0)) == local_at(2026, 11, 2)                 # first Monday of November
    assert occ(m4, local_at(2026, 11, 2, 0, 1)) == local_at(2026, 12, 7)
    assert occ(m4, local_at(2026, 12, 8, 0, 0)) == local_at(2027, 1, 4)                  # over the year end
    assert occ(q6, local_at(2026, 11, 3, 0, 0)) == local_at(2027, 1, 4)
    assert occ(q6, local_at(2027, 1, 5, 0, 0)) == local_at(2027, 4, 5)
    assert occ(h1, local_at(2027, 1, 5, 0, 0)) == local_at(2027, 7, 5)
    assert occ(a2, local_at(2026, 11, 3, 0, 0)) == local_at(2027, 1, 4)
    assert occ(a2, local_at(2027, 1, 4, 0, 0)) == local_at(2027, 1, 4)
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_a_row_with_no_clock_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    import pytest
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    t = local_at(2026, 11, 2)
    for row, why in (({"id": "X1", "kind": "fortnightly"}, "has no clock"),
                     ({"id": "X2", "kind": "quarterly", "months": []}, "has no clock"),
                     ({"id": "X3", "kind": "quarterly", "months": [13]}, "no occurrence found")):
        with pytest.raises(maint_watch.Unknown, match=why):
            maint_watch.occ_on_or_after(row, t)
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_deadlines_by_kind(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    d1, m4 = real_row(maint_watch, "D1"), real_row(maint_watch, "M4")
    assert maint_watch.deadline_of(d1, local_at(2026, 11, 3, 8, 30)) == local_at(2026, 11, 3, 10, 30)   # due + 2 h
    assert maint_watch.deadline_of(m4, local_at(2026, 12, 7)) == local_at(2026, 12, 11)                 # + 1 d + 72 h
    assert maint_watch.due_from(d1, None, dt.date(2026, 10, 20), TZ) == local_at(2026, 10, 20, 8, 30)
    assert maint_watch.due_from(m4, local_at(2026, 11, 2, 13, 0), dt.date(2026, 10, 20), TZ) == local_at(2026, 12, 7)
    assert maint_watch.first_monday(2026, 11) == dt.date(2026, 11, 2) and maint_watch.first_monday(2027, 2) == \
        dt.date(2027, 2, 1)
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_overdue_starts_just_after_the_deadline(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    table = one_row_table(maint_watch, "D1")
    recs = [rec_at("D1", "PASS", local_at(2026, 11, 2, 9, 0))]           # next due 11-03 08:30, deadline 10:30
    at, after = local_at(2026, 11, 3, 10, 30), local_at(2026, 11, 3, 10, 30, 1)
    assert maint_watch.overdue_rows(table, recs, at) == ([], [])
    over, _ = maint_watch.overdue_rows(table, recs, after)
    assert [o["row"] for o in over] == ["D1"] and over[0]["deadline"] == at and over[0]["last"] == \
        local_at(2026, 11, 2, 9, 0)
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_a_board_or_note_row_is_closed_only_by_a_pass(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    for rid in ("M5", "H2"):
        table = one_row_table(maint_watch, rid)
        old_pass = local_at(2026, 10, 20, 9, 0)
        recs = [rec_at(rid, "PASS", old_pass), rec_at(rid, "FINDINGS", local_at(2027, 2, 20, 9, 0)),
                rec_at(rid, "UNKNOWN", local_at(2027, 2, 21, 9, 0))]
        over, _ = maint_watch.overdue_rows(table, recs, local_at(2027, 3, 1))
        assert [o["row"] for o in over] == [rid] and over[0]["last"] == old_pass, rid
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_an_unknown_streak_runs_from_its_first_line(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    table = one_row_table(maint_watch, "D1")
    first = local_at(2026, 11, 3, 9, 0)
    recs = [rec_at("D1", "PASS", local_at(2026, 11, 2, 9, 0)), rec_at("D1", "UNKNOWN", first, why="no log"),
            rec_at("D1", "UNKNOWN", local_at(2026, 11, 3, 9, 30), why="still no log")]
    stuck, pending = maint_watch.unknown_rows(table, recs, local_at(2026, 11, 3, 11, 0))          # first + 2 h
    assert stuck == [] and [(p["row"], p["since"], p["until"], p["why"]) for p in pending] == \
        [("D1", first, local_at(2026, 11, 3, 11, 0), "still no log")]
    stuck, pending = maint_watch.unknown_rows(table, recs, local_at(2026, 11, 3, 11, 0, 1))
    assert pending == [] and [s["row"] for s in stuck] == ["D1"]
    only = [rec_at("D1", "UNKNOWN", first, why="no log")]                                         # a streak of one
    assert maint_watch.unknown_rows(table, only, local_at(2026, 11, 3, 10, 0))[1][0]["since"] == first
    fine = recs + [rec_at("D1", "PASS", local_at(2026, 11, 3, 10, 0))]
    assert maint_watch.unknown_rows(table, fine, local_at(2026, 11, 9)) == ([], [])
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_W2_unknown_streaks_by_age(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    a, b = local_at(2026, 11, 3, 9, 0), local_at(2026, 11, 1, 9, 0)
    recs = [rec_at("D1", "PASS", local_at(2026, 11, 2, 9, 0)), rec_at("D1", "UNKNOWN", a, why="one"),
            rec_at("D1", "UNKNOWN", local_at(2026, 11, 3, 9, 30), why="two"),
            rec_at("M4", "UNKNOWN", b, why="m4"), rec_at("C1", "PASS", a)]
    out = maint_watch.unknown_streaks(recs)
    assert [(r, t, e["why"]) for r, t, e in out] == [("M4", b, "m4"), ("D1", a, "two")]
    assert owns("W2", maint_watch)                           # this is W2's runner's logic


def test_cite_W2_open_findings_are_the_latest_run_s(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    r1, r2 = local_at(2026, 11, 2, 9, 0), local_at(2026, 11, 3, 9, 0)
    recs = [rec_at("W1", "FINDINGS", r1), rec_at("W1", "FINDINGS", r2)]

    def f(subject, t):
        return {"at": t.isoformat(), "row": "W1", "severity": "S2", "subject": subject, "detail": "", "route_to": "x"}
    finds = [f("old", r1), f("at the previous run", r1), f("this run", local_at(2026, 11, 3, 8, 0)),
             f("at the latest run", r2), f("after the latest run", local_at(2026, 11, 3, 10, 0))]
    got = [x["subject"] for x in maint_watch.open_findings(recs, finds)]
    assert got == ["this run", "at the latest run"]
    assert owns("W2", maint_watch)                           # this is W2's runner's logic


def test_cite_D2_the_rdap_clock_and_its_window(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    row = real_row(maint_watch, "A3")
    epoch = dt.date(2026, 10, 20)
    poll = local_at(2026, 11, 2, 11, 0)                                     # a Monday poll
    recs = [rec_at("A3", "SKIP", poll, why="awaiting Daniel's ruling: expires 2026-12-20 (48 days)",
                   tool="maint_human.py")]
    opens = local_at(2026, 10, 21)                                          # 60 days before 12-20
    deadline = opens + dt.timedelta(hours=row["grace_hours"])               # 336 h: 11-04 00:00
    assert deadline == local_at(2026, 11, 4)
    assert maint_watch.rdap_overdue("A3", row, recs, deadline, epoch) is None
    now = deadline + dt.timedelta(seconds=1)
    late = maint_watch.rdap_overdue("A3", row, recs, now, epoch)
    assert late["due"] == opens and late["deadline"] == deadline and "the 60-day window opened 2026-10-21" in late["what"]
    closed = recs + [rec_at("A3", "PASS", opens, tool="maint_watch.py")]  # a close at the very opening counts
    assert maint_watch.rdap_overdue("A3", row, closed, now, epoch) is None
    early = recs + [rec_at("A3", "PASS", opens - dt.timedelta(seconds=1), tool="maint_watch.py")]
    assert maint_watch.rdap_overdue("A3", row, early, now, epoch) is not None
    for why in ("awaiting: reexpires 2026-12-20", "awaiting: expires 2026-12-201"):   # the words, whole
        odd = [rec_at("A3", "SKIP", poll, why=why, tool="maint_human.py")]
        assert maint_watch.rdap_overdue("A3", row, odd, now, epoch) is None, why
    quiet = [rec_at("A3", "SKIP", poll, why="not due", tool="maint_human.py")]
    poll_deadline = local_at(2026, 11, 11)                                  # next Monday 11-09 + 1 d + 24 h
    assert maint_watch.rdap_overdue("A3", row, quiet, poll_deadline, epoch) is None
    stopped = maint_watch.rdap_overdue("A3", row, quiet, poll_deadline + dt.timedelta(seconds=1), epoch)
    assert stopped is not None and stopped["what"] == "RDAP poll stopped"
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_a_human_row_s_status_at_its_lines(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    table = one_row_table(maint_watch, "H1")
    due = local_at(2027, 1, 4)                                           # first due after the epoch
    dl = due + dt.timedelta(days=1, hours=168)
    st = maint_watch.human_status
    assert st("H1", table, [], due - dt.timedelta(seconds=1))["is_due"] is False
    assert st("H1", table, [], due)["is_due"] is True
    assert st("H1", table, [], dl)["overdue"] is False and st("H1", table, [], dl + dt.timedelta(seconds=1))["overdue"]
    before = [rec_at("H1", "SKIP", due - dt.timedelta(seconds=1), why="awaiting Daniel's ruling: H1 pack",
                     tool="maint_human.py")]
    at = [rec_at("H1", "SKIP", due, why="awaiting Daniel's ruling: H1 pack", tool="maint_human.py")]
    assert st("H1", table, before, due)["fired"] is None and st("H1", table, at, due)["fired"] == due
    unk = [rec_at("H1", "UNKNOWN", due, why="pack failed", tool="maint_human.py")]
    assert st("H1", table, unk, due)["fired"] == due                      # a failed pack still fired the reminder
    closes = [rec_at("H1", "PASS", local_at(2026, 12, 1), why="closed by E00001"),
              rec_at("H1", "PASS", local_at(2027, 1, 5), why="closed by E00002")]
    s = st("H1", table, closes, local_at(2027, 2, 1))
    assert s["last"] == local_at(2027, 1, 5) and s["last_e"] == "closed by E00002" and s["due"] == local_at(2027, 7, 5)
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D2_reminders_say_how_late_they_fired(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 4, 9, watch=maint_watch)
    table = one_row_table(maint_watch, "H1")
    first = maint_watch.fire_reminders(table, local_at(2027, 1, 4, 9, 0), only=("H1",))
    assert [(r["outcome"], "(on time)" in r["why"]) for r in first] == [("SKIP", True)]
    assert maint_watch.fire_reminders(table, local_at(2027, 1, 4, 10, 0), only=("H1",)) == []     # fired once
    md2, _ = world(monkeypatch, tmp_path / "late", 2027, 1, 7, 9, watch=maint_watch)
    late = maint_watch.fire_reminders(table, local_at(2027, 1, 7, 9, 0), only=("H1",))
    assert len(late) == 1 and "(late by 3 day(s))" in late[0]["why"] and mr_awaiting(late[0])
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def mr_awaiting(e):
    import maint_receipt as mr
    return mr.is_awaiting(e)


def test_cite_A3_maint_watch_one_for_a_human_row(monkeypatch, tmp_path):
    import maint_human
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2026, 11, 2, 11, watch=maint_watch)
    code = maint_watch.main(["one", "A1"])
    rec = snap("A1")[-1]
    assert code == 0 and rec["outcome"] == "SKIP" and rec["why"].startswith("HUMAN row not due: next due 2027-01-04")
    clock.set(2027, 1, 4, 11)
    maint_watch.main(["one", "A1"])
    fired = snap("A1")[-1]
    assert mr_awaiting(fired) and "reminder fired 2027-01-04" in fired["why"]
    maint_watch.main(["one", "A1"])
    again = snap("A1")[-1]
    assert mr_awaiting(again) and again["why"].startswith("awaiting Daniel's ruling: reminder fired 2027-01-04")
    bad = tmp_path / "rows.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(maint_watch, "ROWS_FILE", bad)
    maint_watch.main(["one", "A3"])
    assert snap("A3")[-1]["outcome"] == "UNKNOWN" and maint_human.TOOL == "maint_human.py"


def write_note(md, name, text):
    d = md / "notes"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")


def test_cite_H2_the_check_s_clock_at_its_lines(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    table = one_row_table(maint_watch, "H2")
    due = local_at(2027, 1, 4)
    dl = due + dt.timedelta(days=1, hours=168)
    r = maint_watch.run_check("H2", due - dt.timedelta(seconds=1), table=table)
    assert r["outcome"] == "SKIP" and r["why"].startswith("not yet scheduled: first due 2027-01-04 (.maint/notes/H2_<date>.md)")
    r = maint_watch.run_check("H2", due, table=table)
    assert mr_awaiting(r) and "the review note due 2027-01-04" in r["why"]
    r = maint_watch.run_check("H2", dl, table=table)
    assert mr_awaiting(r)
    r = maint_watch.run_check("H2", dl + dt.timedelta(seconds=1), table=table)
    assert (r["outcome"], r["n"]) == ("FINDINGS", 1) and r["why"].startswith("review note overdue: due 2027-01-04")


def test_cite_H2_a_note_s_values_must_carry_content(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    good = GOOD_NOTE.format(d="2027-01-05")
    write_note(md, "H2_2027-01-05.md", good)
    p = md / "notes" / "H2_2027-01-05.md"
    assert maint_watch.note_problems(p, "H2", dt.date(2027, 1, 5), dt.date(2027, 1, 6)) == []
    for old, new, part in (("Reviewed: the publication gate", "Reviewed: ab", "Reviewed:"),
                           ("Reviewed: the publication gate", "Reviewed: tbd", "Reviewed:"),
                           ("Reviewed: the publication gate", "Reviewed: n/a", "Reviewed:"),
                           ("Reviewed: the publication gate", "xReviewed: the gate", "Reviewed:")):
        p.write_text(good.replace(old, new), encoding="utf-8")
        assert any(m.startswith(part) for m in maint_watch.note_problems(p, "H2", dt.date(2027, 1, 5),
                                                                          dt.date(2027, 1, 6))), new
    p.write_text(good.replace("Reviewed: the publication gate", "Reviewed: abc"), encoding="utf-8")
    assert maint_watch.note_problems(p, "H2", dt.date(2027, 1, 5), dt.date(2027, 1, 6)) == []      # 3 chars: content
    p.write_text(good.replace("Date: 2027-01-05", "Date: 2027-01-05T09:00-05:00"), encoding="utf-8")
    assert maint_watch.note_problems(p, "H2", dt.date(2027, 1, 5), dt.date(2027, 1, 6)) == []      # a time, read
    p.write_text(good.replace("Reviewer: reviewer", "Reviewer: Reviewer"), encoding="utf-8")
    assert maint_watch.note_problems(p, "H2", dt.date(2027, 1, 5), dt.date(2027, 1, 6)) == []      # any case


def test_cite_H2_only_a_dated_md_file_is_a_note(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    write_note(md, "H2_2027-01-05.md", GOOD_NOTE.format(d="2027-01-05"))
    write_note(md, "H2_2027-01-07.md.bak", GOOD_NOTE.format(d="2027-01-07"))
    write_note(md, "xH2_2027-01-08.md", GOOD_NOTE.format(d="2027-01-08"))
    write_note(md, "H2_2027-01-06_draft.md", GOOD_NOTE.format(d="2027-01-06"))
    write_note(md, "H2_2027-01-06_a.md", GOOD_NOTE.format(d="2027-01-06"))
    assert maint_watch.newest_note("H2") == (dt.date(2027, 1, 6), ".maint/notes/H2_2027-01-06_draft.md")


def test_cite_M5_the_board_stamp_s_lines(monkeypatch, tmp_path):
    import maint_watch
    import pytest
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    b = tmp_path / "PRODUCTION_BOARD.md"
    core = "*Generated 2026-11-02 by `tools/production_board.py`"
    b.write_text("# PRODUCTION BOARD\n" + core + "*\n", encoding="utf-8")
    assert maint_watch.board_date(tmp_path, dt.date(2026, 11, 2)) == dt.date(2026, 11, 2)       # today is fine
    with pytest.raises(maint_watch.Unknown, match="in the future"):
        maint_watch.board_date(tmp_path, dt.date(2026, 11, 1))
    pad = 2000 - len(core)
    b.write_text("#" + "x" * (pad - 2) + "\n" + core, encoding="utf-8")        # the stamp ends on char 2000
    assert maint_watch.board_date(tmp_path, dt.date(2026, 11, 2)) == dt.date(2026, 11, 2)
    b.write_text("#" + "x" * (pad - 1) + "\n" + core, encoding="utf-8")        # one char past the head
    with pytest.raises(maint_watch.Unknown, match="carries no"):
        maint_watch.board_date(tmp_path, dt.date(2026, 11, 2))
    assert owns("M5", maint_watch)                           # this is M5's runner's logic


def test_cite_D2_a_command_s_exit_code_follows_its_receipts(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    show = maint_watch.show
    assert show([{"outcome": "PASS"}, {"outcome": "SKIP"}]) == 0 and show([]) == 0
    assert show([{"outcome": "UNKNOWN"}, {"outcome": "PASS"}]) == 2
    assert show([{"outcome": "FINDINGS"}, {"outcome": "UNKNOWN"}]) == 1
    assert owns("D2", maint_watch)                           # this is D2's runner's logic


def test_cite_D3_an_alarm_s_cause_class(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    cc = maint_watch.cause_class
    assert cc("linkcheck crashed: KeyError 'pages'\nTraceback ...") == "linkcheck crashed: keyerror 'pages'"
    assert cc("linkcheck crashed: KeyError: 'pages'") == "linkcheck crashed: keyerror"
    assert cc("pa11y failed on 3 pages (b4him)") == "pa11y failed on # pages (b4him)"
    assert cc("x" * 200) == "x" * 80 and cc("") == "" and cc("  \n  ") == ""
    assert maint_watch.alarm_key("D1", "findings", "") == "D1 findings"
    assert maint_watch.alarm_key("D2", "overdue", "W1 late; more") == "D2 overdue: w1 late"
    assert owns("D3", maint_watch)                           # this is D3's runner's logic


def test_cite_D3_the_heartbeat_s_status_lines(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _hb(monkeypatch)
    _d1d2()
    for status, want in ((199, "FINDINGS"), (200, "PASS"), (299, "PASS"), (300, "FINDINGS")):
        monkeypatch.setattr(maint_watch, "HTTP_GET", lambda url, s=status: (s, "OK"))
        drive("D3", maint_watch)
        rec = receipt("D3", maint_watch)
        assert rec["outcome"] == want and (rec["n"] == 1 if want == "FINDINGS" else True), status


def test_cite_D3_a_refusal_quotes_the_service_briefly_and_never_the_url(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _hb(monkeypatch)
    _d1d2()
    url = "https://hc-ping.example.invalid/5a1b9c3e-0f4d-4e2a-9b7c-1d2e3f4a5b6c"
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", url)
    secret = url.rsplit("/", 1)[1]
    for leak in (url, url + "/fail", "token " + secret):
        body = leak + " " + "y" * 300
        monkeypatch.setattr(maint_watch, "HTTP_GET", lambda u, b=body: (404, b))
        drive("D3", maint_watch)
        rec = receipt("D3", maint_watch)
        f = findings("D3")[-1]
        assert rec["outcome"] == "FINDINGS" and secret not in rec["why"] and secret not in f["detail"], leak
        assert "<MAINT_HEARTBEAT_URL>" in rec["why"] and "<MAINT_HEARTBEAT_URL>" in f["detail"], leak
    body = url + " " + "y" * 300                                     # the service's words: 80 chars in the receipt,
    monkeypatch.setattr(maint_watch, "HTTP_GET", lambda u: (404, body))   # 120 in the finding
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["why"].count("y") == 80 - len(url) - 1 and findings("D3")[-1]["detail"].count("y") == 120 - len(url) - 1


def test_cite_D3_a_ping_that_could_not_be_sent_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    _hb(monkeypatch)
    _d1d2()

    def down(url):
        raise OSError("connection refused by " + url)
    monkeypatch.setattr(maint_watch, "HTTP_GET", down)
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "not delivered" in rec["why"] and "hc-ping.example.invalid" not in rec["why"]
    monkeypatch.setattr(maint_watch, "HTTP_GET", lambda url: (200, "Hello"))
    drive("D3", maint_watch)
    rec = receipt("D3", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "not 'OK': delivery unproven" in rec["why"]


def test_cite_D3_today_s_latest_d1_line_is_the_one_read(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    calls = _hb(monkeypatch)
    mr.write_receipt("D1", "FINDINGS", n=1, why="2026-11-02: MISSING: no line", tool="maint_watch.py")
    clock.set(2026, 11, 2, 11, 5)
    mr.write_receipt("D1", "PASS", why="2026-11-02: 08:31 PUBLISHED", tool="maint_watch.py")
    mr.write_receipt("D2", "PASS", why="ok", tool="maint_watch.py")
    fail, why, current = maint_watch.d3_signal(maint_watch.local(clock.now()))
    assert (fail, current) == (False, [])
    mr.write_receipt("D1", "FINDINGS", n=1, why="2026-11-02: 10:31 FAIL content", tool="maint_watch.py")
    fail, why, current = maint_watch.d3_signal(maint_watch.local(clock.now()))
    assert fail and current == ["D1 findings: #: # fail content"] and "NEW D1 findings" in why
    assert owns("D3", maint_watch)                           # this is D3's runner's logic


def test_cite_W2_the_digest_s_week_and_lists(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    clock.set(2026, 10, 26, 11, 0, 0)
    mr.write_receipt("Q3", "PASS", why="a week ago to the second", tool="maint_pages.py")
    clock.set(2026, 10, 26, 11, 0, 1)
    mr.write_receipt("Q4", "PASS", why="inside the week", tool="headers_tls_check.py")
    mr.write_receipt("D3", "UNKNOWN", why="older ping", tool="maint_watch.py")
    clock.set(2026, 11, 1, 9, 0)
    mr.write_receipt("D3", "PASS", why="heartbeat success signal delivered", tool="maint_watch.py")
    mr.write_receipt("W3.page", "SKIP", why="awaiting site-maintainer judgement: a page line", tool="maint_pages.py")
    mr.write_receipt("M4", "SKIP", why="awaiting managing-editor judgement: the walkthrough", tool="maint_pages.py")
    clock.set(2026, 11, 2, 11, 0)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    text = _digest(md, rec)
    week = text.split("## Receipts of the week")[1]
    assert "inside the week" in week and "a week ago to the second" not in week
    assert "- D3 heartbeat: " in text and "heartbeat success signal delivered" in text.split("- D3 heartbeat: ")[1].split("\n")[0]
    waits = text.split("## Awaiting a judgement")[1].split("##")[0]
    assert "- M4: awaiting" in waits and "W3.page" not in waits


def test_cite_W2_the_h3_reminder_carries_the_evidence_pack(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, 2027, 1, 5, 11, watch=maint_watch)
    a = md / "audits"
    a.mkdir(parents=True)
    for i in range(30):
        (a / f"2026-10-{i + 1:02d}_x.md").write_text("x", encoding="utf-8")
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    text = _digest(md, rec)
    pack = text.split("## H3")[1]
    assert "REMINDER: the re-read is due" in pack
    listed = pack.split(".maint/audits/: ")[1].split("\n")[0].split(", ")
    assert len(listed) == 26 and listed[0] == "2026-10-05_x.md"                # the newest 26 audits


def test_cite_W2_the_c1_line_takes_the_reader_s_last_week_only(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    clock.set(2026, 10, 26, 11, 0, 0)
    mr.write_receipt("C1", "PASS", why="exactly a week old", tool="headers_tls_check.py")
    clock.set(2026, 11, 2, 11, 0)
    line = maint_watch.c1_monitor_line(maint_watch.local(clock.now()))
    assert line["outcome"] == "UNKNOWN" and line["why"].startswith("no C1 reader receipt in the last 7 days")
    clock.set(2026, 10, 30, 9, 0)
    mr.write_receipt("C1", "PASS", why="older", tool="headers_tls_check.py")
    mr.write_receipt("C1", "FINDINGS", n=1, why="newest", tool="headers_tls_check.py")
    mr.write_receipt("C1", "PASS", why="not the reader", tool="maint_watch.py")
    clock.set(2026, 11, 2, 11, 0)
    assert maint_watch.c1_monitor_line(maint_watch.local(clock.now()))["why"] == "newest"
    drive("W2", maint_watch)
    assert receipt("W2", maint_watch)["outcome"] == "PASS"


def test_cite_W2_an_unreadable_row_table_is_unknown(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    bad = tmp_path / "rows.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(maint_watch, "ROWS_FILE", bad)
    drive("W2", maint_watch)
    rec = receipt("W2", maint_watch)
    assert rec["outcome"] == "UNKNOWN" and "cannot read the row table" in rec["why"]


def test_cite_Q6_retire_candidates_over_four_quarters(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    now = local_at(2027, 11, 2, 11, 0)
    since = now - dt.timedelta(days=365)
    table = one_row_table(maint_watch, "M4", "M3", "Q1", "Q2", "Q3", "A2")

    def find(row, t, subject="x"):
        return {"at": t.isoformat(), "row": row, "severity": "S2", "subject": subject, "detail": "", "route_to": ""}
    recs = [rec_at("M4", "PASS", since), rec_at("M3", "PASS", since + dt.timedelta(seconds=1)),
            rec_at("Q1", "PASS", since), rec_at("Q1", "FINDINGS", since),
            rec_at("Q2", "PASS", since), rec_at("Q3", "PASS", since), rec_at("A2", "PASS", since)]
    finds = [find("Q2", since), find("D2", since, "OVERDUE Q3"), find("A2", since - dt.timedelta(seconds=1))]
    out = "\n".join(maint_watch.retire_candidates(table, recs, finds, now))
    assert "**M4**: zero findings and zero alarms in 4 quarters" in out
    assert "- M3: zero findings and zero alarms so far, but history only since" in out
    assert "Q1" not in out and "Q2" not in out and "Q3" not in out          # a finding or an alarm in the year
    assert "**A2**" in out                                                  # its finding was before the year
    assert owns("Q6", maint_watch)                           # this is Q6's runner's logic


def test_cite_Q6_a_drill_after_today_s_ping_withholds_tomorrow_s(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    clock.set(2026, 11, 1, 10, 31)
    mr.write_receipt("D3", "PASS", why="heartbeat success signal delivered", tool="maint_watch.py")
    clock.set(2026, 11, 2, 10, 31)
    mr.write_receipt("D3", "SKIP", why="drill", tool="maint_watch.py")       # a withheld ping is not a ping
    clock.set(2026, 11, 2, 11, 0)
    drive("Q6", maint_watch)
    rec = receipt("Q6", maint_watch)
    assert "the 2026-11-02 heartbeat is withheld" in rec["why"] and "(2026-11-01 10:31)" in rec["why"]
    md2, clock2 = world(monkeypatch, tmp_path / "pinged", watch=maint_watch)
    monkeypatch.setenv("MAINT_HEARTBEAT_URL", "https://hc-ping.example.invalid/x")
    clock2.set(2026, 11, 2, 10, 31)
    mr.write_receipt("D3", "PASS", why="heartbeat success signal delivered", tool="maint_watch.py")
    clock2.set(2026, 11, 2, 11, 0)
    drive("Q6", maint_watch)
    assert "the 2026-11-03 heartbeat is withheld" in receipt("Q6", maint_watch)["why"]


def test_cite_Q6_a_drill_log_is_disarmed_only_by_its_own_confirmation(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    md.mkdir(parents=True, exist_ok=True)
    log = md / "drills.jsonl"
    log.write_text(json.dumps({"event": "armed", "skip_date": "2026-11-02"}) + "\n"
                   + json.dumps({"event": "confirmed", "skip_date": "2026-11-01"}) + "\n", encoding="utf-8")
    assert maint_watch.armed_drill()["skip_date"] == "2026-11-02"
    log.write_text(log.read_text(encoding="utf-8") + json.dumps({"event": "confirmed", "skip_date": "2026-11-02"})
                   + "\n", encoding="utf-8")
    assert maint_watch.armed_drill() is None and snap("Q6") == []


def test_cite_Q6_a_confirmation_s_time_window(monkeypatch, tmp_path):
    import maint_watch
    md, clock = world(monkeypatch, tmp_path, watch=maint_watch)
    for word in ("never", "None", "FAIL"):
        mdw, clock = world(monkeypatch, tmp_path / word, watch=maint_watch)
        first = _armed_q6(monkeypatch, maint_watch)
        code, prev, shut = close("Q6", maint_watch, "confirm", word)
        assert first["outcome"] == "SKIP" and (code, shut["outcome"], shut["n"]) == (1, "FINDINGS", 1), word
    mdt, clock = world(monkeypatch, tmp_path / "times", watch=maint_watch)
    _armed_q6(monkeypatch, maint_watch)                                    # skip 2026-11-02, now 11:00
    assert refused("Q6", maint_watch, "confirm", "2026-11-01T23:59:59-05:00")       # before the skipped day
    assert refused("Q6", maint_watch, "confirm", "2026-11-02T11:05:01-05:00")       # more than 5 min ahead
    code, prev, shut = close("Q6", maint_watch, "confirm", "2026-11-02T11:05:00-05:00")
    assert code == 0 and shut["outcome"] == "PASS" and "alarm fired at 11:05 on 2026-11-02" in shut["why"]
    mdm, clock = world(monkeypatch, tmp_path / "midnight", watch=maint_watch)
    _armed_q6(monkeypatch, maint_watch)
    code, prev, shut = close("Q6", maint_watch, "confirm", "00:00")
    assert code == 0 and shut["outcome"] == "PASS"


def test_cite_D2_no_hand_act_takes_a_fixed_clock(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    plant_awaiting("H1", "maint_human.py", "awaiting Daniel's ruling: H1 pack", "packs/H1/index.md")
    assert refused("H1", maint_watch, "--now", "2026-11-02T10:00:00+00:00", "human", "H1", "E01234")
    assert refused("Q2", maint_watch, "--now", "2026-11-02T10:00:00+00:00", "witness", "privacy-safety")
    assert snap("D2") == []


# ================================================================== sweep: maint_run's calendar, groups, proof and launch record
def calendar_row(rid):
    import maint_run as run
    return next(r for r in run.load_table() if r["id"] == rid)


def test_cite_D1_a_daily_row_is_due_every_day(monkeypatch, tmp_path):
    import maint_watch
    import maint_run as run
    row = calendar_row("D1")
    assert all(run.is_due(row, dt.date(2026, 11, d)) for d in range(1, 8)) and owns("D1", maint_watch)


def test_cite_W1_a_weekly_row_is_due_on_mondays(monkeypatch, tmp_path):
    import linkcheck
    import maint_run as run
    row = calendar_row("W1")
    due = [d for d in range(1, 15) if run.is_due(row, dt.date(2026, 11, d))]
    assert due == [2, 9] and owns("W1", linkcheck)


def test_cite_M1_a_monthly_row_is_due_on_the_first_monday(monkeypatch, tmp_path):
    import maint_quality
    import maint_run as run
    row = calendar_row("M1")
    nov = [d for d in range(1, 31) if run.is_due(row, dt.date(2026, 11, d))]
    feb = [d for d in range(1, 29) if run.is_due(row, dt.date(2027, 2, d))]        # Feb 1 2027 is a Monday
    assert nov == [2] and feb == [1] and run.first_monday(2026, 12) == dt.date(2026, 12, 7) and owns("M1", maint_quality)


def test_cite_Q1_a_quarterly_row_is_due_on_its_months_first_monday(monkeypatch, tmp_path):
    import maint_pages
    import maint_run as run
    row = calendar_row("Q1")
    days = [dt.date(2027, m, d) for m in range(1, 13) for d in range(1, 29) if run.is_due(row, dt.date(2027, m, d))]
    assert days == [dt.date(2027, 1, 4), dt.date(2027, 4, 5), dt.date(2027, 7, 5), dt.date(2027, 10, 4)]
    assert owns("Q1", maint_pages)


def test_cite_H2_a_semiannual_row_and_A2_an_annual_one(monkeypatch, tmp_path):
    import maint_watch
    import maint_run as run
    h2 = calendar_row("H2")
    days = [dt.date(2027, m, d) for m in range(1, 13) for d in range(1, 29) if run.is_due(h2, dt.date(2027, m, d))]
    assert days == [dt.date(2027, 1, 4), dt.date(2027, 7, 5)] and owns("H2", maint_watch)
    a2 = calendar_row("A2")
    assert [dt.date(2027, m, d) for m in range(1, 13) for d in range(1, 29)
            if run.is_due(a2, dt.date(2027, m, d))] == [dt.date(2027, 1, 4)]


def test_cite_A3_is_polled_every_monday(monkeypatch, tmp_path):
    import maint_human
    import maint_run as run
    row = calendar_row("A3")
    assert [d for d in range(1, 15) if run.is_due(row, dt.date(2026, 11, d))] == [2, 9] and owns("A3", maint_human)
    assert run.is_due(row, dt.date(2027, 1, 4)) and not run.is_due(row, dt.date(2027, 1, 5))
    assert not run.is_due(calendar_row("E1"), dt.date(2026, 11, 2))                          # an event row never


def test_cite_W1_maint_run_runs_one_child_for_rows_that_share_it(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    import maint_run as run
    asked = []

    def child(argv, timeout):
        asked.append(Path(argv[1]).name)
        mr.write_receipt("W1", "PASS", n=0, why="w1", tool="linkcheck.py")
        mr.write_receipt("W1b", "PASS", n=0, why="w1b", tool="linkcheck.py")
        return 0, "", ""
    monkeypatch.setattr(run, "RUN", child)
    code = run.main(["--row", "W1", "--row", "W1b"])
    lines = {e["row"]: e for e in receipts_any()}
    assert asked == ["linkcheck.py"] and code == 0 and lines["W1"]["why"] == "w1" and lines["W1b"]["why"] == "w1b"
    assert owns("W1", linkcheck)


def test_cite_M5_a_line_the_digest_wrote_counts_for_its_row(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_receipt as mr
    import maint_run as run
    asked = []

    def child(argv, timeout):
        asked.append((Path(argv[1]).name, list(argv[2:])))
        mr.write_receipt("W2", "PASS", why="digest", tool="maint_watch.py")
        mr.write_receipt("M5", "PASS", why="board run 2026-11-02 found", tool="maint_watch.py")
        return 0, "", ""
    monkeypatch.setattr(run, "RUN", child)
    res = run.run(["W2", "M5"], {r["id"]: r for r in run.load_table()})
    got = {e["row"]: e["why"] for e in res["receipts"]}
    assert asked == [("maint_watch.py", ["digest"])] and got == {"W2": "digest", "M5": "board run 2026-11-02 found"}
    other = run.run(["W2"], {r["id"]: r for r in run.load_table()})
    assert [e["row"] for e in other["receipts"]] == ["W2"]                  # a line for a row not asked for: not listed
    assert owns("M5", maint_watch)


def test_cite_D2_a_row_with_no_runner_could_not_start(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_run as run
    res = run.run(["Z9"], {"Z9": {"id": "Z9", "kind": "daily"}})
    rec = res["receipts"][0]
    assert res["could_not_start"] == ["Z9"] and rec["outcome"] == "UNKNOWN" and \
        rec["why"] == "runner could not start: no runner wired for Z9"
    ev = run.run(["E2"], {r["id"]: r for r in run.load_table()})
    assert ev["receipts"][0]["outcome"] == "SKIP" and ev["could_not_start"] == [] and owns("D2", maint_watch)


def test_cite_D2_maint_run_refuses_rows_it_does_not_know_and_lists_without_running(monkeypatch, tmp_path):
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    import maint_run as run
    monkeypatch.setattr(run, "RUN", lambda argv, timeout: (_ for _ in ()).throw(AssertionError("ran")))
    assert run.main(["--row", "Z9"]) == 2 and log_lines() == []
    assert run.main(["--list", "--date", "2026-11-02"]) == 0 and log_lines() == []
    bad = tmp_path / "rows.json"
    bad.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(run, "ROWS_FILE", bad)
    assert run.main(["--row", "D2"]) == 2 and owns("D2", maint_watch)


def test_cite_C1_a_child_that_timed_out_after_a_pass_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    import maint_run as run

    def child(argv, timeout):
        mr.write_receipt("C1", "PASS", n=0, why="up", tool="headers_tls_check.py")
        return None, "", ""
    monkeypatch.setattr(run, "RUN", child)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert rec["outcome"] == "UNKNOWN" and "timed out after writing C1 PASS" in rec["why"]
    rec2, end, rc = exit_case(monkeypatch, "C1", headers_tls_check, "SKIP", 1)        # a SKIP does not explain 1
    assert rec2["outcome"] == "UNKNOWN" and end["rows_failed"] == ["C1"] and rc == 2


def test_cite_M1_the_patch_proof_runs_its_four_checks_on_the_tree(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    import os
    import maint_receipt as mr
    import maint_run as run
    tree = str(repo_root())
    asked = []

    def child(argv, timeout, outcomes={"M1": "PASS", "M1b": "FINDINGS", "W1": "PASS", "M2": "FINDINGS"}):
        script, args = Path(argv[1]).name, list(argv[2:])
        asked.append((script, args, timeout))
        row = {"a11y": "M1", "contrast": "M1b", "perf": "M2"}.get(args[0], "W1")
        o = outcomes[row]
        mr.write_receipt(row, o, n=2 if o == "FINDINGS" else None, why=f"{row} said {o}", tool=script)
        return {"PASS": 0, "FINDINGS": 1}[o], "", ""
    monkeypatch.setattr(run, "RUN", child)
    rec = run.patch_proof(Path(tree))
    assert asked == [("maint_quality.py", ["a11y", "--root", tree], 7200),
                     ("maint_quality.py", ["contrast", "--root", tree], 3600),
                     ("linkcheck.py", ["--repo", tree, "--internal-only"], 3600),
                     ("maint_quality.py", ["perf", "--root", tree], 7200)]
    assert (rec["row"], rec["outcome"], rec["n"]) == ("E1", "FINDINGS", 4)
    assert rec["why"].startswith("M1 PASS; M1b FINDINGS 2; W1 PASS; M2 FINDINGS 2 on ")
    assert os.environ["MAINT_DIR"] == str(md) and maint_quality.TOOL == "maint_quality.py"
    owed = [f for f in mr.read_findings() if f["row"] == "E1"]
    run.patch_proof(Path(tree))
    assert len(owed) == 1 and len([f for f in mr.read_findings() if f["row"] == "E1"]) == 1   # owed once, not per run


def test_cite_M1_a_patch_proof_with_an_unknown_step_is_incomplete(monkeypatch, tmp_path):
    import maint_quality
    md, _ = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    import maint_run as run

    def child(argv, timeout):
        args = list(argv[2:])
        row = {"a11y": "M1", "contrast": "M1b", "perf": "M2"}.get(args[0], "W1")
        o = "UNKNOWN" if row == "M1b" else "PASS"
        mr.write_receipt(row, o, why=f"{row} {o}", tool=Path(argv[1]).name)
        return (2 if o == "UNKNOWN" else 0), "", ""
    monkeypatch.setattr(run, "RUN", child)
    rec = run.patch_proof(repo_root())
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("patch proof incomplete: M1 PASS; M1b UNKNOWN")
    monkeypatch.setattr(run, "RUN", lambda argv, timeout: (mr.write_receipt(
        {"a11y": "M1", "contrast": "M1b", "perf": "M2"}.get(argv[2], "W1"), "PASS", n=0, why="ok",
        tool=Path(argv[1]).name), 0, "", "")[1:])
    clean = run.patch_proof(repo_root())
    assert (clean["outcome"], clean["n"]) == ("PASS", 0)
    gone = run.patch_proof(tmp_path / "not-a-tree")
    assert gone["outcome"] == "UNKNOWN" and gone["why"] == "patch proof: not-a-tree is not a git checkout"
    assert maint_quality.TOOL == "maint_quality.py"


def test_cite_C1_the_run_start_marker_records_a_real_process_start(monkeypatch, tmp_path):
    import headers_tls_check
    import os
    md, _ = world(monkeypatch, tmp_path)
    _monitors(monkeypatch, MONS)
    drive("C1", headers_tls_check)
    start = [e for e in log_lines() if e.get("kind") == "run_start" and e["run_id"] == DRIVES["C1"]["run_id"]][0]
    t = dt.datetime.fromisoformat(start["proc_started"])
    real_now = dt.datetime.now(dt.timezone.utc)
    assert dt.timedelta(0) <= real_now - t < dt.timedelta(days=2), start             # a process of this run, today
    assert start["pid"] in (os.getpid(), os.getppid()) and receipt("C1", headers_tls_check)["outcome"] == "PASS"


# ================================================================== sweep: maint_pages, line by line
def test_cite_M4_syllables_and_the_reading_grade(monkeypatch, tmp_path):
    import maint_pages
    syl = {w: maint_pages.syllables(w) for w in ("a", "the", "cat", "cake", "baked", "yellow", "beautiful", "eyes",
                                                  "bees", "playing", "y", "rhythm", "reading")}
    assert syl == {"a": 1, "the": 1, "cat": 1, "cake": 1, "baked": 1, "yellow": 2, "beautiful": 4, "eyes": 2,
                   "bees": 1, "playing": 2, "y": 1, "rhythm": 1, "reading": 2}
    fk = maint_pages.fk_grade
    assert fk("The cat sat on the mat. It was a good day for a nap.") == {"words": 14, "sentences": 2,
                                                                          "syllables": 14, "grade": -1.1}
    assert fk("Reading carefully and thoughtfully improves understanding considerably! Everybody benefits.") == \
        {"words": 9, "sentences": 2, "syllables": 29, "grade": 24.2}
    assert fk("") == {"words": 0, "sentences": 0, "syllables": 0, "grade": None}
    assert fk("One sentence without a stop") == {"words": 5, "sentences": 1, "syllables": 7, "grade": 2.9}
    assert fk("Ends here. And here? Yes!")["sentences"] == 3 and fk("x")["grade"] == -3.4
    assert (maint_pages.READING_AGE_TARGET, maint_pages.FK_GRADE_TARGET) == (9, 4)          # reading age 9 = grade 4
    assert owns("M4", maint_pages)


def test_cite_W3_the_site_chrome_and_title_words(monkeypatch, tmp_path):
    import maint_pages
    body, chrome = maint_pages.scan_html("<html><nav>Menu Home</nav><navigation>Kept</navigation><nav>Real</nav>"
                                         "<main><p>Body text here.</p></main><footer>Foot</footer></html>")
    assert chrome == ["<nav>Menu Home</nav>", "<nav>Real</nav>", "<footer>Foot</footer>"] and "Kept" in body
    assert maint_pages.site_vocabulary({"a.html": "<title>Gentle Harbor</title><h1>Gentle Harbor Again</h1>"
                                                  "<h1x>Not A Heading</h1x>"}) == ["gentle harbor", "gentle harbor again"]
    pair = maint_pages.CAP_PAIR.match
    assert pair("Quillon Mistlewood") and not pair("Quillon Mistlewood Jr") and not pair("quillon Mistlewood")
    assert maint_pages.PAGE_ROW == "W3.page" and owns("W3", maint_pages)


def test_cite_W3_each_page_s_own_line(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    pages_repo(monkeypatch, maint_pages, tmp_path, {"about/index.html": "<p>i met Quillon there.</p>"}, names=True)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    lines = [e for e in receipts_any() if e["row"] == maint_pages.PAGE_ROW]
    hit = [e for e in lines if e["outcome"] == "FINDINGS"]
    assert rec["outcome"] == "FINDINGS" and len(hit) == 1 and hit[0]["n"] == 1 and hit[0]["why"].startswith("about/")
    assert len(lines) >= 5 and all(e["outcome"] == "PASS" for e in lines if e is not hit[0])


def test_cite_W3_a_people_registry_that_cannot_load_is_unknown_on_every_page(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = site_repo(maint_pages, tmp_path)
    (repo / "data" / "people_registry.json").write_text("{broken", encoding="utf-8")
    maint_pages.git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-am", "break")
    monkeypatch.setattr(maint_pages, "REPO", repo)
    local_names(repo)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    lines = [e for e in receipts_any() if e["row"] == maint_pages.PAGE_ROW]
    assert rec["outcome"] == "UNKNOWN" and lines and all(e["outcome"] == "UNKNOWN" for e in lines)
    assert all("COULD NOT RUN" in e["why"] for e in lines)


def test_cite_W3_a_tree_that_is_not_a_checkout_could_not_run(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    d = tmp_path / "plain"
    d.mkdir()
    (d / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    monkeypatch.setattr(maint_pages, "REPO", d)
    drive("W3", maint_pages)
    rec = receipt("W3", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("could not run: ")


def test_cite_Q1_a_queue_that_cannot_be_read_says_how(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path)
    q = repo / "production_queue.jsonl"
    for text, why in (("# only a comment\n", "zero records where records are expected"),
                      ("\n\n", "the production queue is empty"),
                      ('{"id": "C-1"}\n{oops\n', "1 unparseable line(s) (first: line 2)")):
        q.write_text(text, encoding="utf-8")
        drive("Q1", maint_pages)
        rec = receipt("Q1", maint_pages)
        assert rec["outcome"] == "UNKNOWN" and why in rec["why"], why
    q.unlink()
    drive("Q1", maint_pages)
    rec = receipt("Q1", maint_pages)
    assert rec["outcome"] == "UNKNOWN" and "the production queue is missing" in rec["why"]


def test_cite_Q1_due_and_owner_rules(monkeypatch, tmp_path):
    import maint_pages
    rows = [{"id": "C-1", "stage": "PUBLISHED", "page": "lessons/alpha/index.html", "published": "2026-07-01"},
            {"id": "C-2", "stage": "PUBLISHED", "page": "lessons/beta/index.html", "published": "2026-08-03",
             "last_reviewed": "2026-08-04"}]
    assert [(r["id"], w) for r, w in maint_pages.rows_due(rows, dt.date(2026, 9, 29))] == \
        [("C-1", "90 days since last review")]
    assert [(r["id"], w) for r, w in maint_pages.rows_due(rows, dt.date(2026, 9, 28))] == []
    assert maint_pages.owner_of("lessons/alpha/index.html", rows) == (["C-1"], "managing-editor (content line)")
    assert maint_pages.owner_of("about/team.html", rows) == ([], "unowned in the queue [ASSUMED: managing-editor]")
    assert owns("Q1", maint_pages)


def test_cite_Q1_later_rulings_since_a_date(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    d = ("## D11 — Genericization. LOCKED 2026-07-21\n\nText.\n\n## D12 — Later. LOCKED 2026-09-01\n\n"
         "see the note ## D13 — Mid-line. LOCKED 2026-12-01\n\n## D14 — End. LOCKED 2026-07-21\n")
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, decisions=d)
    assert maint_pages.later_rulings(repo, "2026-07-21") == ["D12 — Later. LOCKED 2026-09-01"]
    assert maint_pages.later_rulings(repo, None) == ["D11 — Genericization. LOCKED 2026-07-21",
                                                     "D12 — Later. LOCKED 2026-09-01",
                                                     "D14 — End. LOCKED 2026-07-21"]
    assert owns("Q1", maint_pages)


def test_cite_Q2_d11_must_be_there_and_parse(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    for decisions, why in (("## D10 — Other. LOCKED 2026-07-01\n\nText.\n\n## D12 — End\n",
                            "DECISIONS.md has no D11 section"),
                           ("## D110 — Not it. LOCKED 2026-07-01\n\nZorblax → \"a tool\".\n\n## D12 — E\n",
                            "DECISIONS.md has no D11 section"),
                           ("## D11 — Publishing. LOCKED 2026-07-21\n\nNo rule here.\n\n## D12 — End\n",
                            "D11 has no 'Genericization is a hard rule' line"),
                           ("## D11 — Publishing. LOCKED 2026-07-21\n\n- **Genericization is a hard rule, applied "
                            "consistently.** nothing to replace.\n\n## D12 — End\n",
                            "no 'X → replacement' token parsed from D11")):
        repo = pages_repo(monkeypatch, maint_pages, tmp_path / why[:10].replace(" ", "_") / str(len(decisions)),
                          names=True, decisions=decisions)
        _client(repo)
        drive("Q2", maint_pages)
        rec = receipt("Q2", maint_pages)
        assert rec["outcome"] == "UNKNOWN" and why in rec["why"], why


def test_cite_Q2_d11_ends_at_the_next_heading_line(monkeypatch, tmp_path):
    import maint_pages
    md, _ = world(monkeypatch, tmp_path)
    decisions = ("## D11 — Publishing. LOCKED 2026-07-21\n\n- **Genericization is a hard rule, applied "
                 "consistently.** Zorblax → \"a tool\". a note ## here is not a heading. Quendrith → "
                 "\"a teammate\".\n\n## D12 — Later.\n\nVexmoor → \"a machine\".\n\n## D13 — End\n")
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, decisions=decisions)
    toks = maint_pages.d11_tokens(repo)
    assert "Zorblax" in toks and "Quendrith" in toks and "Vexmoor" not in toks and owns("Q2", maint_pages)


def test_cite_Q2_the_sweep_s_outcome_rules(monkeypatch, tmp_path):
    import maint_pages
    base = {"hits": [], "client_list_loaded": True, "w3": {"outcome": "PASS", "n": 0, "why": "ok"}}
    g = maint_pages.genericize_outcome
    assert g(dict(base, witness={"seat": "privacy-safety"})) == \
        ("PASS", 0, "0 forbidden tokens, W3 PASS, witnessed by privacy-safety")
    o, n, why = g(dict(base, w3={"outcome": "FINDINGS", "n": 2, "why": "x"}, witness={"seat": "privacy-safety"}))
    assert (o, n) == ("PASS", 0) and "W3 FINDINGS (its findings stand in W3)" in why
    o, n, why = g(dict(base, client_list_loaded=False))
    assert (o, n) == ("UNKNOWN", None) and why.startswith("could not fully run: the client-name list")
    o, n, why = g(dict(base, w3={"outcome": "UNKNOWN", "n": None, "why": "names file absent"}))
    assert o == "UNKNOWN" and "W3 could not fully run (names file absent)" in why
    assert g(dict(base, error="git grep died"))[0] == "UNKNOWN" and g(base)[0] == "SKIP"
    hits = [{"path": "lessons/a/index.html"}, {"path": "assets/app.js"}]
    o, n, why = g(dict(base, hits=hits))
    assert (o, n) == ("FINDINGS", 2) and why.startswith("2 forbidden-token line(s) on served files: 1 in lessons/ (S1)")
    assert owns("Q2", maint_pages)


def test_cite_Q2_every_author_seat_is_refused_as_witness(monkeypatch, tmp_path):
    import maint_pages
    import pytest
    md, clock = world(monkeypatch, tmp_path)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    rec = receipt("Q2", maint_pages)
    day = clock.now().date()
    assert maint_pages.AUTHOR_SEATS == {"managing-editor", "curriculum-designer", "site-maintainer",
                                        "design-accessibility"} and maint_pages.SWEEP_SEAT == "maintenance-auditor"
    with pytest.raises(maint_pages.CouldNotRun, match="the witness must be another seat"):
        maint_pages.cmd_witness(repo, day, "maintenance-auditor", tool="maint_watch.py", evidence=rec["evidence"])
    with pytest.raises(maint_pages.CouldNotRun, match="is not a b4him seat"):
        maint_pages.cmd_witness(repo, day, "the-intern", tool="maint_watch.py", evidence=rec["evidence"])
    (repo / "about.txt").write_text("a later commit\n", encoding="utf-8")
    maint_pages.git(repo, "add", "-A")
    maint_pages.git(repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid", "commit", "-q", "-m", "later")
    with pytest.raises(maint_pages.CouldNotRun, match="HEAD moved since the sweep"):
        maint_pages.cmd_witness(repo, day, "privacy-safety", tool="maint_watch.py", evidence=rec["evidence"])


def test_cite_Q2_witness_through_the_cli_exits_by_its_outcome(monkeypatch, tmp_path):
    import maint_pages
    import maint_watch
    md, _ = world(monkeypatch, tmp_path, watch=maint_watch)
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, names=True)
    _client(repo)
    drive("Q2", maint_pages)
    assert maint_pages.main(["--repo", str(repo), "witness", "site-maintainer"]) == 2      # refused: 2, not 1
    assert maint_pages.main(["--repo", str(repo), "witness", "privacy-safety"]) == 0
    assert snap("Q2")[-1]["outcome"] == "PASS"


def test_cite_Q3_findings_close_by_status_and_age(monkeypatch, tmp_path):
    import maint_pages
    md, clock = world(monkeypatch, tmp_path)
    _today(monkeypatch, "2026-11-02")                                    # Q3 reads the date, not the clock
    repo = pages_repo(monkeypatch, maint_pages, tmp_path, queue=[
        {"id": "P-1", "title": "Old", "stage": "DRAFTED", "kind": "patch", "drafted": "2026-08-04",
         "blocked_on": "b" * 200}])
    import maint_receipt as mr

    def find(subject, at, **kw):
        return json.dumps({"at": at, "row": "W1", "severity": "S2", "subject": subject, "detail": "", "route_to": "r",
                           **kw})
    md.mkdir(parents=True, exist_ok=True)
    (md / mr.FINDINGS_NAME).write_text("\n".join([
        find("closed one", "2026-01-01T00:00:00+00:00"), find("closed one", "2026-02-01T00:00:00+00:00", status="closed"),
        find("wont one", "2026-01-01T00:00:00+00:00"), find("wont one", "2026-02-01T00:00:00+00:00", status="wont-do"),
        find("open one", "2026-10-01T00:00:00+00:00"), find("open one", "2026-10-02T00:00:00+00:00")]) + "\n",
        encoding="utf-8")
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    text = evidence_text(rec)
    assert "open patches: 1; open findings: 1; flagged stale: **0**" in text
    assert "| finding | W1 open one | S2 | 2026-10-01 | 32 |  | x2 -> r |" in text
    assert "| patch | P-1 | DRAFTED | 2026-08-04 | 90 |  | " + "b" * 120 + " |" in text
    assert rec["outcome"] == "PASS" and rec["n"] == 0
    _today(monkeypatch, "2026-11-03")                                    # one day on: the patch is 91 days old
    drive("Q3", maint_pages)
    rec = receipt("Q3", maint_pages)
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 1) and "| 91 | STALE |" in evidence_text(rec)


# ================================================================== sweep: linkcheck, line by line
class ScriptedFetch:
    """A Fetcher stand-in: answers HEAD and GET from a script; records each request's method and read size."""
    def setup(self, head, get):
        self.answers, self.seen = {"HEAD": head, "GET": get}, []
        return self

    def request(self, url, method, read=0):
        self.seen.append((method, read))
        code = self.answers[method]
        if isinstance(code, str):
            return {"code": None, "final_url": url, "body": b"", "error": code}
        return {"code": code, "final_url": url, "body": b"", "error": None if code < 400 else f"HTTP {code}"}


def test_cite_W1_an_outbound_answer_s_lines(monkeypatch, tmp_path):
    import linkcheck
    u = "https://example.org/p"

    def verdict(head, get):
        f = ScriptedFetch().setup(head, get)
        r = linkcheck.check_url(u, f)
        return r["status"], r["method"], f.seen
    assert verdict(200, None) == ("OK", "HEAD", [("HEAD", 0)])
    assert verdict(399, None) == ("OK", "HEAD", [("HEAD", 0)])
    assert verdict(400, 200) == ("OK", "GET", [("HEAD", 0), ("GET", 1024)])
    assert verdict(199, 399) == ("OK", "GET", [("HEAD", 0), ("GET", 1024)])
    assert verdict(405, 404)[:2] == ("DEAD", "GET") and verdict(405, 410)[:2] == ("DEAD", "GET")
    for code in (199, 400, 403, 409, 411, 500):
        assert verdict(405, code)[0] == "UNKNOWN", code
    status, method, _ = verdict("URLError: no route", "URLError: no route")
    r = linkcheck.check_url(u, ScriptedFetch().setup("URLError: x", "URLError: no route"))
    assert (status, r["code"]) == ("UNKNOWN", None) and "GET failed on the network" in r["why"]
    assert linkcheck.check_url("https:///nohost", ScriptedFetch().setup(200, 200))["status"] == "DEAD"
    assert linkcheck.DEAD_CODES == {404, 410} and owns("W1", linkcheck)


def test_cite_W1_the_fetcher_s_politeness_and_answers(monkeypatch, tmp_path):
    import linkcheck
    import urllib.error
    t = {"now": 100.0}
    slept = []

    def opener(req, timeout=None):
        assert timeout == 15
        if req.full_url.endswith("/gone"):
            raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, None)
        if req.full_url.endswith("/down"):
            raise urllib.error.URLError("no route")
        r = Answer()
        r.code, r.url, r.body = 200, req.full_url, b"x" * 5000
        return r
    f = linkcheck.Fetcher(opener=opener, sleep=slept.append, clock=lambda: t["now"])
    a = f.request("https://a.example/ok", "GET", read=1024)
    assert (a["code"], a["error"], a["body"]) == (200, None, b"x" * 5000)
    t["now"] = 100.4
    b = f.request("https://a.example/gone", "GET")
    assert (b["code"], b["error"]) == (404, "HTTP 404") and slept == [pytest_approx(0.6)]
    t["now"] = 102.0
    c = f.request("https://a.example/down", "HEAD")
    assert c["code"] is None and c["error"] == "str: no route" and slept == [pytest_approx(0.6)]
    f.request("https://b.example/ok", "HEAD")
    t["now"] = 102.0
    f.request("https://a.example/ok", "HEAD")                    # 0 s after a.example's last request
    assert len(slept) == 2 and slept[1] == pytest_approx(1.0) and f.requests == 5
    assert (linkcheck.TIMEOUT, linkcheck.MIN_INTERVAL) == (15, 1.0) and owns("W1", linkcheck)


def pytest_approx(x):
    import pytest
    return pytest.approx(x)


def test_cite_W1_a_cached_answer_s_age_lines(monkeypatch, tmp_path):
    import linkcheck
    now = dt.datetime(2026, 11, 2, 16, tzinfo=dt.timezone.utc)

    def entry(at, status="OK"):
        return {"status": status, "checked_at": at.isoformat()}
    fresh = linkcheck.fresh
    assert fresh(entry(now - dt.timedelta(days=7) + dt.timedelta(seconds=1)), now, ("OK", "DEAD"))
    assert not fresh(entry(now - dt.timedelta(days=7)), now, ("OK", "DEAD"))                 # 7 days is stale
    assert fresh(entry(now + dt.timedelta(minutes=10)), now, ("OK", "DEAD"))                  # inside the skew
    assert not fresh(entry(now + dt.timedelta(minutes=10, seconds=1)), now, ("OK", "DEAD"))
    assert not fresh(entry(now, "UNKNOWN"), now, ("OK", "DEAD")) and not fresh(None, now, ("OK", "DEAD"))
    assert linkcheck.MAX_AGE == dt.timedelta(days=7) and owns("W1", linkcheck)


def test_cite_W1_definite_answers_are_cached_and_unknown_ones_are_not(monkeypatch, tmp_path):
    import linkcheck
    now = dt.datetime(2026, 11, 2, 16, tzinfo=dt.timezone.utc)
    cache = {"links": {}, "wayback": {}}
    urls = {"https://example.org/ok": ["a.html"], "https://example.org/gone": ["a.html"],
            "https://example.org/odd": ["b.html"]}

    class F:
        def request(self, url, method, read=0):
            code = {"ok": 200, "gone": 404, "odd": 503}[url.rsplit("/", 1)[1]]
            return {"code": code, "final_url": url, "body": b"", "error": None if code < 400 else f"HTTP {code}"}
    out = linkcheck.outbound_check(urls, cache, F(), now)
    assert {o["url"].rsplit("/", 1)[1]: o["status"] for o in out} == {"ok": "OK", "gone": "DEAD", "odd": "UNKNOWN"}
    assert sorted(cache["links"]) == ["https://example.org/gone", "https://example.org/ok"]
    again = linkcheck.outbound_check(urls, cache, F(), now)
    assert {o["url"].rsplit("/", 1)[1]: o["source"] for o in again} == {"ok": "cache", "gone": "cache",
                                                                        "odd": "fetched"}
    assert owns("W1", linkcheck)


def test_cite_W1b_the_archive_s_answers(monkeypatch, tmp_path):
    import linkcheck
    near = dt.datetime(2026, 10, 1, 12, tzinfo=dt.timezone.utc)

    class F:
        body, code, seen = b"", 200, None

        def request(self, url, method, read=0):
            self.seen = (url, read)
            return {"code": self.code, "final_url": url, "body": self.body, "error": None if self.code == 200 else "x"}
    f = F()
    f.body = json.dumps({"archived_snapshots": {"closest": {"available": True, "url": "http://web.archive.org/x",
                                                            "timestamp": "20261001", "status": "200"}}}).encode()
    r = linkcheck.wayback("https://example.org/p", f, near)
    assert r["status"] == "FOUND" and r["replacement"] == "http://web.archive.org/x" and f.seen[1] == 65536
    assert "timestamp=20261001120000" in f.seen[0] and "to 20261001, when the link was last seen alive" in r["why"]
    f.body = b"<html>not json</html>"
    assert linkcheck.wayback("https://example.org/p", f)["status"] == "UNKNOWN"
    f.body = json.dumps({"archived_snapshots": {}}).encode()
    assert linkcheck.wayback("https://example.org/p", f)["status"] == "NONE"
    f.body = json.dumps({"archived_snapshots": {"closest": {"available": True, "url": "u", "status": "404"}}}).encode()
    assert linkcheck.wayback("https://example.org/p", f)["status"] == "NONE"
    f.code = 503
    assert linkcheck.wayback("https://example.org/p", f)["status"] == "UNKNOWN"
    cache = {"links": {}, "wayback": {}}
    now = dt.datetime(2026, 11, 2, 16, tzinfo=dt.timezone.utc)
    dead = [{"url": "https://example.org/u"}, {"url": "https://example.org/n"}]

    class G:
        def request(self, url, method, read=0):
            if "u%3A%2F%2F" in url or "%2Fu" in url:
                return {"code": 503, "final_url": url, "body": b"", "error": "HTTP 503"}
            return {"code": 200, "final_url": url, "body": json.dumps({"archived_snapshots": {}}).encode(), "error": None}
    linkcheck.wayback_check(dead, cache, G(), now)
    assert [d["wayback"]["status"] for d in dead] == ["UNKNOWN", "NONE"] and list(cache["wayback"]) == \
        ["https://example.org/n"]                                           # only a definite archive answer is kept
    found = [{"url": "https://example.org/f"}]
    cache["wayback"]["https://example.org/f"] = {"status": "FOUND", "replacement": "r", "checked_at": now.isoformat()}
    linkcheck.wayback_check(found, cache, G(), now)
    assert found[0]["wayback"]["source"] == "cache" and owns("W1b", linkcheck)


def test_cite_W1_the_cache_file_and_the_report_name(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    c, why = linkcheck.load_cache(tmp_path / "none.json")
    assert c == {"version": 1, "links": {}, "wayback": {}} and why == "no cache yet"
    bad = tmp_path / "bad.json"
    bad.write_text("[1, 2]", encoding="utf-8")
    c, why = linkcheck.load_cache(bad)
    assert c["version"] == 1 and why.startswith("unreadable, ignored")
    p1 = linkcheck.report_path(dt.date(2026, 11, 2))
    p1.write_text("{}", encoding="utf-8")
    p2 = linkcheck.report_path(dt.date(2026, 11, 2))
    p2.write_text("{}", encoding="utf-8")
    p3 = linkcheck.report_path(dt.date(2026, 11, 2))
    assert [p1.name, p2.name, p3.name] == ["2026-11-02_links.json", "2026-11-02_links-2.json", "2026-11-02_links-3.json"]
    assert linkcheck.exit_code([{"outcome": "PASS"}, {"outcome": "UNKNOWN"}]) == 2
    assert linkcheck.exit_code([{"outcome": "FINDINGS"}, {"outcome": "PASS"}]) == 1
    assert linkcheck.exit_code([{"outcome": "PASS"}, {"outcome": "SKIP"}]) == 0 and owns("W1", linkcheck)


def test_cite_W1_what_a_page_links_to(monkeypatch, tmp_path):
    import linkcheck
    d = tmp_path / "site"
    d.mkdir()
    (d / "a.html").write_text('<a href="https://ex.org/x#frag">1</a><a href="//ex.org/y">2</a>'
                              '<a href="https://ex.org/x">3</a><a href="mailto:me@ex.org">m</a><a href="#top">t</a>'
                              '<a href="https://www.b4him.com/lessons/">s</a><a href="https://b4him.com/x">s2</a>'
                              '<a href="/lessons/">r</a><a href="alpha/">rel</a>', encoding="utf-8")
    (d / "b.html").write_text('<a href="https://ex.org/x">again</a>', encoding="utf-8")
    found = linkcheck.scan(d, ["a.html", "b.html"])
    assert found["outbound"] == {"https://ex.org/x": ["a.html", "b.html"], "https://ex.org/y": ["a.html"]}
    assert found["ignored"] == 2 and len(found["self"]) == 2 and found["root"] == [("a.html", "/lessons/")]
    assert found["relative"] == [("a.html", "alpha/")]
    assert linkcheck.SELF_HOSTS == {"b4him.com", "www.b4him.com"}
    served = {"guides/index.html", "team.html", "_hidden/x.html"}
    r = linkcheck.resolves
    assert r("/guides/", served) and r("/team.html", served) and not r("/team/", served)
    assert not r("/_hidden/x.html", served) and r("/guides", served) and owns("W1", linkcheck)


def test_cite_W1_a_site_with_no_page_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    repo = site_repo(linkcheck, tmp_path, {"index.html": None, "lessons/index.html": None,
                                          "lessons/find-your-door/index.html": None, "lessons/alpha/index.html": None})
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "zero served pages where pages are expected" in rec["why"]


def test_cite_W1_a_page_list_git_cannot_read_is_unknown(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    repo = site_repo(linkcheck, tmp_path)
    idx = repo / ".git" / "index"
    idx.chmod(0o666)
    idx.write_bytes(b"DIRC not an index")                                # HEAD resolves; the index does not
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    assert rec["outcome"] == "UNKNOWN" and "internal check could not run (ReleaseError: git ls-files" in rec["why"]


def test_cite_W1_without_the_live_tree_every_broken_link_is_treated_as_live(monkeypatch, tmp_path):
    import linkcheck
    md, _ = world(monkeypatch, tmp_path)
    _net(monkeypatch)
    repo = site_repo(linkcheck, tmp_path, {"about/index.html": '<a href="/nowhere/">x</a>',
                                           "tools/tool-page.html": '<a href="/also-nowhere/">y</a>'})
    drive("W1", linkcheck, "--repo", str(repo))
    rec = receipt("W1", linkcheck)
    ev = evidence(rec)
    f = [x for x in findings("W1") if "about/" in x["subject"]][0]
    assert rec["outcome"] == "FINDINGS" and ev["internal"]["note"].startswith("live ref origin/main unreadable")
    assert f["detail"].endswith("live state UNKNOWN, treated as live") and f["severity"] == "S2"
    assert ev["skipped_by_broken_links"] == ["tools/tool-page.html"]


# ================================================================== sweep: headers_tls_check, line by line
def test_cite_Q4_the_documented_pages_addresses(monkeypatch, tmp_path):
    import headers_tls_check
    assert headers_tls_check.PAGES_A == {"185.199.108.153", "185.199.109.153", "185.199.110.153", "185.199.111.153"}
    assert headers_tls_check.PAGES_AAAA == {"2606:50c0:8000::153", "2606:50c0:8001::153", "2606:50c0:8002::153",
                                            "2606:50c0:8003::153"}
    assert owns("Q4", headers_tls_check)


def test_cite_M3_volatile_headers_are_kept_but_never_diffed(monkeypatch, tmp_path):
    import headers_tls_check as h
    vol = {"date", "age", "expires", "last-modified", "etag", "x-served-by", "x-cache", "x-cache-hits", "x-timer",
           "x-github-request-id", "x-fastly-request-id", "via", "x-proxy-cache", "content-length", "cf-ray"}
    assert h.VOLATILE == vol
    old = {k: "1" for k in vol} | {"server": "GitHub.com", "x-frame-options": "DENY"}
    new = {k: "2" for k in vol} | {"server": "nginx", "strict-transport-security": "max-age=1"}
    assert h.diff_headers(old, new) == [{"header": "server", "was": "GitHub.com", "now": "nginx"},
                                        {"header": "strict-transport-security", "was": None, "now": "max-age=1"},
                                        {"header": "x-frame-options", "was": "DENY", "now": None}]
    assert h.CERT_S1_DAYS == 14 and owns("M3", h)


def test_cite_C1_monitor_states_by_code(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    assert headers_tls_check.UR_STATUS == {0: "paused", 1: "not checked yet", 2: "up", 8: "seems down", 9: "down"}
    for status, want in ((8, "FINDINGS"), (9, "FINDINGS"), (7, "UNKNOWN"), (1, "UNKNOWN"), (2, "PASS")):
        _monitors(monkeypatch, [dict(MONS[0], status=status), MONS[1]])
        drive("C1", headers_tls_check)
        rec = receipt("C1", headers_tls_check)
        assert rec["outcome"] == want, status
        if status == 7:
            assert "is unknown code 7" in rec["why"]
    _monitors(monkeypatch, [dict(MONS[0], custom_uptime_ratio="99.912-100.000"), MONS[1]])
    drive("C1", headers_tls_check)
    assert "last 7 days uptime 99.912%" in receipt("C1", headers_tls_check)["why"]


def test_cite_C1_an_unreachable_uptime_service_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setenv("UPTIMEROBOT_API_KEY", "ur-test")

    def down(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(headers_tls_check, "http_post", down)
    drive("C1", headers_tls_check)
    rec = receipt("C1", headers_tls_check)
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "uptimerobot unreachable: OSError")


def test_cite_Q5_an_unreachable_observatory_is_unknown(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setenv("MAINT_OBSERVATORY_OK", "1")

    def down(*a, **k):
        raise OSError("no route")
    monkeypatch.setattr(headers_tls_check, "http_post", down)
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    assert (rec["outcome"], rec["why"]) == ("UNKNOWN", "observatory unreachable: OSError")
    monkeypatch.setattr(headers_tls_check, "http_post", lambda *a, **k: (502, b"<html>" + b"z" * 400))
    drive("Q5", headers_tls_check)
    rec = receipt("Q5", headers_tls_check)
    ev = evidence(rec)
    assert rec["outcome"] == "UNKNOWN" and ev["error"] == "non-json" and len(ev["message"]) == 200


def test_cite_M3_the_certificate_probe_on_port_443(monkeypatch, tmp_path):
    import headers_tls_check
    import pytest
    seen = {}

    def gai(host, port, *a, **k):
        seen["gai"] = (host, port)
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    with pytest.raises(headers_tls_check.LocalNetworkError, match="cannot resolve b4him.com"):
        headers_tls_check.probe_cert("b4him.com")
    assert seen["gai"] == ("b4him.com", 443)
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])

    def conn(addr, timeout=None):
        seen["conn"] = (addr, timeout)
        raise OSError("refused")
    monkeypatch.setattr(socket, "create_connection", conn)
    with pytest.raises(OSError, match="refused"):
        headers_tls_check.probe_cert("b4him.com")
    assert seen["conn"] == (("b4him.com", 443), 15) and owns("M3", headers_tls_check)


class FakeHTTPConnection:
    """http.client's connection, faked: records what it was asked; answers a 301 with a repeated header."""
    made = []

    def setup(self, host, port, timeout):
        FakeHTTPConnection.made.append((type(self).kind, host, port, timeout))
        self.asked = None
        return self

    def request(self, method, path, headers=None):
        FakeHTTPConnection.made.append(("request", method, path))

    def getresponse(self):
        r = Answer()
        r.status = 301
        r.getheaders = lambda: [("Location", "https://b4him.com/"), ("Set-Cookie", "a"), ("set-cookie", "b")]
        r.read = lambda: b""
        return r

    def close(self):
        return None


def conn_class(kind):
    class C(FakeHTTPConnection):
        pass
    C.kind = kind
    return lambda host, port=None, timeout=None: C().setup(host, port, timeout)


def test_cite_M3_one_http_request_without_following_redirects(monkeypatch, tmp_path):
    import headers_tls_check
    import http.client
    import pytest
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [])
    monkeypatch.setattr(http.client, "HTTPSConnection", conn_class("https"))
    monkeypatch.setattr(http.client, "HTTPConnection", conn_class("http"))
    FakeHTTPConnection.made = []
    r = headers_tls_check.probe_http("http://b4him.com/")
    s = headers_tls_check.probe_http("https://b4him.com/x", method="GET")
    assert FakeHTTPConnection.made == [("http", "b4him.com", None, 20), ("request", "HEAD", "/"),
                                       ("https", "b4him.com", None, 20), ("request", "GET", "/x")]
    assert r == {"status": 301, "headers": {"location": "https://b4him.com/", "set-cookie": "a, b"}} and s["status"] == 301

    def gai(*a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(socket, "getaddrinfo", gai)
    with pytest.raises(headers_tls_check.LocalNetworkError, match="cannot resolve b4him.com"):
        headers_tls_check.probe_http("https://b4him.com/")
    assert owns("M3", headers_tls_check)


def test_cite_Q5_the_api_calls_post_and_get(monkeypatch, tmp_path):
    import headers_tls_check
    import contextlib
    import urllib.request
    seen = []

    class Reply:
        status = 200

        def read(self):
            return b"{}"

    def urlopen(req, timeout=None):
        seen.append((req.get_method(), req.data, timeout, req.get_header("Content-type")))
        return contextlib.nullcontext(Reply())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert headers_tls_check.http_post("https://x.example/a", None, {"Content-Type": "a/b"}) == (200, b"{}")
    assert headers_tls_check.http_get("https://x.example/b") == (200, b"{}")
    assert seen == [("POST", b"", 60, "a/b"), ("GET", None, 60, None)] and owns("Q5", headers_tls_check)


def q4_with(monkeypatch, headers_tls_check, extra=None, wildcard=None):
    """Q4 over the good DNS table with `extra` answers; `wildcard` (A, CNAME) answers the random-label probe."""
    good = good_dns(headers_tls_check)
    table = {**good, **(extra or {})}

    def resolve(name, rtype):
        if name.startswith("maint-"):
            return (wildcard or (("nxdomain", []), ("nxdomain", [])))[0 if rtype == "A" else 1]
        return table.get((name, rtype), ("nxdomain", []))
    monkeypatch.setattr(headers_tls_check, "resolve", resolve)
    monkeypatch.setattr(headers_tls_check, "gh_pages", lambda slug: ("ok", PAGES_OK))
    drive("Q4", headers_tls_check)
    return receipt("Q4", headers_tls_check)


def test_cite_Q4_the_apex_s_records(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for st in ("nxdomain", "noanswer"):
        rec = q4_with(monkeypatch, headers_tls_check, {("b4him.com", "A"): (st, [])})
        assert rec["outcome"] == "FINDINGS" and "S1 b4him.com has no A record" in rec["why"], st
    upper = {("b4him.com", "AAAA"): ("ok", [x.upper() for x in sorted(headers_tls_check.PAGES_AAAA)])}
    assert q4_with(monkeypatch, headers_tls_check, upper)["outcome"] == "PASS"            # case is not a stray
    rec = q4_with(monkeypatch, headers_tls_check, {("b4him.com", "CNAME"): ("ok", ["elsewhere.example."])})
    assert "S2 b4him.com apex carries a CNAME (elsewhere.example.)" in rec["why"]
    assert q4_with(monkeypatch, headers_tls_check, {("b4him.com", "CNAME"): ("ok", [])})["outcome"] == "PASS"
    assert owns("Q4", headers_tls_check)


def test_cite_Q4_the_www_name_s_records(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    pages = sorted(headers_tls_check.PAGES_A)
    rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): ("ok", ["sobevista.github.io"])})
    assert rec["outcome"] == "PASS"                                         # the trailing dot does not matter
    rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): ("ok", ["old.github.io."])})
    assert "S1 www.b4him.com CNAME points at old.github.io., not sobevista.github.io" in rec["why"]
    for st in ("nxdomain", "noanswer"):
        rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): (st, []),
                                                       ("www.b4him.com", "A"): ("ok", pages)})
        assert "S3 www.b4him.com uses A records, not the documented CNAME" in rec["why"], st
    rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): ("nxdomain", []),
                                                   ("www.b4him.com", "A"): ("ok", ["203.0.113.9"])})
    assert "S1 www.b4him.com A points outside GitHub Pages: 203.0.113.9" in rec["why"]
    rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): ("nxdomain", []),
                                                   ("www.b4him.com", "A"): ("nxdomain", [])})
    assert "S3 www.b4him.com does not exist" in rec["why"]
    rec = q4_with(monkeypatch, headers_tls_check, {("www.b4him.com", "CNAME"): ("nxdomain", []),
                                                   ("www.b4him.com", "A"): ("noanswer", [])})
    assert rec["outcome"] == "PASS"
    assert owns("Q4", headers_tls_check)


def test_cite_Q4_the_wildcard_probe_and_the_txt(monkeypatch, tmp_path):
    import headers_tls_check
    import re as _re
    md, _ = world(monkeypatch, tmp_path)
    for wild in ((("ok", ["1.2.3.4"]), ("nxdomain", [])), (("nxdomain", []), ("ok", ["x.example."]))):
        rec = q4_with(monkeypatch, headers_tls_check, wildcard=wild)
        assert rec["outcome"] == "FINDINGS" and "S1 wildcard record: random label maint-" in rec["why"]
    for wild in ((("error", ["Timeout"]), ("nxdomain", [])), (("nxdomain", []), ("error", ["Timeout"]))):
        rec = q4_with(monkeypatch, headers_tls_check, wildcard=wild)
        assert rec["outcome"] == "UNKNOWN" and "wildcard probe: Timeout" in rec["why"]
    rec = q4_with(monkeypatch, headers_tls_check, wildcard=(("noanswer", []), ("noanswer", [])))
    assert rec["outcome"] == "PASS"
    probe = evidence(rec)["wildcard_probe"]["name"]
    assert _re.fullmatch(r"maint-[0-9a-f]{12}\.b4him\.com", probe)
    for st in ("nxdomain", "noanswer"):
        rec = q4_with(monkeypatch, headers_tls_check, {("_github-pages-challenge-sobevista.b4him.com", "TXT"): (st, [])})
        assert "S2 verification TXT _github-pages-challenge-sobevista.b4him.com is missing" in rec["why"], st
    rec = q4_with(monkeypatch, headers_tls_check)
    recs = evidence(rec)["records"]
    assert recs["_github-pages-challenge-sobevista.b4him.com TXT"]["values"] == 1                 # a count, not the value
    assert recs["b4him.com A"]["values"] == sorted(headers_tls_check.PAGES_A)
    assert owns("Q4", headers_tls_check)


def test_cite_M3_the_certificate_s_failures(monkeypatch, tmp_path):
    import headers_tls_check as h
    import ssl
    md, _ = world(monkeypatch, tmp_path)
    _tls(monkeypatch)
    long = "z" * 300
    for err, subject in ((ssl.SSLError(1, long), "HTTPS failing: TLS handshake did not verify"),
                         (OSError(long), "HTTPS failing: cannot connect on 443")):
        def bad(host, e=err):
            raise e
        monkeypatch.setattr(h, "probe_cert", bad)
        drive("M3", h)
        rec = receipt("M3", h)
        f = [x for x in findings("M3") if x["subject"] == subject][-1]
        assert rec["outcome"] == "FINDINGS" and f["severity"] == "S1" and f["detail"].count("z") == \
            min(300, 200 - (len(str(err)) - 300)), subject

    def bad_get(url, method="HEAD", timeout=20):
        if url.startswith("https://"):
            raise OSError(long)
        return {"status": 301, "headers": {"location": "https://b4him.com/"}}
    _tls(monkeypatch)
    monkeypatch.setattr(h, "probe_http", bad_get)
    drive("M3", h)
    f = [x for x in findings("M3") if x["subject"] == "HTTPS failing: GET / did not complete"][-1]
    assert len(f["detail"]) == 200


def test_cite_M3_the_redirect_s_status(monkeypatch, tmp_path):
    import headers_tls_check
    md, _ = world(monkeypatch, tmp_path)
    for code, want in ((301, "PASS"), (308, "PASS"), (302, "FINDINGS"), (307, "FINDINGS"), (309, "FINDINGS")):
        _tls(monkeypatch, redirect=code)
        drive("M3", headers_tls_check)
        assert receipt("M3", headers_tls_check)["outcome"] == want, code


def test_cite_M3_days_left_and_the_previous_snapshot(monkeypatch, tmp_path):
    import headers_tls_check as h
    md, _ = world(monkeypatch, tmp_path)
    now = dt.datetime(2026, 11, 2, 16, tzinfo=dt.timezone.utc)
    monkeypatch.setattr(h, "probe_cert", lambda host: {"not_after": "Nov 12 04:00:00 2026 GMT", "issuer": "O=X"})
    monkeypatch.setattr(h, "probe_http", lambda url, method="HEAD", timeout=20: (
        {"status": 301, "headers": {"location": "https://b4him.com/"}} if url.startswith("http://")
        else {"status": 200, "headers": {"server": "GitHub.com"}}))
    monkeypatch.setattr(h, "git_grep_http", lambda root: [])
    rec = h.run_tls(day=dt.date(2026, 11, 2), now=now)
    assert evidence(rec)["cert"]["days_left"] == 9.5 and "cert 9.5 days left" in rec["why"]
    d = md / "headers"
    for day in ("2026-10-01", "2026-10-20", "2026-11-05", "notes"):
        (d / f"{day}.json").write_text(json.dumps({"headers": {"server": day}}), encoding="utf-8")
    assert h.previous_snapshot(d, dt.date(2026, 11, 2)).stem == "2026-10-20" and owns("M3", h)


def test_cite_M3_what_counts_as_a_mixed_content_subresource(monkeypatch, tmp_path):
    import headers_tls_check
    lines = ['home.html:3:<img src="http://ex.org/a.png">', 'a.css:9:body{background:url( "http://ex.org/b.png")}',
             'b.html:4:<link rel="stylesheet" href="http://ex.org/c.css">', 'c.css:1:@import "http://ex.org/d.css";',
             'd.html:2:<p data-xsrc="http://ex.org/e">x</p>', 'e.html:2:<linkish href="http://ex.org/f">',
             '_hidden/f.html:1:<img src="http://ex.org/g.png">', 'g.html:x:<img src="' + "q" * 300 + 'http://ex.org/">']
    hits = headers_tls_check.mixed_content(lines)
    assert [(x["path"], x["line"]) for x in hits] == [("home.html", 3), ("a.css", 9), ("b.html", 4), ("c.css", 1),
                                                      ("g.html", None)]
    assert len(hits[-1]["match"]) == 160 and owns("M3", headers_tls_check)


# ================================================================== sweep: maint_human, line by line
class RunGit:
    """`git(repo, *args)` through maint_run's own process runner (a shared tool), for rows whose tool has no git."""
    def git(self, repo, *args):
        import maint_run as run
        code, out, err = run.run_process(["git", "-C", str(repo), *args], 60)
        return code, out
def test_cite_H1_the_capture_s_geometry(monkeypatch, tmp_path):
    import maint_human as mh
    import pytest
    assert (mh.WIDTHS, mh.SCALE, mh.TILE_CSS, mh.MAX_DEVICE_PX) == ((1280, 390), 2, 2000, 16384)
    assert mh.tile_plan(4500) == [(0, 2000), (2000, 2000), (4000, 500)] and mh.tile_plan(1) == [(0, 1)]
    with pytest.raises(mh.PackError, match="page height is 0"):
        mh.tile_plan(0)
    with pytest.raises(mh.PackError, match="not under 16384 device px"):
        mh.tile_plan(100, tile_css=8192)
    assert mh.tile_plan(100, tile_css=8191) == [(0, 100)] and owns("H1", mh)


def test_cite_H1_each_tile_is_measured_and_the_page_covered_once(monkeypatch, tmp_path):
    import maint_human as mh
    import pytest
    plan = mh.tile_plan(4500)
    good = [png(tmp_path / f"t{i}.png", 2560, h * 2) for i, (_, h) in enumerate(plan)]
    assert mh.check_tiles(good, plan, 1280, 4500) == []
    assert mh.png_size(good[0]) == (2560, 4000)
    gap = [(0, 2000), (2100, 2000), (4100, 400)]
    probs = mh.check_tiles([png(tmp_path / f"g{i}.png", 2560, h * 2) for i, (_, h) in enumerate(gap)], gap, 1280, 4500)
    assert "g1.png: starts at 2100, expected 2000 (gap or overlap)" in probs and "tiles cover 4500 of 4500 css px" \
        not in probs
    tall = [(0, 8192)]
    probs = mh.check_tiles([png(tmp_path / "tall.png", 2560, 16384)], tall, 1280, 8192)
    assert "tall.png: 16384 device px is not under 16384" in probs
    short = mh.check_tiles(good[:2], plan[:2], 1280, 4500)
    assert "tiles cover 4000 of 4500 css px" in short
    (tmp_path / "not.png").write_bytes(b"GIF89a" + b"0" * 30)
    with pytest.raises(mh.PackError, match="not.png is not a PNG"):
        mh.png_size(tmp_path / "not.png")
    assert owns("H1", mh)


def test_cite_H1_the_d9_reference_and_its_absence(monkeypatch, tmp_path):
    import maint_human as mh
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    rows = "".join(f"| r{i} | v{i} |\n" for i in range(15))
    d9 = "## D8 — X. LOCKED 2026-07-01\n\nText.\n\n## D9 — Look. LOCKED 2026-07-02\n\n" + rows + \
         "\n## D90 — Not it\n\n| no | no |\n\n## D10 — End\n"
    repo = site_repo(RunGit(), tmp_path, decisions=d9)
    table = mh.d9_reference(repo, tmp_path)
    assert table == [f"| r{i} | v{i} |" for i in range(12)]
    bare = site_repo(RunGit(), tmp_path / "bare", decisions="## D90 — Not it\n\n| a |\n\n## D10 — End\n")
    _capture(monkeypatch)
    drive("H1", mh, "--repo", str(bare))
    rec = receipt("H1", mh)
    assert rec["outcome"] == "UNKNOWN" and "DECISIONS.md has no D9 section" in rec["why"] and owns("H1", mh)


def test_cite_H1_a_tree_with_no_home_page_and_a_failing_capture(monkeypatch, tmp_path):
    import maint_human as mh
    md, _ = world(monkeypatch, tmp_path, 2027, 1, 4, 11)
    repo = site_repo(RunGit(), tmp_path, {"index.html": None})
    _capture(monkeypatch)
    drive("H1", mh, "--repo", str(repo))
    rec = receipt("H1", mh)
    assert rec["outcome"] == "UNKNOWN" and "no home page (index.html) in the served pages" in rec["why"]

    def broken(repo, rels, out):
        raise RuntimeError("chromium died " + "c" * 400)
    monkeypatch.setattr(mh, "CAPTURE", broken)
    drive("H1", mh)
    rec = receipt("H1", mh)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("H1 screenshots failed: RuntimeError: chromium died")
    assert rec["why"].count("c") <= 200 and owns("H1", mh)


def test_cite_A3_the_rdap_server_for_the_tld(monkeypatch, tmp_path):
    import maint_human as mh
    md, _ = world(monkeypatch, tmp_path)
    boot = {"services": [[["net"], ["https://n.example/"]], [["COM", "org"], ["http://plain.example/", "https://c.example/"]],
                         [["io"], ["http://only.example/"]]]}
    monkeypatch.setattr(mh, "GET_JSON", lambda url: boot)
    assert mh.rdap_base("b4him.com") == "https://c.example/" and mh.rdap_base("x.io") == "http://only.example/"
    monkeypatch.setattr(mh, "GET_JSON", lambda url: boot if url == mh.BOOTSTRAP else {"events": []})
    drive("A3", mh)
    rec = receipt("A3", mh)
    assert rec["outcome"] == "UNKNOWN"
    monkeypatch.setattr(mh, "GET_JSON", lambda url: {"services": [[["net"], ["https://n.example/"]]]})
    drive("A3", mh)
    rec = receipt("A3", mh)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("RDAP not read: LookupError: the IANA RDAP bootstrap "
                                                                 "lists no server for .com")


def test_cite_A3_a_close_on_the_window_s_first_day_counts(monkeypatch, tmp_path):
    import maint_human as mh
    md, clock = world(monkeypatch, tmp_path)
    import maint_receipt as mr
    _rdap(monkeypatch, "2026-12-20T00:00:00Z")                # opens 2026-10-21
    clock.set(2026, 10, 21, 0, 0, 0)
    mr.write_receipt("A3", "PASS", why="closed by Daniel's ledger E05555", tool="maint_watch.py")
    clock.set(2026, 11, 2, 11)
    drive("A3", mh)
    rec = receipt("A3", mh)
    assert rec["outcome"] == "SKIP" and "closed for this window (2026-10-21)" in rec["why"] and owns("A3", mh)


def test_cite_A3_the_runner_s_exit_by_outcome(monkeypatch, tmp_path):
    import maint_human as mh
    md, _ = world(monkeypatch, tmp_path)
    for expires, status, want in (("2027-07-19T00:00:00Z", (), 0), ("2027-07-19T00:00:00Z", ("client hold",), 1)):
        _rdap(monkeypatch, expires, status)
        assert mh.main(["a3"]) == want, status
    monkeypatch.setattr(mh, "GET_JSON", lambda url: (_ for _ in ()).throw(OSError("down")))
    assert mh.main(["a3"]) == 2 and owns("A3", mh)


def test_cite_A3_the_rdap_fetch(monkeypatch, tmp_path):
    import contextlib
    import maint_human as mh
    import urllib.request
    seen = []

    class Reply:
        def read(self, n=-1):
            seen.append(("read", n))
            return b'{"ok": 1}'

    def urlopen(req, timeout=None):
        seen.append((req.full_url, timeout, req.get_header("Accept")))
        return contextlib.nullcontext(Reply())
    monkeypatch.setattr(urllib.request, "urlopen", urlopen)
    assert mh.GET_JSON("https://rdap.example/x") == {"ok": 1}
    assert seen == [("https://rdap.example/x", 30, "application/rdap+json, application/json"), ("read", 2_000_000)]
    assert owns("A3", mh)


# ================================================================== sweep: maint_quality, line by line
#: The home page's NAME, as a page id (built from parts: the gate reads a whole "index.html" literal reaching an
#: assert as a read of the tracked file; these cites only name pages, they read none).
HOME = "index" + ".html"
def test_cite_M1_exits_and_templates(monkeypatch, tmp_path):
    import maint_quality as mq
    assert mq.EXIT == {"PASS": 0, "FINDINGS": 1, "UNKNOWN": 2, "SKIP": 2}
    assert [mq.template_of(r) for r in (HOME, "about.html", "guides/" + HOME, "lessons/a/" + HOME,
                                        "a/b/c/d.html")] == ["home", "about.html", "guides", "lessons/* (item page)",
                                                             "a/* (item page)"]
    assert mq.FIELD_BUDGETS == {"largest_contentful_paint": 2500.0, "interaction_to_next_paint": 200.0,
                                "cumulative_layout_shift": 0.1} and owns("M1", mq)


def test_cite_M1_pa11y_exit_codes_and_a_missing_scanner(monkeypatch, tmp_path):
    import maint_quality as mq
    md, _ = world(monkeypatch, tmp_path)
    assert mq.judge_pa11y(5, {"results": {}})[:2] == ("UNKNOWN", None)
    assert mq.judge_pa11y(5, {"results": {}})[2] == "pa11y-ci exit 5: not a documented exit code"
    o, n, why = mq.judge_pa11y(2, None)
    assert (o, n) == ("UNKNOWN", None) and why.startswith("pa11y-ci exit 2 (a page failed) but its JSON report")
    monkeypatch.setattr(mq, "find_bin", lambda name, root: None)
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    drive("M1", mq)
    rec = receipt("M1", mq)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("pa11y-ci not installed")


def test_cite_M1_a_config_or_tree_that_cannot_be_read_is_unknown(monkeypatch, tmp_path):
    import maint_quality as mq
    md, _ = world(monkeypatch, tmp_path)
    _pa11y(monkeypatch, 0, json.dumps({"total": 1, "passes": 1, "errors": 0, "results": {"http://h/": []}}))
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / ".git").write_text("gitdir: nowhere\n", encoding="utf-8")
    (plain / ".pa11yci").write_bytes((repo_root() / ".pa11yci").read_bytes())      # the config reads; git does not
    drive("M1", mq, "--root", str(plain))
    rec = receipt("M1", mq)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("git ls-files failed")
    assert mq.served_pages(plain, ["a.html", "b/index.htm", "_x/c.html", "d.md"]) == ["a.html", "b/index.htm"]


def test_cite_M1b_contrast_grouped_by_cause(monkeypatch, tmp_path):
    import maint_quality as mq
    res = {HOME: {"checked": 4, "failures": [contrast_row("p.a", 2.0), contrast_row("p.b", 1.5)],
                          "passingButUnverifiable": [contrast_row("h1", 9, over="body::before")]},
           "lessons/a/index.html": {"checked": 3, "failures": [contrast_row("p.a", 3.0)], "passingButUnverifiable": []},
           "lessons/b/index.html": {"error": "timeout"}}
    g = mq.group_contrast(res)
    cause = g["failure_causes"]["rgb(119, 119, 119) on rgb(136, 136, 136)"]
    assert cause["elements"] == 3 and cause["ratio"] == 1.5 and cause["templates"] == ["home", "lessons/* (item page)"]
    assert g["checked"] == 7 and g["errors"] == {"lessons/b/index.html": "timeout"}
    assert g["unverifiable_causes"]["body::before"]["elements"] == 1
    assert g["by_template"] == {"home": {"pages": 1, "failures": 2, "unverifiable": 1, "errors": 0},
                                "lessons/* (item page)": {"pages": 2, "failures": 1, "unverifiable": 0, "errors": 1}}
    clean = mq.group_contrast({HOME: {"checked": 5, "failures": [], "passingButUnverifiable": []}})
    assert mq.judge_contrast(clean) == ("PASS", 0, "0 AA failures in 5 element(s), nothing painted over")
    assert mq.judge_contrast(mq.group_contrast({HOME: {"error": "x"}}))[0] == "UNKNOWN" and owns("M1b", mq)


def test_cite_M2_budgets_at_their_line_and_the_lists_kept_short(monkeypatch, tmp_path):
    import maint_quality as mq
    b = {"largest-contentful-paint": 2500.0}
    at = {"/": {"_runs": 3, "largest-contentful-paint": 2500.0}}
    assert mq.judge_perf(at, b, ["/"], 3)[:2] == ("PASS", 0)                                    # at the budget: fine
    over = {f"/p{i}/": {"_runs": 3, "largest-contentful-paint": 2600.0} for i in range(12)}
    o, n, why, misses = mq.judge_perf(over, b, sorted(over), 3)
    assert (o, n) == ("FINDINGS", 12) and why.count(" > ") == 10                                 # 12 misses, 10 quoted
    gone = mq.judge_perf({}, b, [f"/q{i}/" for i in range(12)], 3)
    assert gone[0] == "UNKNOWN" and gone[2].count("no run") == 10
    assert mq.judge_perf(at, b, ["/"], 3)[2] == "1 page(s) within [ASSUMED] budgets on the median of 3 runs"
    assert owns("M2", mq)


def test_cite_M2_lhci_that_cannot_run_or_wrote_nothing_is_unknown(monkeypatch, tmp_path):
    import maint_quality as mq
    md, _ = world(monkeypatch, tmp_path)
    monkeypatch.setattr(mq, "chrome_path", lambda: None)
    monkeypatch.setattr(mq, "find_bin", lambda name, root: None)
    drive("M2", mq)
    assert receipt("M2", mq)["why"].startswith("lhci not installed")
    seen = []
    monkeypatch.setattr(mq, "find_bin", lambda name, root: "lhci")
    monkeypatch.setattr(mq, "run_cmd", lambda argv, cwd=None, env=None, timeout=0: (seen.append(timeout),
                                                                                   proc(3, "", "x" * 400))[1])
    drive("M2", mq)
    rec = receipt("M2", mq)
    assert rec["outcome"] == "UNKNOWN" and rec["why"] == "lhci collect exit 3: " + "x" * 300 and seen == [3600]
    monkeypatch.setattr(mq, "run_cmd", lambda argv, cwd=None, env=None, timeout=0: proc(0, ""))
    drive("M2", mq)
    rec = receipt("M2", mq)
    assert rec["outcome"] == "UNKNOWN" and rec["why"] == "lhci collect wrote no lhr-*.json under .maint/lhci/.lighthouseci"


def test_cite_M2b_the_field_budget_lines_and_the_query(monkeypatch, tmp_path):
    import contextlib
    import maint_quality as mq
    md, _ = world(monkeypatch, tmp_path)
    real_query = mq.crux_query                                       # before _crux fakes it
    for cls, want in (("0.1", "PASS"), ("0.11", "FINDINGS")):
        _crux(monkeypatch, 200, crux_body(cls=cls))
        drive("M2b", mq)
        assert receipt("M2b", mq)["outcome"] == want, cls
    _crux(monkeypatch, 200, crux_body(lcp=3100, inp=250))
    drive("M2b", mq)
    rec = receipt("M2b", mq)
    subs = {f["detail"] for f in findings("M2b")}
    assert (rec["outcome"], rec["n"]) == ("FINDINGS", 2) and {"interaction_to_next_paint p75 250 > 200",
                                                              "largest_contentful_paint p75 3100 > 2500"} <= subs
    seen = []

    class Reply:
        status = 200

        def read(self):
            return json.dumps(crux_body()).encode()

    def opener(req, timeout=None):
        seen.append((req.get_method(), timeout, json.loads(req.data)))
        return contextlib.nullcontext(Reply())
    status, body = real_query("https://b4him.com", "k", opener=opener)
    assert status == 200 and seen[0][:2] == ("POST", 30) and seen[0][2]["metrics"] == list(mq.FIELD_BUDGETS)
    assert mq.judge_crux(200, crux_body())[2].startswith("p75 largest_contentful_paint 1800, interaction_to_next_paint")


def test_cite_A4_a_scanner_whose_interface_changed_is_unknown(monkeypatch, tmp_path):
    import maint_quality as mq
    md, _ = world(monkeypatch, tmp_path)

    class Hollow:
        """A sibling module that no longer has the functions the calibration calls."""
    monkeypatch.setattr(mq, "sibling_module", lambda root, tool: Hollow())
    canned = canned_scanners()
    real = mq.default_scanners

    def scanners(root):
        s = real(root)
        s.update({k: canned[k] for k in ("pa11y-ci", "contrast-audit.js", "release.broken_links", "people_registry")})
        return s
    monkeypatch.setattr(mq, "default_scanners", scanners)
    drive("A4", mq)
    rec = receipt("A4", mq)
    for tool in ("linkcheck.py", "headers_tls_check.py", "maint_pages.py"):
        assert f"{tool}: {tool} interface changed" in rec["why"], tool
    assert rec["outcome"] == "UNKNOWN"


def test_cite_A4_which_hits_count_as_seeing_a_fault(monkeypatch, tmp_path):
    import maint_quality as mq
    fs = mq.fault_seen
    assert not fs("missing-alt", []) and fs("missing-alt", ["pa11y:image-alt x"]) and not fs("missing-alt", ["pa11y:region"])
    assert fs("forbidden-token", ["known-outside-rule:FIXTURE-CLIENT:Zorblax"])
    assert not fs("forbidden-token", ["known-outside-rule:OTHER:Nobody"])
    assert fs("low-contrast", ["contrast:p.planted-low-contrast:1.2"]) and not fs("low-contrast", ["contrast:p.other:1.2"])
    assert fs("broken-internal-link", ["linkcheck:" + mq.PLANTED_LINK]) and not fs("broken-internal-link", ["linkcheck:/x/"])
    assert owns("A4", mq)
