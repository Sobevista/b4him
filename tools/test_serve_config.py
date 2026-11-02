"""SITE-PATCH-SERVE-1 (Daniel 2026-10-20, ledger E00761): b4him.com serves the SITE only.

_config.yml's `exclude:` keeps the factory (planning .md, queue, data, boards, tools code and tests) out of the
GitHub Pages build. The matcher and the SERVED/INTERNAL classification live in tools/serve_surface.py (the same logic
approvals.py and release.py use for a site-config patch). This test asserts, on the real repo:
  * every tracked HTML page, and every file a served page or stylesheet references, is NOT excluded;
  * every INTERNAL class IS excluded, today's files and named future ones;
  * tools/tracks/n8n.html is NOT excluded;
  * every tracked file is classified, so a new file forces a decision instead of shipping by default.
_config.yml itself reaches main only through the patch line (it is SITE-PATCH-SERVE-1's one file): until that row
publishes, the tests that read it SKIP and say so; once the row is PUBLISHED, an absent config FAILS (see pats()).
"""
from __future__ import annotations

from pathlib import Path

import pytest

import serve_surface as ss

ROOT = Path(__file__).resolve().parent.parent
FUTURE_INTERNAL = ["OPERATIONS.md", "PUBLICATION_GATE.md", "RESEARCH_2026-12-01.md", "seats/seat-a.md",
                   "seats/roster.json", "release_log.jsonl", "boards/NEW_BOARD.md", "data/new.json",
                   "tools/new_tool.py", "tools/deep/er/test_x.py", "tools/new_audit.js", "tools/run.cmd",
                   "tools/new_rows.json", "tools/deep/er/fixture.json"]


def tree():
    return ss.Tree.worktree(ROOT)


PATCH_ID = "SITE-PATCH-SERVE-1"


