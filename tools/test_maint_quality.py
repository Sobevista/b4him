"""Tests for tools/maint_quality.py (rows M1, M1b, M2, M2b, A4) and tools/maint_receipt.py.

No network: pa11y-ci, lhci and the CrUX API are faked. The one real-browser test drives headless Chromium against the
fixtures on 127.0.0.1 only, and skips when Python Playwright is absent. Every row shows its PASS, FINDINGS and UNKNOWN
paths.
"""
import io
import json
import shutil
import urllib.error
from pathlib import Path

import pytest

import maint_quality as mq
import maint_receipt as mr

REPO = Path(__file__).resolve().parent.parent


def receipts(root):
    p = root / ".maint" / "maintenance_log.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


def findings(root):
    p = root / ".maint" / "maintenance_findings.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ---------------------------------------------------------------- receipts
def test_receipt_shape_and_refusals(tmp_path):
    r = mr.write_receipt("M1", "PASS", n=0, why="ok", evidence=".maint/x.json", tool="t", root=tmp_path)
    assert set(r) == {"at", "row", "outcome", "n", "why", "evidence", "tool"} and r["at"].endswith("Z")
    assert receipts(tmp_path) == [r]
    for bad in (dict(outcome="GREEN"), dict(outcome="FINDINGS", n=0), dict(outcome="UNKNOWN", why=""),
                dict(outcome="PASS", evidence="audits/x.json"), dict(outcome="PASS", evidence=".maint/../x"),
                dict(outcome="PASS", n=-1)):
        kw = {"why": "w", **bad}
        with pytest.raises(mr.ReceiptError):
            mr.write_receipt("M1", root=tmp_path, **kw)
    with pytest.raises(mr.ReceiptError):
        mr.write_finding("M1", "S9", "s", "d", "r", root=tmp_path)
    f = mr.write_finding("M1", "S2", "s", "d", "Site Maintainer", root=tmp_path)
    assert findings(tmp_path) == [f]


# ---------------------------------------------------------------- page list
def test_served_pages_rule():
    files = ["index.html", "about/index.html", "_drafts/x.html", "a/.hidden/x.html", "tools/tracks/n8n.html",
             "tools/maint_fixtures/index.html", "lessons/x/index.html", "README.md"]
    assert mq.served_pages(REPO, files) == ["about/index.html", "index.html", "lessons/x/index.html"]
    assert mq.page_path("index.html") == "/" and mq.page_path("a/b/index.html") == "/a/b/"
    assert mq.page_path("tools/tracks/n8n.html") == "/tools/tracks/n8n.html"
    assert [mq.template_of(r) for r in ("index.html", "lessons/index.html", "lessons/x/index.html")] == [
        "home", "lessons", "lessons/* (item page)"]


def test_served_pages_real_tree_has_no_factory_and_has_home():
    pages = mq.served_pages(REPO)
    assert "index.html" in pages and not any(p.startswith("tools/") for p in pages)


# ---------------------------------------------------------------- M1
REP_BAD = {"total": 2, "passes": 1, "errors": 2, "results": {
    "http://h/": [], "http://h/a/": [
        {"code": "WCAG2AA.Principle1.Guideline1_1.1_1_1.H37", "message": "Img element missing an alt", "runner": "htmlcs"},
        {"code": "image-alt", "message": "Images must have alternate text", "runner": "axe"}]}}
REP_OK = {"total": 2, "passes": 2, "errors": 0, "results": {"http://h/": [], "http://h/a/": []}}


def test_pa11y_exit_codes_map_to_outcomes():
    assert mq.judge_pa11y(0, REP_OK)[0] == "PASS"
    assert mq.judge_pa11y(1, None)[0] == "UNKNOWN"
    assert mq.judge_pa11y(1, REP_BAD)[0] == "UNKNOWN"          # a technical fault is never a page result
    assert mq.judge_pa11y(2, REP_BAD)[:2] == ("FINDINGS", 2)
    assert mq.judge_pa11y(2, None)[0] == "UNKNOWN"             # count unknown: not invented
    assert mq.judge_pa11y(0, None)[0] == "UNKNOWN"
    assert mq.judge_pa11y(7, REP_OK)[0] == "UNKNOWN"
    assert mq.parse_pa11y("noise\n" + json.dumps(REP_BAD)) == REP_BAD and mq.parse_pa11y("garbage") is None


def test_pa11yci_config_is_both_runners_wcag2aa():
    cfg = mq.a11y_config(REPO, ["http://h/"])
    assert cfg["defaults"]["standard"] == "WCAG2AA" and sorted(cfg["defaults"]["runners"]) == ["axe", "htmlcs"]
    assert cfg["urls"] == ["http://h/"]


