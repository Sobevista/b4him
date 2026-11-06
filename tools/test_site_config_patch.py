"""SITE-PATCH-SERVE-1 round 2: the SITE-CONFIG patch class (orchestrator, carrying Daniel's E00761 outcome).

    py -m pytest tools/test_site_config_patch.py -q

A patch row with `patch_scope: "site-config"` may pin ONLY `_config.yml` (exact path, no page), needs a stage-2
record like any non-case patch, may create the file (main has none today), and is verified live NOT by fetching
/_config.yml (Pages never serves a leading-underscore file) but by the served-surface check: every SERVED path at the
release commit answers 200 with main's bytes, and the INTERNAL sample answers 404, polled like verify_live.
Any other path in a site-config patch is refused; _config.yml in any other row is refused; a forged row claiming
site-config for a page is refused at offer, at rack and at release; patch_scope is covered by the v3 binding.
"""
import argparse
import datetime as dt
import hashlib

import pytest

import approvals
import binding
import production_board as pb
import release
import serve_surface
import v3_testkit
from test_production_line_v2 import GIT, Ledger, draft, g, init_repo, qrow, write_queue

pytestmark = pytest.mark.skipif(not GIT, reason="git not on PATH")

TUE = dt.date(2026, 10, 20)
WED = dt.date(2026, 10, 21)
PROOF = "https://claude.ai/artifact/example"
SCHEDULED = argparse.Namespace(push=False, verify_live=False, live_minutes=0)
CONFIG = "_config.yml"
GOOD = 'exclude:\n  - "*.md"\n  - "*.jsonl"\n  - boards/\n  - data/\n  - seats/\n  - "*.py"\n  - "*.cmd"\n' \
       '  - tools/*.js\n  - tools/capability_inventory/\n  - CNAME\n'
HIDES_LESSONS = GOOD + "  - lessons/\n"


def blob_of(text: str) -> str:
    data = text.encode("utf-8")
    return hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()


def stage2():
    return {"date": "2026-10-20", "by": "stage-2 reviewer seat s2r-test", "verdict": "PASS", "proof": "fixture"}


@pytest.fixture
def site(tmp_path, monkeypatch):
    root = init_repo(tmp_path, monkeypatch)
    for rel, text in {"index.html": '<link rel="stylesheet" href="/style.css"><a href="/lessons/a/">a</a>\n',
                      "style.css": "body{}\n", "RESUME.md": "# state\n", "tools/approvals.py": "x = 1\n",
                      "CNAME": "b4him.com\n"}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(text, encoding="utf-8", newline="\n")
    write_queue(root, msg="base")
    return root


def sc_row(pid="SC-1", files=(CONFIG,), **kw):
    row = {"id": pid, "kind": "patch", "patch_scope": "site-config", "order": 104, "title": "serve the site only",
           "stage": "DRAFTED", "branch": f"patch/{pid.lower()}", "files": list(files),
           "drafted_by": "builder seat b-test"}
    row.update(kw)
    return row


def offer_sc(root, row, files):
    draft(root, row, files)
    return approvals.offer(row["id"], row["branch"], PROOF, today=TUE)


# ---------------------------------------------------------------- accepted for exactly _config.yml
def test_site_config_patch_is_offered_racked_and_published_for_exactly_config_yml(site):
    title = offer_sc(site, sc_row(reviewed={**stage2(), "blobs": {CONFIG: blob_of(GOOD)}}), {CONFIG: GOOD})
    led = Ledger()
    led.rule(title, "APPROVE")
    assert approvals.apply(today=TUE, led=led)[0].startswith("APPLIED  APPROVE  SC-1")
    row = qrow("SC-1")
    assert row["approved_blobs"] == {CONFIG: blob_of(GOOD)}
    assert row["replaces_blobs"] == {CONFIG: None}          # main has no _config.yml: the patch may create it
    assert binding.problems(row) == []
    d = [x for x in release.plan_patches(WED) if x["piece"] == "SC-1"][0]
    assert d["outcome"] == "PUBLISH", d
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert (site / CONFIG).read_text(encoding="utf-8") == GOOD
    assert qrow("SC-1")["stage"] == "PUBLISHED"
    assert g(site, "status", "--porcelain") == ""


def test_site_config_patch_still_needs_a_stage_2_record(site):
    with pytest.raises(approvals.ApprovalError, match="stage-2"):
        offer_sc(site, sc_row(), {CONFIG: GOOD})


# ---------------------------------------------------------------- refused with any other file
def test_site_config_patch_with_any_other_file_is_refused(site):
    row = sc_row(files=(CONFIG, "index.html"),
                 reviewed={**stage2(), "blobs": {CONFIG: blob_of(GOOD), "index.html": blob_of("<p>new</p>\n")}})
    with pytest.raises(approvals.ApprovalError, match="only _config.yml"):
        offer_sc(site, row, {CONFIG: GOOD, "index.html": "<p>new</p>\n"})


