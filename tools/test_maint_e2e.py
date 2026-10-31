"""End to end, through the real paths: scanner (or note check) -> pending judgement or note -> judge -> D2's view
across a cadence boundary, for M4, A2, H2 and H3 (the GPT review of build/maint-integration). No network: the site
is a throwaway git repo, the clock is a fake, the scheduler check is a fake."""
import datetime as dt
import json

import pytest

import maint_pages as mp
import maint_receipt as mr
import maint_watch as mw
from test_maint_pages import make_repo, page

TZ = dt.timezone(dt.timedelta(hours=-5))
REAL = {r["id"]: r for r in json.loads(mw.ROWS_FILE.read_text(encoding="utf-8"))["rows"]}


class Clock:
    t = dt.datetime(2026, 11, 2, 11, tzinfo=TZ)

    def set(self, *a):
        self.t = dt.datetime(*a, tzinfo=TZ)

    def __call__(self):
        return self.t.astimezone(dt.timezone.utc)


@pytest.fixture
def e2e(tmp_path, monkeypatch):
    monkeypatch.setenv("MAINT_DIR", str(tmp_path / ".maint"))
    monkeypatch.setattr(mw, "LOCAL_TZ", TZ)
    monkeypatch.setattr(mw, "SCHEDULE_CHECK", lambda now: {"state": "ok", "problems": [], "why": "ok"})
    clock = Clock()
    monkeypatch.setattr(mr, "now_utc", clock)
    return tmp_path, clock


def table(tmp, *ids):
    p = tmp / "rows.json"
    p.write_text(json.dumps({"epoch": "2026-10-20", "rows": [REAL[i] for i in ids]}), encoding="utf-8")
    return p


def d2(clock, rows, *when):
    clock.set(*when)
    return mw.run_d2(mw.local(clock()), rows)


def last(rid):
    return [r for r in mr.read_receipts() if r["row"] == rid][-1]


def judge(rid, outcome, *rest):
    return mw.main(["judge", rid, outcome, *rest])


def test_m4_scanner_finding_waits_for_the_editor_and_the_clock_holds(e2e):
    tmp, clock = e2e
    repo = make_repo(tmp, {"lessons/alpha/index.html": page("Alpha", "<p>then i open the harness again later today "
                                                            "and go home to rest for a while now.</p>")})
    rows = table(tmp, "M4")
    clock.set(2026, 11, 2, 11)                                  # first Monday of November: the scanner runs
    r = mp.cmd_walk(repo, clock.t.date())[0]
    assert mr.is_awaiting(r) and "scanner found 1" in r["why"]  # the finding is evidence, not the row's verdict
    assert [f["row"] for f in mr.read_findings()] == ["M4"]
    assert d2(clock, rows, 2026, 11, 6, 11)["outcome"] == "PASS"
    clock.set(2026, 12, 7, 11)                                  # next month's run, still unjudged: no reset
    assert mr.is_awaiting(mp.cmd_walk(repo, clock.t.date())[0])
    r = d2(clock, rows, 2026, 12, 11, 0, 1)                     # 11-02 + one cadence (12-07) + 1 d + 72 h
    assert r["outcome"] == "FINDINGS" and "M4 (awaiting judgement since 2026-11-02" in r["why"]
    clock.set(2026, 12, 11, 9)
    assert judge("M4", "FINDINGS", "1", "--seat", "managing-editor", "--note", "one unglossed term: 'harness'") == 1
    j = last("M4")
    assert j["outcome"] == "FINDINGS" and j["n"] == 1 and j["evidence"] == ".maint/audits/2026-12-07_reader.md"
    assert d2(clock, rows, 2026, 12, 11, 10)["outcome"] == "PASS"
    clock.set(2027, 1, 4, 11)                                   # across the boundary: a new month, a new judgement owed
    mp.cmd_walk(repo, clock.t.date())
    assert d2(clock, rows, 2027, 1, 8, 0, 1)["outcome"] == "PASS"
    r = d2(clock, rows, 2027, 2, 5, 0, 1)                       # 01-04 + Feb's first Monday + 1 d + 72 h
    assert r["outcome"] == "FINDINGS" and "M4 (awaiting judgement since 2027-01-04" in r["why"]


