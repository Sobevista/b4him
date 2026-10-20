#!/usr/bin/env python3
"""
serve_surface.py — what b4him.com serves, derived from _config.yml and the tracked files (SITE-PATCH-SERVE-1).

Daniel, 2026-10-20 (ledger E00761): "Go with Recommended D The curated Workshop." b4him.com serves the SITE only;
internal/factory files stop being served; the repo stays public; nothing moves or is deleted. _config.yml's only job
is `exclude:`. This module is the one place that knows how GitHub Pages reads it, so the test
(tools/test_serve_config.py), the production line (approvals.py, a `patch_scope: "site-config"` patch) and the live
check (release.py verify_live) all use the same logic.

THE MATCHER (GitHub Pages builds with jekyll 3.10, EntryFilter#glob_include?): a path segment starting with
. _ # ~ is never served; each exclude pattern is File.fnmatch?'d WITHOUT flags (so `*` also matches `/`), or matched
as a plain string prefix; a pattern ending in `/` also drops that directory; a dropped directory drops everything
under it. A user `exclude:` REPLACES jekyll's defaults (and pages-gem adds CNAME only when exclude equals them).

THE SURFACE at a commit: SERVED = every tracked .html page, every tracked file a served page or stylesheet references
(relative, root-relative, or https://b4him.com/ absolute), and SERVED_UNREFERENCED; none may be excluded. INTERNAL =
the classes below; all must be. A SITE-CONFIG patch is verified live by the surface, never by fetching /_config.yml
(Pages never serves it): every SERVED path answers 200 with the commit's bytes, and INTERNAL_SAMPLE answers 404.

    py tools/serve_surface.py            # print the SERVED list and the INTERNAL sample at HEAD's working tree
"""
from __future__ import annotations

import fnmatch
import hashlib
import posixpath
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SITE = "https://b4him.com"
CONFIG = "_config.yml"
#: The patch scope that may change _config.yml, and nothing else.
SITE_CONFIG = "site-config"
SPECIAL = (".", "_", "#", "~")
#: Served on purpose though no page links them: the n8n track furniture (live, kept by the ruling) and the two
#: brand master images (not factory code).
SERVED_UNREFERENCED = frozenset({"tools/tracks/n8n.html", "assets/brand/beacon-emblem-master.png",
                                 "assets/brand/beacon-lockup-master.png"})
#: Never served whatever the config says (leading dot or underscore), or kept unserved as pages-gem did (CNAME).
NEVER_SERVED = frozenset({".gitattributes", ".gitignore", "CNAME", CONFIG})
#: URL path on the live site -> the tracked source whose exclusion hides it. Each must answer 404 once a site-config
#: patch is live. /RESUME.html is jekyll's rendering of RESUME.md (jekyll-optional-front-matter), live before the patch.
INTERNAL_SAMPLE = {"/RESUME.md": "RESUME.md", "/RESUME.html": "RESUME.md",
                   "/production_queue.jsonl": "production_queue.jsonl", "/tools/approvals.py": "tools/approvals.py",
                   "/boards/APPROVALS_OWED.md": "boards/APPROVALS_OWED.md", "/CNAME": "CNAME"}
INTERNAL_SAMPLE_PATHS = frozenset(INTERNAL_SAMPLE.values())
POLL_SECONDS = 30

ATTR = re.compile(r"""(?:href|src|content|poster|srcset)\s*=\s*["']([^"']+)["']""", re.I)
CSS_URL = re.compile(r"""url\(\s*["']?([^"')]+?)["']?\s*\)""", re.I)


class SurfaceError(RuntimeError):
    pass


def internal_class(rel: str) -> bool:
    """The factory: planning/rules Markdown, queues and logs, data, boards, seats, tools code and tests."""
    return (rel.endswith((".md", ".jsonl", ".py", ".cmd"))
            or rel.startswith(("boards/", "data/", "seats/", "tools/capability_inventory/"))
            or (rel.startswith("tools/") and rel.endswith(".js")))


