#!/usr/bin/env python3
"""
maint_human.py: the ASSIST half of the calendar's HUMAN rows. It assembles what Daniel needs to rule, then writes the
row's receipt; it never rules. A HUMAN row closes only with his ledger E-number (`maint_watch.py human <row> <E>`).

    py tools/maint_human.py h1     H1  "feels like home" pack: home + 3 random pages, screenshots beside the D9 reference
    py tools/maint_human.py a1     A1  WCAG-EM evidence pack: page list, axe + pa11y results, the Easy Checks checklist
    py tools/maint_human.py a3     A3  domain registration: RDAP expiry and status, alarm 60 days ahead
    options: --repo <path> (default: this checkout)

RECEIPTS. A pack row (H1, A1) that is due: SKIP "awaiting Daniel's ruling" with the pack as evidence (the
reminder; UNKNOWN is kept for "could not run"). Not due: SKIP with its next due date (the pack is still assembled, as a preview). A pack that cannot be
assembled: UNKNOWN with why. A3: `SKIP awaiting Daniel's ruling` with the RDAP evidence (and an S2 finding) when the
registration expires within 60 days (the calendar's "60 days before renewal"); FINDINGS (S1) when it carries a hold /
redemption / pending-delete status; SKIP with the expiry date otherwise; UNKNOWN
when RDAP cannot be read. A3's renewal date is known only to RDAP, so tools/maint_run.py polls it every Monday.

H1 SCREENSHOTS (harness LESSONS L-012, "A full-page screenshot of a tall page"). Each page is captured at 1280 and
390 CSS px wide, device scale 2, as clipped tiles of at most 2,000 CSS px (4,000 device px, under 16,384), stacked in
order. A check that can fail runs on every capture: each tile's PNG header must give exactly width x scale by
tile-height x scale device px, and the tiles must cover the page's scroll height exactly once (no gap, no overlap, so
the top band appears once). The D9 reference is assets/logo.png (the logo D9 recolors the site to) and D9's palette
table, read from DECISIONS.md at HEAD.

SOURCES (read 2026-10-31): WCAG-EM steps, W3C Group Note 23 July 2026, https://www.w3.org/TR/WCAG-EM/ ;
Easy Checks (updated 21 March 2024), https://www.w3.org/WAI/test-evaluate/easy-checks/ ; new in WCAG 2.2,
https://www.w3.org/WAI/standards-guidelines/wcag/new-in-22/ ; RDAP bootstrap for DNS (RFC 9224),
https://data.iana.org/rdap/dns.json (it lists `com` at https://rdap.verisign.com/com/v1/), RDAP responses RFC 9083
(events, eventAction "expiration"; status values).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import shutil
import struct
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import maint_receipt as mr  # noqa: E402
import maint_watch as mw  # noqa: E402
import site_pages  # noqa: E402

REPO = HERE.parent
TOOL = "maint_human.py"
DOMAIN = "b4him.com"
BOOTSTRAP = "https://data.iana.org/rdap/dns.json"
UA = "b4him-maintenance/1.0 (A3 registration check; +https://b4him.com/)"
WINDOW_DAYS = 60
BAD_STATUS = ("redemption period", "pending delete", "client hold", "server hold", "inactive")
WIDTHS = (1280, 390)
SCALE = 2
TILE_CSS = 2000
MAX_DEVICE_PX = 16384
EASY_CHECKS = ("Image Alternative Text", "Page Title", "Headings", "Color Contrast", "Skip Link",
               "Visible Keyboard Focus", "Language of Page", "Zoom", "Captions", "Transcripts", "Audio Description",
               "Labels", "Required Fields")
WCAG_EM_STEPS = ("Define the evaluation scope", "Explore the target digital product",
                 "Select a representative sample set", "Evaluate the selected sample set",
                 "Report the evaluation findings")
NEW_IN_22 = ("2.4.11 Focus Not Obscured (Minimum), AA", "2.5.7 Dragging Movements, AA",
             "2.5.8 Target Size (Minimum), AA", "3.2.6 Consistent Help, A", "3.3.7 Redundant Entry, A",
             "3.3.8 Accessible Authentication (Minimum), AA")


class PackError(Exception):
    """The pack could not be assembled. UNKNOWN, with this reason."""


def today_local() -> dt.datetime:
    return mw.now_local()


def pack_dir(row: str, day: dt.date) -> Path:
    d = mr.maint_dir() / "packs" / f"{row}_{day.isoformat()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def rel(p: Path) -> str:
    return ".maint/" + p.resolve().relative_to(mr.maint_dir().resolve()).as_posix()


def write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8", newline="\n")


def head_file(repo: Path, path: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), "show", f"HEAD:{path}"], capture_output=True)
    if p.returncode:
        raise PackError(f"cannot read {path} at HEAD")
    return p.stdout.decode("utf-8", "replace")


def receipt_for_pack(row: str, now: dt.datetime, evidence: str, what: str) -> dict:
    table = mw.load_rows()
    s = mw.human_status(row, table, mr.read_receipts(), now)
    if not s["is_due"]:
        return mr.write_receipt(row, "SKIP", why=f"HUMAN row not due: next due {s['due']:%Y-%m-%d}; {what} assembled "
                                "as a preview", evidence=evidence, tool=TOOL)
    return mr.write_receipt(row, "SKIP", why=f"awaiting Daniel's ruling: {what} ready (due {s['due']:%Y-%m-%d}); "
                            f"close with maint_watch.py human {row} <E-number>", evidence=evidence, tool=TOOL)


# ------------------------------------------------------------------ H1: screenshots, tiled and checked
def tile_plan(height: int, tile_css: int = TILE_CSS, scale: int = SCALE) -> list[tuple[int, int]]:
    """[(y, h)] covering 0..height exactly once, each tile under MAX_DEVICE_PX device px."""
    if height <= 0:
        raise PackError("page height is 0")
    if tile_css * scale >= MAX_DEVICE_PX:
        raise PackError(f"tile {tile_css} css px x {scale} is not under {MAX_DEVICE_PX} device px")
    return [(y, min(tile_css, height - y)) for y in range(0, height, tile_css)]


def png_size(p: Path) -> tuple[int, int]:
    b = p.read_bytes()[:24]
    if b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
        raise PackError(f"{p.name} is not a PNG")
    return struct.unpack(">II", b[16:24])


def check_tiles(paths: list[Path], plan: list[tuple[int, int]], width: int, height: int,
                scale: int = SCALE) -> list[str]:
    """The check that can fail: every tile's real pixel size, and the tiles covering the page exactly once."""
    problems = []
    if len(paths) != len(plan):
        problems.append(f"{len(paths)} tiles for a {len(plan)}-tile plan")
    y_next = 0
    for p, (y, h) in zip(paths, plan):
        w_px, h_px = png_size(p)
        if (w_px, h_px) != (width * scale, h * scale):
            problems.append(f"{p.name}: {w_px}x{h_px} px, expected {width * scale}x{h * scale}")
        if h_px >= MAX_DEVICE_PX:
            problems.append(f"{p.name}: {h_px} device px is not under {MAX_DEVICE_PX}")
        if y != y_next:
            problems.append(f"{p.name}: starts at {y}, expected {y_next} (gap or overlap)")
        y_next = y + h
    if y_next != height:
        problems.append(f"tiles cover {y_next} of {height} css px")
    return problems