def test_a2_duplicates_are_evidence_and_the_rot_judgement_closes_it(e2e):
    tmp, clock = e2e
    repo = make_repo(tmp, {"blog/index.html": page("Same", "<p>coming soon</p>"),
                           "videos/index.html": page("Same", "<p>coming soon</p>")})
    rows = table(tmp, "A2")
    clock.set(2027, 1, 4, 11)
    r = mp.cmd_inventory(repo, clock.t.date())[0]
    assert mr.is_awaiting(r) and "1 duplicate group(s), filed as A2 findings" in r["why"]
    assert d2(clock, rows, 2027, 6, 1, 11)["outcome"] == "PASS"
    clock.set(2028, 1, 3, 11)                                   # a year on, rescanned, still unjudged
    mp.cmd_inventory(repo, clock.t.date())
    r = d2(clock, rows, 2028, 1, 18, 0, 1)                      # 2027-01-04 + one cadence + 1 d + 14 d
    assert r["outcome"] == "FINDINGS" and "A2 (awaiting judgement since 2027-01-04" in r["why"]
    clock.set(2028, 1, 18, 9)
    assert judge("A2", "PASS", "--seat", "managing-editor", "--note", "blog and videos are placeholders; keep") == 0
    assert last("A2")["evidence"] == ".maint/audits/2028-01-03_content_audit.md"
    assert d2(clock, rows, 2028, 1, 18, 10)["outcome"] == "PASS"


@pytest.mark.parametrize("rid", ["H2", "H3"])
def test_h2_h3_need_a_real_note_and_d2_sees_the_next_one_owed(e2e, rid):
    tmp, clock = e2e
    rows = table(tmp, rid)
    t = mw.load_rows(rows)
    notes = mr.maint_dir() / "notes"
    notes.mkdir(parents=True)
    clock.set(2027, 1, 4, 11)
    assert mr.is_awaiting(mw.run_check(rid, mw.local(clock()), table=t))       # due, no note yet
    (notes / f"{rid}_2027-01-05.md").write_text("Date: YYYY-MM-DD\nReviewer: <seat>\nReviewed: <what>\n"
                                                "Verdict: <verdict>\nFinding: <one per line>\n", encoding="utf-8")
    clock.set(2027, 1, 5, 11)
    r = mw.run_check(rid, mw.local(clock()), table=t)
    assert r["outcome"] == "UNKNOWN" and "Verdict" in r["why"]                # a template is not a review
    r = d2(clock, rows, 2027, 1, 12, 0, 1)                                     # 01-04 + 1 d + 7 d: still no note
    assert r["outcome"] == "FINDINGS" and f"{rid} (" in r["why"]
    (notes / f"{rid}_2027-01-12.md").write_text(
        "Date: 2027-01-12\nReviewer: reviewer\nReviewed: the calendar and PRODUCTION_PLAN section 5\n"
        "Verdict: no change\nFindings: none\n", encoding="utf-8")
    clock.set(2027, 1, 12, 9)
    assert mw.run_check(rid, mw.local(clock()), table=t)["outcome"] == "PASS"
    assert d2(clock, rows, 2027, 1, 12, 10)["outcome"] == "PASS"
    clock.set(2027, 7, 5, 11)                                                  # across the boundary: July's is owed
    assert mr.is_awaiting(mw.run_check(rid, mw.local(clock()), table=t))
    assert d2(clock, rows, 2027, 7, 12, 23, 59)["outcome"] == "PASS"           # inside the grace
    r = d2(clock, rows, 2027, 7, 13, 0, 1)
    assert r["outcome"] == "FINDINGS" and f"{rid} (last receipt 2027-01-12" in r["why"]
