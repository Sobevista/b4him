"""Tests for tools/maint_input.py, the shared input layer. Hypothesis drives the four input classes the estate
found mutants cluster in: empty, unreadable, future-dated and foreign-timezone."""
import datetime as dt

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

import maint_input as mi

NOW = dt.datetime(2026, 11, 2, 16, 0, tzinfo=dt.timezone.utc)


def test_three_distinct_read_failures(tmp_path):
    with pytest.raises(mi.InputUnknown, match="is missing"):
        mi.read_text(tmp_path / "nope.json", "the thing")
    (tmp_path / "empty.json").write_text("  \n", encoding="utf-8")
    with pytest.raises(mi.InputUnknown, match="is empty"):
        mi.read_text(tmp_path / "empty.json", "the thing")
    (tmp_path / "bad.json").write_bytes(b"\xff\xfe\x00garbage")
    with pytest.raises(mi.InputUnknown, match="is unreadable"):
        mi.read_text(tmp_path / "bad.json", "the thing")
    (tmp_path / "x.json").write_text("{nope", encoding="utf-8")
    with pytest.raises(mi.InputUnknown, match="is not JSON"):
        mi.read_json(tmp_path / "x.json", "the thing")


def test_zero_records_where_records_are_expected(tmp_path):
    (tmp_path / "q.jsonl").write_text("\n\n", encoding="utf-8")
    with pytest.raises(mi.InputUnknown, match="is empty"):
        mi.read_jsonl(tmp_path / "q.jsonl", "the queue")
    with pytest.raises(mi.InputUnknown, match="zero records"):
        mi.parse_jsonl("\n", "the queue")
    assert mi.parse_jsonl("\n", "the queue", expect=False) == []
    with pytest.raises(mi.InputUnknown, match="line 2 is not JSON"):
        mi.parse_jsonl('{"a": 1}\n{oops\n', "the queue")


@given(st.integers(min_value=11, max_value=10 ** 6))
def test_a_future_time_beyond_skew_is_unknown(minutes):
    t = (NOW + dt.timedelta(minutes=minutes)).isoformat()
    with pytest.raises(mi.InputUnknown, match="in the future"):
        mi.parse_time(t, "a line", NOW)


@given(st.integers(min_value=-14 * 60, max_value=14 * 60), st.integers(min_value=0, max_value=10 ** 5))
@settings(max_examples=60)
def test_a_foreign_zone_is_the_same_instant(offset_min, minutes_ago):
    tz = dt.timezone(dt.timedelta(minutes=offset_min))
    t = (NOW - dt.timedelta(minutes=minutes_ago)).astimezone(tz)
    assert mi.parse_time(t.isoformat(), "a line", NOW) == t       # aware equality is by instant


@given(st.text(max_size=30))
def test_garbage_or_naive_times_are_unknown(s):
    try:
        t = dt.datetime.fromisoformat(s.strip().replace("Z", "+00:00"))
        aware = t.tzinfo is not None and t.utcoffset() is not None
    except ValueError:
        aware = False
    if aware:
        return
    with pytest.raises(mi.InputUnknown):
        mi.parse_time(s, "a line")
