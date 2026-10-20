"""Tests for approvals.py: a tap pins exactly the commit on the tile, and the release then publishes those bytes.

    py -m pytest tools/test_approvals.py -q
"""
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
import production_board as pb  # noqa: E402
import release  # noqa: E402

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")
MON = dt.date(2026, 10, 12)
PAGE = "lessons/g2/index.html"
PROOF = "https://claude.ai/artifact/example"


def g(root, *args):
    return subprocess.run([GIT, "-C", str(root), *args], capture_output=True, check=True,
                          encoding="utf-8").stdout.strip()


class FakeLedger:
    def __init__(self):
        self.events = []

    def rule(self, decision, verdict):
        ev = {"id": f"E{len(self.events) + 1:05d}", "kind": "RULING",
              "body": {"decision": decision, "verdict": verdict, "applied": False}}
        self.events.append(ev)
        return ev

    def rulings_owed(self):
        sup = {e["body"]["target"] for e in self.events if e["kind"] == "SUPERSEDE"}
        return [e for e in self.events if e["kind"] == "RULING" and not e["body"]["applied"] and e["id"] not in sup]

    def append(self, kind, by, body):
        ev = {"id": f"E{len(self.events) + 1:05d}", "kind": kind, "by": by, "body": body}
        self.events.append(ev)
        return ev


