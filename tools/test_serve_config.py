"""SITE-PATCH-SERVE-1 (Daniel 2026-10-20, ledger E00761): b4him.com serves the SITE only.

_config.yml's `exclude:` keeps the factory (planning .md, queue, data, boards, tools code and tests) out of the
GitHub Pages build. The matcher and the SERVED/INTERNAL classification live in tools/serve_surface.py (the same logic
approvals.py and release.py use for a site-config patch). This test asserts, on the real repo:
  * every tracked HTML page, and every file a served page or stylesheet references, is NOT excluded;
  * every INTERNAL class IS excluded, today's files and named future ones;
  * tools/tracks/n8n.html is NOT excluded;
  * every tracked file is classified, so a new file forces a decision instead of shipping by default.
"""
from __future__ import annotations

from pathlib import Path

import pytest

import serve_surface as ss

ROOT = Path(__file__).resolve().parent.parent
FUTURE_INTERNAL = ["OPERATIONS.md", "PUBLICATION_GATE.md", "RESEARCH_2026-12-01.md", "seats/seat-a.md",
                   "seats/roster.json", "release_log.jsonl", "boards/NEW_BOARD.md", "data/new.json",
                   "tools/new_tool.py", "tools/deep/er/test_x.py", "tools/new_audit.js", "tools/run.cmd"]


def tree():
    return ss.Tree.worktree(ROOT)


def pats():
    return ss.load_exclude((ROOT / ss.CONFIG).read_text(encoding="utf-8"))


def test_config_has_only_exclude_and_parses():
    assert pats()
    with pytest.raises(ss.SurfaceError):
        ss.load_exclude("exclude:\n  - data/\ntheme: minima\n")


def test_every_served_page_and_asset_is_not_excluded():
    s = ss.served(tree())
    for must in ("index.html", "style.css", "lesson.css", "favicon.ico", "assets/og.png",
                 "assets/fonts/fraunces-normal.woff2", "tools/tracks/n8n.html"):
        assert must in s, f"{must} should be classified SERVED"
    bad = sorted(f for f in s if ss.excluded(f, pats()))
    assert not bad, f"_config.yml would stop serving files the site uses: {bad}"


def test_n8n_track_stays_served():
    assert not ss.excluded("tools/tracks/n8n.html", pats())


def test_every_internal_file_is_excluded_today_and_tomorrow():
    internal = [f for f in tree().files if ss.internal_class(f)] + FUTURE_INTERNAL + sorted(ss.INTERNAL_SAMPLE_PATHS)
    leaks = sorted(f for f in internal if not ss.excluded(f, pats()))
    assert not leaks, f"internal files still served: {leaks}"
    assert all(ss.internal_class(f) for f in FUTURE_INTERNAL)


def test_the_real_surface_has_no_problems():
    blobs, sample, problems = ss.surface(tree())
    assert not problems, problems
    assert "/RESUME.md" in sample and "/production_queue.jsonl" in sample


def test_every_tracked_file_is_classified():
    t = tree()
    s = ss.served(t)
    unknown = sorted(f for f in t.files if f not in s and not ss.internal_class(f) and f not in ss.NEVER_SERVED)
    assert not unknown, f"tracked files with no SERVED/INTERNAL decision: {unknown}"


def test_pages_defaults_kept_cname_and_dotfiles_unserved():
    for f in (".gitignore", ".gitattributes", "CNAME", "_config.yml", "Gemfile", "node_modules/x.js"):
        assert ss.excluded(f, pats()), f


# --- the matcher must discriminate (a test that cannot fail proves nothing) ---
def test_matcher_semantics():
    assert ss.excluded("lessons/x/notes.md", ["*.md"])            # `*` crosses `/` (fnmatch without flags)
    assert ss.excluded("data/a/b.json", ["data/"])
    assert ss.excluded("tools/capability_inventory/tests/t.py", ["tools/capability_inventory/"])
    assert ss.excluded("tools/tracks/n8n.html", ["tools/"])       # why tools/ cannot be excluded whole
    assert ss.excluded("tools/tracks/n8n.html", ["tools/*"])      # a matching ancestor dir drops its files
    assert not ss.excluded("tools/tracks/n8n.html", ["tools/*.py", "tools/*.js"])
    assert ss.excluded("datafile.html", ["data"])                 # the prefix rule: why patterns end in `/`


@pytest.mark.parametrize("extra,victim", [("tools/", "tools/tracks/n8n.html"), ("*.css", "style.css"),
                                          ("assets/", "assets/og.png"), ("*.woff2", "assets/fonts/fraunces-italic.woff2")])
def test_a_bad_exclude_is_caught(extra, victim):
    p = pats() + [extra]
    assert victim in {f for f in ss.served(tree()) if ss.excluded(f, p)}
    text = (ROOT / ss.CONFIG).read_text(encoding="utf-8") + f'  - "{extra}"\n'
    problems = ss.surface(ss.Tree.worktree(ROOT, {ss.CONFIG: text.encode("utf-8")}))[2]
    assert any(victim in pr for pr in problems), problems
