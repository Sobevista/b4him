"""production-line-v2 (Daniel's rulings of 2026-10-20). Each test is RED on main at 3c0d59b and GREEN on the build.

    py -m pytest tools/test_production_line_v2.py -q

1. A REJECT carries his note verbatim onto the piece's queue row (back to DRAFTED, branch kept, blocked_on =
   "REDRAFT owed: <ledger id> <note>"), into the application ledger event, and onto the board. Found 2026-10-20:
   his notes on GC-GLOSS-2/3 (E00615/E00616) were dropped; E00660 wrote note: null and nothing went back to drafting.
2. An APPROVE clears a pre-tap blocked_on (the tap supersedes it) unless it names a post-approval gate.
3. release.py refuses any row whose blocked_on is non-empty, naming the row and the text, in the log.
4. The patch line: kind "patch" is outside the content cadence (no Tuesday rule, no 7-day cap, no content slot),
   publishes on the next run after the tap, and still only the exact pinned bytes. Daniel: "it moves outside the
   queue. Then we will need to establish two different schedules. One is content and one is patches to the site."
"""
import argparse
import datetime as dt
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import approvals  # noqa: E402
import binding  # noqa: E402
import production_board as pb  # noqa: E402
import release  # noqa: E402
import v3_testkit  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")

MON = dt.date(2026, 10, 19)
TUE = dt.date(2026, 10, 20)
WED = dt.date(2026, 10, 21)
PROOF = "https://claude.ai/artifact/example"
NOTE = 'The titles need Sentence Structure or whatever it is for instance the heading "The twenty" should read "The Twenty"'
SCHEDULED = argparse.Namespace(push=False, verify_live=False, live_minutes=0)


def blob_of(text: str) -> str:
    """The git blob id of `text` as the fixtures commit it (LF, utf-8)."""
    data = text.encode("utf-8")
    return __import__("hashlib").sha1(b"blob %d\0" % len(data) + data).hexdigest()


#: The pages the fixtures (here and in the breaker file) draft under a stage-2 record, at the bytes that record
#: checked. Round 5: a record names its bytes (`blobs`, required); the record may name more paths than one piece has.
REVIEWED_PAGES = {
    **{f"lessons/t{n}/index.html": f"<h1>T{n}</h1>\n" for n in range(1, 5)},         # breaker `drafted`
    "lessons/t5/index.html": "<h1>t5</h1>\n",                                        # `labelled`
    "lessons/t7/index.html": "<h1>t7</h1>\n",                                        # `unreviewed`
    "lessons/t9/index.html": "<h1>t9</h1>\n",                                        # breaker `gated`
    "lessons/g2/index.html": "<h1>The twenty</h1>\n",                                # `g2`
    "lessons/three/index.html": "<h1>Three</h1>\n",                                  # C3
    "lessons/p/index.html": '<main class="wide"><h1>The twenty</h1><p>Words.</p></main>\n',   # FIX-R
}
#: round 3: stage 2 is a structured record (approvals.STAGE2_KEYS), never prose; round 5: bound to its bytes
STAGE2 = {"date": "2026-10-12", "by": "independent name-check seat", "verdict": "PASS",
          "proof": "harness helper-report archive, capture 0000",
          "blobs": {rel: blob_of(text) for rel, text in REVIEWED_PAGES.items()}}


def g(root, *args):
    return subprocess.run([GIT, "-C", str(root), *args], capture_output=True, check=True,
                          encoding="utf-8").stdout.strip()


class Ledger:
    """The ledger surface approvals.apply uses, with the note field the harness app writes on a ruling."""
    def __init__(self):
        self.events = []

    def rule(self, decision, verdict, note=None):
        body = {"decision": decision, "verdict": verdict, "applied": False, "by": "daniel"}
        if note is not None:
            body["note"] = note
        ev = {"id": f"E{len(self.events) + 600:05d}", "kind": "RULING", "body": body}
        self.events.append(ev)
        return ev

    def rulings_owed(self):
        sup = {e["body"]["target"] for e in self.events if e["kind"] == "SUPERSEDE"}
        return [e for e in self.events if e["kind"] == "RULING" and not e["body"]["applied"] and e["id"] not in sup]

    def append(self, kind, by, body):
        ev = {"id": f"E{len(self.events) + 600:05d}", "kind": kind, "by": by, "body": body}
        self.events.append(ev)
        return ev

    def applied(self):
        return [e for e in self.events if e["kind"] == "RULING" and e["body"].get("applied")]