def capture_pages(repo: Path, rels: list[str], out: Path) -> dict:
    """{rel: {width: {"tiles": [names], "height": h, "problems": [...]}}}. Raises PackError without Playwright."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise PackError("Python Playwright is not installed (`py -m pip install playwright`)") from None
    import maint_quality as mq
    res: dict = {}
    with mq.serve(repo) as base, sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for w in WIDTHS:
                ctx = browser.new_context(viewport={"width": w, "height": 900}, device_scale_factor=SCALE)
                page = ctx.new_page()
                for r in rels:
                    page.goto(base + mq.page_path(r), wait_until="load", timeout=60000)
                    page.wait_for_timeout(300)
                    height = int(page.evaluate("() => Math.ceil(document.documentElement.scrollHeight)"))
                    plan = tile_plan(height)
                    stem = re.sub(r"[^a-z0-9]+", "-", r.lower()).strip("-")
                    paths = []
                    for i, (y, h) in enumerate(plan):
                        p = out / f"{stem}_{w}_{i + 1:02d}.png"
                        page.screenshot(path=str(p), clip={"x": 0, "y": y, "width": w, "height": h}, full_page=True)
                        paths.append(p)
                    res.setdefault(r, {})[w] = {"tiles": [p.name for p in paths], "height": height,
                                                "problems": check_tiles(paths, plan, w, height)}
                ctx.close()
        finally:
            browser.close()
    return res


#: (repo, rels, out_dir) -> capture dict. Tests replace it.
CAPTURE = capture_pages


def d9_reference(repo: Path, out: Path) -> list[str]:
    text = head_file(repo, "DECISIONS.md")
    m = re.search(r"^## D9\b.*?(?=^## )", text, re.S | re.M)
    if not m:
        raise PackError("DECISIONS.md has no D9 section")
    table = [ln for ln in m.group(0).splitlines() if ln.startswith("|")][:12]
    logo = Path(repo) / "assets" / "logo.png"
    if logo.is_file():
        shutil.copyfile(logo, out / "reference_logo.png")
    return table


def cmd_h1(repo: Path, now: dt.datetime) -> dict:
    day = now.date()
    try:
        pages = site_pages.served_pages(repo)
        if "index.html" not in pages:
            raise PackError("no home page (index.html) in the served pages")
        others = [p for p in pages if p != "index.html"]
        chosen = ["index.html"] + random.Random(day.isoformat()).sample(others, min(3, len(others)))
        out = pack_dir("H1", day)
        table = d9_reference(repo, out)
        shots = CAPTURE(repo, chosen, out)
    except (PackError, site_pages.GitError, OSError) as e:
        return mr.write_receipt("H1", "UNKNOWN", why=f"H1 pack could not be assembled: {e}", tool=TOOL)
    except Exception as e:  # noqa: BLE001 - a browser failure is UNKNOWN for the pack, with its reason
        return mr.write_receipt("H1", "UNKNOWN", why=f"H1 screenshots failed: {type(e).__name__}: {str(e)[:200]}",
                                tool=TOOL)
    problems = [f"{r} @{w}: {p}" for r, ws in shots.items() for w, v in ws.items() for p in v["problems"]]
    notes = sorted((mr.maint_dir() / "audits").glob("*_reader.md")) if (mr.maint_dir() / "audits").is_dir() else []
    L = [f"# H1 \"feels like home\" pack, {day}", "",
         "For Daniel (D4: warmth is taste). Look at each page beside the reference, then rule in the ledger and close: "
         "`py tools/maint_watch.py human H1 <E-number>`.", "",
         "## The D9 reference", "",
         "![the logo D9 recolors the site to](reference_logo.png)" if (out / "reference_logo.png").exists()
         else "(assets/logo.png not found)", ""] + table + ["",
         f"## M4 reader walkthrough notes: {('.maint/audits/' + notes[-1].name) if notes else 'none yet'}", "",
         f"## Pages (home + 3 chosen at random, seed {day})", ""]
    for r, ws in shots.items():
        L.append(f"### {r}")
        for w, v in ws.items():
            L.append(f"- {w} px wide, {v['height']} css px tall, {len(v['tiles'])} tile(s) top to bottom: "
                     + " ".join(f"![{t}]({t})" for t in v["tiles"]))
        L.append("")
    L += ["## Capture check", "", "- " + ("; ".join(problems) if problems else
                                          "every tile measured: exact device px, page covered once, under 16,384 px")]
    write(out / "index.md", "\n".join(L) + "\n")
    if problems:
        mr.write_finding("H1", "S3", "H1 capture check failed", "; ".join(problems)[:500], "Site Maintainer (tool)")
        return mr.write_receipt("H1", "UNKNOWN", why=f"H1 pack built but its capture check failed: {problems[0]}",
                                evidence=rel(out / "index.md"), tool=TOOL)
    return receipt_for_pack("H1", now, rel(out / "index.md"), f"H1 pack ({len(chosen)} pages, {len(WIDTHS)} widths)")


# ------------------------------------------------------------------ A1: the WCAG-EM evidence pack
def cmd_a1(repo: Path, now: dt.datetime) -> dict:
    day = now.date()
    try:
        pages = site_pages.served_pages(repo)
    except site_pages.GitError as e:
        return mr.write_receipt("A1", "UNKNOWN", why=f"A1 pack: no page list: {e}", tool=TOOL)
    out = pack_dir("A1", day)
    m1 = sorted(mr.maint_dir().glob("*_a11y.json"))
    auto = "none: run `py tools/maint_quality.py a11y` (M1) first"
    if m1:
        shutil.copyfile(m1[-1], out / "automated_axe_pa11y.json")
        auto = f"automated_axe_pa11y.json (copied from .maint/{m1[-1].name}: pa11y-ci with the axe and htmlcs runners)"
    L = [f"# A1 WCAG-EM evidence pack, {day}", "",
         "For the Site Maintainer to complete and Daniel to sign off (ledger E-number, then "
         "`py tools/maint_watch.py human A1 <E-number>`). Target: WCAG 2.2 AA. Method: WCAG-EM "
         "(https://www.w3.org/TR/WCAG-EM/), every page evaluated (the site is small, so step 3 is the whole site).", "",
         "## WCAG-EM steps", ""]
    L += [f"{i}. {s}: " + {1: "scope = every served page below, WCAG 2.2 AA",
                           2: "page list below (tools/site_pages.py)",
                           3: f"all {len(pages)} pages (no sampling)",
                           4: "automated results + the manual checklist below",
                           5: "the evaluator writes the report here; Daniel signs off"}[i]
          for i, s in enumerate(WCAG_EM_STEPS, 1)]
    L += ["", f"## Automated results (axe + pa11y): {auto}", "",
          "Automated rules do not cover all of WCAG 2.2 AA [ASSUMED, as M1 states]: the checklist is the rest.", "",
          "## New in WCAG 2.2 at A/AA: check by hand on every page", ""] + [f"- [ ] {c}" for c in NEW_IN_22]
    L += ["", "Also: keyboard-only pass and a screen reader pass (NVDA [ASSUMED tool]).", "",
          "## Easy Checks (https://www.w3.org/WAI/test-evaluate/easy-checks/), per page", "",
          "| page | " + " | ".join(EASY_CHECKS) + " |", "|---|" + "---|" * len(EASY_CHECKS)]
    L += [f"| `{p}` | " + " | ".join("[ ]" for _ in EASY_CHECKS) + " |" for p in pages]
    write(out / "index.md", "\n".join(L) + "\n")
    what = f"A1 WCAG-EM pack ({len(pages)} pages" + ("" if m1 else "; no M1 automated results yet") + ")"
    return receipt_for_pack("A1", now, rel(out / "index.md"), what)


# ------------------------------------------------------------------ A3: RDAP
def _get_json(url: str) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rdap+json, application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read(2_000_000).decode("utf-8", "replace"))


#: (url) -> parsed JSON. Raises on failure. Tests replace it.
GET_JSON = _get_json


def rdap_base(domain: str) -> str:
    tld = domain.rsplit(".", 1)[-1].lower()
    for tlds, urls in GET_JSON(BOOTSTRAP).get("services", []):
        if tld in [t.lower() for t in tlds] and urls:
            return next((u for u in urls if u.startswith("https://")), urls[0])
    raise LookupError(f"the IANA RDAP bootstrap lists no server for .{tld}")


def cmd_a3(repo: Path, now: dt.datetime) -> dict:
    day = now.date()
    try:
        base = rdap_base(DOMAIN)
        data = GET_JSON(base.rstrip("/") + f"/domain/{DOMAIN}")
    except (OSError, ValueError, LookupError, urllib.error.URLError) as e:
        return mr.write_receipt("A3", "UNKNOWN", why=f"RDAP not read: {type(e).__name__}: {str(e)[:160]}", tool=TOOL)
    exp = next((e.get("eventDate") for e in data.get("events", []) if e.get("eventAction") == "expiration"), None)
    status = [str(s) for s in data.get("status", [])]
    ev = mr.maint_dir() / "audits" / f"{day.isoformat()}_rdap.json"
    write(ev, json.dumps({"domain": DOMAIN, "server": base, "expiration": exp, "status": status,
                          "events": data.get("events", [])}, indent=1) + "\n")
    evr = rel(ev)
    if not exp:
        return mr.write_receipt("A3", "UNKNOWN", why="RDAP answered with no expiration event", evidence=evr, tool=TOOL)
    expires = dt.datetime.fromisoformat(exp.replace("Z", "+00:00"))
    days = (expires - now).days
    opens = (expires - dt.timedelta(days=WINDOW_DAYS)).date()
    bad = [s for s in status if any(b in s.lower() for b in BAD_STATUS)]
    closed = [t for t, e in mw.receipts_of(mr.read_receipts(), "A3", {"PASS"}) if t.date() >= opens]
    if bad:
        mr.write_finding("A3", "S1", f"{DOMAIN} registration status: {', '.join(bad)}", f"RDAP {base}", "Daniel")
        return mr.write_receipt("A3", "FINDINGS", n=1, why=f"registration status {', '.join(bad)}; expires "
                                f"{expires:%Y-%m-%d}", evidence=evr, tool=TOOL)
    if days <= WINDOW_DAYS and not closed:
        mr.write_finding("A3", "S2", f"{DOMAIN} expires in {days} days", f"expires {expires:%Y-%m-%d}; confirm "
                         "auto-renew and that the registrar's contact email reaches Daniel", "Daniel")
        # the finding is filed (S2, above); the row waits on Daniel's ruling, which closes it (the HAND CLOSE rule)
        return mr.write_receipt("A3", "SKIP", why=f"awaiting Daniel's ruling: expires {expires:%Y-%m-%d} ({days} "
                                f"days), the 60-day window is open; confirm auto-renew and the registrar contact, then "
                                f"close with maint_watch.py human A3 <E-number>", evidence=evr, tool=TOOL)
    tail = f"closed for this window ({fmt_t(closed[-1])})" if closed else f"the 60-day window opens {opens}"
    return mr.write_receipt("A3", "SKIP", why=f"not due: expires {expires:%Y-%m-%d} ({days} days); {tail}; status "
                            f"{', '.join(status) or 'none'}", evidence=evr, tool=TOOL)


def fmt_t(t: dt.datetime) -> str:
    return f"{t:%Y-%m-%d}"


COMMANDS = {"h1": cmd_h1, "a1": cmd_a1, "a3": cmd_a3}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("row", choices=sorted(COMMANDS))
    ap.add_argument("--repo", default=str(REPO))
    a = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    r = COMMANDS[a.row](Path(a.repo).resolve(), today_local())
    print(json.dumps(r, ensure_ascii=False))
    return {"PASS": 0, "SKIP": 0, "FINDINGS": 1, "UNKNOWN": 2}[r["outcome"]]


if __name__ == "__main__":
    sys.exit(main())
