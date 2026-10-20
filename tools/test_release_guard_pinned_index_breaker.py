"""BREAKER for fix/release-guard-pinned-index (4e88c4f): is_release_of returns True early when the row pins
lessons/index.html. Written by the breaker seat.

    py -m pytest tools/test_release_guard_pinned_index_breaker.py -q
"""
import pytest

import release
from test_production_line_v2 import TUE, content_row, g, live, patch_row, write_queue  # noqa: F401

INDEX = "lessons/index.html"


def _origin(root, tmp_path):
    bare = tmp_path / "origin.git"
    g(tmp_path, "init", "-q", "--bare", "-b", "main", str(bare))
    g(root, "remote", "add", "origin", str(bare))
    g(root, "push", "-q", "origin", "main")


def _forge_index_commit(root, pubrow, row):
    """One unpushed commit: the lessons index rewritten to text nobody approved, and the queue line of today's
    published row edited to 'pin' that forged index blob."""
    (root / INDEX).write_text("<p>FORGED: nobody approved this text</p>\n", encoding="utf-8", newline="\n")
    forged = g(root, "hash-object", "-w", str(root / INDEX))
    row = dict(row, approved_blobs={**row["approved_blobs"], INDEX: forged})
    write_queue(root, pubrow, row, msg="PUBLISHED C1 on its Tue slot")
    return g(root, "rev-parse", "HEAD")


def test_DEFECT_a_forged_index_pin_on_todays_CONTENT_row_lets_any_index_text_ride_the_push(live, tmp_path):
    """preflight checks binding.problems only for PATCH rows. For the content row published today it trusts the
    row's approved_blobs as read from the very commit under judgment. Before 4e88c4f the index was re-rendered from
    the parent, so a forged index was refused; now one queue edit that adds the forged index blob to today's content
    row makes the early return accept the commit as 'today's release', and push_release would send it live."""
    root, old, new, pubrow = live
    c1 = content_row(root, stage="PUBLISHED", published=TUE.isoformat())
    write_queue(root, pubrow, c1, msg="C1 published today")
    _origin(root, tmp_path)
    h = _forge_index_commit(root, pubrow, c1)
    try:
        stranded = release.preflight(TUE)
    except release.ReleaseError:
        return                                          # refused: the forgery is caught
    assert h not in stranded, "a forged lessons index was accepted as today's content release"


def test_HOLDS_without_a_pin_a_forged_index_on_a_content_release_is_still_refused(live, tmp_path):
    root, old, new, pubrow = live
    c1 = content_row(root, stage="PUBLISHED", published=TUE.isoformat())
    write_queue(root, pubrow, c1, msg="C1 published today")
    _origin(root, tmp_path)
    (root / INDEX).write_text("<p>FORGED</p>\n", encoding="utf-8", newline="\n")
    write_queue(root, pubrow, c1, msg="PUBLISHED C1")
    with pytest.raises(release.ReleaseError):
        release.preflight(TUE)


def test_DEFECT_a_forged_index_pin_on_todays_PATCH_row_falls_to_the_unchecked_content_path(live, tmp_path):
    """The forged pin breaks the patch's v3 binding, so on_patch_line() says False and the row is judged as CONTENT,
    where preflight never calls binding.problems: the patch loop's binding refusal is bypassed and, with the early
    return, the forged index is accepted as today's release."""
    root, old, new, pubrow = live
    p = patch_row(old, new, stage="PUBLISHED", published=TUE.isoformat())
    write_queue(root, pubrow, p, msg="FIX-1 published today")
    _origin(root, tmp_path)
    _forge_index_commit(root, pubrow, p)
    with pytest.raises(release.ReleaseError):
        release.preflight(TUE)


def test_HOLDS_a_merge_commit_pinning_the_index_is_not_a_release(live, tmp_path):
    """The early return sits after the exactly-one-parent check, so a merge never passes."""
    root, old, new, pubrow = live
    c1 = content_row(root, stage="PUBLISHED", published=TUE.isoformat())
    write_queue(root, pubrow, c1, msg="C1 published today")
    _origin(root, tmp_path)
    g(root, "checkout", "-q", "-b", "side")
    (root / "side.txt").write_text("x\n", encoding="utf-8")
    g(root, "add", "side.txt")
    g(root, "commit", "-q", "-m", "side")
    g(root, "checkout", "-q", "main")
    (root / INDEX).write_text("<p>pinned</p>\n", encoding="utf-8", newline="\n")
    blob = g(root, "hash-object", "-w", str(root / INDEX))
    write_queue(root, pubrow, dict(c1, approved_blobs={**c1["approved_blobs"], INDEX: blob}), msg="release")
    g(root, "merge", "-q", "--no-ff", "-m", "merge side", "side")
    h = g(root, "rev-parse", "HEAD")
    assert not release.is_release_of(h, release.commit_paths(h), dict(c1, approved_blobs={**c1["approved_blobs"],
                                                                                            INDEX: blob}))
