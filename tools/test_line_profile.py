"""Tests for the stress profile (tools/line_profile.py) and the hopper stress runner (tools/stress/hopper_stress.py).

    py -m pytest tools/test_line_profile.py -q

(a) with B4HIM_LINE_PROFILE unset, every value the profile can supply is today's module constant, byte for byte;
(b) a profile naming the production repo is refused before anything runs;
(c) `release.py --apply --date` is refused without a profile (and with one that does not allow it);
(d) the runner's scratch clone has exactly one remote, and it is the local bare repo;
(e) a 2-tick run with --every 0 publishes both pieces end to end.
"""
import datetime as dt
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import line_profile  # noqa: E402
import production_board as pb  # noqa: E402
import release  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")


def clean_env() -> dict:
    env = {k: v for k, v in os.environ.items() if k != line_profile.ENV}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def runner():
    spec = importlib.util.spec_from_file_location("hopper_stress", HERE / "stress" / "hopper_stress.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def write_profile(path: pathlib.Path, repo, **over) -> pathlib.Path:
    data = {"repo": str(repo), "site": "http://127.0.0.1:9", "cadence_days": [1], "per_week_cap": 1,
            "review_lead_days": 7, "allow_date_apply": True, **over}
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


# ---------------------------------------------------------------- (a) inert by default
PROBE = """
import pathlib, sys
sys.path.insert(0, sys.argv[1])
import production_board as pb, release, approvals, line_profile
home = pathlib.Path(pb.__file__).resolve().parent.parent
print(repr(pb.PROFILE))
print(pb.REPO == home, pb.QUEUE == home / "production_queue.jsonl", pb.BOARD == home / "PRODUCTION_BOARD.md")
print(repr(pb.CADENCE_DAYS), repr(pb.PER_WEEK_CAP), repr(pb.REVIEW_LEAD_DAYS), repr(release.SITE))
print(approvals.repo() == home)
"""


def test_a_with_no_profile_every_value_is_the_module_constant():
    assert os.environ.get(line_profile.ENV) is None and line_profile.load() is None
    for key, sentinel in (("repo", object()), ("site", object()), ("cadence_days", object()),
                          ("per_week_cap", object()), ("review_lead_days", object()),
                          ("allow_date_apply", object()), ("ledger", object())):
        assert line_profile.get(key, sentinel) is sentinel
    # a fresh interpreter with the env removed: what production imports, byte for byte
    p = subprocess.run([sys.executable, "-c", PROBE, str(HERE)], capture_output=True, encoding="utf-8",
                       env=clean_env())
    assert p.returncode == 0, p.stderr
    assert p.stdout.splitlines() == ["None", "True True True", "(1,) 1 7 'https://b4him.com'", "True"]


def test_a_a_profile_supplies_every_value(tmp_path):
    repo = tmp_path / "scratch"
    subprocess.run([GIT, "init", "-q", str(repo)], check=True)
    prof = write_profile(tmp_path / "p.json", repo, cadence_days=[0, 1, 2, 3, 4, 5, 6], per_week_cap=7,
                         review_lead_days=0, ledger=str(tmp_path / "l.jsonl"))
    p = subprocess.run([sys.executable, "-c", PROBE, str(HERE)], capture_output=True, encoding="utf-8",
                       env={**clean_env(), line_profile.ENV: str(prof)})
    assert p.returncode == 0, p.stderr
    lines = p.stdout.splitlines()
    assert lines[1] == "False False False"
    assert lines[2] == "(0, 1, 2, 3, 4, 5, 6) 7 0 'http://127.0.0.1:9'"


# ---------------------------------------------------------------- (b) never the production repo
def test_b_a_profile_naming_the_production_repo_is_refused(tmp_path):
    with pytest.raises(line_profile.ProfileRefused, match="production repo"):
        line_profile.load(write_profile(tmp_path / "home.json", line_profile.HOME))
    common = subprocess.run([GIT, "-C", str(line_profile.HOME), "rev-parse", "--path-format=absolute",
                             "--git-common-dir"], capture_output=True, encoding="utf-8").stdout.strip()
    main_checkout = pathlib.Path(common).parent           # == HOME unless this runs from a worktree
    with pytest.raises(line_profile.ProfileRefused, match="production repo"):
        line_profile.load(write_profile(tmp_path / "main.json", main_checkout))
    # a repo that would push to the production checkout is production too
    other = tmp_path / "other"
    subprocess.run([GIT, "init", "-q", str(other)], check=True)
    subprocess.run([GIT, "-C", str(other), "remote", "add", "origin", str(line_profile.HOME)], check=True)
    with pytest.raises(line_profile.ProfileRefused, match="as a remote"):
        line_profile.load(write_profile(tmp_path / "other.json", other))


def test_b_the_refusal_comes_before_anything_runs(tmp_path):
    prof = write_profile(tmp_path / "home.json", line_profile.HOME)
    log = line_profile.HOME / "release_log.jsonl"
    before = log.read_bytes() if log.exists() else None
    # read-only commands on purpose: if the guard ever broke, this test must not be what writes to production
    for tool in ("release.py", "approvals.py"):
        args = ["--date", "2026-11-17"] if tool == "release.py" else ["status"]
        p = subprocess.run([sys.executable, str(HERE / tool), *args], capture_output=True, encoding="utf-8",
                           env={**clean_env(), line_profile.ENV: str(prof)})
        assert p.returncode == 1 and "REFUSED: line profile" in p.stderr and "Nothing ran" in p.stderr
        assert "Traceback" not in p.stderr
    assert (log.read_bytes() if log.exists() else None) == before


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


# ---------------------------------------------------------------- (d) the scratch clone's only remote
def test_d_the_scratch_clone_has_exactly_one_remote_the_bare_repo(tmp_path):
    hs = runner()
    t = hs.build_scratch(tmp_path / "root")
    clone, bare = t["clone"], t["bare"]
    assert subprocess.run([GIT, "-C", str(clone), "remote"], capture_output=True, encoding="utf-8",
                          check=True).stdout.split() == ["origin"]
    urls = subprocess.run([GIT, "-C", str(clone), "remote", "-v"], capture_output=True, encoding="utf-8",
                          check=True).stdout.splitlines()
    assert len(urls) == 2 and all(pathlib.Path(u.split("\t")[1].rsplit(" ", 1)[0]).resolve() == bare.resolve()
                                  for u in urls)
    refs = subprocess.run([GIT, "-C", str(clone), "for-each-ref", "--format=%(refname)", "refs/remotes"],
                          capture_output=True, encoding="utf-8", check=True).stdout.split()
    assert refs and all(r.startswith("refs/remotes/origin/") for r in refs)
    assert line_profile.production_refusal(clone) is None   # the guard agrees it is not production
    assert (t["live"] / "index.html").exists()              # the hook checked main out


# ---------------------------------------------------------------- (e) end to end
def test_e_a_two_tick_run_publishes_end_to_end(tmp_path):
    root = tmp_path / "stress"
    p = subprocess.run([sys.executable, str(HERE / "stress" / "hopper_stress.py"), "--ticks", "2", "--every", "0",
                        "--root", str(root), "--live-minutes", "1"], capture_output=True, encoding="utf-8",
                       env=clean_env(), timeout=600)
    assert p.returncode == 0, p.stdout + p.stderr
    log = [json.loads(line) for line in (root / "stress_log.jsonl").read_text(encoding="utf-8").splitlines()]
    ticks = [e for e in log if "tick" in e]
    assert [(e["expected"], e["piece"], e["outcome"], e["live_hash_match"]) for e in ticks] == [
        ("STRESS-1", "STRESS-1", "PUBLISHED", True), ("STRESS-2", "STRESS-2", "PUBLISHED", True)]
    assert log[-1]["summary"] == "PASS" and log[-1]["final_live_tree_matches_every_pin"]
    assert not (root / "clone").exists()                  # without --keep the target is removed, the log kept
