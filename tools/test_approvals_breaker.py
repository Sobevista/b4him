"""Independent breaker for build approvals-refusal-safe-v2 (b4him tools/approvals.py).

The property under attack: a refused or failed apply() restores exactly what approvals itself wrote in that
attempt and nothing else; every other uncommitted change in the tree (tracked edits, staged changes, untracked and
ignored files, tags) survives byte-identical; the ruling stays OWED.

    P1  test_break_foreign_*   a-refusal-never-touches-work-that-is-not-its-own
    P2  test_break_own_*       a-refusal-undoes-its-own-partial-work

Every attack drives the real consuming path, approvals.apply(today=..., led=...), against a throwaway git repo built
in tmp_path (the `site` fixture pattern from tools/test_approvals.py, copied so a second piece and a root with a
space in its path can be built). Nothing here touches a real repository.

    py -m pytest tools/test_approvals_breaker.py -q -p no:cacheprovider
"""
import json
import pathlib
import shutil
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import approvals  # noqa: E402
import production_board as pb  # noqa: E402
from test_approvals import MON, PAGE, PROOF, FakeLedger, g  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")
PAGE3 = "lessons/g3/index.html"
OWN = ("production_queue.jsonl", "boards/APPROVALS_OWED.md", "PRODUCTION_BOARD.md")