def init_repo(tmp_path, monkeypatch):
    root = tmp_path / "site"
    (root / "tools" / "tracks").mkdir(parents=True)
    shutil.copy(HERE / "tracks" / "n8n.html", root / "tools" / "tracks" / "n8n.html")
    (root / "lessons" / "a").mkdir(parents=True)
    (root / "lessons" / "a" / "index.html").write_text("<p>a</p>\n", encoding="utf-8", newline="\n")
    (root / "lessons" / "index.html").write_text(
        "<nav></nav>\n\n<!-- b4him:track n8n (generated) -->\n<!-- /b4him:track n8n -->\n", encoding="utf-8",
        newline="\n")
    (root / ".gitignore").write_text("release_log.jsonl\nrelease_alarm.md\n__pycache__/\n", encoding="utf-8")
    g(tmp_path, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t"), ("core.autocrlf", "false")):
        g(root, "config", k, v)
    monkeypatch.setattr(pb, "REPO", root)
    monkeypatch.setattr(pb, "QUEUE", root / "production_queue.jsonl")
    monkeypatch.setattr(pb, "BOARD", root / "PRODUCTION_BOARD.md")
    return root


def write_queue(root, *rows, msg="queue"):
    pb.QUEUE.write_text("# q\n" + "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8", newline="\n")
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", msg)


def draft(root, row, files):
    """Commit `row` and `files` on draft/<id> and return to main. Returns the draft commit."""
    branch = row["branch"]
    g(root, "checkout", "-q", "-b", branch)
    for rel, text in files.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    rows = [r for r in pb.load_queue() if r.get("id") != row["id"]] + [row]
    write_queue(root, *rows, msg="draft")
    commit = g(root, "rev-parse", "HEAD")
    g(root, "checkout", "-q", "main")
    return commit


def qrow(pid):
    return next(r for r in pb.load_queue() if r.get("id") == pid)


# ================================================================ 1. REJECT carries the note
@pytest.fixture
def g2(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    base = {"id": "G2", "order": 2, "title": "Glossary II", "stage": "SOURCE", "track": "n8n"}
    write_queue(root, base, msg="base")
    row = dict(base, stage="DRAFTED", page="lessons/g2/index.html", branch="draft/g2", reviewed=STAGE2)
    draft(root, row, {"lessons/g2/index.html": "<h1>The twenty</h1>\n"})
    return root


def test_reject_carries_daniels_note_onto_the_queue_row_the_ledger_and_the_board(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    ev = led.rule(title, "REJECT", NOTE)
    report = approvals.apply(today=MON, led=led)
    assert report[0].startswith("APPLIED  REJECT  G2"), report
    row = qrow("G2")
    assert row["stage"] == "DRAFTED", row
    assert row["branch"] == "draft/g2"
    assert row["blocked_on"] == f"REDRAFT owed: {ev['id']} {NOTE}"
    done = led.applied()[-1]
    assert done["body"]["note"] == NOTE, done                  # never null when the ruling had one
    assert NOTE in done["body"]["binds"]
    board = (g2 / "PRODUCTION_BOARD.md").read_text(encoding="utf-8")
    assert NOTE in board and "REDRAFT" in board
    assert NOTE in (g2 / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert g(g2, "status", "--porcelain") == ""
    assert NOTE in g(g2, "log", "-1", "--format=%B")
    assert not led.rulings_owed()


def test_reject_with_no_note_still_requeues_and_says_no_note_given(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    ev = led.rule(title, "REJECT")
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  REJECT  G2")
    row = qrow("G2")
    assert row["stage"] == "DRAFTED" and row["blocked_on"] == f"REDRAFT owed: {ev['id']} no note given"
    assert "no note given" in (g2 / "PRODUCTION_BOARD.md").read_text(encoding="utf-8")


def test_reject_of_a_piece_with_no_row_on_main_adds_its_row(g2):
    # GC-GLOSS-3's case: the tile's piece exists only on its draft branch.
    write_queue(g2, msg="main's queue has no G2 row")
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    led.rule(title, "REJECT", "Same as Glossary 2")
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  REJECT  G2")
    row = qrow("G2")
    assert row["stage"] == "DRAFTED" and row["blocked_on"].endswith(" Same as Glossary 2")


def test_reject_never_unpublishes_a_live_row(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    write_queue(g2, {"id": "G2", "order": 2, "title": "Glossary II", "stage": "PUBLISHED", "published": "2026-10-13"},
                msg="already live")
    led = Ledger()
    led.rule(title, "REJECT", NOTE)
    report = approvals.apply(today=MON, led=led)
    assert report[0].startswith("OWED") and "PUBLISHED" in report[0], report
    assert qrow("G2")["stage"] == "PUBLISHED" and len(led.rulings_owed()) == 1


# ================================================================ 2. APPROVE and blocked_on
@pytest.fixture
def labelled(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    write_queue(root, msg="base")

    def make(label):
        row = {"id": "T5", "order": 5, "title": "T5", "stage": "DRAFTED", "page": "lessons/t5/index.html",
               "branch": "draft/t5", "blocked_on": label, "reviewed": STAGE2}
        draft(root, row, {"lessons/t5/index.html": "<h1>t5</h1>\n"})
        title = approvals.offer("T5", "draft/t5", PROOF, today=dt.date(2026, 10, 12))
        led = Ledger()
        led.rule(title, "APPROVE")
        assert approvals.apply(today=dt.date(2026, 10, 12), led=led)[0].startswith("APPLIED  APPROVE  T5")
        return qrow("T5")
    return root, make


def test_approve_clears_only_a_label_marked_pre_tap_and_keeps_the_text(labelled):
    # round 3: the tap clears ONLY a label marked as waiting for the tap; everything else survives it
    root, make = labelled
    row = make("PRE-TAP: waiting for Daniel's one tap on the rendered proof")
    assert "blocked_on" not in row or not row["blocked_on"], row
    assert "waiting for Daniel's one tap" in row["cleared_blocked_on"]
    assert release.plan(TUE)["outcome"] == "PUBLISH"


def test_approve_keeps_an_unmarked_label_and_the_tile_showed_it(labelled):
    root, make = labelled
    row = make("stage 2: independent name check by a seat that did not write the page")
    assert row["blocked_on"].startswith("stage 2:")
    assert "stage 2: independent name check" in (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert release.plan(TUE)["outcome"] == "FAIL"


def test_approve_keeps_a_post_approval_gate_and_release_refuses_it(labelled):
    root, make = labelled
    row = make("POST-APPROVAL: wait for the course page to go live first")
    assert row["blocked_on"].startswith("POST-APPROVAL:")
    d = release.plan(TUE)
    assert d["outcome"] == "FAIL" and "T5" in d["why"] and "course page" in d["why"], d


# ================================================================ release-side fixture
@pytest.fixture
def live(tmp_path, monkeypatch):
    """A site with one published page (PAGE at OLD bytes) and new bytes in the store for a patch."""
    root = init_repo(tmp_path, monkeypatch)
    (root / "lessons" / "p").mkdir(parents=True)
    (root / PAGE).write_text("<h1>The twenty</h1>\n", encoding="utf-8", newline="\n")
    old = pb.blob_sha(root / PAGE)
    pubrow = {"id": "P", "order": 1, "title": "Page P", "stage": "PUBLISHED", "published": "2026-10-06",
              "approved_blobs": {PAGE: old}}
    write_queue(root, pubrow, msg="base")
    src = tmp_path / "fixed.html"
    src.write_bytes(b"<h1>The Twenty</h1>\n")
    new = g(root, "hash-object", "-w", str(src))
    return root, old, new, pubrow


PAGE = "lessons/p/index.html"


def patch_row(old, new, **kw):
    row = {"id": "FIX-1", "kind": "patch", "order": 90, "title": "Heading case on Page P", "stage": "PREVIEWED",
           "previewed": "2026-10-19", "since": "2026-10-19", "approved_blobs": {PAGE: new},
           "replaces_blobs": {PAGE: old}}
    row.update(kw)
    return v3_testkit.bind(row)


def content_row(root, tmp_path_bytes=b"<h1>C</h1>\n", **kw):
    src = root.parent / "c.html"
    src.write_bytes(tmp_path_bytes)
    blob = g(root, "hash-object", "-w", str(src))
    row = {"id": "C1", "order": 3, "title": "Content one", "stage": "PREVIEWED", "previewed": "2026-10-01",
           "approved_blobs": {"lessons/c1/index.html": blob}}
    row.update(kw)
    return v3_testkit.bind(row)


def log_lines(root):
    p = root / "release_log.jsonl"
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()] if p.exists() else []


# ================================================================ 3. release refuses blocked_on
def test_release_refuses_a_row_with_blocked_on_naming_the_row_and_the_text_in_the_log(live):
    root, old, new, pubrow = live
    write_queue(root, pubrow, content_row(root, blocked_on="stage 2: independent name check"))
    entry = {"date": TUE.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, TUE, entry) == 1
    assert entry["outcome"] == "FAIL" and entry["piece"] == "C1"
    assert "C1" in entry["why"] and "stage 2: independent name check" in entry["why"], entry
    release.log(entry)
    assert "stage 2: independent name check" in log_lines(root)[-1]["why"]
    assert not (root / "lessons" / "c1").exists()


def test_a_stale_pre_tap_label_on_an_approved_row_is_refused_with_a_message_that_says_so(live):
    root, old, new, pubrow = live
    write_queue(root, pubrow, content_row(root, blocked_on="Daniel's one tap on the rendered proof (E00472)"))
    d = release.plan(TUE)
    assert d["outcome"] == "FAIL" and "Daniel's one tap on the rendered proof (E00472)" in d["why"]
    assert "stale" in d["why"] and "clear" in d["why"], d


# ================================================================ 4. the patch line
def test_a_tapped_patch_publishes_on_the_next_run_even_a_wednesday(live):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new))
    entry = {"date": WED.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, WED, entry) == 0
    assert entry["outcome"] == "SKIP" and entry.get("lane") == "content"       # the content line: not a release day
    assert pb.blob_sha(root / PAGE) == new
    assert qrow("FIX-1")["stage"] == "PUBLISHED" and qrow("FIX-1")["published"] == WED.isoformat()
    lines = [l for l in log_lines(root) if l.get("lane") == "patch"]
    assert len(lines) == 1 and lines[0]["outcome"] == "COMMITTED" and lines[0]["piece"] == "FIX-1", lines
    assert g(root, "status", "--porcelain") == ""


def test_a_patch_ignores_the_cap_and_never_takes_the_content_slot(live, tmp_path):
    root, old, new, pubrow = live
    # Tue: one content piece published Fri 10-16 fills the cap; the patch goes out anyway.
    capped = {"id": "P0", "order": 2, "title": "P0", "stage": "PUBLISHED", "published": "2026-10-16"}
    write_queue(root, pubrow, capped, patch_row(old, new))
    entry = {"date": TUE.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, TUE, entry) == 0
    assert entry["outcome"] == "SKIP" and "cap" in entry["why"]
    assert pb.blob_sha(root / PAGE) == new


def test_a_published_patch_does_not_consume_the_content_week(live):
    root, old, new, pubrow = live
    a = "lessons/a/index.html"
    shipped = v3_testkit.bind({"id": "FIX-0", "kind": "patch", "order": 91, "title": "earlier fix",
                               "stage": "PUBLISHED", "published": "2026-10-19",
                               "approved_blobs": {a: pb.blob_sha(root / a)}})
    write_queue(root, pubrow, shipped, content_row(root))
    d = release.plan(TUE)
    assert d["outcome"] == "PUBLISH" and d["piece"] == "C1", d
    # round 3: a published row is on the patch line only through its binding (which covers kind)
    write_queue(root, pubrow, {k: v for k, v in shipped.items() if k != "binding"}, content_row(root))
    assert release.plan(TUE)["outcome"] == "SKIP"


def test_tuesday_with_a_patch_and_a_content_piece_publishes_both_and_pushes_each(live, tmp_path):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new), content_row(root))
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")
    args = argparse.Namespace(push=True, verify_live=False, live_minutes=0)
    entry = {"date": TUE.isoformat(), "mode": "apply"}
    with release.scheduled_entry(TUE):
        assert release.run(args, TUE, entry) == 0, entry
    assert entry["outcome"] == "PUSHED-UNVERIFIED" and entry["piece"] == "C1", entry
    assert g(bare, "rev-parse", "main") == g(root, "rev-parse", "HEAD")
    subjects = g(root, "log", "-2", "--format=%s").splitlines()
    assert subjects[0].startswith("PUBLISHED C1") and subjects[1].startswith("PATCHED FIX-1"), subjects
    assert [l["outcome"] for l in log_lines(root) if l.get("lane") == "patch"] == ["PUSHED-UNVERIFIED"]


def test_a_patch_publishes_only_its_pinned_bytes(live):
    root, old, new, pubrow = live
    # an edit to the page after the tap: the tree no longer holds the bytes the patch replaces
    (root / PAGE).write_text("<h1>hand edit</h1>\n", encoding="utf-8", newline="\n")
    g(root, "commit", "-q", "-am", "hand edit")
    write_queue(root, pubrow, patch_row(old, new))
    entry = {"date": WED.isoformat(), "mode": "apply"}
    release.run(SCHEDULED, WED, entry)
    assert (root / PAGE).read_text(encoding="utf-8") == "<h1>hand edit</h1>\n"
    lines = [l for l in log_lines(root) if l.get("lane") == "patch"]
    assert lines and lines[-1]["outcome"] in ("SKIP", "FAIL") and "FIX-1" in json.dumps(lines[-1]), lines


def test_an_unbound_patch_is_refused_and_logged_in_the_patch_lane(live):
    root, old, new, pubrow = live
    row = patch_row(old, new)
    row.pop("binding")
    write_queue(root, pubrow, row)
    entry = {"date": WED.isoformat(), "mode": "apply"}
    release.run(SCHEDULED, WED, entry)
    assert pb.blob_sha(root / PAGE) == old
    lines = [l for l in log_lines(root) if l.get("lane") == "patch"]
    assert lines and lines[-1]["outcome"] == "FAIL" and "UNVERIFIED" in lines[-1]["why"], lines


def test_a_patch_with_blocked_on_is_refused(live):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new, blocked_on="POST-APPROVAL: after the redesign"))
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert pb.blob_sha(root / PAGE) == old
    lines = [l for l in log_lines(root) if l.get("lane") == "patch"]
    assert lines and lines[-1]["outcome"] == "FAIL" and "after the redesign" in lines[-1]["why"], lines


def test_flipping_a_racked_content_row_to_patch_breaks_its_binding(live):
    root, old, new, pubrow = live
    row = content_row(root)
    assert binding.problems(row) == []
    flipped = dict(row, kind="patch")
    assert binding.problems(flipped), "kind is part of what Daniel approved: a content row cannot jump the cadence"
    back = patch_row(old, new)
    assert binding.problems(dict(back, kind="revision of a published page"))


def test_the_board_shows_the_two_lines_separately(live):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new), content_row(root))
    board = pb.build(MON)
    assert "## The content line" in board and "## The patch line" in board
    slots = [l for l in board.splitlines() if l.startswith("| **20")]
    assert not any("Heading case on Page P" in l for l in slots)
    patch_part = board.split("## The patch line", 1)[1]
    assert "Heading case on Page P" in patch_part and "next release run" in patch_part
    assert "**RUNWAY: 1.0 weeks**" in board                  # runway counts the content line only