def serve_row_stage() -> str | None:
    import json
    for line in (ROOT / "production_queue.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("{"):
            row = json.loads(line)
            if row.get("id") == PATCH_ID:
                return row.get("stage")
    return None


def pats():
    """main's _config.yml. It arrives on main only through the patch line (SITE-PATCH-SERVE-1 publishes it), so before
    that the config tests SKIP, saying why. They FAIL if the row says PUBLISHED, or is gone, and the file is absent:
    an absent config is never read as a pass."""
    cfg = ROOT / ss.CONFIG
    if not cfg.exists():
        stage = serve_row_stage()
        if stage is None or stage == "PUBLISHED":
            pytest.fail(f"{ss.CONFIG} is absent but {PATCH_ID} is "
                        f"{'PUBLISHED' if stage else 'not on the queue'}: the site serves the factory")
        pytest.skip(f"{ss.CONFIG} is not on this tree yet: {PATCH_ID} is {stage} on the patch line "
                    f"(the config tests run on its branch, and here once it publishes)")
    return ss.load_exclude(cfg.read_text(encoding="utf-8"))


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
    pats()                                  # skip (or fail) first if main has no _config.yml yet
    blobs, sample, problems = ss.surface(tree())
    assert not problems, problems
    assert "/RESUME.md" in sample and "/production_queue.jsonl" in sample


def test_every_tracked_file_is_classified():
    t = tree()
    s = ss.served(t)
    unknown = sorted(f for f in t.files if f not in s and not ss.internal_class(f) and f not in ss.NEVER_SERVED
                     and not ss.jekyll_special(f))
    assert not unknown, f"tracked files with no SERVED/INTERNAL decision: {unknown}"


def test_dot_and_underscore_paths_are_never_served():
    """Jekyll never serves a path with a part starting `.` or `_`; served() must not list one (the A4 fixtures)."""
    t = tree()
    s = ss.served(t)
    assert not sorted(f for f in s if ss.jekyll_special(f))
    # the maintenance calendar's A4 fixtures (tools/_maint_fixtures/, a separate branch): pages that are never served
    fake = ss.Tree(["index.html", "_drafts/x.html", "a/.hidden/y.html", "a/_b/z.css",
                    "tools/_maint_fixtures/index.html", "tools/_maint_fixtures/missing-alt/index.html"], lambda rel: b"")
    assert ss.served(fake) == {"index.html"}


#: Files the maintenance calendar (build/golive-maint) adds: two dotfiles, four internal. Classified here so that
#: branch can land before or after this one and every tracked file still has a decision.
MAINT_NEVER_SERVED = (".lighthouserc.json", ".pa11yci")
MAINT_INTERNAL = ("package.json", "package-lock.json", "tools/maint_rows.json", "tools/_maint_fixtures/stand_in_names.json")


def test_the_maintenance_files_are_classified():
    for f in MAINT_NEVER_SERVED:
        assert f in ss.NEVER_SERVED and ss.jekyll_special(f)
    for f in MAINT_INTERNAL:
        assert ss.internal_class(f), f


def test_the_maintenance_files_are_excluded_by_the_config():
    p = pats()
    for f in MAINT_NEVER_SERVED + MAINT_INTERNAL:
        assert ss.excluded(f, p), f
    # the config, not only a leading underscore, keeps tools/ JSON off the site
    assert ss.excluded("tools/maint_rows.json", p)
    assert ss.excluded("tools/maint_rows.json", ["tools/*.json"])
    assert not ss.excluded("tools/tracks/n8n.html", p)


PYTEST_INI = b"[pytest]\npythonpath = tools\n"


def test_the_root_pytest_ini_is_internal_and_not_served():
    """The maintenance calendar (058cb2e) adds a root pytest.ini (the test runner's config). It is factory, not site:
    classified INTERNAL, never in the served set, and (once main holds _config.yml) excluded by it, with the surface
    on this tree plus that file reporting no problem about it. Found 2026-11-02: it would have been served."""
    assert ss.internal_class("pytest.ini"), "pytest.ini has no INTERNAL decision"
    assert "pytest.ini" not in ss.served(ss.Tree(["index.html", "pytest.ini"], lambda rel: b""))
    with_ini = ss.Tree.worktree(ROOT, {"pytest.ini": PYTEST_INI})
    assert "pytest.ini" not in ss.served(with_ini)
    # discriminates: a config that does not name it leaves it served, and the surface says so
    bare = ss.surface(ss.Tree(["index.html", "pytest.ini"], lambda rel: b"",
                              {ss.CONFIG: b"exclude:\n  - \"*.md\"\n"}))[2]
    assert any("pytest.ini" in pr for pr in bare), bare
    if (ROOT / ss.CONFIG).exists():
        assert ss.excluded("pytest.ini", pats()), "_config.yml leaves pytest.ini served"
        assert not [pr for pr in ss.surface(with_ini)[2] if "pytest.ini" in pr]


def test_no_json_is_served():
    """No served page uses a .json; tools/maint_rows.json names the owner, so no JSON may be in the served set."""
    s = ss.served(tree())
    assert not [f for f in s if f.endswith(".json")]


def test_pages_defaults_kept_cname_and_dotfiles_unserved():
    for f in (".gitignore", ".gitattributes", "CNAME", "_config.yml", "Gemfile", "node_modules/x.js"):
        assert ss.excluded(f, pats()), f


@pytest.mark.parametrize("stage,outcome", [("DRAFTED", "skip"), ("PREVIEWED", "skip"), ("PUBLISHED", "fail"),
                                           (None, "fail")])
def test_an_absent_config_never_reads_as_a_pass(tmp_path, monkeypatch, stage, outcome):
    rows = [] if stage is None else [{"id": PATCH_ID, "stage": stage}]
    import json
    (tmp_path / "production_queue.jsonl").write_text("# q\n" + "".join(json.dumps(r) + "\n" for r in rows),
                                                     encoding="utf-8")
    monkeypatch.setitem(globals(), "ROOT", tmp_path)
    exc = pytest.skip.Exception if outcome == "skip" else pytest.fail.Exception
    with pytest.raises(exc):
        pats()


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
