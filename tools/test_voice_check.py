"""Tests for voice_check.py (E00480): the floor bites on machine-voice prose and passes Daniel's own.

    py -m pytest tools/test_voice_check.py -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import voice_check as vc  # noqa: E402

REPO = pathlib.Path(__file__).resolve().parent.parent


def test_the_about_page_his_wife_read_as_his_voice_passes_the_first_person_floor():
    r = vc.check(REPO / "about" / "index.html")
    assert r["rate"] >= vc.FLOOR, r


def test_machine_voice_prose_fails_the_floor():
    text = ("The pipeline ran ten threads. The checker returned zero findings. The result was recorded and the "
            "build continued. Nothing in the output indicated a problem. " * 5)
    r = vc.measure(text)
    assert r["rate"] < vc.FLOOR and not r["pass"]


def test_first_person_story_passes():
    text = ("I built a checker and I trusted it. My mistake was believing silence. We found it a week later, "
            "and I wrote down what it cost us. " * 5)
    assert vc.measure(text)["pass"]


def test_an_unglossed_estate_term_fails_and_a_glossed_one_passes():
    base = "I built it and I broke it and we fixed it. " * 10
    bad = base + "Then the breaker found six defects in my work."
    good = base + "Then the breaker (a second AI whose only job is to attack my work) found six defects."
    assert any(u.startswith("breaker") for u in vc.measure(bad)["unglossed"])
    assert vc.measure(good)["unglossed"] == []


def test_a_term_named_after_its_plain_definition_counts_as_glossed():
    base = "I built it and I broke it and we fixed it. " * 10
    assert vc.measure(base + "I lost the real body of research findings (the corpus) for hours.")["unglossed"] == []


def test_an_appositive_or_meaning_gloss_counts_and_a_bare_term_still_fails():
    base = "I built it and I broke it and we fixed it. " * 10
    assert vc.measure(base + "It caught real drift, things that had quietly slipped out of line.")["unglossed"] == []
    assert vc.measure(base + "Reconstruction drifts, meaning what you rebuild from memory changes.")["unglossed"] == []
    assert vc.measure(base + "It caught real drift on its first run that day.")["unglossed"] != []


def test_the_page_title_is_not_visible_text():
    page = "<html><head><title>Grade Each Leg</title></head><body><main><p>I wrote this.</p></main></body></html>"
    assert "Leg" not in vc.visible_text(page)


def test_offer_refuses_a_lesson_tier_page_that_fails_the_voice_check(tmp_path, monkeypatch):
    import approvals
    rows = {"id": "T9-L1", "track": "tier9", "page": "lessons/x/index.html", "stage": "DRAFTED"}
    monkeypatch.setattr(approvals, "row_at", lambda c, p: rows)
    monkeypatch.setattr(approvals, "pinned", lambda c, r: {"lessons/x/index.html": "0" * 40})
    real_git = approvals.git

    def fake_git(*a, **k):
        if a[:2] == ("rev-parse", "--verify"):
            return "a" * 40 + "\n"
        if a[0] == "show":
            return "<main><p>The checker ran. The result was recorded. Nothing failed. The build continued.</p></main>"
        return real_git(*a, **k)
    monkeypatch.setattr(approvals, "git", fake_git)
    import pytest
    with pytest.raises(approvals.ApprovalError, match="voice check"):
        approvals.offer("T9-L1", "x", "https://claude.ai/artifact/x")


def test_chrome_scripts_and_styles_are_not_counted():
    page = ("<html><head><style>.harness{}</style><script>var ledger=1</script></head><body><header>my nav</header>"
            "<main><p>I wrote this and I mean it.</p></main><footer>our footer</footer></body></html>")
    t = vc.visible_text(page)
    assert "harness" not in t and "ledger" not in t and "nav" not in t and "footer" not in t
    assert "I wrote this" in t
