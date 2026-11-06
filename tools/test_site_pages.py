"""The page list every maintenance scanner uses is the site GitHub Pages serves, and the A4 calibration fixtures (which
hold PLANTED FAULTS) are never in it, never served. Reads this checkout's git index; no network."""
import subprocess
from pathlib import Path

import linkcheck
import maint_pages
import maint_quality
import site_pages

REPO = Path(__file__).resolve().parent.parent


def tracked_html() -> list[str]:
    out = subprocess.run(["git", "-C", str(REPO), "ls-files", "-z", "--", "*.html", "*.htm"],
                         capture_output=True, check=True).stdout.decode("utf-8")
    return sorted(f for f in out.split("\0") if f)


def expected() -> list[str]:
    """Jekyll's rule (no part starting with '.' or '_'), and no calibration fixture under any name."""
    return [f for f in tracked_html()
            if not any(p.startswith((".", "_")) for p in f.split("/")) and "maint_fixtures" not in f]


def test_the_fixtures_live_where_pages_never_serves_them():
    assert (REPO / maint_quality.FIXTURES).is_dir()
    assert not site_pages.is_served(maint_quality.FIXTURES + "/index.html")
    assert not any("maint_fixtures" in f and site_pages.is_served(f) for f in tracked_html())


def test_every_scanner_counts_the_served_pages_and_no_fixture():
    want = expected()
    assert want and len(want) == len(site_pages.served_pages(REPO))
    assert site_pages.served_pages(REPO) == want
    assert linkcheck.served_pages(REPO) == want                     # W1
    assert maint_pages.served_files(REPO) == want                   # W3, Q1, Q2, A2
    assert maint_quality.served_pages(REPO) == want                 # M1, M2


def test_the_rule():
    assert site_pages.is_served("lessons/a/index.html") and site_pages.is_served("tools/tracks/n8n.html")
    assert not site_pages.is_served("_drafts/x.html") and not site_pages.is_served("tools/_maint_fixtures/x.html")
    assert not site_pages.is_served(".maint/audits/x.html")
