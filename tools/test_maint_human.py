"""Tests for tools/maint_human.py (H1, A1, A3: the ASSIST half of the HUMAN rows). No network, no browser: RDAP and
the capture are fakes; the tiling check runs on real PNG headers."""
import datetime as dt
import json
import socket
import struct
import zlib
from pathlib import Path

import pytest

import maint_human as mh
import maint_receipt as mr

REPO = Path(__file__).resolve().parent.parent
TZ = dt.timezone(dt.timedelta(hours=-5))
NOT_DUE = dt.datetime(2026, 11, 3, 10, 35, tzinfo=TZ)
DUE = dt.datetime(2027, 1, 4, 10, 35, tzinfo=TZ)


def png(path: Path, w: int, h: int) -> Path:
    raw = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    chunk = b"IHDR" + raw
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + struct.pack(">I", len(raw)) + chunk + struct.pack(">I", zlib.crc32(chunk)))
    return path


@pytest.fixture
def md(tmp_path, monkeypatch):
    d = tmp_path / ".maint"
    monkeypatch.setenv("MAINT_DIR", str(d))

    def no_net(*a, **k):
        raise AssertionError("a test opened a real network connection")
    monkeypatch.setattr(socket, "create_connection", no_net)
    return d


# ------------------------------------------------------------------ H1 tiling (harness LESSONS L-012)
def test_tile_plan_covers_the_page_once_under_16384_device_px():
    assert mh.tile_plan(4500) == [(0, 2000), (2000, 2000), (4000, 500)]
    assert all(h * mh.SCALE < 16384 for _, h in mh.tile_plan(40000))
    with pytest.raises(mh.PackError):
        mh.tile_plan(100, tile_css=9000)                      # 18,000 device px would be clipped by Chromium


def test_check_tiles_can_fail(tmp_path):
    plan = mh.tile_plan(4500)
    good = [png(tmp_path / f"t{i}.png", 2560, h * 2) for i, (_, h) in enumerate(plan)]
    assert mh.check_tiles(good, plan, 1280, 4500) == []
    bad = good[:2] + [png(tmp_path / "short.png", 2560, 600)]
    assert any("expected 2560x1000" in p for p in mh.check_tiles(bad, plan, 1280, 4500))
    assert any("tiles cover" in p for p in mh.check_tiles(good[:2], plan[:2], 1280, 4500))


def fake_capture(problems=()):
    def cap(repo, rels, out):
        res = {}
        for r in rels:
            for w in mh.WIDTHS:
                plan = mh.tile_plan(2500)
                names = [png(out / f"{r.replace('/', '-')}_{w}_{i}.png", w * 2, h * 2).name
                         for i, (_, h) in enumerate(plan)]
                res.setdefault(r, {})[w] = {"tiles": names, "height": 2500, "problems": list(problems)}
        return res
    return cap


def test_h1_pack_beside_the_d9_reference(md, monkeypatch):
    monkeypatch.setattr(mh, "CAPTURE", fake_capture())
    r = mh.cmd_h1(REPO, NOT_DUE)
    assert r["outcome"] == "SKIP" and "next due 2027-01-04" in r["why"] and r["evidence"].endswith("index.md")
    text = (md / "packs" / "H1_2026-11-03" / "index.md").read_text(encoding="utf-8")
    assert "reference_logo.png" in text and "`--navy-800`" in text and text.count("### ") == 4   # home + 3
    assert "### index.html" in text
    r = mh.cmd_h1(REPO, DUE)
    assert mr.is_awaiting(r) and r["why"].startswith("awaiting Daniel's ruling: H1 pack")


def test_h1_capture_failure_and_failed_check_are_unknown(md, monkeypatch):
    monkeypatch.setattr(mh, "CAPTURE", fake_capture(["t.png: 2560x10 px, expected 2560x4000"]))
    r = mh.cmd_h1(REPO, DUE)
    assert r["outcome"] == "UNKNOWN" and "capture check failed" in r["why"]

    def boom(*a):
        raise mh.PackError("Python Playwright is not installed")
    monkeypatch.setattr(mh, "CAPTURE", boom)
    assert "Playwright is not installed" in mh.cmd_h1(REPO, DUE)["why"]


# ------------------------------------------------------------------ A1
def test_a1_pack_has_pages_automated_results_and_easy_checks(md):
    md.mkdir(parents=True)
    (md / "2026-10-31_a11y.json").write_text('{"results": {}}', encoding="utf-8")
    r = mh.cmd_a1(REPO, NOT_DUE)
    assert r["outcome"] == "SKIP"
    text = (md / "packs" / "A1_2026-11-03" / "index.md").read_text(encoding="utf-8")
    assert "Define the evaluation scope" in text and "Report the evaluation findings" in text
    assert "| `index.html` |" in text and "Image Alternative Text" in text and "2.5.8 Target Size (Minimum)" in text
    assert (md / "packs" / "A1_2026-11-03" / "automated_axe_pa11y.json").exists()
    assert mr.is_awaiting(mh.cmd_a1(REPO, DUE))


# ------------------------------------------------------------------ A3 RDAP
BOOT = {"services": [[["net"], ["https://rdap.example.invalid/net/"]],
                     [["com"], ["http://rdap.verisign.example/com/v1/", "https://rdap.verisign.example/com/v1/"]]]}


def rdap(monkeypatch, expires, status=("client transfer prohibited",), fail=False):
    urls = []

    def get(url):
        urls.append(url)
        if url == mh.BOOTSTRAP:
            return BOOT
        if fail:
            raise OSError("connection refused")
        return {"objectClassName": "domain", "ldhName": "B4HIM.COM", "status": list(status),
                "events": [{"eventAction": "registration", "eventDate": "2020-01-01T00:00:00Z"},
                           {"eventAction": "expiration", "eventDate": expires}]}
    monkeypatch.setattr(mh, "GET_JSON", get)
    return urls


def test_a3_rdap_alarms_60_days_ahead(md, monkeypatch):
    urls = rdap(monkeypatch, "2027-06-01T00:00:00Z")
    r = mh.cmd_a3(REPO, NOT_DUE)
    assert r["outcome"] == "SKIP" and "expires 2027-06-01" in r["why"] and "window opens 2027-04-02" in r["why"]
    assert urls == [mh.BOOTSTRAP, "https://rdap.verisign.example/com/v1/domain/b4him.com"]   # https, via IANA
    rdap(monkeypatch, "2026-12-20T00:00:00Z")
    r = mh.cmd_a3(REPO, NOT_DUE)
    assert r["outcome"] == "FINDINGS" and "the 60-day window is open" in r["why"]
    mr.write_receipt("A3", "PASS", why="closed by E01234", tool="maint_watch.py")
    assert mh.cmd_a3(REPO, NOT_DUE)["outcome"] == "SKIP"                  # closed for this window


def test_a3_bad_status_and_unreadable_rdap(md, monkeypatch):
    rdap(monkeypatch, "2027-06-01T00:00:00Z", status=("client hold",))
    r = mh.cmd_a3(REPO, NOT_DUE)
    assert r["outcome"] == "FINDINGS" and json.loads((md / "maintenance_findings.jsonl").read_text(
        encoding="utf-8").splitlines()[-1])["severity"] == "S1"
    rdap(monkeypatch, "x", fail=True)
    assert mh.cmd_a3(REPO, NOT_DUE)["outcome"] == "UNKNOWN"
