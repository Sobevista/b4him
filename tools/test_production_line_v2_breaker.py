"""BREAKER for build/production-line-v2 (head 970bd56). Written by the independent breaker seat, not the builder.

    py -m pytest tools/test_production_line_v2_breaker.py -q

Daniel's rulings of 2026-10-20 under attack:
  (a) a REJECT carries his note onto the queue and sends the piece back to redraft: never dropped;
  (b) release.py refuses rows with an open blocked_on;
  (c) site patches are a separate line outside the content cadence; content stays Tuesdays, 1 per 7 days;
  (d) stage 2 (the independent name check) happens BEFORE his tap.

Naming: test_DEFECT_* is a real defect and stays RED until the build fixes it. test_HOLDS_* is an attack the build
survives (green), kept so a regression turns it red.
"""
import datetime as dt
import json
import subprocess

import pytest

import approvals
import binding
import production_board as pb
import release
import v3_testkit
from test_production_line_v2 import (  # noqa: F401  (fixtures are used by name)
    MON, NOTE, PAGE, PROOF, SCHEDULED, STAGE2, TUE, WED, FURN, GLOSS_PAGE, G1_ENTRY,
    Ledger, draft, g, g2, glossary_live, init_repo, live, log_lines, patch_row, content_row, qrow, write_queue,
)

NEXT_TUE = dt.date(2026, 10, 27)


