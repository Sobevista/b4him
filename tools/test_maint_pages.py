"""Tests for maint_pages.py and maint_receipt.py (maintenance calendar rows W3, Q2, Q1, Q3, M4, A2). No network.

    py -m pytest tools/test_maint_pages.py -q

Every row shows its PASS (or SKIP), FINDINGS and UNKNOWN paths on a throwaway git repo built per test. The names in
these fixtures are invented (no real person, no real client).
"""
import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import maint_pages as mp  # noqa: E402
import maint_receipt as mr  # noqa: E402
import people_registry as pr  # noqa: E402
import production_board as pb  # noqa: E402

REAL = Path(__file__).resolve().parent.parent
TODAY = dt.date(2026, 10, 31)

D11 = ("## D11 — Publishing the Lessons: curated + genericized. LOCKED 2026-07-21\n\n"
       "- **Genericization is a hard rule, applied consistently.** Product/project names → generic: Zorblax → \"a tool "
       "I built\". Collaborator → generic: Quendrith → \"a teammate\". `Vexmoor-rig` → \"a machine\".\n\n"
       "## D12 — Later. LOCKED 2026-09-01\n\nText.\n\n## D13 — End\n")
CLEAN = "<html><head><title>{t}</title></head><body><main><p>i write here about my work and what i learn.</p>{b}</main></body></html>"


def page(title, body=""):
    return CLEAN.format(t=title, b=body)


def g(repo, *args):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid", *args],
                          capture_output=True, check=True).stdout.decode("utf-8")


def make_repo(tmp_path, files=None, queue=None):
    repo = tmp_path / "site"
    (repo / "data").mkdir(parents=True)
    for f in ("people_registry.json", "common_first_names.txt"):
        shutil.copy(REAL / "data" / f, repo / "data" / f)
    base = {
        ".gitignore": ".maint/\ndata/people_names.local.json\ndata/forbidden_tokens.local.json\n",
        "CNAME": "example.invalid\n",
        "DECISIONS.md": D11,
        "index.html": page("Home", '<a href="/lessons/">Lessons</a>'),
        "lessons/index.html": page("Lessons", '<a href="/lessons/find-your-door/">Take the quiz</a>'
                                   '<h2 id="lessons-list">Tier One</h2><a class="mod" href="/lessons/alpha/">Alpha</a>'),
        "lessons/find-your-door/index.html": page("Door", "<script>x='<a href=\"/lessons/#lessons-list\">Start</a>'"
                                                  "</script>"),
        "lessons/alpha/index.html": page("Alpha", "<p>a plain lesson about checking the work, by hand, each time.</p>"),
        "_hidden/secret.html": page("Hidden", "<p>Zorblax</p>"),
    }
    base.update(files or {})
    for rel, text in base.items():
        if text is None:
            continue
        p = repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8", newline="\n")
    rows = queue if queue is not None else [
        {"id": "C-1", "title": "Alpha", "stage": "PUBLISHED", "page": "lessons/alpha/index.html",
         "published": "2026-10-20"},
        {"id": "P-1", "title": "Headings", "stage": "PUBLISHED", "kind": "patch", "published": "2026-10-20",
         "files": ["index.html", "lessons/index.html", "lessons/find-your-door/index.html"]},
        {"id": "P-2", "title": "Shelf", "stage": "DRAFTED", "kind": "patch", "drafted": "2026-10-20",
         "since": "2026-10-20", "drafted_by": "site maintainer agent"},
    ]
    (repo / "production_queue.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8",
                                                 newline="\n")
    g(repo, "init", "-q")
    g(repo, "add", "-A")
    g(repo, "commit", "-q", "-m", "fixture")
    return repo


def local_names(repo, names=("Quillon",), role="client"):
    (repo / "data" / "people_names.local.json").write_text(
        json.dumps({"people": [{"label": "PERSON-X", "role": role, "names": list(names)}]}), encoding="utf-8")


def log(repo, row=None):
    recs = mr.read_jsonl(repo / ".maint" / mr.LOG_NAME)
    return [r for r in recs if row is None or r["row"] == row]


def findings(repo, row=None):
    recs = mr.read_jsonl(repo / ".maint" / mr.FINDINGS_NAME)
    return [r for r in recs if row is None or r["row"] == row]


