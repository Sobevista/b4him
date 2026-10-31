#!/usr/bin/env python3
"""
maint_quality.py - the maintenance calendar's quality rows, each ending in one receipt.  (B4HIM_BUILDER_RULES)

    py tools/maint_quality.py a11y        # M1   pa11y-ci, axe + htmlcs, WCAG2AA, over every served page
    py tools/maint_quality.py contrast    # M1b  tools/contrast-audit.js in headless Chromium, grouped by cause
    py tools/maint_quality.py perf        # M2   Lighthouse CI over the static tree, 3 runs, median vs budgets
    py tools/maint_quality.py crux        # M2b  CrUX API field data for the origin (needs CRUX_API_KEY)
    py tools/maint_quality.py calibrate   # A4   every scanner over tools/_maint_fixtures/, each planted fault seen?

Exit 0 PASS, 1 FINDINGS, 2 UNKNOWN or SKIP (a check that could not run is never a pass). Receipts and findings go
through tools/maint_receipt.py into .maint/ (git-ignored); evidence is .maint/<date>_<row>.json.

THE PAGE LIST. b4him has no sitemap, so the list is the served HTML from tools/site_pages.py, the one page list
every scanner shares: tracked *.html with no path segment starting with "." or "_" (GitHub Pages' Jekyll build does
not serve those). tools/tracks/n8n.html is served, so it is measured; the calibration fixtures sit in
tools/_maint_fixtures/, never served and never listed. The pages are served locally from the working tree by a
throwaway http.server on 127.0.0.1, so a run measures the bytes in the tree, not the live site.

LIMITS, stated so nobody reads silence as success:
  * M1: pa11y's standards are WCAG2A/AA/AAA as HTML_CodeSniffer defines them (WCAG 2.1 era); WCAG 2.2's new
    criteria are covered only as far as axe-core's rules reach. [ASSUMED] the calendar's "WCAG 2.2 AA" is not
    fully met by any automated runner. pa11y-ci exit codes, per its README: 0 passed, 1 technical fault
    (-> UNKNOWN), 2 at least one page failed (-> FINDINGS).
  * M1b: contrast-audit.js cannot measure text over a gradient, image or pseudo-element (b4him's beam): those are
    reported as needing the eye, so the row is UNKNOWN (ASSIST) until a person judges them. It does not check
    hover/focus states or non-text contrast (SC 1.4.11).
  * M2: TBT is a lab proxy for INP, not INP. The budgets are [ASSUMED, Daniel rules] (.lighthouserc.json).
  * M2b: no CrUX data for the origin is UNKNOWN-field, never good. The query is all form factors aggregated.
  * A4: tools/_maint_fixtures/ (never served: the "_") holds a clean control page and five planted faults. They are
    copied into a scratch git repo under .maint/calib/ as maint_fixtures/ (served there, and outside tools/, which
    release.broken_links skips) and the mixed-content fault is armed
    only there, so the tracked, served copy carries no http:// subresource for the live scans to trip on. Sibling
    scanners (linkcheck.py, headers_tls_check.py, maint_pages.py) are called in process when they are on the branch;
    absent, each is UNKNOWN. A scanner that runs and misses its fault, or flags the control page, is FINDINGS.
INSTALL. pa11y-ci and @lhci/cli are pinned devDependencies in package.json, installed repo-locally into
node_modules/ (git-ignored, so the release's clean-tree check still passes): `set PUPPETEER_SKIP_DOWNLOAD=1` then
`npm ci`. Both drive Python Playwright's Chromium (see chrome_path), so no second browser is downloaded. Nothing here
installs anything: a missing pa11y-ci, lhci or Playwright is an UNKNOWN that names the install.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import functools
import http.server
import json
import os
import shutil
import statistics
import subprocess
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_receipt  # noqa: E402
import site_pages  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ORIGIN = "https://b4him.com"
CRUX_ENDPOINT = "https://chromeuxreport.googleapis.com/v1/records:queryRecord"
#: p75 "good" bounds the calendar routes on (row M2b): LCP 2.5 s, INP 200 ms, CLS 0.1.
FIELD_BUDGETS = {"largest_contentful_paint": 2500.0, "interaction_to_next_paint": 200.0,
                 "cumulative_layout_shift": 0.1}
SIBLINGS = ("linkcheck.py", "headers_tls_check.py", "maint_pages.py")
INSTALL = {
    "pa11y-ci": "not in node_modules/.bin; run `npm ci` in the repo root (package.json pins it; set "
                "PUPPETEER_SKIP_DOWNLOAD=1 first so no second browser is fetched)",
    "lhci": "not in node_modules/.bin; run `npm ci` in the repo root (package.json pins @lhci/cli; set "
            "PUPPETEER_SKIP_DOWNLOAD=1 first so no second browser is fetched)",
    "playwright": "the row needs Python Playwright and its Chromium: `py -m pip install playwright` then "
                  "`py -m playwright install chromium`",
}
EXIT = {"PASS": 0, "FINDINGS": 1, "UNKNOWN": 2, "SKIP": 2}
#: M1's stated limit, carried on every M1 receipt (see LIMITS above).
M1_ASSUMPTION = ("[ASSUMED] automated rules (axe + htmlcs, WCAG 2.1-era standards) do not cover all of WCAG 2.2 AA; "
                 "A1's manual evaluation covers the rest")


class Unavailable(RuntimeError):
    """A scanner that could not run. Its message is the UNKNOWN reason."""


# ---------------------------------------------------------------- shared
def today() -> str:
    return dt.datetime.now(dt.timezone.utc).date().isoformat()


def mdir(root: Path) -> Path:
    """Where this run writes: MAINT_DIR if set (maint_receipt's own override), else <root>/.maint."""
    d = Path(os.environ["MAINT_DIR"]) if os.environ.get("MAINT_DIR") else root / ".maint"
    d.mkdir(parents=True, exist_ok=True)
    return d


@contextlib.contextmanager
def _receipts_into(root: Path):
    """maint_receipt writes to MAINT_DIR or this checkout's .maint/; a --root run writes beside the tree it measured."""
    had = "MAINT_DIR" in os.environ
    old = os.environ.get("MAINT_DIR")
    os.environ["MAINT_DIR"] = str(mdir(root))
    try:
        yield
    finally:
        if had:
            os.environ["MAINT_DIR"] = old
        else:
            os.environ.pop("MAINT_DIR", None)


def finding(root: Path, row: str, severity: str, subject: str, detail: str, route_to: str) -> dict:
    with _receipts_into(root):
        return maint_receipt.write_finding(row, severity, subject, detail, route_to)


def evidence_path(root: Path, name: str) -> tuple[Path, str]:
    p = mdir(root) / f"{today()}_{name}.json"
    return p, f".maint/{p.name}"


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")


def served_pages(root: Path, files: list[str] | None = None) -> list[str]:
    """The served HTML, as repo-relative posix paths: the shared rule in tools/site_pages.py."""
    if files is None:
        try:
            return site_pages.served_pages(root)
        except site_pages.GitError as e:
            raise Unavailable(f"git ls-files failed: {e}") from None
    return sorted(f for f in files if f.lower().endswith(site_pages.PAGE_EXTS) and site_pages.is_served(f))


def page_path(rel: str) -> str:
    """index.html -> /, a/index.html -> /a/, a/b.html -> /a/b.html (the URL a reader would use)."""
    if rel == "index.html":
        return "/"
    if rel.endswith("/index.html"):
        return "/" + rel[: -len("index.html")]
    return "/" + rel


def template_of(rel: str) -> str:
    parts = rel.split("/")
    if len(parts) == 1:
        return "home" if rel == "index.html" else rel
    if len(parts) == 2:
        return parts[0]
    return parts[0] + "/* (item page)"


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


@contextlib.contextmanager
def serve(root: Path):
    """Serve `root` on 127.0.0.1 at a free port for the length of the block; yields the base URL."""
    handler = functools.partial(_Quiet, directory=str(root))
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def find_bin(name: str, root: Path) -> str | None:
    """A Node CLI on PATH or in the repo's own node_modules/.bin. Never npx: npx would offer to install."""
    found = shutil.which(name)
    if found:
        return found
    for cand in (root / "node_modules" / ".bin" / f"{name}.cmd", root / "node_modules" / ".bin" / name):
        if cand.exists():
            return str(cand)
    return None


def run_cmd(argv: list[str], cwd: Path | None = None, env: dict | None = None, timeout: int = 1800):
    return subprocess.run(argv, cwd=str(cwd) if cwd else None, capture_output=True, timeout=timeout,
                          env={**os.environ, "PYTHONIOENCODING": "utf-8", **(env or {})},
                          encoding="utf-8", errors="replace")


def receipt(root: Path, row: str, outcome: str, n=None, why="", evidence=None) -> dict:
    with _receipts_into(root):
        return maint_receipt.write_receipt(row, outcome, n=n, why=why, evidence=evidence, tool="maint_quality.py")


# ---------------------------------------------------------------- M1 accessibility (pa11y-ci)
@functools.lru_cache(maxsize=1)
def chrome_path() -> str | None:
    """ONE BROWSER, NO SECOND DOWNLOAD. pa11y-ci (through puppeteer) and lhci (through chrome-launcher) both drive the
    Chromium that Python Playwright already installed (`py -m playwright install chromium`), instead of each fetching
    its own. package.json's install ran with PUPPETEER_SKIP_DOWNLOAD=1 (and npm 11 did not run puppeteer's
    postinstall), so there is no puppeteer browser cache at all. The path is machine-specific, so it is never
    committed: it is resolved here at run time (CHROME_PATH wins if set) and written only into the generated configs
    under .maint/ (pa11y: defaults.chromeLaunchConfig.executablePath; lhci: collect.chromePath) and into the child's
    environment (PUPPETEER_EXECUTABLE_PATH, CHROME_PATH). None -> each scanner falls back to its own lookup and, if it
    finds no browser, fails with exit 1 / non-zero, which is an UNKNOWN."""
    if os.environ.get("CHROME_PATH") and Path(os.environ["CHROME_PATH"]).exists():
        return os.environ["CHROME_PATH"]
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            p = pw.chromium.executable_path
        return p if p and Path(p).exists() else None
    except Exception:
        return None


def a11y_config(root: Path, urls: list[str], chrome: str | None = None) -> dict:
    cfg = json.loads((root / ".pa11yci").read_text(encoding="utf-8"))
    cfg["urls"] = list(urls)
    if chrome:
        d = cfg.setdefault("defaults", {})
        d["chromeLaunchConfig"] = {**d.get("chromeLaunchConfig", {}), "executablePath": chrome}
    return cfg


def parse_pa11y(stdout: str) -> dict | None:
    """pa11y-ci --json prints {"total", "passes", "errors", "results": {url: [issue, ...]}}. None if unreadable."""
    s = (stdout or "").strip()
    start = s.find("{")
    if start < 0:
        return None
    try:
        rep = json.loads(s[start:])
    except ValueError:
        return None
    return rep if isinstance(rep, dict) and isinstance(rep.get("results"), dict) else None


def pa11y_issue_count(rep: dict) -> int:
    return sum(len(v) for v in rep["results"].values() if isinstance(v, list))


def judge_pa11y(code: int, rep: dict | None) -> tuple[str, int | None, str]:
    if code == 1:
        return "UNKNOWN", None, "pa11y-ci exit 1: a technical fault (bad config, a page that would not load), not a page result"
    if code == 0:
        if rep is not None and pa11y_issue_count(rep):
            n = pa11y_issue_count(rep)
            return "FINDINGS", n, f"pa11y-ci exit 0 but its report holds {n} issue(s)"
        if rep is None:
            return "UNKNOWN", None, "pa11y-ci exit 0 but its JSON report could not be read"
        return "PASS", 0, f"{rep.get('total', len(rep['results']))} page(s), 0 WCAG2AA issues (axe + htmlcs)"
    if code == 2:
        if rep is None or not pa11y_issue_count(rep):
            return "UNKNOWN", None, "pa11y-ci exit 2 (a page failed) but its JSON report could not be read: count unknown"
        n = pa11y_issue_count(rep)
        pages = sum(1 for v in rep["results"].values() if v)
        return "FINDINGS", n, f"{n} WCAG2AA issue(s) on {pages} page(s) (axe + htmlcs)"
    return "UNKNOWN", None, f"pa11y-ci exit {code}: not a documented exit code"


def pa11y_findings(rep: dict, base: str) -> list[tuple[str, str]]:
    """One finding per issue code (a cause), naming the pages it is on."""
    by_code: dict[str, dict] = {}
    for url, issues in rep["results"].items():
        for i in issues if isinstance(issues, list) else []:
            code = i.get("code") or i.get("message", "?")[:60]
            g = by_code.setdefault(code, {"pages": set(), "n": 0, "message": i.get("message", ""), "runner": i.get("runner")})
            g["pages"].add(url.replace(base, "") or "/")
            g["n"] += 1
    return [(code, f"{g['n']}x on {len(g['pages'])} page(s) [{', '.join(sorted(g['pages']))}] "
                   f"({g['runner'] or '?'}): {g['message'][:200]}") for code, g in sorted(by_code.items())]


def run_pa11y(root: Path, rels: list[str], tag: str) -> tuple[int, dict | None, dict]:
    """Run pa11y-ci over `rels` served from `root`. Raises Unavailable if it is not installed."""
    exe = find_bin("pa11y-ci", root)
    if not exe:
        raise Unavailable(f"pa11y-ci not installed: {INSTALL['pa11y-ci']}")
    work = mdir(root) / "a11y"
    work.mkdir(exist_ok=True)
    with serve(root) as base:
        urls = [base + page_path(r) for r in rels]
        cfg_path = work / f"pa11yci.{tag}.json"
        write_json(cfg_path, a11y_config(root, urls, chrome_path()))
        p = run_cmd([exe, "--config", str(cfg_path), "--json"], cwd=work, env=chrome_env())
    rep = parse_pa11y(p.stdout)
    return p.returncode, rep, {"base": base, "urls": urls, "exit": p.returncode,
                               "stderr_tail": (p.stderr or "")[-2000:], "report": rep,
                               "stdout_raw": None if rep is not None else (p.stdout or "")[-4000:]}


def cmd_a11y(root: Path) -> dict:
    ev_path, ev = evidence_path(root, "a11y")
    try:
        rels = served_pages(root)
        code, rep, detail = run_pa11y(root, rels, "site")
    except Unavailable as e:
        write_json(ev_path, {"row": "M1", "outcome": "UNKNOWN", "why": str(e)})
        return receipt(root, "M1", "UNKNOWN", why=str(e), evidence=ev)
    outcome, n, why = judge_pa11y(code, rep)
    why += f"; {M1_ASSUMPTION}"                 # a PASS here is the rules' pass, not WCAG 2.2 AA conformance
    write_json(ev_path, {"row": "M1", "pages": rels, **detail, "outcome": outcome, "assumption": M1_ASSUMPTION})
    if outcome == "FINDINGS" and rep is not None:
        for subject, text in pa11y_findings(rep, detail["base"]):
            finding(root, "M1", "S2", subject, text, "Site Maintainer")
    return receipt(root, "M1", outcome, n=n, why=why, evidence=ev)


# ---------------------------------------------------------------- M1b contrast (contrast-audit.js, headless)
AUDIT_JS = """() => { const r = contrastAudit({log: false});
  return {checked: r.checked, lowestRatio: r.lowestRatio, failures: r.failures,
          passingButUnverifiable: r.passingButUnverifiable}; }"""


def audit_contrast(root: Path, rels: list[str], viewport=(1280, 800)) -> dict[str, dict]:
    """{rel: contrast-audit report} for each page, in headless Chromium. Raises Unavailable without Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise Unavailable(f"Python Playwright not installed: {INSTALL['playwright']}") from None
    script = root / "tools" / "contrast-audit.js"
    if not script.exists():
        raise Unavailable("tools/contrast-audit.js is missing")
    out: dict[str, dict] = {}
    with serve(root) as base:
        try:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                try:
                    page = browser.new_page(viewport={"width": viewport[0], "height": viewport[1]})
                    for rel in rels:
                        try:
                            page.goto(base + page_path(rel), wait_until="load", timeout=60000)
                            page.add_script_tag(path=str(script))
                            out[rel] = page.evaluate(AUDIT_JS)
                        except Exception as e:  # one page that will not load is UNKNOWN for that page only
                            out[rel] = {"error": f"{type(e).__name__}: {str(e)[:300]}"}
                finally:
                    browser.close()
        except Exception as e:
            if isinstance(e, Unavailable):
                raise
            raise Unavailable(f"headless Chromium would not start: {type(e).__name__}: {str(e)[:300]}") from None
    return out


def group_contrast(results: dict[str, dict]) -> dict:
    """INV-W8's corollary: one cause is one fact. Failures group by colour pair, unverifiable by what paints over."""
    fail: dict[str, dict] = {}
    unver: dict[str, dict] = {}
    errors, checked = {}, 0
    for rel, rep in results.items():
        if "error" in rep:
            errors[rel] = rep["error"]
            continue
        checked += rep.get("checked", 0)
        tpl = template_of(rel)
        for r in rep.get("failures", []):
            key = f"{r.get('color')} on {r.get('background')}" + (" (large text)" if r.get("large") else "")
            g = fail.setdefault(key, {"elements": 0, "ratio": r.get("ratio"), "templates": set(), "selectors": set(),
                                      "pages": set()})
            g["elements"] += 1
            g["ratio"] = min(g["ratio"], r.get("ratio")) if g["ratio"] is not None else r.get("ratio")
            g["templates"].add(tpl)
            g["selectors"].add(r.get("selector", "?"))
            g["pages"].add(rel)
        for r in rep.get("passingButUnverifiable", []):
            key = r.get("overlaySource") or ("translucent text" if r.get("translucentText") else "unknown")
            g = unver.setdefault(key, {"elements": 0, "templates": set(), "pages": set()})
            g["elements"] += 1
            g["templates"].add(tpl)
            g["pages"].add(rel)
    fix = lambda d: {k: {kk: (sorted(vv) if isinstance(vv, set) else vv) for kk, vv in v.items()}  # noqa: E731
                     for k, v in d.items()}
    by_template: dict[str, dict] = {}
    for rel, rep in results.items():
        t = by_template.setdefault(template_of(rel), {"pages": 0, "failures": 0, "unverifiable": 0, "errors": 0})
        t["pages"] += 1
        if "error" in rep:
            t["errors"] += 1
        else:
            t["failures"] += len(rep.get("failures", []))
            t["unverifiable"] += len(rep.get("passingButUnverifiable", []))
    return {"checked": checked, "failure_causes": fix(fail), "unverifiable_causes": fix(unver), "errors": errors,
            "by_template": by_template}


def judge_contrast(g: dict) -> tuple[str, int | None, str]:
    if g["failure_causes"]:
        n = len(g["failure_causes"])
        els = sum(v["elements"] for v in g["failure_causes"].values())
        return "FINDINGS", n, f"{n} AA contrast cause(s) over {els} element(s); " + "; ".join(
            f"{k}: {v['elements']} el, min {v['ratio']}:1, {','.join(v['templates'])}" for k, v in g["failure_causes"].items())
    if g["errors"]:
        return "UNKNOWN", None, f"{len(g['errors'])} page(s) could not be audited: {', '.join(sorted(g['errors']))}"
    if not g["checked"]:
        return "UNKNOWN", None, "no text elements were measured"
    if g["unverifiable_causes"]:
        u = "; ".join(f"{v['elements']} element(s) painted over by {k}" for k, v in g["unverifiable_causes"].items())
        return "SKIP", None, maint_receipt.awaiting_why(
            "M1b", "site-maintainer", f"0 AA failures in {g['checked']} measured element(s), but {u}: the number is "
            f"not the rendered contrast, judge by eye (evidence: the per-page report)")
    return "PASS", 0, f"0 AA failures in {g['checked']} element(s), nothing painted over"


def cmd_contrast(root: Path) -> dict:
    ev_path, ev = evidence_path(root, "contrast")
    try:
        rels = served_pages(root)
        results = audit_contrast(root, rels)
    except Unavailable as e:
        write_json(ev_path, {"row": "M1b", "outcome": "UNKNOWN", "why": str(e)})
        return receipt(root, "M1b", "UNKNOWN", why=str(e), evidence=ev)
    g = group_contrast(results)
    outcome, n, why = judge_contrast(g)
    write_json(ev_path, {"row": "M1b", "viewport": "1280x800", "outcome": outcome, **g, "per_page": results})
    if outcome == "FINDINGS":
        for k, v in g["failure_causes"].items():
            finding(root, "M1b", "S2", k, f"{v['elements']} element(s), min {v['ratio']}:1, templates "
                    f"{', '.join(v['templates'])}, selectors {', '.join(v['selectors'][:8])}", "Site Maintainer")
    return receipt(root, "M1b", outcome, n=n, why=why, evidence=ev)


# ---------------------------------------------------------------- M2 lab performance (Lighthouse CI)
def lhci_config(root: Path, rels: list[str], work: Path, chrome: str | None = None) -> dict:
    cfg = json.loads((root / ".lighthouserc.json").read_text(encoding="utf-8"))["ci"]
    cfg["collect"] = {**cfg["collect"], "staticDistDir": str(root),
                      "url": ["http://localhost" + page_path(r) for r in rels]}
    if chrome:
        cfg["collect"]["chromePath"] = chrome
    cfg["upload"] = {**cfg.get("upload", {}), "outputDir": str(work / "reports")}
    return {"ci": cfg}


def budgets_of(cfg: dict) -> dict[str, float]:
    out = {}
    for audit, spec in cfg["ci"].get("assert", {}).get("assertions", {}).items():
        if isinstance(spec, list) and len(spec) > 1 and "maxNumericValue" in spec[1]:
            out[audit] = float(spec[1]["maxNumericValue"])
    return out


def url_key(u: str) -> str:
    """http://localhost:51234/a/ -> /a/ (lhci rewrites the port; compare by path)."""
    rest = u.split("://", 1)[-1]
    return "/" + rest.split("/", 1)[1] if "/" in rest else "/"


def perf_medians(lhrs: list[dict], audits) -> dict[str, dict]:
    """{path: {audit: median numericValue or None, "_runs": n}} across every run of each URL."""
    vals: dict[str, dict[str, list]] = {}
    runs: dict[str, int] = {}
    for lhr in lhrs:
        k = url_key(lhr.get("requestedUrl") or lhr.get("finalUrl") or "")
        runs[k] = runs.get(k, 0) + 1
        for a in audits:
            v = (lhr.get("audits", {}).get(a) or {}).get("numericValue")
            if isinstance(v, (int, float)):
                vals.setdefault(k, {}).setdefault(a, []).append(float(v))
    return {k: {**{a: (statistics.median(vals.get(k, {}).get(a, [])) if vals.get(k, {}).get(a) else None)
                   for a in audits}, "_runs": runs[k]} for k in runs}


def judge_perf(med: dict, budgets: dict[str, float], expected: list[str], runs: int) -> tuple[str, int | None, str, list]:
    misses, unknown = [], []
    for path in expected:
        m = med.get(path)
        if m is None:
            unknown.append(f"{path}: no run")
            continue
        if m["_runs"] < runs:
            unknown.append(f"{path}: {m['_runs']}/{runs} runs")
        for a, cap in budgets.items():
            if m.get(a) is None:
                unknown.append(f"{path}: no {a}")
            elif m[a] > cap:
                misses.append((path, a, m[a], cap))
    if misses:
        why = f"{len(misses)} budget miss(es) on the median of {runs}: " + "; ".join(
            f"{p} {a} {v:g} > {c:g}" for p, a, v, c in misses[:10])
        if unknown:
            why += f" (also UNKNOWN: {'; '.join(unknown[:5])})"
        return "FINDINGS", len(misses), why, misses
    if unknown:
        return "UNKNOWN", None, "incomplete Lighthouse results: " + "; ".join(unknown[:10]), []
    return "PASS", 0, f"{len(expected)} page(s) within [ASSUMED] budgets on the median of {runs} runs", []


def chrome_env() -> dict:
    """The environment both Node scanners run under: no browser download, and Playwright's Chromium as THE browser."""
    p = chrome_path()
    env = {"PUPPETEER_SKIP_DOWNLOAD": "1"}
    if p:
        env.update(CHROME_PATH=p, PUPPETEER_EXECUTABLE_PATH=p)
    return env


def cmd_perf(root: Path) -> dict:
    ev_path, ev = evidence_path(root, "perf")
    try:
        exe = find_bin("lhci", root)
        if not exe:
            raise Unavailable(f"lhci not installed: {INSTALL['lhci']}")
        rels = served_pages(root)
        work = mdir(root) / "lhci"
        work.mkdir(exist_ok=True)
        cfg = lhci_config(root, rels, work, chrome_path())
        cfg_path = work / "lighthouserc.generated.json"
        write_json(cfg_path, cfg)
        p = run_cmd([exe, "collect", f"--config={cfg_path}"], cwd=work, env=chrome_env(), timeout=3600)
        if p.returncode:
            raise Unavailable(f"lhci collect exit {p.returncode}: {(p.stderr or p.stdout or '')[-300:].strip()}")
        lhrs = []
        for f in sorted((work / ".lighthouseci").glob("lhr-*.json")):
            lhrs.append(json.loads(f.read_text(encoding="utf-8")))
        if not lhrs:
            raise Unavailable("lhci collect wrote no lhr-*.json under .maint/lhci/.lighthouseci")
    except Unavailable as e:
        write_json(ev_path, {"row": "M2", "outcome": "UNKNOWN", "why": str(e)})
        return receipt(root, "M2", "UNKNOWN", why=str(e), evidence=ev)
    budgets = budgets_of(cfg)
    runs = int(cfg["ci"]["collect"].get("numberOfRuns", 3))
    med = perf_medians(lhrs, budgets)
    outcome, n, why, misses = judge_perf(med, budgets, [page_path(r) for r in rels], runs)
    write_json(ev_path, {"row": "M2", "budgets_assumed": budgets, "runs": runs, "medians": med, "outcome": outcome,
                         "note": "TBT is a lab proxy for INP, not INP. Budgets are [ASSUMED, Daniel rules]."})
    for path, a, v, c in misses:
        finding(root, "M2", "S3", f"{path} {a}", f"median {v:g} > budget {c:g} [ASSUMED budget]", "Site Maintainer")
    return receipt(root, "M2", outcome, n=n, why=why, evidence=ev)


# ---------------------------------------------------------------- M2b field performance (CrUX API)
def crux_query(origin: str, key: str, opener=urllib.request.urlopen, timeout: int = 30) -> tuple[int, dict | None]:
    """POST records:queryRecord {"origin": ...}. Returns (HTTP status, parsed body or None). The key never leaves
    this call: it is in the query string the API requires and is not logged."""
    body = json.dumps({"origin": origin, "metrics": list(FIELD_BUDGETS)}).encode("utf-8")
    req = urllib.request.Request(f"{CRUX_ENDPOINT}?key={urllib.parse.quote(key)}", data=body, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        with opener(req, timeout=timeout) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8"))
        except Exception:
            return e.code, None


def judge_crux(status: int, body: dict | None) -> tuple[str, int | None, str, dict]:
    if status == 404:
        return "UNKNOWN", None, "UNKNOWN-field: no CrUX data for the origin (HTTP 404 'chrome ux report data not found')", {}
    if status != 200 or not body or "record" not in body:
        msg = ((body or {}).get("error") or {}).get("message", "") if isinstance(body, dict) else ""
        return "UNKNOWN", None, f"CrUX API HTTP {status}{': ' + msg[:120] if msg else ''}", {}
    metrics = body["record"].get("metrics", {})
    p75, misses, missing = {}, [], []
    for m, cap in FIELD_BUDGETS.items():
        v = ((metrics.get(m) or {}).get("percentiles") or {}).get("p75")
        try:
            v = float(v)
        except (TypeError, ValueError):
            missing.append(m)
            continue
        p75[m] = v
        if v > cap:
            misses.append(f"{m} p75 {v:g} > {cap:g}")
    period = body["record"].get("collectionPeriod", {})
    if misses:
        why = "p75 misses: " + "; ".join(misses) + (f" (UNKNOWN-field: {', '.join(missing)})" if missing else "")
        return "FINDINGS", len(misses), why, p75
    if missing:
        return "UNKNOWN", None, f"UNKNOWN-field: no p75 for {', '.join(missing)}; have {p75}", p75
    return "PASS", 0, "p75 " + ", ".join(f"{k} {v:g}" for k, v in p75.items()) + f" (28-day window {period.get('lastDate', '?')})", p75


def cmd_crux(root: Path, origin: str = ORIGIN, opener=urllib.request.urlopen) -> dict:
    ev_path, ev = evidence_path(root, "crux")
    key = os.environ.get("CRUX_API_KEY", "").strip()
    if not key:
        write_json(ev_path, {"row": "M2b", "outcome": "UNKNOWN", "why": "no CRUX_API_KEY"})
        return receipt(root, "M2b", "UNKNOWN", why="no CRUX_API_KEY", evidence=ev)
    try:
        status, body = crux_query(origin, key, opener=opener)
    except (urllib.error.URLError, OSError, ValueError) as e:
        why = f"CrUX API unreachable: {type(e).__name__}: {str(e)[:150]}".replace(key, "<key>")
        write_json(ev_path, {"row": "M2b", "outcome": "UNKNOWN", "why": why})
        return receipt(root, "M2b", "UNKNOWN", why=why, evidence=ev)
    outcome, n, why, p75 = judge_crux(status, body)
    write_json(ev_path, {"row": "M2b", "origin": origin, "status": status, "outcome": outcome, "p75": p75,
                         "record": (body or {}).get("record"), "error": (body or {}).get("error")})
    for m in why.split("p75 misses: ", 1)[-1].split("; ") if outcome == "FINDINGS" else []:
        finding(root, "M2b", "S3", origin, m.split(" (UNKNOWN")[0], "Site Maintainer")
    return receipt(root, "M2b", outcome, n=n, why=why, evidence=ev)


# ---------------------------------------------------------------- A4 calibration
FIXTURES = "tools/_maint_fixtures"     # the "_" keeps Pages from serving it
CONTROL = "index.html"
#: fault id -> (fixture page, scanners expected to see it)
FAULTS = {
    "broken-internal-link": ("broken-link/index.html", ("release.broken_links", "linkcheck.py")),
    "missing-alt": ("missing-alt/index.html", ("pa11y-ci",)),
    "low-contrast": ("low-contrast/index.html", ("contrast-audit.js", "pa11y-ci")),
    "mixed-content": ("mixed-content/index.html", ("headers_tls_check.py",)),
    "forbidden-token": ("forbidden-token/index.html", ("people_registry", "maint_pages.py")),
}
PLANTED_LINK = "/tools/maint_fixtures/planted-missing-target/"
PLANTED_HOST = "planted-mixed-content.invalid"
STAND_IN_LABEL = "FIXTURE-CLIENT"
PA11Y_CODES = {"missing-alt": ("image-alt", "H37", "1_1_1"), "low-contrast": ("color-contrast", "G18", "1_4_3")}


def fixture_pages(root: Path) -> list[str]:
    base = root / FIXTURES
    return sorted(p.relative_to(base).as_posix() for p in base.rglob("*.html"))


def arm(text: str) -> str:
    """The tracked mixed-content fixture is disarmed (no http:// in the served tree, so the live M3 mixed-content grep
    and the W1 outbound check stay clean); the scratch copy gets the real fault."""
    return text.replace(f'data-planted-mixed="{PLANTED_HOST}/', f'src="http://{PLANTED_HOST}/')


def scratch_site(root: Path) -> Path:
    """A throwaway git repo holding the fixtures OUTSIDE tools/ (release.broken_links and linkcheck's root-link pass
    skip tools/ by design), with the mixed-content fault armed, so the reused release check and the sibling scanners
    can be pointed at it. Lives under .maint/ (ignored); never deleted here."""
    d = mdir(root) / "calib" / dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    shutil.copytree(root / FIXTURES, d / "maint_fixtures")
    mc = d / "maint_fixtures" / FAULTS["mixed-content"][0]
    mc.write_text(arm(mc.read_text(encoding="utf-8")), encoding="utf-8", newline="\n")
    for argv in (["git", "init", "-q", str(d)], ["git", "-C", str(d), "add", "-A"]):
        p = subprocess.run(argv, capture_output=True)
        if p.returncode:
            raise Unavailable(f"scratch repo: {' '.join(argv[:3])} failed")
    return d


def cal_broken_links(root: Path, site: Path) -> tuple[dict[str, bool], list[str]]:
    """{fixture page: flagged?} from the reused release.broken_links over the scratch repo."""
    import release
    with repo_at(site):
        bad = release.broken_links([site / "maint_fixtures" / r for r in fixture_pages(root)])
    return {r: any(b.startswith(f"maint_fixtures/{r} -> ") for b in bad) for r in fixture_pages(root)}, bad


def cal_people(root: Path) -> dict[str, list[str]]:
    """{fixture page: findings} with the invented stand-in loaded in place of the git-ignored names file."""
    import people_registry as preg
    reg = preg.load_registry(local_path=root / FIXTURES / "stand_in_names.json")
    out = {}
    for r in fixture_pages(root):
        res = preg.check_text((root / FIXTURES / r).read_text(encoding="utf-8"), registry=reg)
        out[r] = [f"{f.kind}:{f.label or ''}:{f.text}" for f in res.findings]
    return out


def sibling_module(root: Path, tool: str):
    """Import a sibling builder's scanner from this branch's tools/, or say it is not here. Its pure functions are
    called in process, against the scratch site: its CLI would write W1/M3/W3 receipts for a run that is not one."""
    if not (root / "tools" / tool).exists():
        raise Unavailable(f"{tool} is not on this branch")
    import importlib
    try:
        return importlib.import_module(tool[:-3])
    except Exception as e:
        raise Unavailable(f"{tool} would not import: {type(e).__name__}: {str(e)[:150]}") from None


@contextlib.contextmanager
def repo_at(site: Path):
    """Point release/production_board's repo() at the scratch site for the length of the block."""
    import production_board as pb
    old = pb.REPO
    pb.REPO = site
    try:
        yield
    finally:
        pb.REPO = old


def _fixture_page(path: str) -> str | None:
    return path.split("maint_fixtures/", 1)[1] if "maint_fixtures/" in path else None


def cal_linkcheck(root: Path, site: Path) -> dict[str, list[str]]:
    """linkcheck.py's W1(a) internal pass (scan + internal_check), no network: live=None, outbound not fetched."""
    lc = sibling_module(root, "linkcheck.py")
    try:
        with repo_at(site):
            pages = lc.served_pages(site)
            bad = lc.internal_check(site, pages, lc.scan(site, pages), None)
    except AttributeError as e:
        raise Unavailable(f"linkcheck.py interface changed: {e}") from None
    out = {r: [] for r in fixture_pages(root)}
    for b in bad:
        r = _fixture_page(b.get("page", ""))
        if r in out:
            out[r].append(f"linkcheck:{b.get('link')}")
    return out


def cal_mixed(root: Path, site: Path) -> dict[str, list[str]]:
    """headers_tls_check.py's M3 mixed-content pass (git grep over the tracked tree), no network."""
    htc = sibling_module(root, "headers_tls_check.py")
    try:
        hits = htc.mixed_content(htc.git_grep_http(site))
    except AttributeError as e:
        raise Unavailable(f"headers_tls_check.py interface changed: {e}") from None
    out = {r: [] for r in fixture_pages(root)}
    for h in hits:
        r = _fixture_page(h.get("path", ""))
        if r in out:
            out[r].append(f"mixed:{h.get('match')}")
    return out


def cal_maint_pages(root: Path) -> dict[str, list[str]]:
    """maint_pages.py's W3 per-page mapping (people_page), with the invented stand-in loaded."""
    mp = sibling_module(root, "maint_pages.py")
    import people_registry as preg
    reg = preg.load_registry(local_path=root / FIXTURES / "stand_in_names.json")
    out = {}
    try:
        for r in fixture_pages(root):
            res = mp.people_page((root / FIXTURES / r).read_text(encoding="utf-8"), reg)
            out[r] = [f"{f['kind']}:{f.get('label') or ''}:{f['text']}" for f in res["findings"]]
    except (AttributeError, KeyError, TypeError) as e:
        raise Unavailable(f"maint_pages.py interface changed: {e}") from None
    return out


def run_calibration(root: Path, scanners: dict | None = None) -> dict:
    """scanners: {name: callable() -> {fixture page: [evidence strings]}}; raising Unavailable = could not run.
    Default scanners are the real ones. Returns the calibration matrix."""
    if scanners is None:
        scanners = default_scanners(root)
    pages = fixture_pages(root)
    seen_by: dict[str, dict] = {}
    for name, fn in scanners.items():
        try:
            seen_by[name] = {"ran": True, "pages": fn()}
        except Unavailable as e:
            seen_by[name] = {"ran": False, "why": str(e)}
        except Exception as e:
            seen_by[name] = {"ran": False, "why": f"{type(e).__name__}: {str(e)[:200]}"}
    matrix, problems = {}, []
    for fault, (page, expected) in FAULTS.items():
        row = {}
        for s in expected:
            info = seen_by.get(s) or {"ran": False, "why": "no such scanner wired"}
            if not info["ran"]:
                row[s] = f"UNKNOWN {info['why']}"
            elif fault_seen(fault, info["pages"].get(page, [])):
                row[s] = "SEEN"
            else:
                row[s] = "MISSED"
                problems.append(f"{s} missed {fault}")
        matrix[fault] = row
    control = {}
    for s, info in seen_by.items():
        if info["ran"]:
            hits = info["pages"].get(CONTROL, [])
            control[s] = "CLEAN" if not hits else f"NOISY {hits[:3]}"
            if hits:
                problems.append(f"{s} flagged the clean control page")
    return {"pages": pages, "matrix": matrix, "control": control, "problems": problems,
            "scanners": seen_by}


def fault_seen(fault: str, hits: list[str]) -> bool:
    """Each scanner's per-page evidence is reduced to strings; this says which strings count as seeing the fault."""
    if not hits:
        return False
    if fault in PA11Y_CODES and any(h.startswith("pa11y:") for h in hits):
        return any(any(c in h for c in PA11Y_CODES[fault]) for h in hits)
    if fault == "forbidden-token" and any(h.startswith("known-outside-rule") or h.startswith("unknown-name") for h in hits):
        return any(STAND_IN_LABEL in h or "Zorblax" in h for h in hits)
    if fault == "low-contrast" and any(h.startswith("contrast:") for h in hits):
        return any("planted-low-contrast" in h for h in hits)
    if fault == "broken-internal-link" and any(h.startswith("linkcheck:") for h in hits):
        return any(PLANTED_LINK in h for h in hits)
    if fault == "mixed-content" and any(h.startswith("mixed:") for h in hits):
        # headers_tls_check's match ends AT "http://" (its regex stops there), so the host is not in it: a hit on the
        # planted page is the fault, and the control page proves the scanner is not flagging everything.
        return any("http://" in h for h in hits)
    return True


def judge_calibration(cal: dict) -> tuple[str, int | None, str]:
    if cal["problems"]:
        return "FINDINGS", len(cal["problems"]), "; ".join(cal["problems"])
    uncovered = [f for f, row in cal["matrix"].items() if "SEEN" not in row.values()]
    unknown = sorted({f"{s}: {v[8:]}" for row in cal["matrix"].values() for s, v in row.items() if v.startswith("UNKNOWN")})
    seen = [f"{f} by {','.join(s for s, v in row.items() if v == 'SEEN')}" for f, row in cal["matrix"].items()
            if "SEEN" in row.values()]
    if uncovered or unknown:
        why = (f"seen: {'; '.join(seen) or 'none'}. NOT calibrated: {', '.join(uncovered) or 'none'}. "
               f"Scanners that could not run: {' | '.join(unknown)}")
        return "UNKNOWN", None, why
    return "PASS", 0, f"all {len(cal['matrix'])} planted faults seen by every scanner, control clean: {'; '.join(seen)}"


def default_scanners(root: Path) -> dict:
    site_box: dict = {}

    def site() -> Path:
        if "d" not in site_box:
            site_box["d"] = scratch_site(root)
        return site_box["d"]

    def broken():
        flagged, _ = cal_broken_links(root, site())
        return {r: ["broken-link"] if f else [] for r, f in flagged.items()}

    def people():
        return cal_people(root)

    def contrast():
        res = audit_contrast(root, [f"{FIXTURES}/{r}" for r in fixture_pages(root)])
        out = {}
        for rel, rep in res.items():
            r = rel[len(FIXTURES) + 1:]
            if "error" in rep:
                raise Unavailable(f"contrast-audit could not load {r}: {rep['error']}")
            out[r] = [f"contrast:{f.get('selector')}:{f.get('ratio')}" for f in rep.get("failures", [])]
        return out

    def pa11y():
        rels = [f"{FIXTURES}/{r}" for r in fixture_pages(root)]
        code, rep, _ = run_pa11y(root, rels, "calibration")
        if code == 1 or rep is None:
            raise Unavailable(f"pa11y-ci exit {code}, no readable report")
        out = {}
        for url, issues in rep["results"].items():
            r = url.split(FIXTURES + "/", 1)[-1]
            r = (r + "index.html") if (r.endswith("/") or r == "") else r
            out[r] = [f"pa11y:{i.get('code', '')}" for i in issues if isinstance(i, dict)]
        return out

    return {
        "release.broken_links": broken,
        "people_registry": people,
        "contrast-audit.js": contrast,
        "pa11y-ci": pa11y,
        "linkcheck.py": lambda: cal_linkcheck(root, site()),
        "headers_tls_check.py": lambda: cal_mixed(root, site()),
        "maint_pages.py": lambda: cal_maint_pages(root),
    }


def cmd_calibrate(root: Path, scanners: dict | None = None) -> dict:
    ev_path, ev = evidence_path(root, "calibration")
    cal = run_calibration(root, scanners)
    outcome, n, why = judge_calibration(cal)
    write_json(ev_path, {"row": "A4", "outcome": outcome, **cal})
    for p in cal["problems"]:
        finding(root, "A4", "S2", p.split(" ", 1)[0], p, "Site Maintainer (a tool fix)")
    return receipt(root, "A4", outcome, n=n, why=why, evidence=ev)


# ---------------------------------------------------------------- CLI
COMMANDS = {"a11y": cmd_a11y, "contrast": cmd_contrast, "perf": cmd_perf, "crux": cmd_crux, "calibrate": cmd_calibrate}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("row", choices=sorted(COMMANDS))
    ap.add_argument("--root", default=str(REPO), help="the b4him tree to measure (default: this checkout)")
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    rec = COMMANDS[a.row](Path(a.root).resolve())
    print(json.dumps(rec, ensure_ascii=False))
    return EXIT[rec["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