def test_forged_site_config_row_for_a_page_is_refused_at_offer(site):
    row = sc_row(files=("index.html",), reviewed={**stage2(), "blobs": {"index.html": blob_of("<p>new</p>\n")}})
    with pytest.raises(approvals.ApprovalError, match="only _config.yml"):
        offer_sc(site, row, {"index.html": "<p>new</p>\n"})


def test_a_site_config_patch_cannot_also_be_a_page_patch(site):
    row = sc_row(page="index.html", reviewed={**stage2(), "blobs": {CONFIG: blob_of(GOOD)}})
    with pytest.raises(approvals.ApprovalError, match="page"):
        offer_sc(site, row, {CONFIG: GOOD})


def test_config_yml_in_any_other_row_is_refused(site):
    # an ordinary (case-only) patch and a content row may not carry _config.yml
    patch = {"id": "FIX-C", "kind": "patch", "patch_scope": "case-only", "order": 90, "title": "t", "stage": "DRAFTED",
             "branch": "patch/fix-c", "files": [CONFIG]}
    with pytest.raises(approvals.ApprovalError, match="site-config"):
        offer_sc(site, patch, {CONFIG: GOOD})
    content = {"id": "C-C", "order": 5, "title": "t", "stage": "DRAFTED", "branch": "draft/c-c",
               "files": ["lessons/c/index.html", CONFIG],
               "reviewed": {**stage2(), "blobs": {CONFIG: blob_of(GOOD), "lessons/c/index.html": blob_of("<p/>\n")}}}
    with pytest.raises(approvals.ApprovalError, match="site-config"):
        offer_sc(site, content, {CONFIG: GOOD, "lessons/c/index.html": "<p/>\n"})


def test_a_config_that_would_hide_a_served_page_is_refused_at_offer(site):
    row = sc_row(reviewed={**stage2(), "blobs": {CONFIG: blob_of(HIDES_LESSONS)}})
    with pytest.raises(approvals.ApprovalError, match="lessons/a/index.html"):
        offer_sc(site, row, {CONFIG: HIDES_LESSONS})


# ---------------------------------------------------------------- release refuses a forged racked row
def _store(root, text):
    src = root.parent / "blob.tmp"
    src.write_bytes(text.encode("utf-8"))
    return g(root, "hash-object", "-w", str(src))


def test_release_refuses_a_bound_site_config_row_that_pins_a_page(site):
    new = _store(site, "<p>forged</p>\n")
    row = v3_testkit.bind({"id": "SC-F", "kind": "patch", "patch_scope": "site-config", "order": 104, "title": "f",
                           "stage": "PREVIEWED", "previewed": "2026-10-20", "since": "2026-10-20",
                           "approved_blobs": {"index.html": new},
                           "replaces_blobs": {"index.html": pb.blob_sha(site / "index.html")}})
    write_queue(site, row)
    d = [x for x in release.plan_patches(WED) if x["piece"] == "SC-F"][0]
    assert d["outcome"] == "FAIL" and "only _config.yml" in d["why"], d
    release.run(SCHEDULED, WED, {"date": WED.isoformat(), "mode": "apply"})
    assert "forged" not in (site / "index.html").read_text(encoding="utf-8")


def test_release_refuses_config_yml_on_a_patch_that_is_not_site_config(site):
    blob = _store(site, GOOD)
    row = v3_testkit.bind({"id": "FIX-X", "kind": "patch", "order": 90, "title": "f", "stage": "PREVIEWED",
                           "previewed": "2026-10-20", "since": "2026-10-20", "approved_blobs": {CONFIG: blob},
                           "replaces_blobs": {CONFIG: None}})
    write_queue(site, row)
    d = [x for x in release.plan_patches(WED) if x["piece"] == "FIX-X"][0]
    assert d["outcome"] == "FAIL" and "site-config" in d["why"], d
    assert not (site / CONFIG).exists()


def test_release_refuses_a_racked_config_that_would_hide_a_page_published_since(site):
    blob = _store(site, HIDES_LESSONS)
    row = v3_testkit.bind({"id": "SC-H", "kind": "patch", "patch_scope": "site-config", "order": 104, "title": "h",
                           "stage": "PREVIEWED", "previewed": "2026-10-20", "since": "2026-10-20",
                           "approved_blobs": {CONFIG: blob}, "replaces_blobs": {CONFIG: None}})
    write_queue(site, row)
    d = [x for x in release.plan_patches(WED) if x["piece"] == "SC-H"][0]
    assert d["outcome"] == "FAIL" and "lessons/a/index.html" in d["why"], d