def nongit(tmp_path):
    d = tmp_path / "not-a-repo"
    d.mkdir()
    return d


# ------------------------------------------------------------------------------------------------- maint_receipt
def test_receipt_shape_and_refusals(tmp_path):
    r = mr.write_receipt("W3", "UNKNOWN", why="no names", evidence=".maint/x", tool="t.py", root=tmp_path)
    assert set(r) == {"at", "row", "outcome", "n", "why", "evidence", "tool"}
    assert json.loads((tmp_path / ".maint" / "maintenance_log.jsonl").read_text(encoding="utf-8")) == r
    for bad in (("W3", "OK"), ("W3", "FINDINGS")):          # not an outcome; FINDINGS without n
        with pytest.raises(ValueError):
            mr.write_receipt(*bad, root=tmp_path)
    with pytest.raises(ValueError):
        mr.write_receipt("W3", "UNKNOWN", root=tmp_path)     # an UNKNOWN says why
    f = mr.write_finding("W3", "S1", "s", "d", "r", root=tmp_path)
    assert set(f) == {"at", "row", "severity", "subject", "detail", "route_to"}
    with pytest.raises(ValueError):
        mr.write_finding("W3", "S9", "s", "d", "r", root=tmp_path)


def test_served_pages_skip_dot_and_underscore_paths(tmp_path):
    repo = make_repo(tmp_path)
    s = mp.served_files(repo)
    assert "_hidden/secret.html" not in s and "index.html" in s and len(s) == 4


def test_runs_leave_the_tree_clean(tmp_path):
    repo = make_repo(tmp_path)
    for c in (mp.cmd_people, mp.cmd_genericize, mp.cmd_reread, mp.cmd_hygiene, mp.cmd_walk, mp.cmd_inventory):
        c(repo, TODAY)
    assert g(repo, "status", "--porcelain") == ""          # everything went under the ignored .maint/
    assert (repo / ".maint" / "audits").is_dir()


# ------------------------------------------------------------------------------------------------------ W3 people
def test_w3_unknown_without_the_names_file(tmp_path):
    repo = make_repo(tmp_path)
    recs = mp.cmd_people(repo, TODAY)
    assert len(recs) == 5 and all(r["row"] == "W3" for r in recs)          # one per page + the summary
    assert recs[-1]["outcome"] == "UNKNOWN" and "people_names.local.json absent" in recs[-1]["why"]
    assert all(r["outcome"] == "UNKNOWN" for r in recs[:-1])
    assert recs[-1]["evidence"] == ".maint/audits/2026-10-31_people.json"


def test_w3_pass_with_the_names_file_and_clean_pages(tmp_path):
    repo = make_repo(tmp_path)
    local_names(repo)
    recs = mp.cmd_people(repo, TODAY)
    assert [r["outcome"] for r in recs] == ["PASS"] * 5
    assert mp.main(["--repo", str(repo), "people"]) == 0


def test_w3_findings_route_s1_and_heuristic(tmp_path):
    repo = make_repo(tmp_path, {"about/index.html": page("About", "<p>i met Quillon there.</p>"
                                                         "<p>i asked Peregrine Farquharson once.</p>")})
    local_names(repo)
    recs = mp.cmd_people(repo, TODAY)
    assert recs[-1]["outcome"] == "FINDINGS" and recs[-1]["n"] == 2
    about = next(r for r in recs if r["why"].startswith("about/index.html"))
    assert about["outcome"] == "FINDINGS" and about["n"] == 2
    routes = {f["subject"]: (f["severity"], f["route_to"]) for f in findings(repo, "W3")}
    assert routes["about/index.html: known-outside-rule"] == ("S1", mp.S1_ROUTE)
    assert routes["about/index.html: unknown-name"] == ("S1", mp.HEURISTIC_ROUTE)
    assert mp.main(["--repo", str(repo), "people"]) == 1


def test_w3_unreadable_registry_is_unknown(tmp_path):
    repo = make_repo(tmp_path)
    (repo / "data" / "people_registry.json").write_text("{not json", encoding="utf-8")
    recs = mp.cmd_people(repo, TODAY)
    assert recs[-1]["outcome"] == "UNKNOWN" and "could not run" in recs[-1]["why"]


