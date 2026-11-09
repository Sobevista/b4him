"""Tests for the stress profile (tools/line_profile.py) and the hopper stress runner (tools/stress/hopper_stress.py).

    py -m pytest tools/test_line_profile.py -q

(a) with B4HIM_LINE_PROFILE unset, every value the profile can supply is today's module constant, byte for byte;
(b) a profile naming production, by any path spelling or any remote spelling, is refused before anything runs;
(c) `release.py --apply --date` is refused without a profile (and with one that does not allow it);
(d) the runner's scratch clone has exactly one remote, the local bare repo, and only main (deep --root included);
(e) a 2-tick run with --every 0 publishes both pieces end to end;
plus the review of 2026-11-09: the production oracle sees ignored files (M2), serve_surface follows the profile and a
failed patch fails a tick (M3), the HTTP oracle (L1), and a non-empty --root is refused (L6).
"""
import ctypes
import datetime as dt
import functools
import http.server
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import line_profile  # noqa: E402
import production_board as pb  # noqa: E402
import release  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")
WINDOWS = sys.platform == "win32"


def g(root, *args, check=True):
    return subprocess.run([GIT, "-C", str(root), *args], capture_output=True, encoding="utf-8", check=check).stdout


def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != line_profile.ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def runner():
    spec = importlib.util.spec_from_file_location("hopper_stress", HERE / "stress" / "hopper_stress.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def new_repo(path: pathlib.Path, *config) -> pathlib.Path:
    subprocess.run([GIT, "init", "-q", "-b", "main", str(path)], check=True)
    for k, v in config:
        g(path, "config", k, v)
    return path


def write_profile(path: pathlib.Path, repo, **over) -> pathlib.Path:
    data = {"repo": str(repo), "site": "http://127.0.0.1:9", "cadence_days": [1], "per_week_cap": 1,
            "review_lead_days": 7, "allow_date_apply": True, **over}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def long_root(tmp_path: pathlib.Path) -> pathlib.Path:
    """A --root of at least 180 characters (review M1: a deep root once broke the scratch clone)."""
    root = tmp_path / ("r" * max(8, 185 - len(str(tmp_path))))
    assert len(str(root)) >= 180
    return root


# ---------------------------------------------------------------- (a) inert by default
PROBE = """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import production_board as pb, release, approvals, line_profile, serve_surface
home = pathlib.Path(pb.__file__).resolve().parent.parent
print(repr(pb.PROFILE))
print(pb.REPO == home, pb.QUEUE == home / "production_queue.jsonl", pb.BOARD == home / "PRODUCTION_BOARD.md")
print(repr(pb.CADENCE_DAYS), repr(pb.PER_WEEK_CAP), repr(pb.REVIEW_LEAD_DAYS), repr(release.SITE))
print(approvals.repo() == home)
print(repr(serve_surface.LIVE), repr(serve_surface.SITE))
"""


def probe(env) -> list[str]:
    p = subprocess.run([sys.executable, "-c", PROBE, str(HERE)], capture_output=True, encoding="utf-8", env=env)
    assert p.returncode == 0, p.stderr
    return p.stdout.splitlines()


def test_a_with_no_profile_every_value_is_the_module_constant():
    assert os.environ.get(line_profile.ENV) is None and line_profile.load() is None
    for key, sentinel in (("repo", object()), ("site", object()), ("cadence_days", object()),
                          ("per_week_cap", object()), ("review_lead_days", object()),
                          ("allow_date_apply", object()), ("ledger", object())):
        assert line_profile.get(key, sentinel) is sentinel
    # a fresh interpreter with the env removed: what production imports, byte for byte
    assert probe(clean_env()) == ["None", "True True True", "(1,) 1 7 'https://b4him.com'", "True",
                                  "'https://b4him.com' 'https://b4him.com'"]


def test_a_a_profile_supplies_every_value_and_points_the_live_checks_at_its_site(tmp_path):
    repo = new_repo(tmp_path / "scratch")
    prof = write_profile(tmp_path / "p.json", repo, cadence_days=[0, 1, 2, 3, 4, 5, 6], per_week_cap=7,
                         review_lead_days=0, ledger=str(tmp_path / "l.jsonl"))
    lines = probe({**clean_env(), line_profile.ENV: str(prof)})
    assert lines[1] == "False False False"
    assert lines[2] == "(0, 1, 2, 3, 4, 5, 6) 7 0 'http://127.0.0.1:9'"
    # M3: a site-config patch's live check polls the profile's site, never b4him.com; absolute links keep their name
    assert lines[4] == "'http://127.0.0.1:9' 'https://b4him.com'"


# ---------------------------------------------------------------- (b) never production: paths
def refused(repo, match="production repo"):
    why = line_profile.production_refusal(pathlib.Path(repo))
    assert why and match in why, why
    fd, name = tempfile.mkstemp(suffix=".json")             # and load() refuses it the same way
    os.close(fd)
    try:
        with pytest.raises(line_profile.ProfileRefused):
            line_profile.load(write_profile(pathlib.Path(name), repo))
    finally:
        os.unlink(name)


def test_b_a_profile_naming_the_production_repo_is_refused(tmp_path):
    with pytest.raises(line_profile.ProfileRefused, match="production repo"):
        line_profile.load(write_profile(tmp_path / "home.json", line_profile.HOME))
    common = g(line_profile.HOME, "rev-parse", "--path-format=absolute", "--git-common-dir").strip()
    with pytest.raises(line_profile.ProfileRefused, match="production repo"):
        line_profile.load(write_profile(tmp_path / "main.json", pathlib.Path(common).parent))


def test_b_the_main_checkout_behind_a_worktree_is_found_by_its_git_directory(tmp_path, monkeypatch):
    """line_profile.py's common-dir branch: a worktree of production shares its git directory, so its pushes go to
    production's origin. Proved on a scratch 'production' so nothing real is touched."""
    prod = new_repo(tmp_path / "prod", ("user.name", "t"), ("user.email", "t@example.invalid"))
    g(prod, "commit", "-q", "--allow-empty", "-m", "base")
    g(prod, "worktree", "add", "-q", str(tmp_path / "wt"), "-b", "wt")
    monkeypatch.setattr(line_profile, "HOME", prod)
    refused(tmp_path / "wt", match="shares the production repo's git directory")


@pytest.mark.skipif(not line_profile.PRODUCTION_PATH.is_dir(), reason="no production checkout on this machine")
def test_b_production_is_refused_even_when_this_code_runs_from_a_plain_clone(tmp_path, monkeypatch):
    monkeypatch.setattr(line_profile, "HOME", new_repo(tmp_path / "plain-clone"))
    refused(line_profile.PRODUCTION_PATH)
    trees = [l[len("worktree "):] for l in g(line_profile.PRODUCTION_PATH, "worktree", "list", "--porcelain")
             .splitlines() if l.startswith("worktree ")]
    siblings = [t for t in trees if line_profile._key(t) != line_profile._key(line_profile.PRODUCTION_PATH)
                and pathlib.Path(t).is_dir()]
    if siblings:                                         # a sibling worktree pushes to production's origin too
        refused(siblings[0], match="production repo")


@pytest.mark.skipif(not WINDOWS, reason="junctions are a Windows feature")
def test_b_a_junction_to_production_is_production(tmp_path):
    j = tmp_path / "j"
    made = subprocess.run(["cmd", "/c", "mklink", "/J", str(j), str(line_profile.HOME)], capture_output=True)
    if made.returncode:
        pytest.skip(f"could not create a junction without elevation: {made.stderr!r}")
    try:
        refused(j)
    finally:
        os.rmdir(j)                                      # removes the link only, never the target


@pytest.mark.skipif(not WINDOWS, reason="UNC admin shares and \\\\?\\ paths are Windows spellings")
def test_b_unc_long_and_short_spellings_of_production_are_production():
    home = str(line_profile.HOME)
    refused("\\\\?\\" + home)
    unc = f"\\\\localhost\\{home[0]}$\\{home[3:]}"
    if os.path.isdir(unc):
        refused(unc)
    buf = ctypes.create_unicode_buffer(1024)
    short = buf.value if ctypes.windll.kernel32.GetShortPathNameW(home, buf, 1024) else home
    if short.lower() != home.lower():
        refused(short)
    if not os.path.isdir(unc) and short.lower() == home.lower():
        pytest.skip("the admin share is not reachable and 8.3 names are off on this volume; \\\\?\\ was checked")


# ---------------------------------------------------------------- (b) never production: remotes
SPELLINGS = {
    "no .git": [("remote.origin.url", "https://github.com/Sobevista/b4him")],
    "case": [("remote.origin.url", "https://github.com/sobevista/B4HIM.git")],
    "trailing slash": [("remote.origin.url", "https://github.com/Sobevista/b4him.git/")],
    "scp ssh": [("remote.origin.url", "git@github.com:Sobevista/b4him.git")],
    "ssh url": [("remote.origin.url", "ssh://git@github.com:22/Sobevista/b4him.git")],
    "pushurl": [("remote.origin.url", "https://example.invalid/harmless.git"),
                ("remote.origin.pushurl", "https://github.com/Sobevista/b4him.git")],
    "insteadOf": [("url.https://github.com/Sobevista/.insteadOf", "prod:"), ("remote.origin.url", "prod:b4him")],
    "pushInsteadOf": [("url.git@github.com:Sobevista/.pushInsteadOf", "safe:"), ("remote.origin.url", "safe:b4him")],
    "second remote": [("remote.origin.url", "https://example.invalid/harmless.git"),
                      ("remote.backup.url", "https://GitHub.com/Sobevista/b4him")],
}


@pytest.mark.parametrize("spelling", sorted(SPELLINGS))
def test_b_every_spelling_of_production_s_remote_is_refused(tmp_path, spelling):
    refused(new_repo(tmp_path / "r", *SPELLINGS[spelling]), match="production's remote")


def test_b_a_local_path_remote_to_production_is_refused(tmp_path):
    refused(new_repo(tmp_path / "r", ("remote.origin.url", str(line_profile.HOME))), match="as a remote")


def test_b_another_repo_on_the_same_host_is_not_production(tmp_path):
    """Phase 2's throwaway Pages repo must stay usable: a name that only starts like production is not production."""
    repo = new_repo(tmp_path / "r", ("remote.origin.url", "https://github.com/Sobevista/b4him-stress.git"))
    assert line_profile.production_refusal(repo) is None


def test_b_the_refusal_comes_before_anything_runs(tmp_path):
    """A scratch repo that is NOT production but can push to it: under a working bypass this apply would write
    release_log.jsonl and release_alarm.md into the scratch repo. The refusal must come first, so neither exists."""
    repo = new_repo(tmp_path / "r", ("remote.origin.url", "https://github.com/Sobevista/b4him.git"))
    prof = write_profile(tmp_path / "p.json", repo)
    later = (dt.date.today() + dt.timedelta(days=8)).isoformat()
    for args in ((HERE / "release.py", "--apply", "--date", later), (HERE / "approvals.py", "apply")):
        p = subprocess.run([sys.executable, *map(str, args)], capture_output=True, encoding="utf-8",
                           env={**clean_env(), line_profile.ENV: str(prof)})
        assert p.returncode == 1 and "REFUSED: line profile" in p.stderr and "Nothing ran" in p.stderr, p
        assert "Traceback" not in p.stderr
    assert not (repo / "release_log.jsonl").exists() and not (repo / "release_alarm.md").exists()


# ---------------------------------------------------------------- (c) a dated apply needs a profile
def test_c_apply_with_a_date_is_refused_without_a_profile(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(pb, "REPO", tmp_path)              # if anything ran, its log line would land here
    later = dt.date.today() + dt.timedelta(days=8)
    assert pb.PROFILE is None
    assert release.main(["--apply", "--push", "--verify-live", "--date", later.isoformat()]) == 1
    assert "REFUSED: --apply publishes today" in capsys.readouterr().out
    assert not (tmp_path / "release_log.jsonl").exists()
    # a profile that does not allow it refuses the same way
    prof = line_profile.Profile(path=tmp_path / "p.json", repo=tmp_path, site="http://127.0.0.1:9",
                                cadence_days=(1,), per_week_cap=1, review_lead_days=7, allow_date_apply=False,
                                ledger=None)
    monkeypatch.setattr(pb, "PROFILE", prof)
    assert release.main(["--apply", "--date", later.isoformat()]) == 1
    assert "REFUSED: --apply publishes today" in capsys.readouterr().out
    assert not (tmp_path / "release_log.jsonl").exists()


# ---------------------------------------------------------------- (d) the scratch clone
def test_d_the_scratch_clone_has_exactly_one_remote_the_bare_repo_and_only_main(tmp_path):
    hs = runner()
    t = hs.build_scratch(long_root(tmp_path))
    clone, bare = t["clone"], t["bare"]
    assert g(clone, "remote").split() == ["origin"]
    urls = g(clone, "remote", "-v").splitlines()
    assert len(urls) == 2 and all(pathlib.Path(u.split("\t")[1].rsplit(" ", 1)[0]).resolve() == bare.resolve()
                                  for u in urls)
    assert g(clone, "for-each-ref", "--format=%(refname)", "refs/heads").split() == ["refs/heads/main"]
    assert g(clone, "for-each-ref", "--format=%(refname)", "refs/tags").split() == []
    refs = g(clone, "for-each-ref", "--format=%(refname)", "refs/remotes").split()
    assert refs and all(r.startswith("refs/remotes/origin/") for r in refs)
    assert g(bare, "remote").split() == []                  # the bare repo points nowhere
    assert line_profile.production_refusal(clone) is None   # the guard agrees it is not production
    assert (t["live"] / "index.html").exists()


# ---------------------------------------------------------------- (e) end to end
def test_e_a_two_tick_run_publishes_end_to_end_from_a_deep_root(tmp_path):
    root = long_root(tmp_path)
    p = subprocess.run([sys.executable, str(HERE / "stress" / "hopper_stress.py"), "--ticks", "2", "--every", "0",
                        "--root", str(root), "--live-minutes", "1"], capture_output=True, encoding="utf-8",
                       env=clean_env(), timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    log = [json.loads(line) for line in (root / "stress_log.jsonl").read_text(encoding="utf-8").splitlines()]
    ticks = [e for e in log if "tick" in e]
    assert [(e["expected"], e["piece"], e["outcome"], e["live_hash_match"], e["http_match"]) for e in ticks] == [
        ("STRESS-1", "STRESS-1", "PUBLISHED", True, True), ("STRESS-2", "STRESS-2", "PUBLISHED", True, True)]
    assert log[-1]["summary"] == "PASS" and log[-1]["final_live_tree_matches_every_pin"]
    assert all(dt.datetime.fromisoformat(e["at"]) for e in log)
    assert not (root / "clone").exists()                  # without --keep the target is removed, the log kept


# ---------------------------------------------------------------- review 2026-11-09
def test_m2_the_production_oracle_sees_git_ignored_logs(tmp_path, monkeypatch):
    prod = new_repo(tmp_path / "prod")
    (prod / ".gitignore").write_text("release_log.jsonl\nrelease_alarm.md\n", encoding="utf-8")
    (prod / "release_log.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    monkeypatch.setattr(line_profile, "HOME", prod)
    monkeypatch.setattr(line_profile, "PRODUCTION_PATH", prod)
    hs = runner()
    before = hs.production_state()
    assert before == hs.production_state()
    with (prod / "release_log.jsonl").open("a", encoding="utf-8") as fh:   # status --ignored cannot see this
        fh.write('{"leak": true}\n')
    assert hs.production_state() != before
    (prod / "release_log.jsonl").write_text('{"a": 1}\n', encoding="utf-8")
    assert hs.production_state() == before
    (prod / "release_alarm.md").write_text("x", encoding="utf-8")            # absent -> present
    assert hs.production_state() != before


def test_m3_a_failed_patch_fails_the_tick():
    hs = runner()
    ok = {"outcome": "PUBLISHED", "piece": "S-1"}
    assert hs.judge(ok, "S-1", [], []) is None
    why = hs.judge({**ok, "patch_outcomes": [{"piece": "P-1", "outcome": "FAIL", "why": "drift"}]}, "S-1", [], [])
    assert why and "patch P-1 FAIL" in why
    assert hs.judge({**ok, "patch_outcomes": [{"piece": "P-1", "outcome": "PUBLISHED"}]}, "S-1", [], []) is None


def test_l1_the_http_oracle_compares_served_bytes_to_the_drafted_page_and_the_stage2_blob(tmp_path):
    hs = runner()
    page = "lessons/stress-1/index.html"
    (tmp_path / "lessons" / "stress-1").mkdir(parents=True)
    good = hs.page_html(1).encode("utf-8")
    (tmp_path / page).write_bytes(good)
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    site = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        blob = hs.blob_sha(tmp_path / page)
        assert hs.http_problems(site, 1, page, blob) == []
        (tmp_path / page).write_bytes(good.replace(b"Stress Piece 1", b"Stress Piece X"))
        bad = hs.http_problems(site, 1, page, blob)
        assert any("not the drafted page" in b for b in bad) and any("stage-2 blob" in b for b in bad)
    finally:
        srv.shutdown()


def test_l6_a_root_that_is_not_empty_is_refused(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    (root / "keep.txt").write_text("mine", encoding="utf-8")
    p = subprocess.run([sys.executable, str(HERE / "stress" / "hopper_stress.py"), "--ticks", "1", "--every", "0",
                        "--root", str(root), "--live-minutes", "1"], capture_output=True, encoding="utf-8",
                       env=clean_env(), timeout=600)
    assert p.returncode == 2 and "not an empty directory" in p.stderr, p.stdout + p.stderr
    assert sorted(x.name for x in root.iterdir()) == ["keep.txt"]


def test_l5_the_daily_job_clears_any_profile_before_it_runs_anything():
    lines = [l.strip() for l in (HERE / "daily.cmd").read_text(encoding="utf-8").splitlines()]
    cmds = [l for l in lines if l and not l.lower().startswith(("rem", "@echo"))]
    assert cmds[0] == 'set "B4HIM_LINE_PROFILE="'
