"""Tests for production_board.py's two rules that publishing depends on.

    py -m pytest tools/test_production_board.py -q

1. A piece takes the earliest slot whose review-by date (T-7) it met (PRODUCTION_PLAN section 3).
2. RULED and PREVIEWED cover the bytes Daniel saw: a page changed after approval holds no slot (section 2).
"""
import datetime as dt
import hashlib
import json
import pathlib
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import production_board as pb  # noqa: E402

TUE = dt.date(2026, 10, 13)          # a Tuesday: the next slots are Tue 10-20 (review by 10-13) and Tue 10-27 (10-20); E00568: Tuesdays only


def board(tmp_path, monkeypatch, rows, today=TUE):
    queue = tmp_path / "production_queue.jsonl"
    queue.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    monkeypatch.setattr(pb, "REPO", tmp_path)
    monkeypatch.setattr(pb, "QUEUE", queue)
    return pb.build(today)


def row(pid, order, **kw):
    return {"id": pid, "order": order, "title": pid, "stage": "PREVIEWED", "since": "2026-10-13", **kw}


def slot_line(text, day):
    return next(line for line in text.splitlines() if line.startswith(f"| **{day}**"))


def test_a_piece_previewed_today_takes_the_first_slot_whose_review_date_it_met(tmp_path, monkeypatch):
    text = board(tmp_path, monkeypatch, [row("GLOSS", 1, previewed="2026-10-13 - Daniel")])
    assert slot_line(text, "2026-10-20").startswith("| **2026-10-20** Tue | GLOSS | 2026-10-13 |  |")
    # a day late for 10-20 (review-by 10-13): that slot skips and the piece takes the next Tuesday
    text = board(tmp_path, monkeypatch, [row("GLOSS", 1, previewed="2026-10-14 - Daniel")])
    assert "*(skip)*" in slot_line(text, "2026-10-20")
    assert "previewed after this slot's review-by date" in slot_line(text, "2026-10-20")
    assert slot_line(text, "2026-10-27").startswith("| **2026-10-27** Tue | GLOSS | 2026-10-20 |  |")


def test_a_piece_with_no_preview_date_keeps_the_old_rule(tmp_path, monkeypatch):
    text = board(tmp_path, monkeypatch, [row("OLD", 1)], today=dt.date(2026, 10, 14))
    assert "| OLD | 2026-10-13 | review window already passed |" in slot_line(text, "2026-10-20")
    assert "no eligible piece" in slot_line(text, "2026-10-27")


def test_pieces_previewed_early_fill_consecutive_slots_in_queue_order(tmp_path, monkeypatch):
    text = board(tmp_path, monkeypatch, [row("B", 2, previewed="2026-10-01"), row("A", 1, previewed="2026-10-01")])
    assert "| A | 2026-10-13 |  |" in slot_line(text, "2026-10-20")
    assert "| B | 2026-10-20 |  |" in slot_line(text, "2026-10-27")


def test_the_board_lists_only_tuesday_slots_and_weekly_runway(tmp_path, monkeypatch):
    # E00568: Tuesdays only, hard cap 1 per 7 days, runway counted at one piece a week.
    assert pb.CADENCE_DAYS == (1,) and pb.PER_WEEK_CAP == 1
    rows = [row(p, n, previewed="2026-10-01") for n, p in enumerate("ABCD", 1)]
    text = board(tmp_path, monkeypatch, rows)
    slots = [line for line in text.splitlines() if line.startswith("| **20")]
    assert len(slots) == 12
    days = [dt.date.fromisoformat(line.split("**")[1]) for line in slots]
    assert all(d.weekday() == 1 for d in days)
    assert all((b - a).days == 7 for a, b in zip(days, days[1:]))
    assert not any(" Fri " in line for line in slots)
    assert "cadence Tuesday only, hard cap 1 per 7 days" in text
    assert "Tue + Fri" not in text and "2 per 7" not in text
    assert "**RUNWAY: 4.0 weeks**" in text and "÷ 1/week" in text


def test_a_page_changed_since_approval_holds_no_slot_and_goes_back_to_daniel(tmp_path, monkeypatch):
    page = tmp_path / "lessons" / "x" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_bytes(b"<h1>approved</h1>\n")
    approved = {"lessons/x/index.html": pb.blob_sha(page)}
    rows = [row("GLOSS", 1, previewed="2026-10-13", approved_blobs=approved)]

    text = board(tmp_path, monkeypatch, rows)
    assert "| GLOSS |" in slot_line(text, "2026-10-20")
    assert "CHANGED SINCE" not in text

    page.write_bytes(b"<h1>approved, then collapsed</h1>\n")
    text = board(tmp_path, monkeypatch, rows)
    assert "CHANGED SINCE DANIEL'S APPROVAL" in text
    assert "lessons/x/index.html (approved " in text
    assert "| GLOSS |" not in slot_line(text, "2026-10-20")
    assert "| GLOSS | PREVIEWED | a new RULING and PREVIEW: changed since he approved it |" in text

    page.unlink()                                   # a deleted page is a change too
    assert "now missing" in board(tmp_path, monkeypatch, rows)


def test_blob_sha_is_gits_blob_id_and_a_crlf_checkout_is_not_a_change(tmp_path):
    lf, crlf = tmp_path / "lf.html", tmp_path / "crlf.html"
    lf.write_bytes(b"<p>a</p>\n<p>b</p>\n")
    crlf.write_bytes(b"<p>a</p>\r\n<p>b</p>\r\n")
    data = lf.read_bytes()
    assert pb.blob_sha(lf) == hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    assert pb.blob_sha(crlf) == pb.blob_sha(lf)
    git = shutil.which("git")
    if not git:
        pytest.skip("git not on PATH: the blob id was checked by formula only")
    out = subprocess.run([git, "hash-object", "--no-filters", str(lf)], capture_output=True, encoding="utf-8")
    assert out.stdout.strip() == pb.blob_sha(lf)