def test_w3_exit_mapping_matches_the_people_registry_cli(tmp_path, monkeypatch):
    repo = make_repo(tmp_path)
    d = repo / "data"
    monkeypatch.setattr(pr, "REGISTRY_FILE", d / "people_registry.json")
    monkeypatch.setattr(pr, "LOCAL_NAMES_FILE", d / "people_names.local.json")
    monkeypatch.setattr(pr, "FIRST_NAMES_FILE", d / "common_first_names.txt")
    cases = {"clean": page("x"), "hit": page("x", "<p>i asked Peregrine Farquharson.</p>")}
    for names in (False, True):
        if names:
            local_names(repo)
        for text in cases.values():
            f = tmp_path / "p.html"
            f.write_text(text, encoding="utf-8")
            assert mp.people_page(text, mp._registry(repo))["exit"] == pr.main([str(f)])


# -------------------------------------------------------------------------------------------------- Q2 genericize
def test_d11_tokens_are_read_from_decisions_not_written_in_the_tool(tmp_path):
    repo = make_repo(tmp_path)
    assert mp.d11_tokens(repo) == ["Zorblax", "Quendrith", "Vexmoor-rig"]     # "Collaborator → generic" skipped


def test_q2_findings_on_a_lesson_is_s1(tmp_path):
    repo = make_repo(tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>i built zorblax for this.</p>"),
                                "about/index.html": page("About", "<p>with Quendrith.</p>")})
    recs = mp.cmd_genericize(repo, TODAY)
    assert recs[0]["outcome"] == "FINDINGS" and recs[0]["n"] == 2
    sev = {f["subject"]: f["severity"] for f in findings(repo, "Q2")}
    assert sev == {"lessons/alpha/index.html: forbidden token": "S1", "about/index.html: forbidden token": "S2"}
    md = (repo / ".maint" / "audits" / "2026-10-31_genericize.md").read_text(encoding="utf-8")
    assert "witness: (none recorded" in md and "_hidden" not in md      # an unserved path is not a hit


def test_q2_unknown_until_witnessed_and_witness_rules(tmp_path):
    repo = make_repo(tmp_path)
    r = mp.cmd_genericize(repo, TODAY)[0]
    assert r["outcome"] == "UNKNOWN" and r["why"].startswith("no witness recorded")
    for bad in ("site-maintainer", "managing-editor", "maintenance-auditor", "nobody"):
        with pytest.raises(mp.CouldNotRun):
            mp.cmd_witness(repo, TODAY, bad)
    assert mp.main(["--repo", str(repo), "witness", "site-maintainer"]) == 2
    w = mp.cmd_witness(repo, TODAY, "reviewer")[0]
    assert w["outcome"] == "UNKNOWN" and "witnessed by reviewer, but" in w["why"]   # client list absent, W3 UNKNOWN
    assert "witness: reviewer at" in (repo / ".maint" / "audits" / "2026-10-31_genericize.md").read_text(
        encoding="utf-8")


def test_q2_pass_needs_witness_client_list_and_w3_pass(tmp_path):
    repo = make_repo(tmp_path)
    local_names(repo)
    (repo / "data" / "forbidden_tokens.local.json").write_text(json.dumps({"tokens": ["Brindlecorp"]}),
                                                               encoding="utf-8")
    assert mp.cmd_genericize(repo, TODAY)[0]["outcome"] == "UNKNOWN"
    w = mp.cmd_witness(repo, TODAY, "privacy-safety")[0]
    assert w["outcome"] == "PASS" and "witnessed by privacy-safety" in w["why"]


def test_q2_witness_refused_after_head_moves(tmp_path):
    repo = make_repo(tmp_path)
    mp.cmd_genericize(repo, TODAY)
    (repo / "x.html").write_text(page("x"), encoding="utf-8")
    g(repo, "add", "x.html")
    g(repo, "commit", "-q", "-m", "move")
    with pytest.raises(mp.CouldNotRun, match="HEAD moved"):
        mp.cmd_witness(repo, TODAY, "reviewer")