@pytest.fixture
def site(tmp_path, monkeypatch):
    root = tmp_path / "site"
    (root / "tools" / "tracks").mkdir(parents=True)
    shutil.copy(HERE / "tracks" / "n8n.html", root / "tools" / "tracks" / "n8n.html")
    (root / "lessons").mkdir()
    (root / "lessons" / "index.html").write_text(
        "<nav></nav>\n\n<!-- b4him:track n8n (generated) -->\n<!-- /b4him:track n8n -->\n", encoding="utf-8")
    (root / ".gitignore").write_text("release_log.jsonl\n__pycache__/\n", encoding="utf-8")
    base = {"id": "G2", "order": 2, "title": "Glossary II", "stage": "SOURCE", "track": "n8n"}
    (root / "production_queue.jsonl").write_text("# q\n" + json.dumps(base) + "\n", encoding="utf-8", newline="\n")
    g(tmp_path, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.email", "t@example.invalid"), ("user.name", "t"), ("core.autocrlf", "false")):
        g(root, "config", k, v)
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", "base")
    # the draft, on its own branch
    g(root, "checkout", "-q", "-b", "draft/g2")
    (root / "lessons" / "g2").mkdir()
    (root / PAGE).write_text("<h1>Glossary II</h1>\n", encoding="utf-8", newline="\n")
    drafted = dict(base, stage="DRAFTED", page=PAGE, branch="draft/g2", reviewed={"date": "2026-10-12", "by": "other seat", "verdict": "PASS", "proof": "fixture"},
                   index_entry={"track": "n8n", "numeral": "II", "href": "/lessons/g2/", "title": "Glossary II",
                                "blurb": "More words."})
    (root / "production_queue.jsonl").write_text("# q\n" + json.dumps(drafted) + "\n", encoding="utf-8", newline="\n")
    g(root, "add", "-A")
    g(root, "commit", "-q", "-m", "draft")
    g(root, "checkout", "-q", "main")
    monkeypatch.setattr(pb, "REPO", root)
    monkeypatch.setattr(pb, "QUEUE", root / "production_queue.jsonl")
    monkeypatch.setattr(pb, "BOARD", root / "PRODUCTION_BOARD.md")
    return root


def test_offer_writes_a_tile_the_gate_can_read_and_commits_it(site):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    text = (site / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert f"### {title}\n" in text and approvals.PENDING in text and PROOF in text
    assert approvals.TITLE_RE.match(title)["commit"] == g(site, "rev-parse", "--short=7", "draft/g2")
    assert g(site, "status", "--porcelain") == ""
    with pytest.raises(approvals.ApprovalError, match="already offered"):
        approvals.offer("G2", "draft/g2", PROOF, today=MON)


def test_offer_refuses_without_a_proof_link(site):
    with pytest.raises(approvals.ApprovalError, match="proof"):
        approvals.offer("G2", "draft/g2", "", today=MON)


def test_a_tap_racks_exactly_the_tiled_commit_and_the_release_publishes_it(site):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    tiled = g(site, "rev-parse", "draft/g2")
    # the draft moves on AFTER the tile was offered: the approval must still mean the tiled bytes
    g(site, "checkout", "-q", "draft/g2")
    (site / PAGE).write_text("<h1>Glossary II, edited after the proof</h1>\n", encoding="utf-8", newline="\n")
    g(site, "commit", "-q", "-am", "later edit")
    g(site, "checkout", "-q", "main")

    led = FakeLedger()
    led.rule(title, "APPROVE")
    report = approvals.apply(today=MON, led=led)
    assert report[0].startswith("APPLIED  APPROVE  G2")
    row = next(r for r in pb.load_queue() if r["id"] == "G2")
    assert row["stage"] == "PREVIEWED" and row["approved_commit"] == tiled
    furn = "tools/tracks/n8n.html"
    assert row["approved_blobs"] == {PAGE: g(site, "rev-parse", f"{tiled}:{PAGE}"),
                                     furn: g(site, "rev-parse", f"{tiled}:{furn}")}
    assert row["approved_index_entry"] == pb.entry_sha(row["index_entry"])
    assert g(site, "rev-parse", "approved/G2") == tiled
    assert "[RULED 2026-10-12 APPROVE" in (site / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert not led.rulings_owed()                      # applied + superseded
    assert g(site, "status", "--porcelain") == ""

    day = dt.date(2026, 10, 20)                         # first Tuesday slot at least 7 days after Mon 10-12 (E00568)
    assert release.plan(dt.date(2026, 10, 16))["outcome"] == "SKIP"
    decision = release.plan(day)
    assert decision["outcome"] == "PUBLISH"
    release.apply(day, decision, push=False)
    assert (site / PAGE).read_text(encoding="utf-8") == "<h1>Glossary II</h1>\n"
    assert '<a class="mod" href="/lessons/g2/">' in (site / "lessons" / "index.html").read_text(encoding="utf-8")


def test_a_tap_racks_on_the_first_tuesday_at_least_7_days_out(site):
    # E00568: Tuesdays only. Tapped Mon 10-12: the 10-13 Tuesday is under 7 days out and skips; 10-20 is the first.
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    text = (site / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    assert "first Tuesday slot at least 7 days out" in text
    assert "Tue/Fri" not in text and "a week)" in text and "2 a week" not in text
    led = FakeLedger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  APPROVE  G2")
    board = pb.build(MON)
    assert "| **2026-10-20** Tue | Glossary II |" in board
    assert not any(line.startswith("| **") and " Fri " in line for line in board.splitlines())
    assert release.plan(dt.date(2026, 10, 16))["outcome"] == "SKIP"        # the Friday is not a release day
    assert release.plan(dt.date(2026, 10, 20))["outcome"] == "PUBLISH"
    late = pb.build(dt.date(2026, 10, 14))      # a board read on Wed 10-14: the piece was previewed 10-12, still meets 10-20
    assert "| **2026-10-20** Tue | Glossary II |" in late
    assert pb.next_slots(dt.date(2026, 10, 14), 2) == [dt.date(2026, 10, 20), dt.date(2026, 10, 27)]


def test_a_reject_marks_the_tile_and_racks_nothing(site):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = FakeLedger()
    led.rule(title, "REJECT")
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  REJECT")
    # production-line-v2 (Daniel, 2026-10-20): a reject goes back to DRAFTED with a redraft owed (it used to stay at
    # SOURCE, which is how his GC-GLOSS-2/3 notes were lost). It still racks nothing: no pins, no tag.
    row = next(r for r in pb.load_queue() if r["id"] == "G2")
    assert row["stage"] == "DRAFTED" and row["blocked_on"].startswith("REDRAFT owed:")
    assert "approved_blobs" not in row and "binding" not in row
    assert subprocess.run([GIT, "-C", str(site), "rev-parse", "-q", "--verify", "refs/tags/approved/G2"],
                          capture_output=True).returncode != 0
    assert "[RULED 2026-10-12 REJECT" in (site / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")


def test_a_ruling_it_cannot_apply_stays_owed_and_the_tree_is_restored(site):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    (site / "stray.txt").write_text("x", encoding="utf-8")
    led = FakeLedger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=MON, led=led)[0].startswith("OWED")
    assert len(led.rulings_owed()) == 1
    assert next(r for r in pb.load_queue() if r["id"] == "G2")["stage"] == "SOURCE"


def test_rulings_on_other_titles_are_ignored(site):
    led = FakeLedger()
    led.rule("MEM-5 something else entirely", "APPROVE")
    assert approvals.apply(today=MON, led=led) == []
