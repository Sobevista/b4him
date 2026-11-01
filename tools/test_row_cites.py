"""The harness scope lock's cite tests for the 28 b4him maintenance-baseline rows (C1 .. A4).

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
import contextlib
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


class Sink:
    """A text sink for a tool's stdout / stderr while it runs in process."""
    parts = None

    def write(self, text):
        if self.parts is None:
            self.parts = []
        self.parts.append(str(text))
        return len(str(text))

    def flush(self):
        return None

    def text(self):
        return "".join(self.parts or [])


def in_process(tool, *pre):
    """maint_run's RUN for one drive, in process: maint_run asks for `[python, tools/<script>, *args]`; when <script>
    is the script `tool` (the row's own module, imported by the test) declares as its TOOL, its main(pre + args) runs
    here with stdout and stderr captured, and its exit code is returned, as a child process would. Any other script
    is refused (exit 2, nothing written): the test runs only the tool it imported."""
    import maint_receipt as mr

    def run_here(argv, timeout):
        script = Path(argv[1]).name
        if mr.tool_path(tool.TOOL) != "tools/" + script:
            return 2, "", f"the test imported {tool.TOOL}, not {script}"
        out, err = Sink(), Sink()
        try:
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = tool.main([*pre, *argv[2:]])
        except SystemExit as e:
            code = e.code if isinstance(e.code, int) else 1
        except Exception as e:  # noqa: BLE001 - a tool crash is the runner's to judge, as in a real child process
            return 1, out.text(), repr(e)
        return code, out.text(), err.text()
    return run_here


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
        run.RUN = in_process(tool, *pre)
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
    """Check `tool` (the module the test imported) is the module maint_run.py runs for `row`: the script it declares
    as its TOOL is exactly maint_run's RUNNERS script for the row (and in_process runs nothing else). -> the receipt
    `tool` field that module writes (tools/<script>)."""
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


def site_repo(tool, tmp_path, files=None, queue=None):
    """A throwaway b4him-shaped git repo, committed with the row's own tool's public `git(repo, *args)` (maint_pages
    and linkcheck each define one: the test starts no process itself). Same shape as tools/test_maint_pages.make_repo."""
    repo = tmp_path / "site"
    (repo / "data").mkdir(parents=True)
    for f in ("people_registry.json", "common_first_names.txt"):
        (repo / "data" / f).write_bytes((repo_root() / "data" / f).read_bytes())
    base = {
        ".gitignore": ".maint/\ndata/people_names.local.json\ndata/forbidden_tokens.local.json\n",
        "CNAME": "example.invalid\n",
        "DECISIONS.md": D11,
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


def pages_repo(monkeypatch, mp, tmp_path, files=None, names=False, queue=None):
    """The fixture site as maint_pages' tree (`mp` is maint_pages, imported by the test)."""
    repo = site_repo(mp, tmp_path, files, queue)
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

PROPS = settings(max_examples=6, deadline=None, derandomize=True,
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
        code, out, err = in_process(headers_tls_check)(argv, timeout)                         # the tool writes its PASS ...
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
