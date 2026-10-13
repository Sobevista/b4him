#!/usr/bin/env python3
"""
preview.py — the rendered proof Daniel approves from: exactly the committed bytes, rendered and checked.

    py tools/preview.py <git-ref> <page-path> [<page-path> ...] --out <dir> [--overlay <ref>:<path> ...]

    py tools/preview.py draft/gc-gloss-2 lessons/glossary-intermediate/index.html \
        --overlay approved/GC-GLOSS-1:lessons/glossary-beginner/index.html --out proof

1. EXPORT. `git archive <ref>` into a temp dir, then every exported file is re-hashed to the blob id the tree names
   at <ref>: the proof shows the bytes an approval tile pins, or it says it does not. An --overlay adds one file
   from another ref (an already-approved page the draft links to), recorded with its own ref and blob.
2. SERVE the export on 127.0.0.1, ephemeral port.
3. RENDER each page in Edge (Playwright, channel="msedge"): desktop 1280 wide, device scale 1; phone 390 wide,
   device scale 2. Never one full-page phone screenshot (harness LESSONS L-012: Chromium repeats content past
   16,384 device px) — clipped tiles of 2,000 CSS px, proved against the page:
     http 200          the page answers 200
     no h-scroll       scrollWidth <= innerWidth at 360/375/390/414/430
     tiles cover       the tile plan covers the page height exactly (no gap, no overlap) and every tile image has
                       the planned pixel size; the height did not change during capture
     tiles = viewport  at the h1/h2 headings, the stitched tiles show the same pixels as a plain viewport screenshot
                       (a viewport screenshot cannot wrap)
     top band once     the top 120 CSS px (logo and navigation) appear once in the stitched phone image; the
                       detector must also find a repeat planted into a copy of this very image, or it proves nothing
     links resolve     every site-root and relative link, and every in-page #anchor, resolves in the export
     console clean     zero console errors and page errors, every same-origin request answered < 400
     webfonts loaded   after document.fonts.ready, each @font-face family the page uses has a loaded face, and the
                       engine (CDP CSS.getPlatformFontsForNode) reports it rendered that custom font, not a fallback
4. WRITE <out>/proof.html (one self-contained page, tiles inlined as JPEG) and <out>/proof.json (the same facts).

Exit 0 only if every check on every page is PASS. 1 = a check FAILED. 2 = a check could not run (UNKNOWN —
never rounded to PASS).
"""
from __future__ import annotations

import argparse
import base64
import functools
import hashlib
import html
import html.parser
import http.server
import io
import json
import posixpath
import shutil
import subprocess
import sys
import tarfile
import tempfile
import threading
import urllib.parse
from pathlib import Path

PHONE_W, PHONE_VH, PHONE_DPR = 390, 844, 2
DESK_W, DESK_VH, DESK_DPR = 1280, 800, 1
TILE_CSS = 2000
HSCROLL_WIDTHS = (360, 375, 390, 414, 430)
BAND_CSS = 120            # the top band: logo and navigation
JPEG_Q = 80
PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"
LINK_ATTRS = {"a": "href", "area": "href", "link": "href", "img": "src", "script": "src", "source": "src",
              "iframe": "src", "video": "src", "audio": "src", "track": "src"}


# --------------------------------------------------------------------------------------------- pure parts (tested)

def plan_tiles(height: int, tile: int = TILE_CSS) -> list[tuple[int, int]]:
    """(y, h) tiles in CSS px covering [0, height) exactly, each at most `tile` tall."""
    if height <= 0 or tile <= 0:
        raise ValueError(f"height {height} and tile {tile} must be positive")
    return [(y, min(tile, height - y)) for y in range(0, height, tile)]


def tiles_cover(plan: list[tuple[int, int]], height: int) -> bool:
    """True iff the tiles are contiguous from 0, non-empty, and end exactly at height."""
    y = 0
    for ty, th in plan:
        if ty != y or th <= 0:
            return False
        y += th
    return y == height and bool(plan)


def blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class _Scan(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self.ids: set[str] = set()

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if a.get("id"):
            self.ids.add(a["id"])
        if tag == "a" and a.get("name"):
            self.ids.add(a["name"])
        attr = LINK_ATTRS.get(tag)
        if attr and a.get(attr) is not None:
            self.links.append((tag, a[attr].strip()))
        if tag in ("img", "source") and a.get("srcset"):
            for part in a["srcset"].split(","):
                if part.strip():
                    self.links.append((tag, part.strip().split()[0]))

    handle_startendtag = handle_starttag


def scan_html(text: str) -> tuple[list[tuple[str, str]], set[str]]:
    """(links as (tag, url), ids and a[name]s) of one HTML document."""
    s = _Scan()
    s.feed(text)
    s.close()
    return s.links, s.ids


def resolve_link(href: str, page_rel: str, exists, ids_for) -> tuple[str, str]:
    """Resolve one link found on page_rel against the export.

    exists(rel) -> bool says whether a file is in the export; ids_for(rel) -> set of ids in that HTML file.
    Returns (status, detail) with status "ok", "broken" or "external" (scheme links, //host links: not ours to check).
    """
    if not href:
        return "broken", "empty link"
    parts = urllib.parse.urlsplit(href)
    if parts.scheme or href.startswith("//"):
        return "external", parts.scheme or "network-path"
    path, frag = urllib.parse.unquote(parts.path), urllib.parse.unquote(parts.fragment)
    if not path:                                       # "#x" or "?q#x": this page
        target = page_rel
    else:
        base = "/" + posixpath.dirname(page_rel) + "/"
        joined = path if path.startswith("/") else posixpath.join(base, path)
        norm = posixpath.normpath(joined)
        if norm.startswith("/.."):
            return "broken", f"{href} climbs above the site root"
        rel = norm.lstrip("/")
        if joined.endswith("/") or rel == "":
            target = posixpath.join(rel, "index.html") if rel else "index.html"
        elif exists(rel):
            target = rel
        elif exists(rel + "/index.html"):
            target = rel + "/index.html"
        else:
            return "broken", f"{href}: no file {rel} in the export"
        if not exists(target):
            return "broken", f"{href}: no file {target} in the export"
    if frag:
        if not target.endswith((".html", ".htm")):
            return "broken", f"{href}: fragment on a non-HTML target {target}"
        if frag not in ids_for(target):
            if frag == "top":                         # HTML spec: #top scrolls to the document's top
                return "ok", f"{target}#top (no id=top: the spec-defined top of the document)"
            return "broken", f"{href}: {target} has no id or a[name] '{frag}'"
    return "ok", target + (f"#{frag}" if frag else "")


def top_band_repeats(arr, band_rows: int, min_gap_rows: int, css_per_row: float = 2.0,
                     threshold: float = 6.0) -> list[tuple[int, float]]:
    """Where the top band (the first band_rows rows) appears again, as (CSS y, mean abs difference).

    arr is a 2-D grayscale float array (rows of the page, top first). Neighbouring hits collapse into one.
    """
    import numpy as np
    band = arr[:band_rows]
    hits = []
    for y in range(min_gap_rows, arr.shape[0] - band_rows + 1):
        mad = float(np.abs(arr[y:y + band_rows] - band).mean())
        if mad < threshold:
            hits.append((round(y * css_per_row), round(mad, 2)))
    out: list[tuple[int, float]] = []
    for y, m in hits:
        if out and y - out[-1][0] <= 20:
            if m < out[-1][1]:
                out[-1] = (y, m)
        else:
            out.append((y, m))
    return out


def gray_rows(im, width_css: int, css_scale: float):
    """Grayscale array at half CSS scale (one row = 2 CSS px) from an image with css_scale pixels per CSS px."""
    import numpy as np
    from PIL import Image
    g = im.convert("L")
    return np.asarray(g.resize((width_css // 2, max(1, round(g.height / css_scale / 2))), Image.BILINEAR),
                      dtype=np.float32)


def top_band_check(arr) -> dict:
    """The phone top-band check, with its own proof of sight: a repeat planted into a copy must be found."""
    band_rows = BAND_CSS // 2
    min_gap = band_rows * 3
    hits = top_band_repeats(arr, band_rows, min_gap)
    planted_at = None
    if arr.shape[0] >= min_gap + 2 * band_rows:
        planted = arr.copy()
        r = max(min_gap, (arr.shape[0] - band_rows) // 2)
        planted[r:r + band_rows] = arr[:band_rows]
        planted_at = r * 2
        seen = any(abs(y - planted_at) <= 4 for y, _ in top_band_repeats(planted, band_rows, min_gap))
    else:
        seen = False
    if planted_at is None:
        status, why = UNKNOWN, "page too short to plant a repeat: the detector's sight is unproven"
    elif not seen:
        status, why = UNKNOWN, f"the detector did not find a band planted at {planted_at} CSS px: it is blind here"
    elif hits:
        status, why = FAIL, f"top band repeats at CSS y {[y for y, _ in hits]}"
    else:
        status, why = PASS, f"once; detector found a band planted at {planted_at} CSS px in a copy"
    return {"status": status, "detail": why, "repeats": hits, "planted_at_css": planted_at, "planted_seen": seen}


# --------------------------------------------------------------------------------------------- git export

class PreviewError(RuntimeError):
    pass


def git(repo: Path, *args: str, binary: bool = False):
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True)
    if p.returncode:
        raise PreviewError(f"git {' '.join(args)}: {p.stderr.decode('utf-8', 'replace').strip()}")
    return p.stdout if binary else p.stdout.decode("utf-8", "replace")


def tree_blobs(repo: Path, ref: str) -> dict[str, str]:
    out = {}
    for rec in git(repo, "ls-tree", "-r", "-z", ref).split("\0"):
        if rec:
            meta, path = rec.split("\t", 1)
            mode, kind, sha = meta.split()
            if kind == "blob" and mode != "120000":
                out[path] = sha
    return out


def export(repo: Path, ref: str, overlays: list[tuple[str, str]], dest: Path) -> dict:
    """Export <ref> to dest, then overlays; prove every file hashes to its blob. Returns the manifest."""
    commit = git(repo, "rev-parse", "--verify", f"{ref}^{{commit}}").strip()
    tar = git(repo, "archive", "--format=tar", commit, binary=True)
    with tarfile.open(fileobj=io.BytesIO(tar)) as tf:
        tf.extractall(dest, filter="data")
    blobs = tree_blobs(repo, commit)
    files = {p: {"ref": ref, "commit": commit, "blob": b} for p, b in blobs.items()}
    for oref, opath in overlays:
        ocommit = git(repo, "rev-parse", "--verify", f"{oref}^{{commit}}").strip()
        oblob = git(repo, "rev-parse", f"{ocommit}:{opath}").strip()
        target = dest / opath
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(git(repo, "cat-file", "blob", oblob, binary=True))
        files[opath] = {"ref": oref, "commit": ocommit, "blob": oblob, "overlay": True,
                        "replaces": blobs.get(opath)}
    mismatched = [p for p, f in files.items()
                  if not (dest / p).is_file() or blob_sha((dest / p).read_bytes()) != f["blob"]]
    return {"commit": commit, "files": files, "mismatched": mismatched}


# --------------------------------------------------------------------------------------------- rendering

class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


DOM_JS = """() => ({height: document.documentElement.scrollHeight,
  scrollWidth: Math.max(document.documentElement.scrollWidth, document.body ? document.body.scrollWidth : 0),
  innerWidth: innerWidth,
  heads: [...document.querySelectorAll('h1, h2')].filter(h => h.getClientRects().length).map(h => {
    const r = h.getBoundingClientRect(); return {text: h.textContent.trim().slice(0, 60), top: r.top + scrollY,
    height: r.height}; })})"""

FONT_JS = """() => document.fonts.ready.then(() => {
  const unq = s => s.trim().replace(/^["']|["']$/g, '');
  const faces = [...document.fonts].map(f => ({family: unq(f.family), style: f.style, weight: f.weight,
                                              status: f.status}));
  const declared = new Set(faces.map(f => f.family));
  const used = {}; let n = 0;
  for (const el of document.querySelectorAll('body, body *')) {
    const own = [...el.childNodes].some(c => c.nodeType === 3 && c.textContent.trim());
    if (!own || !el.getClientRects().length) continue;
    const fam = unq(getComputedStyle(el).fontFamily.split(',')[0]);
    if (!used[fam]) { el.setAttribute('data-preview-probe', String(n));
                      used[fam] = {count: 0, probe: String(n++), stack: getComputedStyle(el).fontFamily}; }
    used[fam].count++;
  }
  return {faces, used, declared: [...declared]};
})"""


def platform_fonts(page, probe: str) -> list[dict]:
    cdp = page.context.new_cdp_session(page)
    try:
        root = cdp.send("DOM.getDocument", {"depth": -1})["root"]["nodeId"]
        cdp.send("CSS.enable")
        node = cdp.send("DOM.querySelector", {"nodeId": root, "selector": f'[data-preview-probe="{probe}"]'})["nodeId"]
        return cdp.send("CSS.getPlatformFontsForNode", {"nodeId": node})["fonts"]
    finally:
        cdp.detach()


def font_check(page) -> dict:
    info = page.evaluate(FONT_JS)
    loaded = {f["family"] for f in info["faces"] if f["status"] == "loaded"}
    declared = {f["family"] for f in info["faces"]}
    rows, system, ok = [], [], True
    for fam, u in info["used"].items():
        rendered = platform_fonts(page, u["probe"])
        drawn = [f"{f['familyName']}{' (custom)' if f.get('isCustomFont') else ''} x{f.get('glyphCount')}"
                 for f in rendered]
        if fam not in declared:          # a system stack: reported, not judged (no webfont was promised)
            system.append({"family": fam, "stack": u["stack"], "elements": u["count"], "engine_rendered": drawn})
            continue
        good = fam in loaded and any(f.get("isCustomFont") for f in rendered)
        ok &= good
        rows.append({"family": fam, "elements": u["count"], "face_loaded": fam in loaded,
                     "engine_rendered": drawn, "pass": good})
    sys_note = "; system stacks (not judged): " + "; ".join(
        f"{s['family']} x{s['elements']} el. drawn in {', '.join(s['engine_rendered']) or '?'}" for s in system)
    if not rows:
        return {"status": UNKNOWN, "detail": "the page uses no @font-face family: nothing to prove loaded" + sys_note,
                "families": rows, "system": system}
    detail = "; ".join(f"{r['family']} ({r['elements']} el.): face {'loaded' if r['face_loaded'] else 'NOT loaded'}, "
                       f"engine drew {', '.join(r['engine_rendered']) or 'nothing'}" for r in rows)
    return {"status": PASS if ok else FAIL, "detail": detail + sys_note, "families": rows, "system": system}


def capture(page, width: int, dpr: int) -> tuple[dict, list]:
    """Tile the page. Returns (facts, [(y, h, PIL image)])."""
    from PIL import Image
    dom = page.evaluate(DOM_JS)
    height = dom["height"]
    plan = plan_tiles(height)
    tiles = []
    for y, h in plan:
        png = page.screenshot(clip={"x": 0, "y": y, "width": width, "height": h}, full_page=True)
        tiles.append((y, h, Image.open(io.BytesIO(png)).convert("RGB")))
    after = page.evaluate(DOM_JS)["height"]
    sizes_ok = all(im.size == (width * dpr, h * dpr) for _, h, im in tiles)
    ok = tiles_cover(plan, height) and sizes_ok and after == height
    facts = {"page_height_css": height, "height_after_capture": after, "plan": plan,
             "sizes": [list(im.size) for *_, im in tiles], "sizes_ok": sizes_ok, "pass": ok, "heads": dom["heads"]}
    return facts, tiles


def viewport_agreement(page, stitched, heads: list[dict], dpr: int, vh: int, limit: int = 24) -> list[dict]:
    import numpy as np
    from PIL import Image
    st = np.asarray(stitched, dtype=np.float32)
    if len(heads) > limit:
        step = len(heads) / limit
        heads = [heads[int(i * step)] for i in range(limit)]
    rows = []
    for t in heads:
        page.evaluate(f"window.scrollTo(0, {t['top']} - 300)")
        page.wait_for_timeout(60)
        sy = page.evaluate("scrollY")
        shot = np.asarray(Image.open(io.BytesIO(page.screenshot())).convert("RGB"), dtype=np.float32)
        a = round((t["top"] - sy - 12) * dpr)
        b = round((t["top"] - sy + t["height"] + 12) * dpr)
        if a < 0 or b > vh * dpr:
            rows.append({"head": t["text"], "top_css": round(t["top"]), "mad": None, "pass": None,
                         "note": "band not inside the viewport"})
            continue
        s0 = round((t["top"] - 12) * dpr)
        view, cap = shot[a:b], st[s0:s0 + (b - a)]
        mad = float(np.abs(view - cap).mean()) if view.shape == cap.shape else 999.0
        rows.append({"head": t["text"], "top_css": round(t["top"]), "mad": round(mad, 2), "pass": mad < 3.0})
    page.evaluate("window.scrollTo(0, 0)")
    return rows


def stitch(tiles, width_px: int, dpr: int):
    from PIL import Image
    total = sum(h for _, h, _ in tiles) * dpr
    out = Image.new("RGB", (width_px, total))
    for y, _, im in tiles:
        out.paste(im, (0, y * dpr))
    return out


def jpeg(im) -> bytes:
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
    return buf.getvalue()


def url_rel(url: str, base: str) -> str | None:
    if not url.startswith(base):
        return None
    path = urllib.parse.unquote(urllib.parse.urlsplit(url).path).lstrip("/")
    return path + "index.html" if path == "" or path.endswith("/") else path


def check_page(browser, base: str, root: Path, rel: str, manifest: dict, out: Path, stem: str) -> dict:
    from PIL import Image
    Image.MAX_IMAGE_PIXELS = None
    url = f"{base}/{rel}"
    checks: dict[str, dict] = {}
    console, bad_requests, loaded = [], [], set()

    def watch(page):
        page.on("console", lambda m: console.append(f"{m.type}: {m.text} @ {m.location.get('url', '')}")
                if m.type == "error" else None)
        page.on("pageerror", lambda e: console.append(f"pageerror: {e}"))
        page.on("requestfailed", lambda r: bad_requests.append(f"{r.url}: {r.failure}"))

        def resp(r):
            p = url_rel(r.url, base)
            if p:
                loaded.add(p)
                if r.status >= 400:
                    bad_requests.append(f"{r.url}: HTTP {r.status}")
        page.on("response", resp)

    def open_page(width, vh, dpr, mobile):
        ctx = browser.new_context(viewport={"width": width, "height": vh}, device_scale_factor=dpr,
                                  is_mobile=mobile, has_touch=mobile)
        pg = ctx.new_page()
        watch(pg)
        r = pg.goto(url, wait_until="networkidle")
        pg.evaluate("document.fonts.ready.then(() => true)")
        return ctx, pg, r

    # http + horizontal scroll at five phone widths
    hs, statuses = {}, []
    for w in HSCROLL_WIDTHS:
        ctx, pg, r = open_page(w, PHONE_VH, PHONE_DPR, True)
        statuses.append(r.status if r else None)
        d = pg.evaluate(DOM_JS)
        hs[w] = {"scrollWidth": d["scrollWidth"], "innerWidth": d["innerWidth"],
                 "pass": d["innerWidth"] == w and d["scrollWidth"] <= w}
        ctx.close()

    # desktop
    ctx, pg, r = open_page(DESK_W, DESK_VH, DESK_DPR, False)
    statuses.append(r.status if r else None)
    dfacts, dtiles = capture(pg, DESK_W, DESK_DPR)
    dstitched = stitch(dtiles, DESK_W * DESK_DPR, DESK_DPR)
    dagree = viewport_agreement(pg, dstitched, dfacts.pop("heads"), DESK_DPR, DESK_VH)
    dfont = font_check(pg)
    ctx.close()

    # phone
    ctx, pg, r = open_page(PHONE_W, PHONE_VH, PHONE_DPR, True)
    statuses.append(r.status if r else None)
    pfacts, ptiles = capture(pg, PHONE_W, PHONE_DPR)
    pstitched = stitch(ptiles, PHONE_W * PHONE_DPR, PHONE_DPR)
    pagree = viewport_agreement(pg, pstitched, pfacts.pop("heads"), PHONE_DPR, PHONE_VH)
    pfont = font_check(pg)
    ctx.close()

    checks["http 200"] = {"status": PASS if statuses and all(s == 200 for s in statuses) else FAIL,
                          "detail": f"{len(statuses)} loads: {sorted(set(statuses), key=str)}"}
    checks["no horizontal scroll"] = {
        "status": PASS if all(v["pass"] for v in hs.values()) else FAIL,
        "detail": ", ".join(f"{w}: {v['scrollWidth']}/{v['innerWidth']}" for w, v in hs.items()), "widths": hs}
    cov = dfacts["pass"] and pfacts["pass"]
    checks["tiles cover the page"] = {
        "status": PASS if cov else FAIL,
        "detail": f"desktop {dfacts['page_height_css']} CSS px in {len(dfacts['plan'])} tiles; phone "
                  f"{pfacts['page_height_css']} CSS px in {len(pfacts['plan'])} tiles of {TILE_CSS}; heights stable "
                  f"{dfacts['height_after_capture'] == dfacts['page_height_css'] and pfacts['height_after_capture'] == pfacts['page_height_css']}"
                  f"; pixel sizes as planned {dfacts['sizes_ok'] and pfacts['sizes_ok']}",
        "desktop": dfacts, "phone": pfacts}
    rows = [dict(r, view="desktop") for r in dagree] + [dict(r, view="phone") for r in pagree]
    judged = [r for r in rows if r["pass"] is not None]
    if not judged:
        st = UNKNOWN
    else:
        st = PASS if all(r["pass"] for r in judged) else FAIL
    worst = max((r["mad"] for r in judged), default=None)
    checks["tiles match the live viewport"] = {
        "status": st, "detail": f"{len(judged)} headings compared (desktop {sum(1 for r in judged if r['view'] == 'desktop')}, "
        f"phone {sum(1 for r in judged if r['view'] == 'phone')}), worst mean abs diff {worst} (< 3.0 passes); "
        f"{len(rows) - len(judged)} skipped", "rows": rows}
    tb = top_band_check(gray_rows(pstitched, PHONE_W, PHONE_DPR))
    checks["top band appears once (phone)"] = tb

    # links, from the exported bytes of the page
    exists = lambda p: (root / p).is_file()  # noqa: E731
    ids_cache: dict[str, set] = {}

    def ids_for(p):
        if p not in ids_cache:
            ids_cache[p] = scan_html((root / p).read_text("utf-8", "replace"))[1] if exists(p) else set()
        return ids_cache[p]
    links, _ = scan_html((root / rel).read_text("utf-8", "replace"))
    seen, broken, n_ok, n_ext = set(), [], 0, 0
    for tag, href in links:
        if href in seen or href.startswith(("mailto:", "tel:", "javascript:", "data:")):
            continue
        seen.add(href)
        status, why = resolve_link(href, rel, exists, ids_for)
        if status == "broken":
            broken.append(why)
        elif status == "external":
            n_ext += 1
        else:
            n_ok += 1
    checks["links resolve"] = {"status": FAIL if broken else PASS,
                               "detail": f"{n_ok} distinct internal links/anchors resolve, {len(broken)} broken"
                                         f"{': ' + '; '.join(broken) if broken else ''} ({n_ext} external, not checked)",
                               "broken": broken}
    errs = console + bad_requests
    checks["console clean"] = {"status": FAIL if errs else PASS,
                               "detail": f"{len(console)} console/page errors, {len(bad_requests)} failed requests"
                                         f" across {len(statuses)} loads" + (": " + " | ".join(errs[:10]) if errs else ""),
                               "errors": errs}
    fst = UNKNOWN if UNKNOWN in (dfont["status"], pfont["status"]) else (
        PASS if dfont["status"] == pfont["status"] == PASS else FAIL)
    checks["webfonts loaded"] = {"status": fst, "detail": f"desktop: {dfont['detail']} | phone: {pfont['detail']}",
                                 "desktop": dfont, "phone": pfont}

    # images
    imgs = {"desktop": [], "phone": []}
    for view, tiles in (("desktop", dtiles), ("phone", ptiles)):
        for i, (y, h, im) in enumerate(tiles, 1):
            data = jpeg(im)
            name = f"{stem}-{view}-{i:02d}.jpg"
            (out / name).write_bytes(data)
            imgs[view].append({"file": name, "y": y, "h": h, "bytes": len(data), "data": data})

    files = {}
    for p in sorted(loaded | {rel}):
        f = manifest["files"].get(p)
        files[p] = dict(f) if f else {"blob": None, "note": "served but not in the export manifest"}
    verdict = (FAIL if any(c["status"] == FAIL for c in checks.values()) else
               UNKNOWN if any(c["status"] == UNKNOWN for c in checks.values()) else PASS)
    return {"page": rel, "url_path": "/" + rel, "verdict": verdict, "checks": checks, "files": files, "images": imgs}


# --------------------------------------------------------------------------------------------- report

CSS = """
:root{--bg:#f6f4ef;--ink:#1c1b19;--muted:#5d5a53;--line:#d9d4c8;--pass:#1d6b3a;--fail:#a3221b;--unk:#8a5a00;--card:#fff}
@media (prefers-color-scheme:dark){:root{--bg:#141412;--ink:#ecebe6;--muted:#a19d92;--line:#3a3833;--pass:#5cc184;
--fail:#ff7a6e;--unk:#f0b545;--card:#1d1c1a}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}
main{max-width:1320px;margin:0 auto;padding:16px}h1{font-size:1.4rem;margin:.2rem 0}h2{font-size:1.2rem;margin:2rem 0 .4rem}
h3{font-size:1rem;margin:1.4rem 0 .4rem}code{font:12.5px ui-monospace,Consolas,monospace;word-break:break-all}
.meta{color:var(--muted);font-size:.86rem}.verdict{font-weight:700;padding:.1rem .45rem;border:1.5px solid}
.PASS{color:var(--pass)}.FAIL{color:var(--fail)}.UNKNOWN{color:var(--unk)}
table{border-collapse:collapse;width:100%;background:var(--card);font-size:.86rem}
td,th{border:1px solid var(--line);padding:.35rem .5rem;text-align:left;vertical-align:top}
th{font-weight:600}td.s{font-weight:700;white-space:nowrap}.wrap{overflow-x:auto}
.desk img{display:block;width:100%;max-width:1280px;height:auto}
.phone{width:390px;max-width:100%;margin:0 auto;border:1px solid var(--line)}
.phone img{display:block;width:100%;height:auto}section{border-top:2px solid var(--line);margin-top:2rem}
"""


def render_html(report: dict) -> str:
    e = html.escape
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' "
             f"content='width=device-width,initial-scale=1'><title>Preview proof {e(report['commit'][:7])}</title>"
             f"<style>{CSS}</style></head><body><main>",
             f"<h1>Preview proof: <span class='verdict {report['verdict']}'>{report['verdict']}</span></h1>",
             f"<p class='meta'>ref <code>{e(report['ref'])}</code> = commit <code>{e(report['commit'])}</code><br>"
             f"export re-hashed to the tree: {len(report['export']['files'])} files, "
             f"{len(report['export']['mismatched'])} mismatched<br>"
             + "".join(f"overlay <code>{e(o['path'])}</code> from <code>{e(o['ref'])}</code> = commit "
                       f"<code>{e(o['commit'])}</code>, blob <code>{e(o['blob'])}</code><br>" for o in report['overlays'])
             + f"browser {e(report['browser'])} · generated {e(report['generated'])} by tools/preview.py</p>"]
    for pg in report["pages"]:
        parts.append(f"<section><h2>/{e(pg['page'])} <span class='verdict {pg['verdict']}'>{pg['verdict']}</span></h2>"
                     f"<p class='meta'>commit <code>{e(report['commit'])}</code></p>")
        parts.append("<h3>Files this page loaded (git blob ids)</h3><div class='wrap'><table><tr><th>path</th>"
                     "<th>from</th><th>blob</th></tr>")
        for p, f in pg["files"].items():
            src = f.get("ref", "?") + (" (overlay)" if f.get("overlay") else "")
            parts.append(f"<tr><td><code>{e(p)}</code></td><td><code>{e(src)}</code></td>"
                         f"<td><code>{e(str(f.get('blob')))}</code></td></tr>")
        parts.append("</table></div><h3>Checks</h3><div class='wrap'><table><tr><th>check</th><th>result</th>"
                     "<th>evidence</th></tr>")
        for name, c in pg["checks"].items():
            parts.append(f"<tr><td>{e(name)}</td><td class='s {c['status']}'>{c['status']}</td>"
                         f"<td>{e(c['detail'])}</td></tr>")
        parts.append("</table></div>")
        for view, cls, label in (("desktop", "desk", f"Desktop, {DESK_W} wide"),
                                 ("phone", "phone", f"Phone, {PHONE_W} wide, device scale {PHONE_DPR}")):
            ims = pg["images"][view]
            parts.append(f"<h3>{label}: {len(ims)} tiles, top to bottom</h3><p class='meta'>"
                         + ", ".join(f"{i['y']}–{i['y'] + i['h']}" for i in ims) + " CSS px</p>"
                         f"<div class='{cls}'>")
            for i in ims:
                b64 = base64.b64encode(i["data"]).decode("ascii")
                parts.append(f"<img alt='{view} {i['y']}–{i['y'] + i['h']} CSS px' src='data:image/jpeg;base64,{b64}'>")
            parts.append("</div>")
        parts.append("</section>")
    parts.append("</main></body></html>")
    return "".join(parts)


# --------------------------------------------------------------------------------------------- main

def parse_overlay(s: str) -> tuple[str, str]:
    ref, sep, path = s.partition(":")
    if not sep or not ref or not path:
        raise argparse.ArgumentTypeError(f"--overlay wants <ref>:<path>, got {s!r}")
    return ref, path.replace("\\", "/").lstrip("/")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ref")
    ap.add_argument("pages", nargs="+")
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--overlay", action="append", default=[], type=parse_overlay)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    a = ap.parse_args(argv)
    import datetime as dt
    try:
        from playwright.sync_api import sync_playwright
        import numpy  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError as exc:
        print(f"UNKNOWN: a dependency is missing ({exc}); preview.py installs nothing on its own", file=sys.stderr)
        return 2

    a.out.mkdir(parents=True, exist_ok=True)
    pages = [p.replace("\\", "/").lstrip("/") for p in a.pages]
    tmp = Path(tempfile.mkdtemp(prefix="b4him-preview-"))
    report = {"ref": a.ref, "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"), "pages": []}
    try:
        man = export(a.repo, a.ref, a.overlay, tmp)
        report.update(commit=man["commit"], export={"files": man["files"], "mismatched": man["mismatched"]},
                      overlays=[dict(path=p, **man["files"][p]) for _, p in a.overlay])
        missing = [p for p in pages if not (tmp / p).is_file()]
        if missing:
            raise PreviewError(f"not in the export at {a.ref}: {missing}")
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(_Quiet, directory=str(tmp)))
        threading.Thread(target=server.serve_forever, daemon=True).start()
        base = f"http://127.0.0.1:{server.server_address[1]}"
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(channel="msedge")
                report["browser"] = f"msedge {browser.version} (Playwright)"
                for i, rel in enumerate(pages, 1):
                    stem = f"p{i}-" + rel.replace("/index.html", "").replace("/", "_").replace(".html", "")
                    res = check_page(browser, base, tmp, rel, man, a.out, stem)
                    if man["mismatched"]:
                        res["checks"]["export = committed bytes"] = {
                            "status": FAIL, "detail": f"{len(man['mismatched'])} exported files do not hash to "
                                                      f"their blob: {man['mismatched'][:10]}"}
                        res["verdict"] = FAIL
                    else:
                        res["checks"] = {"export = committed bytes": {
                            "status": PASS, "detail": f"all {len(man['files'])} exported files re-hash to the blob "
                                                      f"ids at {man['commit'][:12]} (overlays to theirs)"},
                            **res["checks"]}
                    report["pages"].append(res)
                    print(f"{res['verdict']:7} /{rel}")
                    for name, c in res["checks"].items():
                        print(f"   {c['status']:7} {name}: {c['detail'][:300]}")
                browser.close()
        finally:
            server.shutdown()
    except Exception as exc:  # a check that could not run is UNKNOWN, never PASS
        report["error"] = f"{type(exc).__name__}: {exc}"
        print(f"UNKNOWN: {report['error']}", file=sys.stderr)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    verdicts = [pg["verdict"] for pg in report["pages"]]
    if report.get("error") or len(verdicts) != len(pages):
        report["verdict"] = UNKNOWN
    elif FAIL in verdicts:
        report["verdict"] = FAIL
    elif UNKNOWN in verdicts:
        report["verdict"] = UNKNOWN
    else:
        report["verdict"] = PASS
    report.setdefault("commit", "?")
    report.setdefault("browser", "?")
    report.setdefault("overlays", [])
    report.setdefault("export", {"files": {}, "mismatched": []})
    (a.out / "proof.html").write_text(render_html(report), encoding="utf-8")
    slim = json.loads(json.dumps(report, default=lambda o: None))
    for pg, full in zip(slim["pages"], report["pages"]):
        for view in pg["images"]:
            for im, fim in zip(pg["images"][view], full["images"][view]):
                im.pop("data", None)
                im["file"] = fim["file"]
    slim["export"]["files"] = len(report["export"]["files"])
    (a.out / "proof.json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
    print(f"{report['verdict']}: {a.out / 'proof.html'}")
    return {PASS: 0, FAIL: 1}.get(report["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