@pytest.mark.parametrize("code,rep,outcome,n", [(0, REP_OK, "PASS", 0), (2, REP_BAD, "FINDINGS", 2),
                                                (1, None, "UNKNOWN", None)])
def test_cmd_a11y_receipts(tmp_path, monkeypatch, code, rep, outcome, n):
    monkeypatch.setattr(mq, "served_pages", lambda root: ["index.html", "a/index.html"])
    monkeypatch.setattr(mq, "run_pa11y", lambda root, rels, tag: (code, rep, {"base": "http://h", "exit": code}))
    rec = mq.cmd_a11y(tmp_path)
    assert (rec["row"], rec["outcome"], rec["n"]) == ("M1", outcome, n)
    assert (tmp_path / rec["evidence"]).exists()
    if outcome == "FINDINGS":
        f = findings(tmp_path)
        assert {x["subject"] for x in f} == {"image-alt", "WCAG2AA.Principle1.Guideline1_1.1_1_1.H37"}
        assert all(x["severity"] == "S2" and x["route_to"] == "Site Maintainer" for x in f)


def test_cmd_a11y_not_installed_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mq, "served_pages", lambda root: ["index.html"])
    monkeypatch.setattr(mq, "find_bin", lambda name, root: None)
    rec = mq.cmd_a11y(tmp_path)
    assert rec["outcome"] == "UNKNOWN" and "pa11y-ci not installed" in rec["why"]


# ---------------------------------------------------------------- M1b
def _row(sel, ratio, color="rgb(119, 119, 119)", bg="rgb(136, 136, 136)", over=None):
    return {"selector": sel, "ratio": ratio, "color": color, "background": bg, "large": False,
            "overlaySource": over, "overImage": bool(over), "translucentText": False}


def test_contrast_groups_by_cause_and_judges():
    res = {"index.html": {"checked": 10, "failures": [_row("p.a", 1.2), _row("p.b", 1.3)],
                          "passingButUnverifiable": [_row("h1", 9, over="body::before")]},
           "lessons/x/index.html": {"checked": 5, "failures": [_row("p.a", 1.2)], "passingButUnverifiable": []}}
    g = mq.group_contrast(res)
    assert list(g["failure_causes"]) == ["rgb(119, 119, 119) on rgb(136, 136, 136)"]      # three elements, one cause
    cause = g["failure_causes"]["rgb(119, 119, 119) on rgb(136, 136, 136)"]
    assert cause["elements"] == 3 and cause["templates"] == ["home", "lessons/* (item page)"]
    assert mq.judge_contrast(g)[:2] == ("FINDINGS", 1)
    unver = mq.group_contrast({"index.html": {"checked": 3, "failures": [],
                                              "passingButUnverifiable": [_row("h1", 9, over="body::before")] * 2}})
    out, n, why = mq.judge_contrast(unver)
    assert out == "UNKNOWN" and "2 element(s) painted over by body::before" in why and "ASSIST" in why
    assert mq.judge_contrast(mq.group_contrast({"index.html": {"checked": 3, "failures": [],
                                                               "passingButUnverifiable": []}}))[0] == "PASS"
    assert mq.judge_contrast(mq.group_contrast({"index.html": {"error": "timeout"}}))[0] == "UNKNOWN"
    assert mq.judge_contrast(mq.group_contrast({"index.html": {"checked": 0, "failures": [],
                                                               "passingButUnverifiable": []}}))[0] == "UNKNOWN"


def test_cmd_contrast_without_browser_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mq, "served_pages", lambda root: ["index.html"])

    def no_browser(root, rels):
        raise mq.Unavailable("Python Playwright not installed: install it")
    monkeypatch.setattr(mq, "audit_contrast", no_browser)
    rec = mq.cmd_contrast(tmp_path)
    assert rec["outcome"] == "UNKNOWN" and "Playwright" in rec["why"]


def test_contrast_audit_sees_the_planted_fault_in_a_real_browser():
    pytest.importorskip("playwright.sync_api")
    rels = [f"{mq.FIXTURES}/low-contrast/index.html", f"{mq.FIXTURES}/index.html"]
    try:
        res = mq.audit_contrast(REPO, rels)
    except mq.Unavailable as e:
        pytest.skip(str(e))
    bad = res[rels[0]]["failures"]
    assert any("planted-low-contrast" in f["selector"] and f["ratio"] < 1.5 for f in bad)
    assert res[rels[1]]["failures"] == []


# ---------------------------------------------------------------- M2
def _lhr(path, lcp, cls, tbt):
    return {"requestedUrl": f"http://localhost:5555{path}", "audits": {
        "largest-contentful-paint": {"numericValue": lcp}, "cumulative-layout-shift": {"numericValue": cls},
        "total-blocking-time": {"numericValue": tbt}}}


