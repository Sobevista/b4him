"""Tests for preview.py's pure parts: tile planning, link resolution, the top-band detector, the blob hash.
No browser, no git.

    py -m pytest tools/test_preview.py -q
"""
import hashlib
import pathlib
import subprocess
import shutil
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import preview  # noqa: E402


# ---------------------------------------------------------------- tile planning

@pytest.mark.parametrize("height", [1, 844, 1999, 2000, 2001, 4000, 18151, 36302])
def test_plan_covers_height_exactly(height):
    plan = preview.plan_tiles(height, 2000)
    assert preview.tiles_cover(plan, height)
    assert sum(h for _, h in plan) == height
    assert all(0 < h <= 2000 for _, h in plan)
    assert plan[0][0] == 0 and plan[-1][0] + plan[-1][1] == height


def test_cover_rejects_gap_overlap_short_and_empty():
    assert not preview.tiles_cover([(0, 2000), (2001, 999)], 3000)    # gap
    assert not preview.tiles_cover([(0, 2000), (1999, 1001)], 3000)   # overlap
    assert not preview.tiles_cover([(0, 2000)], 3000)                 # short
    assert not preview.tiles_cover([], 0)
    assert not preview.tiles_cover([(0, 2000), (2000, 0)], 2000)      # empty tile


def test_plan_refuses_nonpositive():
    with pytest.raises(ValueError):
        preview.plan_tiles(0)


# ---------------------------------------------------------------- link resolution

FILES = {"index.html", "style.css", "lessons/index.html", "lessons/a/index.html", "lessons/b/index.html",
         "assets/logo.png"}
IDS = {"lessons/a/index.html": {"one", "two"}, "lessons/b/index.html": {"deep"}}


def res(href, page="lessons/a/index.html"):
    return preview.resolve_link(href, page, lambda p: p in FILES, lambda p: IDS.get(p, set()))


@pytest.mark.parametrize("href", ["/", "/style.css", "/lessons/", "/lessons/b/", "/lessons/b/#deep", "/lessons/b",
                                  "#one", "?x=1#two", "../b/", "../b/index.html#deep", "/assets/logo.png",
                                  "/lessons/b/index.html", "#top"])
def test_links_that_resolve(href):
    assert res(href)[0] == "ok", res(href)


@pytest.mark.parametrize("href", ["/lessons/glossary-beginner/", "/lessons/b/#nope", "#missing", "/nope.css",
                                  "../../../../etc/passwd", "/style.css#x", ""])
def test_links_that_do_not(href):
    assert res(href)[0] == "broken", res(href)


def test_external_links_are_not_judged():
    assert res("https://b4him.com/")[0] == "external"
    assert res("//cdn.example/x.js")[0] == "external"


def test_scan_finds_links_ids_and_srcset():
    links, ids = preview.scan_html('<a id="x" href="/a/">a</a><a name="n"></a><img src="/i.png" srcset="/i2.png 2x">'
                                   '<link rel="stylesheet" href="/s.css"><p id="y">')
    assert ("a", "/a/") in links and ("img", "/i.png") in links and ("img", "/i2.png") in links
    assert ("link", "/s.css") in links
    assert ids == {"x", "n", "y"}


# ---------------------------------------------------------------- top band detector

def page_image(rows=3000, seed=7):
    """A synthetic page at half CSS scale: a textured top band, then varied content."""
    rng = np.random.default_rng(seed)
    arr = np.empty((rows, 195), dtype=np.float32)
    arr[:] = 40.0
    arr[:60] = rng.uniform(0, 255, size=(60, 195))                    # logo + navigation: busy pixels
    for y in range(80, rows, 37):                                     # text lines, varied
        arr[y:y + 9] = rng.uniform(150, 230, size=(min(9, rows - y), 195))
    return arr


def test_clean_image_has_no_repeat():
    assert preview.top_band_repeats(page_image(), 60, 180) == []
    tb = preview.top_band_check(page_image())
    assert tb["status"] == preview.PASS and tb["planted_seen"]


def test_planted_repeat_is_found_where_planted():
    arr = page_image()
    arr[2048:2108] = arr[:60]                                         # the wrap: the top restarts at 4096 CSS px
    hits = preview.top_band_repeats(arr, 60, 180)
    assert [y for y, _ in hits] == [4096]
    assert preview.top_band_check(arr)["status"] == preview.FAIL


def test_detector_blind_on_flat_band_is_unknown_not_pass():
    arr = np.full((3000, 195), 40.0, dtype=np.float32)                # flat: a band matches everywhere
    tb = preview.top_band_check(arr)
    assert tb["status"] != preview.PASS


# ---------------------------------------------------------------- blob hash

@pytest.mark.skipif(not shutil.which("git"), reason="git not on PATH")
def test_blob_sha_matches_git(tmp_path):
    f = tmp_path / "x.bin"
    data = b"line one\nline two\n\x00binary"
    f.write_bytes(data)
    want = subprocess.run(["git", "hash-object", "--no-filters", str(f)], capture_output=True, text=True).stdout.strip()
    assert preview.blob_sha(data) == want
    assert preview.blob_sha(b"") == hashlib.sha1(b"blob 0\0").hexdigest()


def test_overlay_parse():
    assert preview.parse_overlay("approved/GC-GLOSS-1:lessons/glossary-beginner/index.html") == (
        "approved/GC-GLOSS-1", "lessons/glossary-beginner/index.html")
    with pytest.raises(Exception):
        preview.parse_overlay("no-colon")