def test_q2_private_token_is_searched_and_not_echoed(tmp_path):
    repo = make_repo(tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>for brindlecorp.</p>")})
    (repo / "data" / "forbidden_tokens.local.json").write_text(json.dumps({"tokens": ["Brindlecorp"]}),
                                                               encoding="utf-8")
    assert mp.cmd_genericize(repo, TODAY)[0]["outcome"] == "FINDINGS"


def test_q2_without_d11_is_unknown(tmp_path):
    repo = make_repo(tmp_path, {"DECISIONS.md": "## D1 — Voice\n"})
    r = mp.cmd_genericize(repo, TODAY)[0]
    assert r["outcome"] == "UNKNOWN" and "D11" in r["why"]


# ------------------------------------------------------------------------------------------------------- Q1 reread
def test_q1_skip_when_nothing_due(tmp_path):
    repo = make_repo(tmp_path)
    r = mp.cmd_reread(repo, TODAY)[0]
    assert r["outcome"] == "SKIP" and r["n"] == 0 and "next due 2027-01-18" in r["why"]


def test_q1_findings_n_is_pages_due_with_the_checklist(tmp_path):
    repo = make_repo(tmp_path, {"about/index.html": page("About")})        # no published row carries it
    r = mp.cmd_reread(repo, TODAY)[0]
    assert r["outcome"] == "FINDINGS" and r["n"] == 1
    later = mp.cmd_reread(repo, dt.date(2027, 2, 1))[0]
    assert later["outcome"] == "FINDINGS" and later["n"] == 5
    md = (repo / ".maint" / "audits" / "2027-02-01_reread.md").read_text(encoding="utf-8")
    assert md.count("7. [ ] Outcome: `MAINTAINED") == 5 and "W3 has no receipt yet: UNKNOWN" in md


def test_q1_rows_due_matches_production_board(tmp_path, monkeypatch):
    rows = [{"id": "A", "title": "Old", "stage": "PUBLISHED", "published": "2026-01-01"},
            {"id": "B", "title": "New", "stage": "PUBLISHED", "published": "2026-10-30"},
            {"id": "C", "title": "Undated", "stage": "MAINTAINED"},
            {"id": "D", "title": "Draft", "stage": "DRAFTED"}]
    q = tmp_path / "q.jsonl"
    q.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    monkeypatch.setattr(pb, "QUEUE", q)
    board = pb.build(TODAY).split("## Maintenance due", 1)[1].split("\n---\n", 1)[0]
    mine = mp.rows_due(pb.load_queue(), TODAY)
    assert sorted(r["title"] for r, _ in mine) == ["Old", "Undated"]
    assert all(f"| {r['title']} | {why} |" in board for r, why in mine)
    assert "| New |" not in board


def test_q1_unknown_when_git_cannot_run(tmp_path):
    d = nongit(tmp_path)
    assert mp.main(["--repo", str(d), "reread"]) == 2
    assert log(d, "Q1")[-1]["outcome"] == "UNKNOWN"


# ------------------------------------------------------------------------------------------------------ Q3 hygiene
def test_q3_pass_when_nothing_is_stale(tmp_path):
    repo = make_repo(tmp_path)
    r = mp.cmd_hygiene(repo, TODAY)[0]
    assert r["outcome"] == "PASS" and "1 patch" in r["why"]


def test_q3_findings_for_old_patch_and_old_finding_but_not_closed(tmp_path):
    repo = make_repo(tmp_path)
    old = {"at": "2026-01-02T00:00:00+00:00", "row": "W1", "severity": "S3", "subject": "dead link",
           "detail": "d", "route_to": "site-maintainer"}
    closed = dict(old, subject="fixed one")
    (repo / ".maint").mkdir()
    (repo / ".maint" / mr.FINDINGS_NAME).write_text(
        "\n".join(json.dumps(x) for x in (old, closed, dict(closed, status="closed"))) + "\n", encoding="utf-8")
    r = mp.cmd_hygiene(repo, dt.date(2027, 3, 1))[0]
    assert r["outcome"] == "FINDINGS" and r["n"] == 2                     # the patch (132 d) and the open finding
    md = (repo / ".maint" / "audits" / "2027-03-01_hygiene.md").read_text(encoding="utf-8")
    assert "dead link" in md and "fixed one" not in md


def test_q3_unknown_on_an_unparseable_queue_line(tmp_path):
    repo = make_repo(tmp_path)
    with (repo / "production_queue.jsonl").open("a", encoding="utf-8") as f:
        f.write("{broken\n")
    assert mp.cmd_hygiene(repo, TODAY)[0]["outcome"] == "UNKNOWN"


# --------------------------------------------------------------------------------------------------------- M4 walk
def test_fk_grade_is_an_indicator_that_moves_the_right_way():
    easy = mp.fk_grade("The cat sat. The dog ran. We had fun.")
    hard = mp.fk_grade("Institutional accountability necessitates comprehensive documentation of organisational "
                       "responsibilities, notwithstanding considerable administrative complexity.")
    assert easy["grade"] < 2 < 10 < hard["grade"] and easy["sentences"] == 3


def test_m4_unknown_when_route_is_whole_and_no_jargon(tmp_path):
    repo = make_repo(tmp_path)
    r = mp.cmd_walk(repo, TODAY)[0]
    assert r["outcome"] == "UNKNOWN" and "await the seat" in r["why"]
    md = (repo / ".maint" / "audits" / "2026-10-31_reader.md").read_text(encoding="utf-8")
    assert "/ -> /lessons/ -> /lessons/find-your-door/ -> /lessons/ -> /lessons/alpha/" in md
    assert md.count("Answer (seat): ____") == 16 and "never a gate" in md and '"Start"' in md


def test_m4_findings_for_unglossed_jargon(tmp_path):
    repo = make_repo(tmp_path, {"lessons/alpha/index.html": page("Alpha", "<p>then i open the harness again later "
                                                                 "today and go home to rest for a while now.</p>")})
    r = mp.cmd_walk(repo, TODAY)[0]
    assert r["outcome"] == "FINDINGS" and r["n"] == 1
    assert findings(repo, "M4")[0]["route_to"].startswith("managing-editor")


def test_m4_findings_for_a_broken_path(tmp_path):
    repo = make_repo(tmp_path, {"lessons/index.html": page("Lessons", "<p>no links</p>")})
    r = mp.cmd_walk(repo, TODAY)[0]
    assert r["outcome"] == "FINDINGS" and "1 broken" in r["why"]
    assert findings(repo, "M4")[0]["severity"] == "S2"


def test_m4_unknown_when_git_cannot_run(tmp_path):
    d = nongit(tmp_path)
    assert mp.main(["--repo", str(d), "walk"]) == 2 and log(d, "M4")[-1]["outcome"] == "UNKNOWN"


# ---------------------------------------------------------------------------------------------------- A2 inventory
def test_a2_inventory_unknown_awaits_the_editor(tmp_path):
    repo = make_repo(tmp_path)
    r = mp.cmd_inventory(repo, TODAY)[0]
    assert r["outcome"] == "UNKNOWN" and "4 pages inventoried" in r["why"]
    md = (repo / ".maint" / "audits" / "2026-10-31_content_audit.md").read_text(encoding="utf-8")
    assert "annotate, never erase" in md and "only Daniel rules a removal" in md
    assert "https://example.invalid/lessons/alpha/" in md and md.count("- [ ] Redundant?") == 4
    inv = json.loads((repo / ".maint" / "audits" / "2026-10-31_inventory.json").read_text(encoding="utf-8"))
    alpha = next(x for x in inv if x["page"] == "lessons/alpha/index.html")
    assert alpha["owner"].startswith("managing-editor (content line)") and alpha["commits"] == 1 and alpha["first"]


def test_a2_findings_for_true_duplicates(tmp_path):
    repo = make_repo(tmp_path, {"blog/index.html": page("Same", "<p>coming soon</p>"),
                                "videos/index.html": page("Same", "<p>coming soon</p>")})
    r = mp.cmd_inventory(repo, TODAY)[0]
    assert r["outcome"] == "FINDINGS" and r["n"] == 1
    assert "Daniel" in findings(repo, "A2")[0]["route_to"]


def test_a2_unknown_when_git_cannot_run(tmp_path):
    d = nongit(tmp_path)
    assert mp.main(["--repo", str(d), "inventory"]) == 2 and log(d, "A2")[-1]["outcome"] == "UNKNOWN"