def test_lighthouserc_budgets_are_the_calendars_and_marked_assumed():
    raw = json.loads((REPO / ".lighthouserc.json").read_text(encoding="utf-8"))
    assert "[ASSUMED, Daniel rules]" in raw["_budgets"] and "proxy" in raw["_budgets"]
    assert raw["ci"]["collect"]["numberOfRuns"] == 3 and raw["ci"]["collect"]["staticDistDir"] == "."
    assert mq.budgets_of(raw) == {"largest-contentful-paint": 2500.0, "cumulative-layout-shift": 0.1,
                                  "total-blocking-time": 200.0}
    assert all(v[1]["aggregationMethod"] == "median" for v in raw["ci"]["assert"]["assertions"].values())
    cfg = mq.lhci_config(REPO, ["index.html", "a/index.html"], REPO / ".maint" / "lhci")
    assert cfg["ci"]["collect"]["url"] == ["http://localhost/", "http://localhost/a/"]


def test_perf_median_of_three_and_judgement():
    budgets = {"largest-contentful-paint": 2500.0, "cumulative-layout-shift": 0.1, "total-blocking-time": 200.0}
    good = [_lhr("/", 1000, 0.0, 10), _lhr("/", 9000, 0.5, 900), _lhr("/", 1200, 0.01, 20)]   # one outlier run
    med = mq.perf_medians(good, budgets)
    assert med["/"]["largest-contentful-paint"] == 1200 and med["/"]["_runs"] == 3
    assert mq.judge_perf(med, budgets, ["/"], 3)[0] == "PASS"
    slow = [_lhr("/", 3000, 0.0, 10)] * 3
    out, n, why, misses = mq.judge_perf(mq.perf_medians(slow, budgets), budgets, ["/"], 3)
    assert (out, n) == ("FINDINGS", 1) and "largest-contentful-paint 3000 > 2500" in why
    assert mq.judge_perf(mq.perf_medians([good[0], good[2]], budgets), budgets, ["/"], 3)[0] == "UNKNOWN"     # 2 of 3 runs
    assert mq.judge_perf(med, budgets, ["/", "/a/"], 3)[0] == "UNKNOWN"                            # a page never ran


def test_cmd_perf_not_installed_is_unknown(tmp_path, monkeypatch):
    monkeypatch.setattr(mq, "find_bin", lambda name, root: None)
    rec = mq.cmd_perf(tmp_path)
    assert rec["row"] == "M2" and rec["outcome"] == "UNKNOWN" and "lhci not installed" in rec["why"]


# ---------------------------------------------------------------- M2b
def _crux(lcp=1800, inp=150, cls="0.05"):
    m = {}
    for k, v in (("largest_contentful_paint", lcp), ("interaction_to_next_paint", inp), ("cumulative_layout_shift", cls)):
        if v is not None:
            m[k] = {"percentiles": {"p75": v}}
    return {"record": {"key": {"origin": "https://b4him.com"}, "metrics": m,
                       "collectionPeriod": {"lastDate": {"year": 2026, "month": 10, "day": 29}}}}


def test_judge_crux_paths():
    assert mq.judge_crux(200, _crux())[0] == "PASS"
    out, n, why, _ = mq.judge_crux(200, _crux(lcp=3100))
    assert (out, n) == ("FINDINGS", 1) and "largest_contentful_paint p75 3100 > 2500" in why
    out, _, why, _ = mq.judge_crux(404, {"error": {"code": 404, "message": "chrome ux report data not found"}})
    assert out == "UNKNOWN" and why.startswith("UNKNOWN-field")                 # no data is never good
    out, _, why, _ = mq.judge_crux(200, _crux(inp=None))
    assert out == "UNKNOWN" and "UNKNOWN-field" in why and "interaction_to_next_paint" in why
    assert mq.judge_crux(403, {"error": {"message": "API key not valid"}})[0] == "UNKNOWN"


def test_cmd_crux_no_key_is_unknown(tmp_path, monkeypatch):
    monkeypatch.delenv("CRUX_API_KEY", raising=False)
    rec = mq.cmd_crux(tmp_path)
    assert (rec["row"], rec["outcome"], rec["why"]) == ("M2b", "UNKNOWN", "no CRUX_API_KEY")


