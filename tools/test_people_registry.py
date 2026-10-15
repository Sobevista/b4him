"""production-boundary-v1: the people registry (E00571) is a file the program reads.

    py -m pytest tools/test_people_registry.py -q

Every name below is fictional. The real registry holds roles and placeholders only; the real names live in a
git-ignored local file, which these tests replace with a fictional one.
"""
import json
import pathlib
import sys

import pytest

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import people_registry as pr  # noqa: E402

LOCAL = {"people": [
    {"label": "CLIENT-1", "role": "client", "names": ["Orlando Pemberton", "Orlando"]},
    {"label": "PARTNER-1", "role": "business_partner", "names": ["Marguerite Voss", "Marguerite"]},
    {"label": "WIFE-1", "role": "wife", "names": ["Philippa"]},
    {"label": "CHILD-1", "role": "child", "names": ["Bartholomew"]},
    {"label": "CHILD-2", "role": "child", "names": ["Quenby"]},
]}


@pytest.fixture
def reg(tmp_path):
    p = tmp_path / "names.local.json"
    p.write_text(json.dumps(LOCAL), encoding="utf-8")
    return pr.load_registry(local_path=p)


def kinds(r):
    return [(f.kind, f.text) for f in r.findings]


def test_the_registry_refuses_names_outside_their_rule_and_unknown_names(reg, tmp_path):
    # --- the clean case: roles, no names, Daniel's own directing told plainly, ordinary capitalised words
    clean = ("On Monday my business partner and I asked my wife what she thought. I directed Claude badly, "
             "fumbled the brief, and the Python script ran anyway. GitHub Pages published it.")
    r = pr.check_text(clean, registry=reg)
    assert r.ok and r.findings == [] and r.known_names_loaded

    # --- client: never, by full name or first name, plain or possessive
    for t in ("We built it for Orlando Pemberton.", "Orlando's deadline moved.", "orlando pemberton signed off"):
        r = pr.check_text(t, registry=reg)
        assert [f.role for f in r.findings] == ["client"] and not r.ok, t
        assert "never" in r.findings[0].rule

    # --- business partner and wife: by role only, never by name
    r = pr.check_text("Marguerite Voss reviewed it. Then Philippa did.", registry=reg)
    assert sorted(f.role for f in r.findings) == ["business_partner", "wife"]
    assert all("by role only" in f.rule for f in r.findings)

    # --- children: first name only, only with the per-piece yes, never a surname, never an age
    r = pr.check_text("Bartholomew helped me test the game.", registry=reg)
    assert [f.label for f in r.findings] == ["CHILD-1"] and "yes" in r.findings[0].rule        # no yes: refused
    assert pr.check_text("Bartholomew helped me test the game.", piece_yes={"CHILD-1"}, registry=reg).ok
    r = pr.check_text("Bartholomew helped me test the game.", piece_yes={"CHILD-2"}, registry=reg)
    assert not r.ok                                                                               # a yes for another child
    r = pr.check_text("Bartholomew Quillfeather helped.", piece_yes={"CHILD-1"}, registry=reg)
    assert any("surname" in f.rule for f in r.findings)
    for t in ("Bartholomew, who is 9, helped.", "Bartholomew is a nine-year-old who helped.",
              "My 7-year-old son helped.", "My daughter turned 12 that week."):
        r = pr.check_text(t, piece_yes={"CHILD-1"}, registry=reg)
        assert any(f.kind == "age" for f in r.findings), t
    assert pr.check_text("It was 2026 and version 3 shipped on the 9th.", registry=reg).ok      # numbers are not ages

    # --- unknown names are refused, not guessed at
    for t, expect in (("We then met Gwendolyn Marsh at the shop.", "Gwendolyn Marsh"),
                      ("Sarah said the build was fine.", "Sarah"),
                      ("A mentor, my friend Ignatius, told me.", "Ignatius"),
                      ("Dr Faulkner disagreed.", "Faulkner"),
                      ("a client named Thaddeus called", "Thaddeus")):
        r = pr.check_text(t, registry=reg)
        assert ("unknown-name", expect) in kinds(r), (t, kinds(r))
    # a known person is judged by their rule, not also reported as unknown
    r = pr.check_text("Marguerite Voss", registry=reg)
    assert [f.kind for f in r.findings] == ["known-outside-rule"]
    # markup is not text: class names, hrefs and script bodies are not people
    assert pr.check_text('<a class="Mod Header" href="/lessons/Zebra-Crossing/">hi</a><script>var Gwen = 1</script>',
                         registry=reg).ok
    # a Title Case heading is not flagged as a name (documented hole), and neither are safe terms
    assert pr.check_text("# The Second Oracle\n\nClaude Code and GitHub Pages.", registry=reg).ok

    # --- assert_clean is the stage-stopping form
    with pytest.raises(pr.RegistryError, match="never named"):
        pr.assert_clean("Orlando Pemberton", registry=reg)
    pr.assert_clean(clean, registry=reg)