def test_a_patch_tapped_end_to_end_records_what_it_replaces_and_ships_next_run(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    (root / PAGE).parent.mkdir(parents=True)
    (root / PAGE).write_text("<h1>The twenty</h1>\n", encoding="utf-8", newline="\n")
    old = pb.blob_sha(root / PAGE)
    write_queue(root, {"id": "P", "order": 1, "title": "Page P", "stage": "PUBLISHED", "published": "2026-10-06",
                       "approved_blobs": {PAGE: old}}, msg="base")
    draft(root, {"id": "FIX-1", "kind": "patch", "order": 90, "title": "Heading case", "stage": "DRAFTED",
                 "page": PAGE, "branch": "draft/fix-1", "patch_scope": "case-only"}, {PAGE: "<h1>The Twenty</h1>\n"})
    title = approvals.offer("FIX-1", "draft/fix-1", PROOF, today=TUE)
    assert "patch line" in (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    led = Ledger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=TUE, led=led)[0].startswith("APPLIED  APPROVE  FIX-1")
    assert qrow("FIX-1")["replaces_blobs"] == {PAGE: old}
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert (root / PAGE).read_text(encoding="utf-8") == "<h1>The Twenty</h1>\n"


# ================================================================ round 2: stage 2 is a gate on the OFFER
@pytest.fixture
def unreviewed(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    (root / PAGE).parent.mkdir(parents=True)
    (root / PAGE).write_text("<main><h1>The twenty</h1><p>Words.</p></main>\n", encoding="utf-8", newline="\n")
    write_queue(root, {"id": "P", "order": 1, "title": "Page P", "stage": "PUBLISHED", "published": "2026-10-06",
                       "approved_blobs": {PAGE: pb.blob_sha(root / PAGE)}}, msg="base")

    def make(pid, files, **row):
        r = {"id": pid, "order": 7, "title": pid, "stage": "DRAFTED", "branch": f"draft/{pid.lower()}", **row}
        r.setdefault("page", next(iter(files)))
        draft(root, r, files)
        return f"draft/{pid.lower()}"
    return root, make


def test_offer_refuses_a_content_piece_with_no_stage2_record_and_names_what_is_missing(unreviewed):
    root, make = unreviewed
    ref = make("T5", {"lessons/t5/index.html": "<h1>t5</h1>\n"})
    with pytest.raises(approvals.ApprovalError, match=r"no stage-2 PASS.*`reviewed` is empty"):
        approvals.offer("T5", ref, PROOF, today=MON)
    ref = make("T6", {"lessons/t6/index.html": "<h1>t6</h1>\n"},
               reviewed="2026-10-12 - stage 2 by a seat that neither wrote nor rendered the page: PASS")
    with pytest.raises(approvals.ApprovalError, match="prose never admits a new offer"):
        approvals.offer("T6", ref, PROOF, today=MON)
    ref = make("T8", {"lessons/t8/index.html": "<h1>t8</h1>\n"}, reviewed=dict(STAGE2, verdict="FAIL"))
    with pytest.raises(approvals.ApprovalError, match="verdict is 'FAIL'"):
        approvals.offer("T8", ref, PROOF, today=MON)
    ref = make("T9", {"lessons/t9/index.html": "<h1>t9</h1>\n"}, reviewed=dict(STAGE2, by="seat-42"),
               drafted_by="seat-42")
    with pytest.raises(approvals.ApprovalError, match="recorded as drafting the piece"):
        approvals.offer("T9", ref, PROOF, today=MON)
    # round 4: the git author of the piece's bytes is the drafter too (fixture commits are authored by "t")
    ref = make("T11", {"lessons/t11/index.html": "<h1>t11</h1>\n"}, reviewed=dict(STAGE2, by="t"))
    with pytest.raises(approvals.ApprovalError, match="git author of the piece's own bytes"):
        approvals.offer("T11", ref, PROOF, today=MON)
    ref = make("T12", {"lessons/t12/index.html": "<h1>t12</h1>\n"}, reviewed=dict(STAGE2, by="Claude"))
    with pytest.raises(approvals.ApprovalError, match="names a model, not a seat"):
        approvals.offer("T12", ref, PROOF, today=MON)
    ref = make("T10", {"lessons/t10/index.html": "<h1>t10</h1>\n"}, reviewed={k: STAGE2[k] for k in ("date", "by")})
    with pytest.raises(approvals.ApprovalError, match="lacks verdict, proof"):
        approvals.offer("T10", ref, PROOF, today=MON)
    assert not (root / "boards" / "APPROVALS_OWED.md").exists()
    ref = make("T7", {"lessons/t7/index.html": "<h1>t7</h1>\n"}, reviewed=STAGE2)
    assert approvals.offer("T7", ref, PROOF, today=MON)
    assert "stage 2 PASS on 2026-10-12 by independent name-check seat" in \
        (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")


def test_the_stage2_refusal_hint_names_blobs_so_following_it_is_not_refused_again(unreviewed):
    """The hint used to show reviewed = {"date", "by", "verdict": "PASS", "proof"}: a record built from it lacks the
    required `blobs` and the next offer is refused again. The hint must name `blobs` and say it is required."""
    root, make = unreviewed
    ref = make("T13", {"lessons/t13/index.html": "<h1>t13</h1>\n"})
    with pytest.raises(approvals.ApprovalError) as e:
        approvals.offer("T13", ref, PROOF, today=MON)
    hint = str(e.value).split("Record it on the row as", 1)[1]
    assert '"blobs"' in hint and "required" in hint
    # following the hint literally (no blobs) is refused for exactly that reason, so the hint must carry it
    ref = make("T14", {"lessons/t14/index.html": "<h1>t14</h1>\n"},
               reviewed={k: STAGE2[k] for k in ("date", "by", "verdict", "proof")})
    with pytest.raises(approvals.ApprovalError, match="names no `blobs`"):
        approvals.offer("T14", ref, PROOF, today=MON)


def test_a_patch_needs_stage2_unless_a_case_only_claim_is_proved_on_the_full_bytes(unreviewed):
    root, make = unreviewed
    ref = make("FIX-W", {PAGE: "<main><h1>The Twenty</h1><p>New words.</p></main>\n"}, kind="patch",
               patch_scope="case-only")
    with pytest.raises(approvals.ApprovalError, match="changes more than letter case"):
        approvals.offer("FIX-W", ref, PROOF, today=MON)
    ref = make("FIX-N", {PAGE: "<main><h1>The Twenty</h1><p>Words.</p></main>\n"}, kind="patch")
    with pytest.raises(approvals.ApprovalError, match="no stage-2 PASS"):
        approvals.offer("FIX-N", ref, PROOF, today=MON)
    # layout-only no longer exempts (round 3): markup changes need stage 2 like anything else
    ref = make("FIX-L", {PAGE: '<main class="wide">\n  <h1>The twenty</h1>\n  <p>Words.</p>\n</main>\n'},
               kind="patch", patch_scope="layout-only")
    with pytest.raises(approvals.ApprovalError, match="layout-only no longer exempts"):
        approvals.offer("FIX-L", ref, PROOF, today=MON)
    ref = make("FIX-C", {PAGE: "<main><h1>The Twenty</h1><p>Words.</p></main>\n"}, kind="patch",
               patch_scope="case-only")
    approvals.offer("FIX-C", ref, PROOF, today=MON)
    tiles = (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert "EXEMPT from stage 2 as a case-only patch" in tiles
    # with a stage-2 PASS a layout change is a fine patch
    ref = make("FIX-R", {PAGE: '<main class="wide"><h1>The twenty</h1><p>Words.</p></main>\n'}, kind="patch",
               reviewed=STAGE2)
    approvals.offer("FIX-R", ref, PROOF, today=MON)


# ================================================================ round 2: a tapped patch RE-PINS what it changes
GLOSS_PAGE = "lessons/glossary-beginner/index.html"
FURN = "tools/tracks/n8n.html"
G1_ENTRY = {"track": "n8n", "numeral": "I", "href": "/lessons/glossary-beginner/", "title": "Glossary I",
            "blurb": "Words."}


@pytest.fixture
def glossary_live(tmp_path, monkeypatch):
    """GC-GLOSS-1 as on main: PUBLISHED, pinning its page and the n8n furniture, both in the tree."""
    root = init_repo(tmp_path, monkeypatch)
    (root / GLOSS_PAGE).parent.mkdir(parents=True)
    (root / GLOSS_PAGE).write_text("<h1>The twenty</h1>\n", encoding="utf-8", newline="\n")
    old_furn, old_page = pb.blob_sha(root / FURN), pb.blob_sha(root / GLOSS_PAGE)
    g1 = {"id": "GC-GLOSS-1", "order": 1, "title": "Glossary I", "stage": "PUBLISHED", "published": "2026-10-20",
          "previewed": "2026-10-12", "approved_blobs": {GLOSS_PAGE: old_page, FURN: old_furn},
          "index_entry": G1_ENTRY, "approved_index_entry": pb.entry_sha(G1_ENTRY)}
    write_queue(root, g1, msg="base")
    return root, g1, old_furn, old_page


def fix_h(root):
    """FIX-H: the Glossary I heading-case patch, on its draft branch: page and n8n furniture, case-only."""
    new_furn_text = (root / FURN).read_text(encoding="utf-8").replace("track", "Track", 1)
    draft(root, {"id": "FIX-H", "kind": "patch", "order": 90, "title": "Heading case", "stage": "DRAFTED",
                 "files": [GLOSS_PAGE, FURN], "branch": "draft/fix-h", "patch_scope": "case-only"},
          {GLOSS_PAGE: "<h1>The Twenty</h1>\n", FURN: new_furn_text})


def racked_c2(root, g1, old_furn, previewed="2026-10-14"):
    src = root.parent / "c2.html"
    src.write_bytes(b"<h1>Two</h1>\n")
    c2_entry = {**G1_ENTRY, "numeral": "II", "href": "/lessons/two/", "title": "Two"}
    return v3_testkit.bind({"id": "C2", "order": 2, "title": "Two", "stage": "PREVIEWED", "previewed": previewed,
                            "approved_blobs": {"lessons/two/index.html": g(root, "hash-object", "-w", str(src)),
                                               FURN: old_furn},
                            "index_entry": c2_entry, "approved_index_entry": pb.entry_sha(c2_entry)})


def test_a_tapped_patch_to_a_published_pieces_pins_leaves_the_next_content_release_publish(glossary_live):
    root, g1, old_furn, old_page = glossary_live
    fix_h(root)
    # untapped: offering the patch never touches main's pins, and the content line is unaffected
    queue_before = pb.QUEUE.read_text(encoding="utf-8")
    title = approvals.offer("FIX-H", "draft/fix-h", PROOF, today=TUE)
    assert pb.QUEUE.read_text(encoding="utf-8") == queue_before

    led = Ledger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=TUE, led=led)[0].startswith("APPLIED  APPROVE  FIX-H")
    fix = qrow("FIX-H")
    assert fix["supersedes_pins"] == {GLOSS_PAGE: {"piece": "GC-GLOSS-1", "blob": old_page},
                                      FURN: {"piece": "GC-GLOSS-1", "blob": old_furn}}
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    new_furn = pb.blob_sha(root / FURN)
    assert new_furn == fix["approved_blobs"][FURN] and new_furn != old_furn
    assert "Re-pin: supersedes GC-GLOSS-1's pin" in g(root, "log", "-1", "--format=%B")

    # a content piece on the same track, approved BEFORE the patch, pinning the OLD furniture, racked
    write_queue(root, *pb.load_queue(), racked_c2(root, g1, old_furn), msg="C2 racked")
    nxt = dt.date(2026, 10, 27)
    d = release.plan(nxt)
    assert (d["outcome"], d.get("piece")) == ("PUBLISH", "C2"), d
    entry = {"date": nxt.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, nxt, entry) == 0 and entry["outcome"] == "COMMITTED", entry
    assert pb.blob_sha(root / FURN) == new_furn            # the older pin never writes the patch back out
    assert "keeps patch FIX-H's bytes" in g(root, "log", "-1", "--format=%B")
    assert "CHANGED SINCE" not in pb.build(nxt)
    assert release.live_drift(pb.load_queue()) == []


def test_a_patch_over_a_path_a_racked_piece_pins_is_refused_at_offer_and_at_rack(glossary_live):
    # round 4: a racked piece's PAGE pin still locks it; furniture does not (next test)
    root, g1, old_furn, old_page = glossary_live
    fix_h(root)
    title = approvals.offer("FIX-H", "draft/fix-h", PROOF, today=TUE)       # nothing racked yet: offered
    src = root.parent / "rev.html"
    src.write_bytes(b"<h1>The twenty, revised</h1>\n")
    rev = v3_testkit.bind({"id": "R1", "order": 5, "title": "rev", "kind": pb.REVISION, "stage": "PREVIEWED",
                           "previewed": "2026-10-19",
                           "approved_blobs": {GLOSS_PAGE: g(root, "hash-object", "-w", str(src))}})
    write_queue(root, g1, rev, msg="a revision of the page racked after the offer")
    with pytest.raises(approvals.ApprovalError, match="pinned by racked R1"):
        approvals.offer("FIX-H", "draft/fix-h", "https://claude.ai/artifact/again", today=TUE)
    led = Ledger()
    led.rule(title, "APPROVE")
    report = approvals.apply(today=TUE, led=led)
    assert report[0].startswith("OWED") and "pinned by racked R1" in report[0], report
    assert "FIX-H" not in {r.get("id") for r in pb.load_queue()}


def test_a_patch_over_furniture_racked_content_pins_is_allowed_and_the_re_pin_is_recorded(glossary_live):
    # round 4 (Daniel: "a website fix shouldnt take a week"): racked content does not lock its track's furniture
    root, g1, old_furn, old_page = glossary_live
    write_queue(root, g1, racked_c2(root, g1, old_furn), msg="C2 racked")
    fix_h(root)
    title = approvals.offer("FIX-H", "draft/fix-h", PROOF, today=TUE)
    tile = (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert "Furniture re-pinned by FIX-H" in tile and "C2" in tile
    led = Ledger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=TUE, led=led)[0].startswith("APPLIED  APPROVE  FIX-H")
    assert qrow("C2")["furniture_repinned_by"][FURN].startswith("FIX-H")
    assert binding.problems(qrow("C2")) == []                  # the mark is not part of C2's approval
    assert "re-pinned by FIX-H" in (root / "PRODUCTION_BOARD.md").read_text(encoding="utf-8")
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    new_furn = pb.blob_sha(root / FURN)
    assert new_furn != old_furn
    nxt = dt.date(2026, 10, 27)
    entry = {"date": nxt.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, nxt, entry) == 0 and entry.get("piece") == "C2", entry
    assert pb.blob_sha(root / FURN) == new_furn


def test_a_reject_tapped_but_not_yet_applied_stops_the_release(live, monkeypatch):
    # round 4 gap: a REJECT tapped before a Tuesday run but not applied must not let the piece publish
    root, old, new, pubrow = live
    write_queue(root, pubrow, content_row(root), patch_row(old, new))
    owed = [{"id": "E00999", "kind": "RULING", "body": {"decision": "APPROVE C1 at 1234567 — Content one",
                                                        "verdict": "REJECT", "applied": False}},
            {"id": "E01000", "kind": "RULING", "body": {"decision": "APPROVE FIX-1 at 1234567 — fix",
                                                        "verdict": "REJECT", "applied": False}}]
    monkeypatch.setattr(release, "OWED_SOURCE", lambda: owed)
    entry = {"date": TUE.isoformat(), "mode": "apply"}
    assert release.run(SCHEDULED, TUE, entry) == 1
    assert entry["outcome"] == "FAIL" and "E00999" in entry["why"], entry
    assert not (root / "lessons" / "c1").exists() and pb.blob_sha(root / PAGE) == old
    assert [p["outcome"] for p in entry["patch_outcomes"]] == ["FAIL"]

    def unreadable():
        raise OSError("ledger offline")
    monkeypatch.setattr(release, "OWED_SOURCE", unreadable)
    with pytest.raises(release.ReleaseError, match="UNKNOWN"):
        release.run(SCHEDULED, TUE, {"date": TUE.isoformat(), "mode": "apply"})


def test_a_second_racked_patch_on_the_same_path_is_refused_at_rack(glossary_live):
    root, g1, old_furn, old_page = glossary_live
    fix_h(root)
    draft(root, {"id": "FIX-K", "kind": "patch", "order": 91, "title": "Other case", "stage": "DRAFTED",
                 "page": GLOSS_PAGE, "branch": "draft/fix-k2", "patch_scope": "case-only"},
          {GLOSS_PAGE: "<h1>THE twenty</h1>\n"})
    t1 = approvals.offer("FIX-H", "draft/fix-h", PROOF, today=TUE)
    t2 = approvals.offer("FIX-K", "draft/fix-k2", PROOF, today=TUE)
    led = Ledger()
    led.rule(t1, "APPROVE")
    assert approvals.apply(today=TUE, led=led)[0].startswith("APPLIED  APPROVE  FIX-H")
    led.rule(t2, "APPROVE")
    report = approvals.apply(today=TUE, led=led)
    assert report[0].startswith("OWED") and "pinned by racked FIX-H" in report[0], report


def test_content_drafted_before_a_patch_and_tapped_after_it_is_refused_at_rack(glossary_live):
    root, g1, old_furn, old_page = glossary_live
    # C3 is drafted now, on the pre-patch furniture
    entry = {**G1_ENTRY, "numeral": "III", "href": "/lessons/three/", "title": "Three"}
    draft(root, {"id": "C3", "order": 3, "title": "Three", "stage": "DRAFTED", "page": "lessons/three/index.html",
                 "branch": "draft/c3", "track": "n8n", "index_entry": entry, "reviewed": STAGE2},
          {"lessons/three/index.html": "<h1>Three</h1>\n"})
    fix_h(root)
    t = approvals.offer("FIX-H", "draft/fix-h", PROOF, today=TUE)
    led = Ledger()
    led.rule(t, "APPROVE")
    approvals.apply(today=TUE, led=led)
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert qrow("FIX-H")["stage"] == "PUBLISHED"
    t3 = approvals.offer("C3", "draft/c3", PROOF, today=dt.date(2026, 10, 22))
    led.rule(t3, "APPROVE")
    report = approvals.apply(today=dt.date(2026, 10, 22), led=led)
    assert report[0].startswith("OWED") and "Redraft on current main" in report[0], report


def test_production_plan_names_the_two_lines_in_daniels_words():
    text = (HERE.parent / "PRODUCTION_PLAN.md").read_text(encoding="utf-8")
    assert "it moves outside the queue" in text and "two different schedules" in text
    assert "shouldnt take a week" in text or "shouldn't take a week" in text
    assert "patch line" in text.lower() and "content line" in text.lower()


# ================================================================ release guard: a patch that pins the index
INDEX = "lessons/index.html"
FURN = "tools/tracks/n8n.html"
A_ENTRY = {"track": "n8n", "numeral": "I", "href": "/lessons/a/", "title": "A", "blurb": "Words."}


@pytest.fixture
def pinned_index(tmp_path, monkeypatch):
    """Live 2026-10-20: SITE-PATCH-HEADINGS-1 pinned lessons/index.html (static headings), SITE-PATCH-HEADINGS-2
    re-pinned track furniture. One run, --push. A published content row lists one entry on the n8n track."""
    root = init_repo(tmp_path, monkeypatch)
    furn_old = pb.blob_sha(root / FURN)
    c0 = {"id": "C0", "order": 1, "title": "A", "stage": "PUBLISHED", "published": "2026-10-06",
          "index_entry": A_ENTRY, "approved_index_entry": pb.entry_sha(A_ENTRY),
          "approved_blobs": {"lessons/a/index.html": pb.blob_sha(root / "lessons/a/index.html"), FURN: furn_old}}
    shell = "<nav></nav>\n<h1>the lessons</h1>\n\n<!-- b4him:track n8n (generated) -->\n<!-- /b4him:track n8n -->\n"
    (root / INDEX).write_text(release.render_tracks(shell, [c0]), encoding="utf-8", newline="\n")
    write_queue(root, c0, msg="base")
    idx_old = pb.blob_sha(root / INDEX)

    def store(text):
        src = tmp_path / "src.bin"
        src.write_bytes(text.encode("utf-8"))
        return g(root, "hash-object", "-w", str(src))
    idx_new = store((root / INDEX).read_text(encoding="utf-8").replace("the lessons", "The Lessons"))
    furn_new = store((root / FURN).read_text(encoding="utf-8").replace("The n8n track", "The n8n Track"))
    base = {"kind": "patch", "stage": "PREVIEWED", "previewed": "2026-10-19", "since": "2026-10-19"}
    h1 = v3_testkit.bind(dict(base, id="H1", order=90, title="Index headings",
                              approved_blobs={INDEX: idx_new}, replaces_blobs={INDEX: idx_old}))
    h2 = v3_testkit.bind(dict(base, id="H2", order=91, title="Track headings",
                              approved_blobs={FURN: furn_new}, replaces_blobs={FURN: furn_old}))
    write_queue(root, c0, h1, h2, msg="racked")
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")
    return root, bare, idx_new, furn_new


def test_a_patch_pinning_the_index_then_a_furniture_patch_both_push_in_one_run(pinned_index):
    root, bare, idx_new, furn_new = pinned_index
    args = argparse.Namespace(push=True, verify_live=False, live_minutes=0)
    entry = {"date": TUE.isoformat(), "mode": "apply"}
    with release.scheduled_entry(TUE):
        assert release.run(args, TUE, entry) == 0, entry
    assert [(p["piece"], p["outcome"]) for p in entry["patch_outcomes"]] == \
        [("H1", "PUSHED-UNVERIFIED"), ("H2", "PUSHED-UNVERIFIED")], entry
    assert g(bare, "rev-parse", "main") == g(root, "rev-parse", "HEAD")
    subjects = g(root, "log", "-2", "--format=%s").splitlines()
    assert subjects[0].startswith("PATCHED H2") and subjects[1].startswith("PATCHED H1"), subjects
    h1_commit = g(root, "rev-parse", "HEAD~1")
    assert g(root, "rev-parse", f"{h1_commit}:{INDEX}") == idx_new          # H1 shipped exactly its pinned index
    # H2's index is generated on top of H1's: H1's static heading kept, H2's furniture rendered in
    index = (root / INDEX).read_text(encoding="utf-8")
    assert "The Lessons" in index and "The n8n Track" in index and "the lessons" not in index
    assert pb.blob_sha(root / FURN) == furn_new


def test_a_pinned_index_commit_carrying_other_index_text_is_not_a_release(pinned_index):
    root, bare, idx_new, furn_new = pinned_index
    with release.scheduled_entry(TUE):
        release.run(SCHEDULED, TUE, {"date": TUE.isoformat(), "mode": "apply"})
    h1_commit = g(root, "rev-parse", "HEAD~1")
    h1 = qrow("H1")
    assert release.is_release_of(h1_commit, release.commit_paths(h1_commit), h1)
    # the same row, but the commit's index is not the pinned blob: refused
    g(root, "checkout", "-q", "-b", "smuggle", h1_commit)
    (root / INDEX).write_text((root / INDEX).read_text(encoding="utf-8") + "<p>unapproved</p>\n",
                              encoding="utf-8", newline="\n")
    g(root, "commit", "-q", "-a", "--amend", "--no-edit")
    forged = g(root, "rev-parse", "HEAD")
    assert not release.is_release_of(forged, release.commit_paths(forged), h1)
    # H2 does not pin the index: its release still faces the re-render check, so extra index text is refused there
    g(root, "checkout", "-q", "main")
    h2_commit = g(root, "rev-parse", "HEAD")
    h2 = qrow("H2")
    assert release.is_release_of(h2_commit, release.commit_paths(h2_commit), h2)
    g(root, "checkout", "-q", "-b", "smuggle2", h2_commit)
    (root / INDEX).write_text((root / INDEX).read_text(encoding="utf-8") + "<p>unapproved</p>\n",
                              encoding="utf-8", newline="\n")
    g(root, "commit", "-q", "-a", "--amend", "--no-edit")
    forged2 = g(root, "rev-parse", "HEAD")
    assert not release.is_release_of(forged2, release.commit_paths(forged2), h2)
