#!/usr/bin/env python3
"""
site_pages.py: the one answer to "which pages does b4him.com serve?", shared by every maintenance scanner
(W1 linkcheck.py; W3, Q1, Q2, A2 maint_pages.py; M1, M2 maint_quality.py; M3's mixed-content grep).

THE RULE. GitHub Pages builds this repo with Jekyll (there is no .nojekyll and no _config.yml), and Jekyll never
serves a file or folder whose name starts with "." or "_", at any depth. So a served page is a tracked *.html / *.htm
file with no path part starting with "." or "_". Everything else that is tracked IS served, tools/ included.

That is why the A4 calibration fixtures, which hold PLANTED FAULTS (a broken link, a missing alt, low contrast, a
mixed-content subresource, a name stand-in), live in tools/_maint_fixtures/: never served, never in any page list.

    served_pages(root)              tracked pages in the git index of `root`
    served_pages(root, ref="HEAD")  pages in a commit's tree instead
    is_served(path)                 the rule alone, for one repo-relative posix path
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PAGE_EXTS = (".html", ".htm")


class GitError(RuntimeError):
    """git could not list the tree. Callers turn this into their own UNKNOWN."""


def is_served(path: str) -> bool:
    return not any(part.startswith((".", "_")) for part in path.replace("\\", "/").split("/") if part)


def tracked(root: Path, ref: str | None = None) -> list[str]:
    argv = ["git", "-C", str(root)] + (["ls-tree", "-r", "--name-only", "-z", ref] if ref else ["ls-files", "-z"])
    try:
        p = subprocess.run(argv, capture_output=True)
    except OSError as e:
        raise GitError(f"git could not start: {e}") from None
    if p.returncode:
        raise GitError(f"git {argv[3]} exited {p.returncode}: {p.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return [f for f in p.stdout.decode("utf-8", "replace").split("\0") if f]


def served_pages(root: Path, exts: tuple[str, ...] = PAGE_EXTS, ref: str | None = None) -> list[str]:
    return sorted(f for f in tracked(root, ref) if f.lower().endswith(exts) and is_served(f))