def load_exclude(text: str) -> list[str]:
    """The exclude list. Refuses a config that does anything else: its only job is exclude:."""
    try:
        import yaml
        cfg = yaml.safe_load(text) or {}
    except ImportError:  # the file is a flat list; read it by hand
        cfg = {"exclude": [ln.strip()[2:].strip().strip('"') for ln in text.splitlines()
                           if ln.strip().startswith("- ")]}
        if any(re.match(r"^[A-Za-z_]+\s*:", ln) and not ln.startswith("exclude:") for ln in text.splitlines()):
            cfg["?"] = True
    if not isinstance(cfg, dict) or set(cfg) - {"exclude"}:
        raise SurfaceError(f"_config.yml's only job is exclude:, found keys {sorted(cfg) if isinstance(cfg, dict) else cfg}")
    pats = cfg.get("exclude") or []
    if not isinstance(pats, list) or not all(isinstance(p, str) and p for p in pats):
        raise SurfaceError("_config.yml exclude: must be a list of non-empty strings")
    return pats


def _hit(path: str, patterns: list[str], is_dir: bool) -> bool:
    return any(fnmatch.fnmatchcase(path, pat) or path.startswith(pat) or (is_dir and pat == path + "/")
               for pat in patterns)


def excluded(rel: str, patterns: list[str]) -> bool:
    parts = rel.split("/")
    for i in range(1, len(parts) + 1):
        if parts[i - 1].startswith(SPECIAL):
            return True
        if _hit("/".join(parts[:i]), patterns, is_dir=i < len(parts)):
            return True
    return False


def git_blob_id(data: bytes) -> str:
    if b"\0" not in data:                     # text: compare as git stores it (LF), like pb.blob_sha
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


class Tree:
    """A set of tracked paths and their bytes: a commit, or the working tree's tracked files, optionally with some
    paths overridden (a proposed _config.yml laid over main)."""

    def __init__(self, files, reader, override=None):
        self.override = dict(override or {})
        self.files = sorted(set(files) | set(self.override))
        self._reader = reader

    def read(self, rel: str) -> bytes | None:
        if rel in self.override:
            return self.override[rel]
        return self._reader(rel) if rel in self.files else None

    def blob(self, rel: str) -> str | None:
        data = self.read(rel)
        return None if data is None else git_blob_id(data)

    @classmethod
    def at_commit(cls, repo: Path, commit: str, override=None) -> "Tree":
        out = subprocess.run(["git", "-C", str(repo), "ls-tree", "-r", "-z", "--name-only", commit],
                             capture_output=True, check=True).stdout.decode("utf-8")

        def read(rel):
            p = subprocess.run(["git", "-C", str(repo), "show", f"{commit}:{rel}"], capture_output=True)
            return p.stdout if p.returncode == 0 else None
        return cls([p for p in out.split("\0") if p], read, override)

    @classmethod
    def worktree(cls, repo: Path, override=None) -> "Tree":
        out = subprocess.run(["git", "-C", str(repo), "ls-files", "-z"], capture_output=True,
                             check=True).stdout.decode("utf-8")

        def read(rel):
            try:
                return (repo / rel).read_bytes()
            except OSError:
                return None
        return cls([p for p in out.split("\0") if p and (repo / p).exists()], read, override)


def references(tree: Tree, rel: str) -> set[str]:
    """Tracked files that served file `rel` points at (relative, root-relative or https://b4him.com/ URLs)."""
    text = (tree.read(rel) or b"").decode("utf-8", "replace")
    files, found = set(tree.files), set()
    for raw in ATTR.findall(text) + CSS_URL.findall(text):
        for url in raw.split(","):                       # srcset lists
            url = url.strip().split(" ")[0].split("#")[0].split("?")[0]
            if url.startswith(SITE + "/"):
                url = url[len(SITE):]
            if not url or re.match(r"^[a-z][a-z0-9+.-]*:", url, re.I) or url.startswith("//"):
                continue
            path = url.lstrip("/") if url.startswith("/") else posixpath.normpath(
                posixpath.join(posixpath.dirname(rel), url))
            for cand in (path, posixpath.join(path, "index.html")):
                if cand in files:
                    found.add(cand)
    return found


def served(tree: Tree) -> set[str]:
    fs = set(tree.files)
    pages = {f for f in fs if f.endswith(".html")}
    out = set(pages) | (SERVED_UNREFERENCED & fs)
    todo = list(pages) + [f for f in fs if f.endswith(".css")]
    while todo:
        cur = todo.pop()
        if not cur.endswith((".html", ".css")) or cur not in fs:
            continue
        for ref in references(tree, cur):
            if ref not in out:
                out.add(ref)
                todo.append(ref)
    # an internal file a served page references stays in: surface() then reports the config hides what a page uses
    return {f for f in out if f not in NEVER_SERVED}