# ================================================================ (d) stage 2: the phrase gate accepts fakes
@pytest.fixture
def drafted(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    write_queue(root, msg="base")
    n = {"i": 0}

    def make(**row):
        n["i"] += 1
        pid = f"T{n['i']}"
        r = {"id": pid, "order": 7, "title": pid, "stage": "DRAFTED", "branch": f"draft/{pid.lower()}",
             "page": f"lessons/{pid.lower()}/index.html", **row}
        draft(root, r, {r["page"]: f"<h1>{pid}</h1>\n"})
        return pid, r["branch"]
    return root, make


FAKE_STAGE2 = [
    "stage 2 not done",
    "Stage 2: NOT YET",
    "pending stage 2",
    "stage 2 FAILED: two real names found",
    "no stage-2 review yet",
    "awaiting the other seat",
    "the other seat did not write anything yet",
    " NOT  YET - stage 2",
]


@pytest.mark.parametrize("fake", FAKE_STAGE2)
def test_DEFECT_stage2_gate_accepts_a_reviewed_field_that_says_stage2_was_not_done(drafted, fake):
    """Ruling (d): stage 2 happens before his tap. STAGE2_RE matches the bare words 'stage 2' / 'other seat' /
    'did not write' anywhere, and only a leading 'NOT YET' is refused, so text that says stage 2 is NOT done (or
    FAILED) puts a tile in front of Daniel."""
    root, make = drafted
    pid, ref = make(reviewed=fake)
    with pytest.raises(approvals.ApprovalError):
        approvals.offer(pid, ref, PROOF, today=MON)


@pytest.mark.parametrize("ok", ["NOT YET stage 2", "not yet: stage 2 queued", ""])
def test_HOLDS_stage2_gate_refuses_not_yet_prefix_and_empty(drafted, ok):
    root, make = drafted
    pid, ref = make(reviewed=ok)
    with pytest.raises(approvals.ApprovalError):
        approvals.offer(pid, ref, PROOF, today=MON)


# ================================================================ (d)+(c) the layout-only exemption is provable-false
BASE = ('<!doctype html><html><head><title>Page P</title><meta name="description" content="About P"></head>'
        '<body><nav><a href="/">Home</a></nav><main><h1>The twenty</h1><p>Words.</p>'
        '<img src="/a.png" alt="a chart"><abbr title="plain">P</abbr></main><footer>b4him</footer></body></html>\n')
HIDDEN_TEXT_CHANGES = {
    "title-element": BASE.replace("<title>Page P</title>", "<title>Page P, by Jane Roe</title>"),
    "css-content": BASE.replace("</head>", '<style>h1::before{content:"Jane Roe says "}</style></head>'),
    "img-alt": BASE.replace('alt="a chart"', 'alt="Jane Roe at her desk"'),
    "title-attribute": BASE.replace('title="plain"', 'title="what Jane Roe calls it"'),
    "nav-text": BASE.replace(">Home<", ">Jane Roe<"),
    "footer-text": BASE.replace("<footer>b4him</footer>", "<footer>written with Jane Roe</footer>"),
    "meta-description": BASE.replace('content="About P"', 'content="Jane Roe"'),
    "script-text": BASE.replace("</body>", '<script>document.querySelector("h1").textContent="Jane Roe"</script></body>'),
}


@pytest.fixture
def layout(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    (root / PAGE).parent.mkdir(parents=True)
    (root / PAGE).write_text(BASE, encoding="utf-8", newline="\n")
    write_queue(root, {"id": "P", "order": 1, "title": "Page P", "stage": "PUBLISHED", "published": "2026-10-06",
                       "approved_blobs": {PAGE: pb.blob_sha(root / PAGE)}}, msg="base")
    return root


@pytest.mark.parametrize("channel", sorted(HIDDEN_TEXT_CHANGES))
def test_DEFECT_layout_only_exemption_lets_reader_visible_text_change_without_stage2(layout, channel):
    """A 'layout-only' patch skips stage 2 when voice_check.visible_text is unchanged. That function drops <head>
    (title, meta), <style> (CSS content:), <script>, <nav>/<header>/<footer>, and every attribute (alt, title). Each
    of those is text a reader sees (people_registry.visible_text itself keeps alt/title 'because it is shown to
    readers'), so a NAME can reach the live site with no stage-2 name check and on the any-day patch line."""
    draft(layout, {"id": "FIX-X", "kind": "patch", "order": 90, "title": "layout", "stage": "DRAFTED",
                   "page": PAGE, "branch": "draft/fix-x", "patch_scope": "layout-only"},
          {PAGE: HIDDEN_TEXT_CHANGES[channel]})
    with pytest.raises(approvals.ApprovalError):
        approvals.offer("FIX-X", "draft/fix-x", PROOF, today=MON)


def test_DEFECT_layout_only_patch_can_add_a_lessons_index_listing_without_stage2(layout):
    """The exemption proves only piece_files; an index_entry (new reader-visible text in the lessons index) and the
    track furniture it pins ride along unchecked."""
    entry = {"track": "n8n", "numeral": "IX", "href": "/lessons/p/", "title": "Jane Roe's page", "blurb": "Jane Roe."}
    draft(layout, {"id": "FIX-I", "kind": "patch", "order": 90, "title": "layout", "stage": "DRAFTED", "page": PAGE,
                   "branch": "draft/fix-i", "patch_scope": "layout-only", "index_entry": entry},
          {PAGE: BASE.replace("<main>", '<main class="wide">')})
    with pytest.raises(approvals.ApprovalError):
        approvals.offer("FIX-I", "draft/fix-i", PROOF, today=MON)


# ================================================================ (c) content masquerading as a patch
def test_DEFECT_a_patch_that_adds_a_new_page_publishes_on_a_wednesday_outside_the_cadence(tmp_path, monkeypatch):
    """Ruling (c): the patch line is for fixes to already-published pages and site furniture. Nothing checks that a
    kind:"patch" row only touches paths main already serves: a brand-new lesson page (with an index listing) labelled
    patch is offered, tapped and published on a Wednesday, skipping the Tuesday slot and the 1-per-7-days cap."""
    root = init_repo(tmp_path, monkeypatch)
    write_queue(root, msg="base")
    new = "lessons/new/index.html"
    entry = {"track": "n8n", "numeral": "IX", "href": "/lessons/new/", "title": "A whole new lesson", "blurb": "New."}
    draft(root, {"id": "FIX-NEW", "kind": "patch", "order": 90, "title": "A whole new lesson", "stage": "DRAFTED",
                 "page": new, "branch": "draft/fix-new", "reviewed": STAGE2, "index_entry": entry},
          {new: "<h1>A whole new lesson</h1>\n"})
    try:
        title = approvals.offer("FIX-NEW", "draft/fix-new", PROOF, today=MON)
    except approvals.ApprovalError:
        return                                          # refused at the offer: the masquerade is caught
    led = Ledger()
    led.rule(title, "APPROVE")
    if not approvals.apply(today=MON, led=led)[0].startswith("APPLIED"):
        return
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert not (root / new).exists(), "a new page went live on a Wednesday as a 'patch'"


def test_DEFECT_flipping_a_published_content_row_to_patch_frees_the_slot_and_the_cap(live):
    """Once PUBLISHED, `kind` is read by plan() to decide 'already published today' and the 7-day cap, but nothing
    re-checks the published row's binding. One queue edit (kind -> patch) on today's piece lets a second content
    piece publish the same Tuesday."""
    root, old, new, pubrow = live
    c1 = content_row(root)
    c1.update(stage="PUBLISHED", published=TUE.isoformat())
    src = root.parent / "c2.html"
    src.write_bytes(b"<h1>C2</h1>\n")
    c2 = v3_testkit.bind({"id": "C2", "order": 4, "title": "C2", "stage": "PREVIEWED", "previewed": "2026-10-01",
                          "approved_blobs": {"lessons/c2/index.html": g(root, "hash-object", "-w", str(src))}})
    write_queue(root, pubrow, c1, c2)
    assert release.plan(TUE)["outcome"] == "SKIP"          # control: one slot, one piece
    write_queue(root, pubrow, dict(c1, kind="patch"), c2, msg="relabel today's piece")
    assert release.plan(TUE)["outcome"] != "PUBLISH", "a relabelled published row freed the content slot"


def test_HOLDS_flipping_a_racked_content_row_to_patch_after_the_tap_publishes_nothing(live):
    root, old, new, pubrow = live
    c = content_row(root)
    write_queue(root, pubrow, dict(c, kind="patch"))
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert not (root / "lessons" / "c1").exists()
    lines = [l for l in log_lines(root) if l.get("lane") == "patch"]
    assert lines and lines[-1]["outcome"] == "FAIL" and "UNVERIFIED" in lines[-1]["why"], lines


# ================================================================ re-pin (supersedes_pins)
def test_DEFECT_a_patch_silently_discards_a_racked_revisions_approved_bytes(live):
    """A REVISION of page P is racked (approved 10-14). A case-fix patch on P (based on the old bytes) is tapped and
    publishes Wednesday. On the next Tuesday the revision 'publishes': superseding_patch() treats its pin on P as
    superseded, so release keeps the patch's bytes, marks the revision PUBLISHED, and the text Daniel approved never
    goes live. Only a 'Re-pin: keeps' line in the commit body says so; board and drift report nothing."""
    root, old, new, pubrow = live
    src = root.parent / "rev.html"
    src.write_bytes(b"<h1>The twenty, rewritten</h1>\n<p>New section.</p>\n")
    rev = g(root, "hash-object", "-w", str(src))
    c2 = v3_testkit.bind({"id": "C2", "order": 3, "title": "Page P revised", "kind": pb.REVISION,
                          "stage": "PREVIEWED", "previewed": "2026-10-14", "approved_blobs": {PAGE: rev}})
    write_queue(root, pubrow, c2, patch_row(old, new))
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert qrow("FIX-1")["stage"] == "PUBLISHED"
    entry = {"date": NEXT_TUE.isoformat(), "mode": "apply"}
    release.run(SCHEDULED, NEXT_TUE, entry)
    published = qrow("C2")["stage"] == "PUBLISHED"
    assert not (published and pb.blob_sha(root / PAGE) != rev), (
        "C2 is PUBLISHED but the page holds the patch's bytes, not the revision Daniel approved")


def test_DEFECT_content_drafted_before_a_patch_but_tapped_after_it_reverts_the_patch(glossary_live):
    """A furniture patch publishes 10-21. A content piece whose draft pinned the PRE-patch furniture is tapped 10-22
    (after the patch) and released 10-27: it is 'newer' by approval date, so it is not superseded, and the release
    writes the old furniture back over the fix: the patch is silently undone."""
    root, g1, old_furn, old_page = glossary_live
    furn_text = (root / FURN).read_text(encoding="utf-8")
    fixed = furn_text.replace("track", "Track", 1)
    src = root.parent / "furn.html"
    src.write_text(fixed, encoding="utf-8", newline="\n")
    new_furn = g(root, "hash-object", "-w", str(src))
    fix = v3_testkit.bind({"id": "FIX-F", "kind": "patch", "order": 90, "title": "Track case", "stage": "PREVIEWED",
                           "previewed": "2026-10-20", "since": "2026-10-20", "approved_blobs": {FURN: new_furn},
                           "replaces_blobs": {FURN: old_furn}})
    write_queue(root, g1, fix)
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert pb.blob_sha(root / FURN) == new_furn
    src = root.parent / "c3.html"
    src.write_bytes(b"<h1>Three</h1>\n")
    c3_entry = {**G1_ENTRY, "numeral": "III", "href": "/lessons/three/", "title": "Three"}
    c3 = v3_testkit.bind({"id": "C3", "order": 3, "title": "Three", "stage": "PREVIEWED", "previewed": "2026-10-22",
                          "approved_blobs": {"lessons/three/index.html": g(root, "hash-object", "-w", str(src)),
                                             FURN: old_furn},
                          "index_entry": c3_entry, "approved_index_entry": pb.entry_sha(c3_entry)})
    write_queue(root, *[r for r in pb.load_queue() if r.get("id") != "C3"], c3, msg="C3 racked")
    release.run(SCHEDULED, dt.date(2026, 11, 3), {"date": "2026-11-03", "mode": "apply"})
    assert pb.blob_sha(root / FURN) == new_furn, "the patch's fix to the furniture was reverted by an older draft"


def test_DEFECT_two_racked_patches_on_shared_furniture_the_second_erases_the_first(glossary_live):
    """Two patches, both tapped against the same furniture bytes, fix different words. FIX-A publishes; FIX-B's
    replaces_blobs no longer matches, but the tree holds 'approved' bytes and furniture is replaceable, so FIX-B
    overwrites FIX-A's fix in the same run with no refusal."""
    root, g1, old_furn, old_page = glossary_live
    text = (root / FURN).read_text(encoding="utf-8")
    assert "track" in text
    a_text = text.replace("track", "TRACK-A-FIX", 1)
    b_text = text + "<!-- B-FIX -->\n"
    blobs = {}
    for k, t in (("a", a_text), ("b", b_text)):
        p = root.parent / f"{k}.html"
        p.write_text(t, encoding="utf-8", newline="\n")
        blobs[k] = g(root, "hash-object", "-w", str(p))
    fa = v3_testkit.bind({"id": "FIX-A", "kind": "patch", "order": 90, "title": "A", "stage": "PREVIEWED",
                          "previewed": "2026-10-19", "since": "2026-10-19", "approved_blobs": {FURN: blobs["a"]},
                          "replaces_blobs": {FURN: old_furn}})
    fb = v3_testkit.bind({"id": "FIX-B", "kind": "patch", "order": 91, "title": "B", "stage": "PREVIEWED",
                          "previewed": "2026-10-20", "since": "2026-10-20", "approved_blobs": {FURN: blobs["b"]},
                          "replaces_blobs": {FURN: old_furn}})
    write_queue(root, g1, fa, fb)
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    final = (root / FURN).read_text(encoding="utf-8")
    assert not (qrow("FIX-A")["stage"] == "PUBLISHED" and "TRACK-A-FIX" not in final), \
        "FIX-A is recorded PUBLISHED but FIX-B wrote the furniture back without A's fix"


def test_HOLDS_two_racked_patches_on_one_page_the_second_is_refused_and_logged(live):
    root, old, new, pubrow = live
    p = root.parent / "b.html"
    p.write_bytes(b"<h1>The twenty!</h1>\n")
    other = g(root, "hash-object", "-w", str(p))
    write_queue(root, pubrow, patch_row(old, new),
                patch_row(old, other, id="FIX-2", order=91, since="2026-10-20", previewed="2026-10-20"))
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert pb.blob_sha(root / PAGE) == new
    fails = [l for l in log_lines(root) if l.get("lane") == "patch" and l.get("piece") == "FIX-2"]
    assert fails and fails[-1]["outcome"] == "FAIL", fails


# ================================================================ (a) REJECT
ODD_NOTE = 'He said "no" — "The twenty" | pipes | Ünïcödé ✓ \U0001F600\nline two: back\\slash'


def test_HOLDS_reject_note_with_quotes_newlines_unicode_survives_queue_ledger_board(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    ev = led.rule(title, "REJECT", ODD_NOTE)
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  REJECT  G2")
    assert qrow("G2")["blocked_on"] == f"REDRAFT owed: {ev['id']} {ODD_NOTE}"
    assert led.applied()[-1]["body"]["note"] == ODD_NOTE
    assert ODD_NOTE in led.applied()[-1]["body"]["binds"]
    flat = " ".join(ODD_NOTE.split())
    board = (g2 / "PRODUCTION_BOARD.md").read_text(encoding="utf-8")
    assert flat.replace("|", "\\|") in board
    assert " ".join(ODD_NOTE.splitlines()) in (g2 / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
    body = g(g2, "log", "-1", "--format=%B")
    assert all(line in body for line in ODD_NOTE.splitlines())


def test_HOLDS_two_owed_rulings_on_one_tile_latest_wins_and_the_other_never_racks(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    led.rule(title, "APPROVE")
    led.rule(title, "REJECT", "changed my mind")
    approvals.apply(today=MON, led=led)
    assert qrow("G2")["stage"] == "DRAFTED"
    again = approvals.apply(today=MON, led=led)            # the stale APPROVE is still owed
    assert again and again[0].startswith("OWED"), again
    assert qrow("G2")["stage"] == "DRAFTED" and "approved_blobs" not in qrow("G2")
    assert g(g2, "status", "--porcelain") == ""


def test_DEFECT_a_reject_tapped_after_an_applied_approve_is_left_owed_and_the_piece_still_publishes(g2):
    """Ruling (a): a REJECT sends the piece back to redraft, never dropped. Daniel approves G2, it is racked; he then
    REJECTs the same tile with a note. apply() refuses it ('no pending marker'), reports it OWED, and nothing stops
    release: G2 publishes on Tuesday over his later REJECT."""
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    led = Ledger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=MON, led=led)[0].startswith("APPLIED  APPROVE")
    led.rule(title, "REJECT", NOTE)
    approvals.apply(today=MON, led=led)
    d = release.plan(NEXT_TUE)
    assert not (d["outcome"] == "PUBLISH" and d.get("piece") == "G2"), \
        f"G2 publishes despite his later REJECT: queue stage {qrow('G2')['stage']}, owed {led.rulings_owed()}"


def test_HOLDS_reject_of_a_published_piece_is_left_owed_and_unpublishes_nothing(g2):
    title = approvals.offer("G2", "draft/g2", PROOF, today=MON)
    write_queue(g2, {"id": "G2", "order": 2, "title": "Glossary II", "stage": "PUBLISHED", "published": "2026-10-13"},
                msg="live")
    led = Ledger()
    led.rule(title, "REJECT", ODD_NOTE)
    r = approvals.apply(today=MON, led=led)
    assert r[0].startswith("OWED") and qrow("G2")["stage"] == "PUBLISHED" and led.rulings_owed()


# ================================================================ blocked_on survives the tap?
@pytest.fixture
def gated(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    write_queue(root, msg="base")

    def make(label):
        row = {"id": "T9", "order": 5, "title": "T9", "stage": "DRAFTED", "page": "lessons/t9/index.html",
               "branch": "draft/t9", "blocked_on": label, "reviewed": STAGE2}
        draft(root, row, {"lessons/t9/index.html": "<h1>t9</h1>\n"})
        title = approvals.offer("T9", "draft/t9", PROOF, today=dt.date(2026, 10, 12))
        tile = (root / "boards" / "APPROVALS_OWED.md").read_text(encoding="utf-8")
        led = Ledger()
        led.rule(title, "APPROVE")
        approvals.apply(today=dt.date(2026, 10, 12), led=led)
        return tile, qrow("T9")
    return root, make


def test_DEFECT_a_tap_erases_a_blocked_on_gate_the_tile_never_showed_him(gated):
    """The tile omits blocked_on entirely, yet the tap clears every label not starting exactly 'POST-APPROVAL:'.
    A real gate (written permission to name someone) is erased by a tap on a tile that never mentioned it."""
    root, make = gated
    label = "PERMISSION: written OK from the client named in section 3, not yet received"
    tile, row = make(label)
    assert label in tile or row.get("blocked_on") == label, \
        f"gate erased by a tap on a tile that never showed it; row now: cleared_blocked_on={row.get('cleared_blocked_on')!r}"


def test_DEFECT_post_approval_prefix_is_case_sensitive_so_a_lowercase_gate_is_erased(gated):
    root, make = gated
    tile, row = make("post-approval: wait for the course page to go live first")
    assert row.get("blocked_on"), "a post-approval gate spelled in lower case was cleared by the tap"


# ================================================================ (b)+(c) release: push and logging
def test_HOLDS_patch_and_content_same_tuesday_push_only_release_commits(live, tmp_path):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new), content_row(root))
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")
    before = g(root, "rev-parse", "HEAD")
    import argparse
    args = argparse.Namespace(push=True, verify_live=False, live_minutes=0)
    with release.scheduled_entry(TUE):
        assert release.run(args, TUE, {"date": TUE.isoformat(), "mode": "apply"}) == 0
    pushed = g(root, "log", "--format=%s", f"{before}..origin/main").splitlines()
    assert len(pushed) == 2 and pushed[0].startswith("PUBLISHED C1") and pushed[1].startswith("PATCHED FIX-1"), pushed


def test_HOLDS_an_unrelated_unpushed_commit_stops_a_patch_push_and_is_logged(live, tmp_path):
    root, old, new, pubrow = live
    write_queue(root, pubrow, patch_row(old, new))
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")
    (root / "lessons" / "a" / "index.html").write_text("<p>sneak</p>\n", encoding="utf-8", newline="\n")
    g(root, "commit", "-q", "-am", "sneak")
    import argparse
    args = argparse.Namespace(push=True, verify_live=False, live_minutes=0)
    entry = {"date": WED.isoformat(), "mode": "apply"}
    with release.scheduled_entry(WED):
        with pytest.raises(release.ReleaseError):
            release.run(args, WED, entry)
    assert "sneak" not in g(bare, "log", "--format=%s", "main")