def test_patch_scope_site_config_is_covered_by_the_binding(site):
    blob = _store(site, GOOD)
    row = v3_testkit.bind({"id": "SC-B", "kind": "patch", "patch_scope": "site-config", "order": 104, "title": "b",
                           "stage": "PREVIEWED", "approved_blobs": {CONFIG: blob}})
    assert binding.problems(row) == []
    assert binding.problems(dict(row, patch_scope="case-only"))
    assert binding.problems({k: v for k, v in row.items() if k != "patch_scope"})
    case = v3_testkit.bind({"id": "FIX-B", "kind": "patch", "patch_scope": "case-only", "order": 90, "title": "b",
                            "stage": "PREVIEWED", "approved_blobs": {"index.html": pb.blob_sha(site / "index.html")}})
    assert binding.problems(dict(case, patch_scope="site-config")), "flipping to site-config after the tap"


# ---------------------------------------------------------------- verify: the served surface, never /_config.yml
class FakeSite:
    def __init__(self, root, internal_status=404, wrong=None, flip_after=None):
        self.root, self.internal_status, self.wrong, self.flip_after = root, internal_status, wrong, flip_after
        self.seen, self.rounds = [], 0

    def __call__(self, url):
        self.seen.append(url)
        path = url[len(serve_surface.SITE):]
        rel = path.lstrip("/")
        rel = rel + "index.html" if (rel == "" or rel.endswith("/")) else rel
        if rel in serve_surface.INTERNAL_SAMPLE_PATHS or path in serve_surface.INTERNAL_SAMPLE:
            late = self.flip_after is not None and self.seen.count(url) <= self.flip_after
            return (200, b"old") if late else (self.internal_status, b"")
        if rel == self.wrong:
            return 200, b"not main's bytes"
        f = self.root / rel
        return (200, f.read_bytes()) if f.is_file() else (404, b"")


def _published_site_config(site):
    (site / CONFIG).write_text(GOOD, encoding="utf-8", newline="\n")
    g(site, "add", "-A")
    g(site, "commit", "-q", "-m", "release")
    return g(site, "rev-parse", "HEAD"), {"id": "SC-1", "kind": "patch", "patch_scope": "site-config",
                                          "approved_blobs": {CONFIG: blob_of(GOOD)}}


def test_verify_live_for_site_config_checks_the_surface_not_config_yml(site, monkeypatch):
    commit, row = _published_site_config(site)
    fake = FakeSite(site)
    monkeypatch.setattr(serve_surface, "FETCH", fake)
    out = release.verify_live(row, 0, commit=commit)
    assert "surface" in out
    assert not any(u.endswith("/_config.yml") for u in fake.seen), fake.seen
    for must in ("https://b4him.com/", "https://b4him.com/style.css", "https://b4him.com/lessons/a/",
                 "https://b4him.com/tools/tracks/n8n.html", "https://b4him.com/RESUME.md",
                 "https://b4him.com/RESUME.html", "https://b4him.com/production_queue.jsonl",
                 "https://b4him.com/tools/approvals.py", "https://b4him.com/boards/APPROVALS_OWED.md"):
        assert must in fake.seen, (must, fake.seen)


def test_verify_fails_when_an_internal_path_is_still_served(site, monkeypatch):
    commit, row = _published_site_config(site)
    monkeypatch.setattr(serve_surface, "FETCH", FakeSite(site, internal_status=200))
    with pytest.raises(release.ReleaseError, match="RESUME.md"):
        release.verify_live(row, 0, commit=commit)


def test_verify_fails_when_a_served_page_is_not_mains_bytes(site, monkeypatch):
    commit, row = _published_site_config(site)
    monkeypatch.setattr(serve_surface, "FETCH", FakeSite(site, wrong="style.css"))
    with pytest.raises(release.ReleaseError, match="style.css"):
        release.verify_live(row, 0, commit=commit)


def test_verify_polls_until_the_pages_build_lands(site, monkeypatch):
    commit, row = _published_site_config(site)
    fake = FakeSite(site, flip_after=2)            # the internal paths answer 200 twice, then 404
    naps = []
    monkeypatch.setattr(serve_surface, "FETCH", fake)
    monkeypatch.setattr(serve_surface, "SLEEP", naps.append)
    assert "surface" in release.verify_live(row, 5, commit=commit)
    assert len(naps) == 2 and all(n == serve_surface.POLL_SECONDS for n in naps)


def test_a_content_row_still_verifies_its_own_bytes(site, monkeypatch):
    # the old path is unchanged for every other row: it fetches the pinned page, never the surface
    seen = []

    class Resp:
        def __init__(self, data):
            self.data = data

        def read(self):
            return self.data

    def urlopen(req, timeout=20):
        seen.append(req.full_url)
        return Resp((site / "index.html").read_bytes())
    monkeypatch.setattr(release.urllib.request, "urlopen", urlopen)
    row = {"id": "P", "approved_blobs": {"index.html": pb.blob_sha(site / "index.html")}}
    release.verify_live(row, 0)
    assert seen == ["https://b4him.com/index.html"]              # the existing mapping, unchanged