def surface(tree: Tree) -> tuple[dict[str, str], list[str], list[str]]:
    """({served path: blob id}, [internal sample URL paths], [problems]). A problem is a served file the config
    hides, or an internal sample (or tracked internal file) the config leaves served."""
    text = (tree.read(CONFIG) or b"").decode("utf-8")
    pats = load_exclude(text)
    s = served(tree)
    problems = [f"{CONFIG} would stop serving {f}, which the site uses" for f in sorted(s) if excluded(f, pats)]
    problems += [f"{CONFIG} leaves internal {f} served" for f in sorted(set(tree.files) | INTERNAL_SAMPLE_PATHS)
                 if (internal_class(f) or f in INTERNAL_SAMPLE_PATHS) and not excluded(f, pats)]
    return {f: tree.blob(f) for f in sorted(s)}, sorted(INTERNAL_SAMPLE), problems


def scope_problems(row: dict, files) -> list[str]:
    """What is wrong with a row's site-config scope, judged on the paths it pins/changes. Shared by approvals.py
    (offer, rack) and release.py (plan): a site-config patch pins ONLY _config.yml and is not a page patch; no other
    row may carry _config.yml."""
    files = set(files)
    scope = row.get("patch_scope")
    if scope == SITE_CONFIG:
        out = []
        if row.get("kind") != "patch":
            out.append(f"patch_scope {SITE_CONFIG!r} is a patch scope, but the row's kind is {row.get('kind')!r}")
        if files != {CONFIG}:
            out.append(f"a {SITE_CONFIG} patch may change only {CONFIG}; it names {sorted(files)}")
        if row.get("page") or row.get("index_entry"):
            out.append(f"a {SITE_CONFIG} patch cannot also be a page patch (it names page "
                       f"{row.get('page') or row.get('index_entry', {}).get('href')!r})")
        return out
    if CONFIG in files:
        return [f"{CONFIG} changes only through a patch_scope {SITE_CONFIG!r} patch (this row's scope is "
                f"{scope!r})"]
    return []


def url_for(rel: str) -> str:
    if rel == "index.html" or rel.endswith("/index.html"):
        rel = rel[:-len("index.html")]
    return f"{SITE}/{rel}"


def _fetch(url: str) -> tuple[int | None, bytes]:
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "User-Agent": "b4him-release"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, b""
    except OSError:
        return None, b""


#: Injection points for tests (and nothing else): the HTTP GET and the nap between looks.
FETCH = _fetch
SLEEP = time.sleep


def verify(tree: Tree, minutes: float) -> str:
    """Poll the live site until every SERVED path answers 200 with the tree's bytes and every INTERNAL sample path
    answers 404, or `minutes` pass (a Pages build takes minutes). Always looks at least once."""
    blobs, sample, problems = surface(tree)
    if problems:
        raise SurfaceError("the committed config does not give the intended surface: " + "; ".join(problems))
    deadline = time.time() + minutes * 60
    want_200 = {url_for(rel): blob for rel, blob in blobs.items()}
    want_404 = {SITE + p for p in sample}
    last: dict[str, str] = {}
    while True:
        for url, blob in list(want_200.items()):
            status, data = FETCH(url)
            if status == 200 and git_blob_id(data) == blob:
                del want_200[url]
            else:
                last[url] = f"{status}" + (" with other bytes" if status == 200 else "")
        for url in list(want_404):
            status, _ = FETCH(url)
            if status == 404:
                want_404.discard(url)
            else:
                last[url] = f"{status}, expected 404"
        if (not want_200 and not want_404) or time.time() >= deadline:
            break
        SLEEP(POLL_SECONDS)
    if want_200 or want_404:
        bad = [f"{u} ({last.get(u, '?')})" for u in sorted(want_200) + sorted(want_404)]
        raise SurfaceError(f"after {minutes} min the live surface is not the committed one: " + "; ".join(bad))
    return f"served surface matches: {len(blobs)} paths 200 with main's bytes, {len(sample)} internal paths 404"


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    blobs, sample, problems = surface(Tree.worktree(root))
    for rel in blobs:
        print("SERVED  ", rel)
    for p in sample:
        print("404     ", p)
    for p in problems:
        print("PROBLEM ", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