# ---------------------------------------------------------------- the arena
def build_site(root, monkeypatch, second_piece=False):
    """tools/test_approvals.py::site, with an optional second piece G3 on draft/g3 and any root path."""
    (root / "tools" / "tracks").mkdir(parents=True)
    shutil.copy(HERE / "tracks" / "n8n.html", root / "tools" / "tracks" / "n8n.html")
    (root / "lessons").mkdir()
    (root / "lessons" / "index.html").write_text(
        "<nav></nav>\n\n<!-- b4him:track n8n (generated) -->\n<!-- /b4him:track n8n -->\n", encoding="utf-8")
    (root / ".gitignore").write_text("release_log.jsonl\n__pycache__/\n", encoding="utf-8")
    base2 = {"id": "G2", "order": 2, "title": "Glossary II", "stage": "SOURCE", "track": "n8n"}
    base3 = {"id": "G3", "order": 3, "title": "Glossary III", "stage": "SOURCE", "track": "n8n"}
    rows = [base2] + ([base3] if second_piece else [])

    def write_queue(*rs):
        (root / "production_queue.jsonl").write_text("# q\n" + "".join(json.dumps(r) + "\n" for r in rs),
                                                     encoding="utf-8", newline="\n")
    write_queue(*rows)
    g(root.parent, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t"), ("core.autocrlf", "false")):
        g(root, "config", k, v)
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", "base")

    def draft(base, page, branch, numeral):
        g(root, "checkout", "-q", "-b", branch)
        (root / page).parent.mkdir()
        (root / page).write_text(f"<h1>{base['title']}</h1>\n", encoding="utf-8", newline="\n")
        drafted = dict(base, stage="DRAFTED", page=page, branch=branch,
                       reviewed={"date": "2026-10-12", "by": "other seat", "verdict": "PASS", "proof": "fixture",
                                 "blobs": {page: pb.blob_sha(root / page)}},
                       index_entry={"track": "n8n", "numeral": numeral, "href": f"/lessons/{base['id'].lower()}/",
                                    "title": base["title"], "blurb": "More words."})
        write_queue(*[drafted if r["id"] == base["id"] else r for r in rows])
        g(root, "add", "-A")
        g(root, "commit", "-q", "-m", f"draft {base['id']}")
        g(root, "checkout", "-q", "main")
    draft(base2, PAGE, "draft/g2", "II")
    if second_piece:
        draft(base3, PAGE3, "draft/g3", "III")
    monkeypatch.setattr(pb, "REPO", root)
    monkeypatch.setattr(pb, "QUEUE", root / "production_queue.jsonl")
    monkeypatch.setattr(pb, "BOARD", root / "PRODUCTION_BOARD.md")
    return root


@pytest.fixture
def site(tmp_path, monkeypatch):
    return build_site(tmp_path / "site", monkeypatch)


@pytest.fixture
def site2(tmp_path, monkeypatch):
    return build_site(tmp_path / "site", monkeypatch, second_piece=True)


def state(root, flags=True):
    """Everything the property promises to leave alone: every file's bytes (ignored ones included), the index, the
    staged diff, status, HEAD, the branch, and every tag with its target."""
    files = {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*")
             if p.is_file() and ".git" not in p.relative_to(root).parts}
    out = {"files": files,
           "index": g(root, "ls-files", "-s"),
           "staged": g(root, "diff", "--cached"),
           "status": g(root, "status", "--porcelain", "--ignored"),
           "head": g(root, "rev-parse", "HEAD"),
           "branch": g(root, "rev-parse", "--abbrev-ref", "HEAD"),
           "tags": g(root, "for-each-ref", "refs/tags")}
    if flags:
        out["flags"] = g(root, "ls-files", "-v")
    return out


def tag_target(root, name):
    import subprocess
    p = subprocess.run([GIT, "-C", str(root), "rev-parse", "-q", "--verify", f"refs/tags/{name}"],
                       capture_output=True, encoding="utf-8")
    return p.stdout.strip() if p.returncode == 0 else None


def after_status_check(monkeypatch, fn, nth=1):
    """Run fn() right after approvals' nth clean-tree check passes: work landing in the checkout mid-apply."""
    real, seen = approvals.git, [0]

    def spy(*args, **kw):
        out = real(*args, **kw)
        if args[:2] == ("status", "--porcelain"):
            seen[0] += 1
            if seen[0] == nth:
                fn()
        return out
    monkeypatch.setattr(approvals, "git", spy)


def fail_git(monkeypatch, subcommand, exc):
    """Make approvals' own `git <subcommand>` fail with exc (an ApprovalError is what a failing git call raises)."""
    real = approvals.git

    def spy(*args, **kw):
        if args and args[0] == subcommand:
            raise exc(f"injected failure of git {subcommand}")
        return real(*args, **kw)
    monkeypatch.setattr(approvals, "git", spy)


def boom_build(monkeypatch, exc, on_call=1):
    """pb.build raises exc on its on_call-th call: by then approvals has written the queue and the board (and, for an
    APPROVE, moved the tag), and has not yet written PRODUCTION_BOARD.md, staged or committed."""
    real, n = pb.build, [0]

    def fake(today):
        n[0] += 1
        if n[0] == on_call:
            raise exc("injected")
        return real(today)
    monkeypatch.setattr(pb, "build", fake)


def refuse_commits(root):
    """A pre-commit hook that refuses every commit: approvals' `git commit` fails after `git add` staged its files."""
    hook = root / ".git" / "hooks" / "pre-commit"
    hook.parent.mkdir(exist_ok=True)
    hook.write_bytes(b"#!/bin/sh\necho 'refused by hook' >&2\nexit 1\n")


def owed_refusal(led, n_owed=1):
    report = approvals.apply(today=MON, led=led)
    assert report and all(l.startswith("OWED") for l in report), report
    assert len(led.rulings_owed()) == n_owed
    return report


# ================================================================ P1: a refusal never touches work that is not its own
def test_break_foreign_staged_edit_survives_the_dirty_tree_refusal(site):
    """A STAGED foreign edit, with a further unstaged edit on top, an untracked file and an ignored file: the clean-tree
    refusal must leave the index and every byte exactly as found. The old reset+checkout emptied the index and
    discarded the staged bytes."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    (site / "lessons" / "index.html").write_bytes(b"<nav>staged foreign edit</nav>\r\n")
    g(site, "add", "lessons/index.html")
    (site / "lessons" / "index.html").write_bytes(b"<nav>staged foreign edit</nav>\r\n<p>and an unstaged one</p>\n")
    (site / "notes.txt").write_bytes(b"untracked\n")
    (site / "release_log.jsonl").write_bytes(b"ignored\n")
    before = state(site)
    assert "M  lessons/index.html" in before["status"] or "MM lessons/index.html" in before["status"]
    led = FakeLedger()
    led.rule(title, "APPROVE")
    report = owed_refusal(led)
    assert "not clean" in report[0]
    assert state(site) == before
    assert tag_target(site, "approved/G2") is None


def test_break_foreign_staged_new_file_survives_the_not_on_main_refusal(site):
    """On a non-main branch with a staged new file (its name has a space) and a staged deletion: the not-on-main
    refusal leaves the index exactly as it was."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    g(site, "checkout", "-q", "-b", "other")
    (site / "new note.txt").write_bytes(b"brand new, staged\n")
    g(site, "add", "new note.txt")
    g(site, "rm", "-q", "--cached", "lessons/index.html")
    before = state(site)
    assert 'A  "new note.txt"' in before["status"] and "D  lessons/index.html" in before["status"]
    led = FakeLedger()
    led.rule(title, "APPROVE")
    report = owed_refusal(led)
    assert "not on main" in report[0]
    assert state(site) == before


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_foreign_deletion_and_edit_survive_a_pre_commit_hook_refusal(site, monkeypatch, verdict):
    """Work lands after the clean check (a tracked file deleted, another edited with CRLF bytes, an untracked file in
    a directory with a space, an ignored file); then approvals' own commit is refused by a pre-commit hook, i.e. it
    fails AFTER `git add` staged approvals' files. Everything foreign must survive, unstaged, and nothing of
    approvals' own may remain (staged or in the tree)."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    refuse_commits(site)
    foreign = b"release_log.jsonl\r\n__pycache__/\r\n# foreign edit\r\n"

    def land():
        (site / "lessons" / "index.html").unlink()
        (site / ".gitignore").write_bytes(foreign)
        (site / "scratch dir").mkdir()
        (site / "scratch dir" / "notes.txt").write_bytes(b"untracked notes\n")
        (site / "release_log.jsonl").write_bytes(b"ignored log\n")
    after_status_check(monkeypatch, land)
    led = FakeLedger()
    led.rule(title, verdict)
    report = owed_refusal(led)
    assert "commit" in report[0]
    assert not (site / "lessons" / "index.html").exists()
    assert (site / ".gitignore").read_bytes() == foreign
    assert (site / "scratch dir" / "notes.txt").read_bytes() == b"untracked notes\n"
    assert (site / "release_log.jsonl").read_bytes() == b"ignored log\n"
    assert g(site, "diff", "--cached", "--name-only") == ""
    assert set(g(site, "diff", "--name-only").splitlines()) == {"lessons/index.html", ".gitignore"}
    assert g(site, "ls-files", "--others", "--exclude-standard") == "scratch dir/notes.txt"
    assert not (site / "PRODUCTION_BOARD.md").exists()
    assert tag_target(site, "approved/G2") is None
    assert next(r for r in pb.load_queue() if r["id"] == "G2")["stage"] == "SOURCE"


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_foreign_edits_to_approvals_own_files_landing_before_its_snapshot_survive(site, monkeypatch, verdict):
    """Foreign bytes appended to the queue and the tile board right after the clean check (before approvals reads or
    writes them). A refusal must put back the bytes as approvals FOUND them, foreign lines included, not HEAD's."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    board = site / "boards" / "APPROVALS_OWED.md"
    want = {}

    def land():
        q = pb.QUEUE.read_bytes() + b"# foreign comment line, uncommitted\n"
        pb.QUEUE.write_bytes(q)
        b = board.read_bytes() + b"\nA foreign note under the tile, uncommitted.\n"
        board.write_bytes(b)
        want.update(queue=q, board=b)
    led = FakeLedger()
    led.rule(title, verdict)
    after_status_check(monkeypatch, land)
    boom_build(monkeypatch, approvals.ApprovalError)
    owed_refusal(led)
    assert pb.QUEUE.read_bytes() == want["queue"]
    assert board.read_bytes() == want["board"]
    assert g(site, "diff", "--cached", "--name-only") == ""
    assert not (site / "PRODUCTION_BOARD.md").exists()
    assert tag_target(site, "approved/G2") is None


def test_break_foreign_assume_unchanged_edit_survives(site, monkeypatch):
    """A foreign edit git has been told to ignore (update-index --assume-unchanged) passes the clean check, so apply()
    goes ahead and then refuses mid-way. The edit is uncommitted work and must survive; `git checkout -- .` writes
    HEAD's bytes over it."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    (site / "lessons" / "index.html").write_bytes(b"<nav>hidden foreign edit</nav>\n")
    g(site, "update-index", "--assume-unchanged", "lessons/index.html")
    assert g(site, "status", "--porcelain") == ""
    before = state(site)
    led = FakeLedger()
    led.rule(title, "APPROVE")
    boom_build(monkeypatch, approvals.ApprovalError)
    owed_refusal(led)
    assert (site / "lessons" / "index.html").read_bytes() == b"<nav>hidden foreign edit</nav>\n"
    assert state(site) == before


def test_break_foreign_work_survives_a_keyboard_interrupt_at_the_commit(site, monkeypatch):
    """Ctrl-C (or the scheduler killing the job) while approvals' own commit runs: foreign work that landed after the
    clean check is still there, byte-identical, and none of it is staged."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)

    def land():
        (site / "lessons" / "index.html").write_bytes(b"<nav>mid-apply foreign edit</nav>\n")
        (site / "notes.txt").write_bytes(b"untracked\n")
    after_status_check(monkeypatch, land)
    real = approvals.git

    def spy(*args, **kw):
        if args and args[0] == "commit":
            raise KeyboardInterrupt
        return real(*args, **kw)
    monkeypatch.setattr(approvals, "git", spy)
    led = FakeLedger()
    led.rule(title, "APPROVE")
    with pytest.raises(KeyboardInterrupt):
        approvals.apply(today=MON, led=led)
    assert len(led.rulings_owed()) == 1
    assert (site / "lessons" / "index.html").read_bytes() == b"<nav>mid-apply foreign edit</nav>\n"
    assert (site / "notes.txt").read_bytes() == b"untracked\n"
    assert g(site, "diff", "--cached", "--name-only") == ""
    assert set(g(site, "diff", "--name-only").splitlines()) == {"lessons/index.html"}
    assert g(site, "ls-files", "--others", "--exclude-standard") == "notes.txt"


def test_break_foreign_work_survives_when_an_earlier_ruling_in_the_same_run_applied(site2, monkeypatch):
    """Two owed rulings. The first (G2) applies and commits; foreign work lands after the second ruling's clean check;
    the second (G3) refuses mid-way. The foreign work survives, the first application stands, G3 stays owed."""
    t2 = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    t3 = approvals.offer("G3", "draft/g3", PROOF, today=MON)
    tiled2 = g(site2, "rev-parse", "draft/g2")

    def land():
        (site2 / "lessons" / "index.html").write_bytes(b"<nav>foreign, between two rulings</nav>\n")
        (site2 / "notes.txt").write_bytes(b"untracked\n")
    after_status_check(monkeypatch, land, nth=2)
    boom_build(monkeypatch, approvals.ApprovalError, on_call=2)
    led = FakeLedger()
    led.rule(t2, "APPROVE")
    led.rule(t3, "APPROVE")
    report = approvals.apply(today=MON, led=led)
    assert report[0].startswith("APPLIED  APPROVE  G2") and report[1].startswith("OWED     APPROVE  G3"), report
    assert [e["body"]["decision"] for e in led.rulings_owed()] == [t3]
    assert (site2 / "lessons" / "index.html").read_bytes() == b"<nav>foreign, between two rulings</nav>\n"
    assert (site2 / "notes.txt").read_bytes() == b"untracked\n"
    assert g(site2, "diff", "--cached", "--name-only") == ""
    assert set(g(site2, "diff", "--name-only").splitlines()) == {"lessons/index.html"}
    assert g(site2, "ls-files", "--others", "--exclude-standard") == "notes.txt"
    rows = {r["id"]: r for r in pb.load_queue()}
    assert rows["G2"]["stage"] == "PREVIEWED" and rows["G2"]["approved_commit"] == tiled2
    assert rows["G3"]["stage"] == "SOURCE"
    assert tag_target(site2, "approved/G2") == tiled2 and tag_target(site2, "approved/G3") is None


def test_break_foreign_work_survives_in_a_repo_whose_path_has_a_space(tmp_path, monkeypatch):
    """Same refusal (hook), in a checkout whose root path contains a space, with a foreign untracked file whose name
    has one too."""
    root = build_site(tmp_path / "my site", monkeypatch)
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    refuse_commits(root)

    def land():
        (root / "lessons" / "index.html").write_bytes(b"<nav>foreign</nav>\n")
        (root / "my notes.txt").write_bytes(b"untracked, with a space\n")
    after_status_check(monkeypatch, land)
    led = FakeLedger()
    led.rule(title, "REJECT")
    owed_refusal(led)
    assert (root / "lessons" / "index.html").read_bytes() == b"<nav>foreign</nav>\n"
    assert (root / "my notes.txt").read_bytes() == b"untracked, with a space\n"
    assert g(root, "diff", "--cached", "--name-only") == ""
    assert set(g(root, "diff", "--name-only").splitlines()) == {"lessons/index.html"}
    assert g(root, "ls-files", "--others", "--exclude-standard") == "my notes.txt"
    assert not (root / "PRODUCTION_BOARD.md").exists()


# ================================================================ P2: a refusal undoes its own partial work
@pytest.mark.parametrize("refusal", ["board_build", "pre_commit_hook"])
def test_break_own_tag_returns_to_its_prior_target(site, monkeypatch, refusal):
    """approved/G2 already points at an older commit (a previous approval). An APPROVE moves it, then refuses: the tag
    must point back at the OLD target, not stay on the new commit, and the tree must be as before the attempt."""
    old = g(site, "rev-parse", "HEAD")
    g(site, "tag", "approved/G2", old)
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    if refusal == "board_build":
        boom_build(monkeypatch, approvals.ApprovalError)
    else:
        refuse_commits(site)
    before = state(site)
    led = FakeLedger()
    led.rule(title, "APPROVE")
    owed_refusal(led)
    assert tag_target(site, "approved/G2") == old
    assert state(site) == before


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_production_board_it_created_is_removed_again(site, verdict):
    """PRODUCTION_BOARD.md does not exist before the attempt. approvals writes it, stages it, and the commit is refused
    (hook). The file it created must be gone and unstaged; the queue, the tile board and the tag as before."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    assert not pb.BOARD.exists()
    refuse_commits(site)
    before = state(site)
    led = FakeLedger()
    led.rule(title, verdict)
    report = owed_refusal(led)
    assert "commit" in report[0]
    assert not pb.BOARD.exists()
    assert state(site) == before
    assert next(r for r in pb.load_queue() if r["id"] == "G2")["stage"] == "SOURCE"


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_writes_are_undone_on_a_keyboard_interrupt(site, monkeypatch, verdict):
    """A BaseException (Ctrl-C, the scheduler killing the job) after approvals wrote the queue and the board and moved
    the tag: the interrupt propagates, but its own writes are undone first and the ruling stays owed."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    before = state(site)
    seen = {}

    def interrupt(today):
        seen["queue"] = pb.QUEUE.read_bytes() != before["files"]["production_queue.jsonl"]
        seen["tag"] = tag_target(site, "approved/G2")
        raise KeyboardInterrupt
    monkeypatch.setattr(pb, "build", interrupt)
    led = FakeLedger()
    led.rule(title, verdict)
    with pytest.raises(KeyboardInterrupt):
        approvals.apply(today=MON, led=led)
    assert seen["queue"] and (seen["tag"] is not None) == (verdict == "APPROVE")   # it really had written first
    assert len(led.rulings_owed()) == 1
    assert state(site) == before
    assert tag_target(site, "approved/G2") is None


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_writes_are_undone_when_writing_production_board_itself_fails(site, monkeypatch, verdict):
    """An unexpected OSError at the PRODUCTION_BOARD.md write (its directory is gone), i.e. not an ApprovalError and
    not from an injected stub: queue, tile board and tag go back; the error still propagates; the ruling stays owed."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    monkeypatch.setattr(pb, "BOARD", site / "no such dir" / "PRODUCTION_BOARD.md")
    before = state(site)
    led = FakeLedger()
    led.rule(title, verdict)
    with pytest.raises(FileNotFoundError):
        approvals.apply(today=MON, led=led)
    assert len(led.rulings_owed()) == 1
    assert state(site) == before
    assert tag_target(site, "approved/G2") is None
    assert next(r for r in pb.load_queue() if r["id"] == "G2")["stage"] == "SOURCE"


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_queue_write_is_undone_when_the_board_marker_refuses_on_the_real_path(site, verdict):
    """No stub: the tile's pending marker was ruled by hand and committed, so mark_board refuses AFTER rack/requeue
    wrote the queue. The queue must be back as it was; the ruling stays owed."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    board = site / "boards" / "APPROVALS_OWED.md"
    board.write_text(board.read_text(encoding="utf-8").replace(approvals.PENDING, "**DANIEL:** ruled by hand"),
                     encoding="utf-8", newline="\n")
    g(site, "commit", "-q", "-am", "hand-ruled")
    before = state(site)
    led = FakeLedger()
    led.rule(title, verdict)
    report = owed_refusal(led)
    assert "no pending marker" in report[0]
    assert state(site) == before


def test_break_own_refusal_after_an_applied_ruling_restores_to_that_application(site2, monkeypatch):
    """Two owed rulings in one run: G2 applies and commits; G3 writes queue + board, moves its tag, then refuses. The
    tree and tags must equal the state right after G2's application (recorded at G3's clean check), G3 stays owed."""
    t2 = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    t3 = approvals.offer("G3", "draft/g3", PROOF, today=MON)
    tiled2 = g(site2, "rev-parse", "draft/g2")
    mid = {}
    after_status_check(monkeypatch, lambda: mid.update(state(site2)), nth=2)
    boom_build(monkeypatch, approvals.ApprovalError, on_call=2)
    led = FakeLedger()
    led.rule(t2, "APPROVE")
    led.rule(t3, "APPROVE")
    report = approvals.apply(today=MON, led=led)
    assert report[0].startswith("APPLIED  APPROVE  G2") and report[1].startswith("OWED     APPROVE  G3"), report
    assert mid and mid["head"] != g(site2, "rev-parse", "main~1") and mid["status"] == ""
    assert state(site2) == mid
    assert [e["body"]["decision"] for e in led.rulings_owed()] == [t3]
    assert tag_target(site2, "approved/G2") == tiled2 and tag_target(site2, "approved/G3") is None
    rows = {r["id"]: r for r in pb.load_queue()}
    assert rows["G2"]["stage"] == "PREVIEWED" and rows["G3"]["stage"] == "SOURCE"


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_crlf_queue_and_board_come_back_byte_exact(site, monkeypatch, verdict):
    """The queue and the tile board are committed with CRLF line endings. approvals rewrites them LF; the restore must
    bring back the exact CRLF bytes, not an LF normalisation."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    board = site / "boards" / "APPROVALS_OWED.md"
    for p in (pb.QUEUE, board):
        p.write_bytes(p.read_bytes().replace(b"\n", b"\r\n"))
    g(site, "commit", "-q", "-am", "crlf")
    assert b"\r\n" in pb.QUEUE.read_bytes()
    before = state(site)
    boom_build(monkeypatch, approvals.ApprovalError)
    led = FakeLedger()
    led.rule(title, verdict)
    owed_refusal(led)
    assert state(site) == before


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_staging_is_undone_when_the_commit_fails_with_a_tracked_production_board(site, monkeypatch, verdict):
    """PRODUCTION_BOARD.md is tracked. approvals writes all three files, stages them, and `git commit` fails: the index
    and every byte must be as before the attempt."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    pb.BOARD.write_text(pb.build(MON), encoding="utf-8", newline="\n")
    g(site, "add", "PRODUCTION_BOARD.md")
    g(site, "commit", "-q", "-m", "board")
    before = state(site)
    fail_git(monkeypatch, "commit", approvals.ApprovalError)
    led = FakeLedger()
    led.rule(title, verdict)
    owed_refusal(led)
    assert state(site) == before


def test_break_own_queue_with_a_hidden_foreign_line_is_restored_as_found(site, monkeypatch):
    """The queue carries an uncommitted foreign line that git was told to ignore (assume-unchanged), so the clean check
    passes. approvals rewrites the queue, then refuses. The queue must come back with the foreign line, i.e. as
    approvals found it, not as HEAD has it."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    found = pb.QUEUE.read_bytes() + b"# hidden foreign line\n"
    pb.QUEUE.write_bytes(found)
    g(site, "update-index", "--assume-unchanged", "production_queue.jsonl")
    assert g(site, "status", "--porcelain") == ""
    before = state(site, flags=False)
    boom_build(monkeypatch, approvals.ApprovalError)
    led = FakeLedger()
    led.rule(title, "APPROVE")
    owed_refusal(led)
    assert pb.QUEUE.read_bytes() == found
    assert state(site, flags=False) == before
    assert tag_target(site, "approved/G2") is None


@pytest.mark.parametrize("verdict", ["APPROVE", "REJECT"])
def test_break_own_staging_is_undone_or_the_refusal_is_loud_when_the_index_is_locked(site, monkeypatch, verdict):
    """Round 2 (0a540ec). Another git process takes .git/index.lock right after approvals' `git add` and holds it
    through the attempt: `git commit` fails on the lock, and so does the restore's `git reset -q -- <path>`, which is
    check=False. approvals' own staged entries are its own writes: either they are undone (the index as before the
    attempt once the lock is gone) or the refusal is LOUD (RuntimeError, as round 2 promises for a restore that could
    not put something back). A clean OWED report over an index still holding approvals' staging is neither."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    before = state(site)
    lock = site / ".git" / "index.lock"
    real = approvals.git

    def spy(*args, **kw):
        out = real(*args, **kw)
        if args and args[0] == "add":
            lock.write_bytes(b"")
        return out
    monkeypatch.setattr(approvals, "git", spy)
    led = FakeLedger()
    led.rule(title, verdict)
    raised = None
    try:
        report = approvals.apply(today=MON, led=led)
    except RuntimeError as e:
        raised = e
    assert lock.exists()
    lock.unlink()                                   # the other process let go: what did the attempt leave behind?
    assert len(led.rulings_owed()) == 1
    assert tag_target(site, "approved/G2") is None
    if raised is None:
        assert report and report[0].startswith("OWED"), report
        assert state(site) == before                # a clean OWED must mean a clean restore, index included
    else:
        for rel in OWN:                             # loud, and everything it COULD put back is back
            p = site / rel
            assert (p.read_bytes() if p.exists() else None) == before["files"].get(rel)
