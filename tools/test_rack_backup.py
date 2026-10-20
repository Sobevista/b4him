"""Tests for rack_backup.py against a scratch repo, a scratch bare "origin", and a temp destination. No network.

    py -m pytest tools/test_rack_backup.py -q
"""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rack_backup  # noqa: E402

GIT_ENV_ARGS = ["-c", "user.name=rack-test", "-c", "user.email=rack@test.invalid",
                "-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false", "-c", "init.defaultBranch=main"]


def g(cwd, *args):
    p = subprocess.run(["git", *GIT_ENV_ARGS, *args], cwd=str(cwd), capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    return p.stdout.strip()


def commit(repo, name):
    (repo / name).write_text(name, encoding="utf-8")
    g(repo, "add", name)
    g(repo, "commit", "-q", "-m", name)
    return g(repo, "rev-parse", "HEAD")


@pytest.fixture
def scratch(tmp_path):
    """A repo with approved/* tags (lightweight + annotated, on different commits), decoy tags, and a bare origin
    that holds main and a decoy tag but no approved tag."""
    origin = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", str(origin))
    repo = tmp_path / "repo"
    g(tmp_path, "init", "-q", str(repo))
    c1 = commit(repo, "one.txt")
    g(repo, "tag", "approved/A", c1)
    c2 = commit(repo, "two.txt")
    g(repo, "tag", "-a", "approved/B", "-m", "annotated", c2)
    g(repo, "tag", "approved/GC-GLOSS-1-R1", c2)
    c3 = commit(repo, "three.txt")
    g(repo, "tag", "v1", c3)                        # decoys: must NOT be in the bundle
    g(repo, "tag", "notapproved/X", c3)
    g(repo, "tag", "approvedish", c3)
    g(repo, "remote", "add", "origin", str(origin))
    g(repo, "push", "-q", "origin", "main", "refs/tags/v1")   # scaffolding only: the tool itself never pushes
    dest = tmp_path / "dest"
    dest.mkdir()
    return {"repo": repo, "origin": origin, "dest": dest, "log": tmp_path / "rack.log", "root": tmp_path,
            "commits": {"approved/A": c1, "approved/B": c2, "approved/GC-GLOSS-1-R1": c2}}


def run(s, *extra, env=None, find_drive=lambda: None):
    return rack_backup.run(["--repo", str(s["repo"]), "--log", str(s["log"]), *extra],
                           env={} if env is None else env, find_drive=find_drive)


def bundles(dest):
    return sorted(p for p in dest.iterdir() if p.suffix == ".bundle")


def peeled(repo, ref):
    return g(repo, "rev-parse", ref + "^{commit}")


# ---------------------------------------------------------------- the bundle

def test_bundle_holds_exactly_the_approved_tags(scratch):
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    [b] = bundles(scratch["dest"])
    heads = rack_backup.bundle_heads(b, scratch["repo"])
    assert heads == rack_backup.approved_tags(scratch["repo"])
    assert sorted(heads) == ["refs/tags/approved/A", "refs/tags/approved/B", "refs/tags/approved/GC-GLOSS-1-R1"]


def test_sha256_sidecar_matches_bundle_bytes_and_log(scratch):
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    [b] = bundles(scratch["dest"])
    digest = hashlib.sha256(b.read_bytes()).hexdigest()
    assert b.with_suffix(".sha256").read_text(encoding="utf-8") == f"{digest}  {b.name}\n"
    [line] = scratch["log"].read_text(encoding="utf-8").splitlines()
    entry = json.loads(line)
    assert entry["sha256"] == digest and entry["tag_count"] == 3 and entry["outcome"] == "OK"
    assert entry["dest"] == str(scratch["dest"]) and entry["origin_check"] == "clean" and entry["date"]


# ---------------------------------------------------------------- destination: UNKNOWN never rounds to OK

def test_missing_dest_everywhere_is_exit_2_and_writes_nothing(scratch, capsys):
    assert run(scratch) == 2
    assert "no destination" in capsys.readouterr().err
    assert json.loads(scratch["log"].read_text(encoding="utf-8"))["outcome"] == "FAIL"


def test_named_dest_that_does_not_exist_is_exit_2_and_no_fallthrough(scratch):
    missing = scratch["root"] / "nope"
    drive = scratch["root"] / "My Drive"
    drive.mkdir()
    assert run(scratch, "--dest", str(missing), find_drive=lambda: drive) == 2
    assert run(scratch, env={"B4HIM_RACK_DEST": str(missing)}, find_drive=lambda: drive) == 2
    assert not missing.exists() and list(drive.iterdir()) == []


def test_dest_order_cli_then_env_then_drive(scratch):
    envd = scratch["root"] / "envd"
    envd.mkdir()
    drive = scratch["root"] / "My Drive"
    drive.mkdir()
    assert run(scratch, "--dest", str(scratch["dest"]), env={"B4HIM_RACK_DEST": str(envd)},
               find_drive=lambda: drive) == 0
    assert len(bundles(scratch["dest"])) == 1 and not bundles(envd)
    assert run(scratch, env={"B4HIM_RACK_DEST": str(envd)}, find_drive=lambda: drive) == 0
    assert len(bundles(envd)) == 1
    assert run(scratch, find_drive=lambda: drive) == 0
    assert len(bundles(drive / "b4him-rack")) == 1


def test_no_approved_tags_is_exit_2(scratch, tmp_path):
    empty = tmp_path / "empty"
    g(tmp_path, "init", "-q", str(empty))
    commit(empty, "x.txt")
    assert rack_backup.run(["--repo", str(empty), "--log", str(scratch["log"]), "--dest", str(scratch["dest"])],
                           env={}, find_drive=lambda: None) == 2
    assert list(scratch["dest"].iterdir()) == []


# ---------------------------------------------------------------- never pushes

def test_never_invokes_push(scratch, monkeypatch):
    calls = []
    real = subprocess.run

    def spy(cmd, *a, **k):
        calls.append([str(x) for x in cmd])
        return real(cmd, *a, **k)

    monkeypatch.setattr(rack_backup.subprocess, "run", spy)
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    bundle = bundles(scratch["dest"])[0]
    assert rack_backup.run(["--restore-check", str(bundle)], env={}) == 0
    assert calls and all(c[0] == "git" for c in calls)
    assert not any(tok.lower() == "push" or tok.lower().startswith("--push") for c in calls for tok in c)
    assert any(c[1:3] == ["ls-remote", "--tags"] for c in calls)


def test_git_door_refuses_push_without_running(monkeypatch):
    monkeypatch.setattr(rack_backup.subprocess, "run", lambda *a, **k: pytest.fail("git ran"))
    assert "push" not in rack_backup.ALLOWED_GIT
    for args in (["push", "origin", "refs/tags/approved/A"], ["-c", "remote.origin.pushurl=x", "status"],
                 ["fetch", "-c", "x=y"], ["send-pack", "origin"], []):
        with pytest.raises(rack_backup.RackError, match="never pushes"):
            rack_backup._git(args, ".")


def test_origin_untouched_and_leak_is_loud_exit_3(scratch, capsys):
    before = g(scratch["origin"], "for-each-ref")
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    assert g(scratch["origin"], "for-each-ref") == before
    g(scratch["repo"], "push", "-q", "origin", "refs/tags/approved/B")  # simulate a leak (test scaffolding)
    assert run(scratch, "--dest", str(scratch["dest"])) == 3
    err = capsys.readouterr().err
    assert "LEAK" in err and "refs/tags/approved/B" in err
    assert json.loads(scratch["log"].read_text(encoding="utf-8").splitlines()[-1])["outcome"] == "LEAK"
    assert len(bundles(scratch["dest"])) == 2   # the backup itself still landed


def test_origin_unreachable_is_unknown_exit_4_not_ok(scratch):
    g(scratch["repo"], "remote", "set-url", "origin", str(scratch["root"] / "gone.git"))
    assert run(scratch, "--dest", str(scratch["dest"])) == 4
    entry = json.loads(scratch["log"].read_text(encoding="utf-8"))
    assert entry["outcome"] == "ORIGIN-UNKNOWN" and entry["origin_check"] == "unknown"


# ---------------------------------------------------------------- retention

def test_retention_keeps_newest_n_and_leaves_foreign_files(scratch, monkeypatch):
    stamps = iter(f"20261020T0800{i:02d}000000Z" for i in range(6))
    monkeypatch.setattr(rack_backup, "stamp", lambda: next(stamps))
    foreign = scratch["dest"] / "notes.txt"
    foreign.write_text("Daniel's", encoding="utf-8")
    for _ in range(6):
        assert run(scratch, "--dest", str(scratch["dest"]), "--keep", "3") == 0
    kept = [p.name for p in bundles(scratch["dest"])]
    assert kept == [f"b4him-approved-20261020T0800{i:02d}000000Z.bundle" for i in (3, 4, 5)]
    assert sorted(p.name for p in scratch["dest"].glob("*.sha256")) == [k[:-7] + ".sha256" for k in kept]
    assert foreign.exists()


def test_default_keep_is_8(scratch, monkeypatch):
    stamps = iter(f"20261020T0900{i:02d}000000Z" for i in range(10))
    monkeypatch.setattr(rack_backup, "stamp", lambda: next(stamps))
    for _ in range(10):
        assert run(scratch, "--dest", str(scratch["dest"])) == 0
    assert len(bundles(scratch["dest"])) == 8


# ---------------------------------------------------------------- restore drill

def test_restore_check_round_trip_restores_every_tag_at_the_same_commit(scratch, tmp_path, capsys):
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    [b] = bundles(scratch["dest"])
    capsys.readouterr()
    assert rack_backup.run(["--restore-check", str(b)], env={}) == 0
    out = capsys.readouterr().out
    assert "RESTORE-CHECK OK" in out and "3 tags" in out
    fresh = tmp_path / "fresh"
    g(tmp_path, "init", "-q", str(fresh))
    g(fresh, "fetch", "-q", str(b), "refs/tags/*:refs/tags/*")
    assert rack_backup.approved_tags(fresh) == rack_backup.approved_tags(scratch["repo"])
    for ref, c in scratch["commits"].items():
        assert peeled(fresh, ref) == c
    assert g(fresh, "cat-file", "-t", "refs/tags/approved/B") == "tag"   # annotated tag survives as a tag object


def test_restore_check_catches_tampering(scratch, capsys):
    assert run(scratch, "--dest", str(scratch["dest"])) == 0
    [b] = bundles(scratch["dest"])
    b.write_bytes(b.read_bytes() + b"x")
    assert rack_backup.run(["--restore-check", str(b)], env={}) == 2
    assert "MISMATCH" in capsys.readouterr().err
    b.with_suffix(".sha256").unlink()
    assert rack_backup.run(["--restore-check", str(b)], env={}) == 2