class _Resp:
    def __init__(self, status, body):
        self.status, self._b = status, json.dumps(body).encode()

    def read(self):
        return self._b

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_cmd_crux_request_shape_and_key_never_logged(tmp_path, monkeypatch):
    monkeypatch.setenv("CRUX_API_KEY", "SECRET-TEST-KEY")
    seen = {}

    def opener(req, timeout):
        seen.update(url=req.full_url, method=req.get_method(), body=json.loads(req.data),
                    ctype=req.get_header("Content-type"))
        return _Resp(200, _crux(cls="0.4"))
    rec = mq.cmd_crux(tmp_path, opener=opener)
    assert seen["url"] == mq.CRUX_ENDPOINT + "?key=SECRET-TEST-KEY" and seen["method"] == "POST"
    assert seen["body"]["origin"] == "https://b4him.com" and seen["ctype"] == "application/json"
    assert rec["outcome"] == "FINDINGS" and rec["n"] == 1
    every = (tmp_path / ".maint").rglob("*")
    assert not any("SECRET-TEST-KEY" in p.read_text(encoding="utf-8") for p in every if p.is_file())

    def not_found(req, timeout):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {},
                                     io.BytesIO(b'{"error":{"code":404,"message":"chrome ux report data not found"}}'))
    rec = mq.cmd_crux(tmp_path, opener=not_found)
    assert rec["outcome"] == "UNKNOWN" and rec["why"].startswith("UNKNOWN-field")

    def offline(req, timeout):
        raise urllib.error.URLError("getaddrinfo failed")
    assert mq.cmd_crux(tmp_path, opener=offline)["outcome"] == "UNKNOWN"


# ---------------------------------------------------------------- A4
def _scanners(**override):
    base = {
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
    base.update(override)
    return base


def _unavailable(why):
    def fn():
        raise mq.Unavailable(why)
    return fn


def test_calibration_pass_findings_unknown(tmp_path):
    assert mq.judge_calibration(mq.run_calibration(REPO, _scanners()))[0] == "PASS"
    blind = mq.run_calibration(REPO, _scanners(**{"contrast-audit.js": lambda: {"low-contrast/index.html": []}}))
    assert mq.judge_calibration(blind)[:2] == ("FINDINGS", 1) and blind["matrix"]["low-contrast"]["contrast-audit.js"] == "MISSED"
    wrong = mq.run_calibration(REPO, _scanners(**{"pa11y-ci": lambda: {"missing-alt/index.html": ["pa11y:region"]}}))
    assert wrong["matrix"]["missing-alt"]["pa11y-ci"] == "MISSED"           # an unrelated issue is not the fault
    noisy = mq.run_calibration(REPO, _scanners(**{"people_registry": lambda: {
        "forbidden-token/index.html": ["known-outside-rule:FIXTURE-CLIENT:Zorblax"], "index.html": ["unknown-name::X Y"]}}))
    assert mq.judge_calibration(noisy)[0] == "FINDINGS" and "control" in noisy["problems"][0]
    absent = mq.run_calibration(REPO, _scanners(**{"headers_tls_check.py": _unavailable("not on this branch")}))
    out, n, why = mq.judge_calibration(absent)
    assert out == "UNKNOWN" and "mixed-content" in why and "headers_tls_check.py: not on this branch" in why
    rec = mq.cmd_calibrate(tmp_path, _scanners(**{"pa11y-ci": _unavailable("pa11y-ci not installed")}))
    assert rec["row"] == "A4" and rec["outcome"] == "UNKNOWN"


def test_real_cheap_scanners_see_their_planted_faults(tmp_path):
    """release.broken_links (reused, through a scratch repo) and people_registry (with the invented stand-in)."""
    shutil.copytree(REPO / mq.FIXTURES, tmp_path / mq.FIXTURES)
    flagged, bad = mq.cal_broken_links(tmp_path, mq.scratch_site(tmp_path))
    assert flagged["broken-link/index.html"] and not flagged["index.html"]
    assert bad == [f"maint_fixtures/broken-link/index.html -> {mq.PLANTED_LINK}"]
    people = mq.cal_people(tmp_path)
    assert people["forbidden-token/index.html"] == ["known-outside-rule:FIXTURE-CLIENT:Zorblax"]
    assert people["index.html"] == []


def test_fixtures_hold_no_real_names_and_stay_quiet_on_the_live_people_scan():
    """The stand-in is seen ONLY when stand_in_names.json is loaded: the plain heuristic (what W3 runs on every served
    page) finds nothing on any fixture, so the fixtures cannot raise an S1 on the live site."""
    import people_registry as preg
    base = REPO / mq.FIXTURES
    assert not [p for p in base.rglob("*") if ".local." in p.name]
    stand = json.loads((base / "stand_in_names.json").read_text(encoding="utf-8"))
    assert [n for p in stand["people"] for n in p["names"]] == ["Zorblax"]
    reg = preg.load_registry(local_path=base / "does-not-exist.json")
    for page in mq.fixture_pages(REPO):
        assert preg.check_text((base / page).read_text(encoding="utf-8"), registry=reg).findings == [], page
    assert set(mq.fixture_pages(REPO)) == {mq.CONTROL} |{p for p, _ in mq.FAULTS.values()}