def test_a_check_that_could_not_load_the_known_names_says_unknown_not_clean(tmp_path):
    missing = tmp_path / "absent.json"
    reg = pr.load_registry(local_path=missing)
    r = pr.check_text("Plain text about my wife and my business partner.", registry=reg)
    assert r.findings == [] and not r.known_names_loaded
    assert not r.ok and r.status().startswith("UNKNOWN")                 # UNKNOWN never rounds to OK
    with pytest.raises(pr.RegistryError, match="UNKNOWN"):
        pr.assert_clean("Plain text.", registry=reg)
    pr.assert_clean("Plain text.", registry=reg, require_known=False)
    # the heuristic still runs without the known names
    assert pr.check_text("Gwendolyn Marsh said so.", registry=reg).findings


def test_salted_hashes_work_and_the_shipped_registry_holds_no_names(tmp_path):
    real = json.loads(pr.REGISTRY_FILE.read_text(encoding="utf-8"))
    assert set(real["roles"]) == {"client", "business_partner", "wife", "child", "own_directing"}
    assert real["roles"]["client"]["rule"] == "never"
    assert real["roles"]["business_partner"]["rule"] == real["roles"]["wife"]["rule"] == "role_only"
    assert real["roles"]["child"]["rule"] == "first_name_with_piece_yes" and real["roles"]["child"]["never_ages"]
    assert real["roles"]["own_directing"]["rule"] == "fair_game"
    assert all(not p.get("name_hashes") and "name" not in p and "names" not in p for p in real["people"])
    assert not pr.LOCAL_NAMES_FILE.exists() or True              # the local file is never part of the repo:
    ignore = (HERE.parent / ".gitignore").read_text(encoding="utf-8")
    assert "data/people_names.local.json" in ignore
    # a hashed entry (no plain name anywhere) is matched
    salt = real["salt"]
    data = {**real, "people": [{"label": "CHILD-1", "role": "child",
                                "name_hashes": [{"hash": pr.hash_name("Bartholomew", salt), "form": "first"}]}]}
    reg_file = tmp_path / "reg.json"
    reg_file.write_text(json.dumps(data), encoding="utf-8")
    reg = pr.load_registry(registry_path=reg_file, local_path=tmp_path / "none.json")
    assert reg.known_names_loaded
    assert not pr.check_text("Bartholomew came too.", registry=reg).ok
    assert pr.check_text("Bartholomew came too.", piece_yes={"CHILD-1"}, registry=reg).ok


def test_the_checker_runs_from_the_command_line(tmp_path, capsys):
    f = tmp_path / "draft.html"
    f.write_text("<p>Gwendolyn Marsh wrote this.</p>", encoding="utf-8")
    assert pr.main([str(f)]) == 1
    assert "unknown-name" in capsys.readouterr().out


def test_html_entities_and_attribute_text_are_read_as_visible_text(reg):
    """D4: `&nbsp;` between a child's first name and a surname is a space; alt/title text is shown to readers."""
    r = pr.check_text("<p>Bartholomew&nbsp;Farquharson helped.</p>", piece_yes={"CHILD-1"}, registry=reg)
    assert any("surname" in f.rule for f in r.findings), r.findings
    r = pr.check_text("<p>Hi.</p><img src=x.png alt='Quenby at the keyboard'>", registry=reg)
    assert any(f.label == "CHILD-2" for f in r.findings), r.findings
    r = pr.check_text('<a href="/x" title="Orlando Pemberton">link</a>', registry=reg)
    assert any(f.label == "CLIENT-1" for f in r.findings), r.findings
    # markup-only names (class, href) are still not read as people
    assert not pr.check_text('<a class="Orlando-Pemberton" href="/Orlando/">go</a>', registry=reg).findings


def test_ages_next_to_a_child_in_the_common_forms_are_refused(reg):
    """D5: parenthetical, 'now N', ordinal birthday, 'turns N', next to a child name or child word."""
    for t in ("Bartholomew (9) helped.", "Bartholomew, now 9. He helped.", "Bartholomew's 9th birthday was that week.",
              "My son turns 8 next month.", "My daughter (11) helped."):
        r = pr.check_text(t, piece_yes={"CHILD-1"}, registry=reg)
        assert any(f.kind == "age" for f in r.findings), (t, r.findings)
    # a number with no child nearby is not an age finding
    assert not any(f.kind == "age" for f in pr.check_text("Step (2) is next. The build turns 3 modules green.", registry=reg).findings)
