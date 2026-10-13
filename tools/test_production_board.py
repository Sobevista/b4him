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

TUE = dt.date(2026, 10, 13)          # a Tuesday: the next slots are Fri 10-16 (review by 10-09) and Tue 10-20 (10-13)


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
    assert "*(skip)*" in slot_line(text, "2026-10-16")
    assert "previewed after this slot's review-by date" in slot_line(text, "2026-10-16")
    assert slot_line(text, "2026-10-20").startswith("| **2026-10-20** Tue | GLOSS | 2026-10-13 |  |")


def test_a_piece_with_no_preview_date_keeps_the_old_rule(tmp_path, monkeypatch):
    text = board(tmp_path, monkeypatch, [row("OLD", 1)])
    assert "| OLD | 2026-10-09 | review window already passed |" in slot_line(text, "2026-10-16")
    assert "no eligible piece" in slot_line(text, "2026-10-20")


def test_pieces_previewed_early_fill_consecutive_slots_in_queue_order(tmp_path, monkeypatch):
    text = board(tmp_path, monkeypatch, [row("B", 2, previewed="2026-10-01"), row("A", 1, previewed="2026-10-01")])
    assert "| A | 2026-10-09 |  |" in slot_line(text, "2026-10-16")
    assert "| B | 2026-10-13 |  |" in slot_line(text, "2026-10-20")


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
