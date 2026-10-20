"""BREAKER round 2 for fix/release-guard-pinned-index (ea2a60f): preflight's content path now requires
binding.problems(row) == [] for the row judged as today's stranded release. Written by the breaker seat.

    py -m pytest tools/test_release_guard_r2_breaker.py -q
"""
import json

import pytest

import binding
import production_board as pb
import release
import v3_testkit
from test_production_line_v2 import SCHEDULED, TUE, g, live, write_queue  # noqa: F401

FURN = "tools/tracks/n8n.html"
INDEX = "lessons/index.html"
C1_PAGE = "lessons/c1/index.html"
ENTRY = {"track": "n8n", "numeral": "I", "href": "/lessons/c1/", "title": "Content one", "blurb": "What he approved."}


def _racked_listed_c1(root):
    src = root.parent / "c1.html"
    src.write_bytes(b"<h1>C1</h1>\n")
    return v3_testkit.bind({"id": "C1", "order": 3, "title": "Content one", "stage": "PREVIEWED",
                            "previewed": "2026-10-01",
                            "approved_blobs": {C1_PAGE: g(root, "hash-object", "-w", str(src)),
                                               FURN: pb.blob_sha(root / FURN)},
                            "index_entry": ENTRY, "approved_index_entry": pb.entry_sha(ENTRY)})


def _origin(root, tmp_path):
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")


def _stranded_release(root, tmp_path, pubrow):
    write_queue(root, pubrow, _racked_listed_c1(root), msg="C1 racked")
    _origin(root, tmp_path)
    d = release.plan(TUE)
    assert d["outcome"] == "PUBLISH" and d["piece"] == "C1", d
    return release.apply(TUE, d)                        # committed, not pushed: stranded


def test_HOLDS_a_genuine_stranded_listed_content_release_is_recognised(live, tmp_path):
    root, old, new, pubrow = live
    h = _stranded_release(root, tmp_path, pubrow)
    assert release.preflight(TUE) == [h]


def test_DEFECT_a_stranded_release_amended_to_change_the_index_entry_text_passes_the_binding_check(live, tmp_path):
    """The v3 digest covers approved_index_entry (a hash) but not index_entry, and preflight never re-checks
    entry_sha(index_entry) == approved_index_entry (plan() does, via pin_problems). Amend the stranded release so the
    queue's blurb says something Daniel never approved and re-render the index from it: is_release_of re-renders from
    the commit's own queue, so it matches; binding.problems is []; the forged listing text is pushed as 'today's
    release'."""
    root, old, new, pubrow = live
    _stranded_release(root, tmp_path, pubrow)
    lines = pb.QUEUE.read_text(encoding="utf-8").split("\n")
    rows = []
    for i, l in enumerate(lines):
        if l.strip().startswith("{") and json.loads(l).get("id") == "C1":
            r = json.loads(l)
            r["index_entry"] = dict(r["index_entry"], blurb="FORGED: a blurb Daniel never saw")
            lines[i] = json.dumps(r, ensure_ascii=False)
    pb.QUEUE.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    idx = root / INDEX
    parent_index = g(root, "show", f"HEAD~1:{INDEX}")
    idx.write_text(release.render_tracks(parent_index + "\n", [x for x in pb.load_queue() if not x.get("_broken")]),
                   encoding="utf-8", newline="\n")
    assert "FORGED" in idx.read_text(encoding="utf-8")
    g(root, "add", "-A")
    g(root, "commit", "-q", "--amend", "--no-edit")
    h = g(root, "rev-parse", "HEAD")
    c1 = next(x for x in pb.load_queue() if x.get("id") == "C1")
    assert binding.problems(c1) == []                    # the binding does not see the entry text
    try:
        stranded = release.preflight(TUE)
    except release.ReleaseError:
        return
    assert h not in stranded, "a forged lessons-index blurb was accepted as today's stranded release"


def test_HOLDS_a_furniture_repin_label_leaves_a_racked_rows_binding_intact(live):
    root, old, new, pubrow = live
    c1 = _racked_listed_c1(root)
    c1["furniture_repinned_by"] = {FURN: "SITE-PATCH-HEADINGS-2 (tapped 2026-10-20; takes effect when it publishes)"}
    assert binding.problems(c1) == []


def test_HOLDS_two_content_rows_published_today_with_a_stranded_release_is_refused(live, tmp_path):
    root, old, new, pubrow = live
    h = _stranded_release(root, tmp_path, pubrow)
    rows = [x for x in pb.load_queue() if not x.get("_broken")]
    extra = {"id": "C9", "order": 9, "title": "C9", "stage": "PUBLISHED", "published": TUE.isoformat()}
    pb.QUEUE.write_text("# q\n" + "".join(json.dumps(r) + "\n" for r in rows + [extra]), encoding="utf-8",
                        newline="\n")
    g(root, "commit", "-q", "-am", "a second row says published today")
    with pytest.raises(release.ReleaseError):
        release.preflight(TUE)
