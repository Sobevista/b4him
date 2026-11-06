#!/usr/bin/env python3
"""
maint_input.py: the one input layer every b4him maintenance tool reads through. Its rule is the calendar's first:
an input that cannot be judged is UNKNOWN, never a pass and never a quiet skip.

    parse_time(value, what, now=None)    a timezone-aware datetime. No time, an unreadable time, a time with no
                                         zone, or (given `now`) a time more than SKEW in the future: InputUnknown.
                                         A foreign zone is fine: the instant is what counts, compared as aware.
    read_text(path, what)                missing, unreadable and empty are three distinct InputUnknowns.
    read_json(path, what)                read_text, then JSON; not JSON is InputUnknown.
    read_jsonl(path, what, expect=True)  one JSON object per line; a bad line, or zero records where records are
                                         expected, is InputUnknown.
    require_records(seq, what)           zero records where records are expected is InputUnknown.

Every InputUnknown's message is the UNKNOWN reason, naming the input (`what`) and the kind of failure.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

#: How far ahead of `now` a time may be before it is a future-dated input (clock skew between machines).
SKEW = dt.timedelta(minutes=10)


class InputUnknown(ValueError):
    """An input that cannot be judged. Its message is the UNKNOWN reason."""


def parse_time(value, what: str, now: dt.datetime | None = None, skew: dt.timedelta = SKEW) -> dt.datetime:
    if value is None or not str(value).strip():
        raise InputUnknown(f"{what}: no time")
    s = str(value).strip()
    try:
        t = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        raise InputUnknown(f"{what}: unreadable time {s[:40]!r}") from None
    if t.tzinfo is None or t.utcoffset() is None:
        raise InputUnknown(f"{what}: time {s[:40]!r} has no timezone")
    if now is not None and t > now + skew:
        raise InputUnknown(f"{what}: time {s[:40]} is in the future")
    return t


def read_text(path: Path, what: str) -> str:
    p = Path(path)
    if not p.exists():
        raise InputUnknown(f"{what} is missing ({p.name})")
    try:
        text = p.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as e:
        raise InputUnknown(f"{what} is unreadable ({p.name}: {type(e).__name__})") from None
    if not text.strip():
        raise InputUnknown(f"{what} is empty ({p.name})")
    return text


def read_json(path: Path, what: str):
    text = read_text(path, what)
    try:
        return json.loads(text)
    except ValueError as e:
        raise InputUnknown(f"{what} is not JSON ({Path(path).name}: {e})") from None


def parse_jsonl(text: str, what: str, expect: bool = True) -> list[dict]:
    out = []
    for n, raw in enumerate(text.split("\n"), 1):     # JSONL lines end at \n only: U+0085 may sit in a value
        if not raw.strip():
            continue
        try:
            e = json.loads(raw)
        except ValueError as ex:
            raise InputUnknown(f"{what} line {n} is not JSON ({ex})") from None
        if not isinstance(e, dict):
            raise InputUnknown(f"{what} line {n} is not a JSON object")
        out.append(e)
    return require_records(out, what) if expect else out


def read_jsonl(path: Path, what: str, expect: bool = True) -> list[dict]:
    return parse_jsonl(read_text(path, what), what, expect)


def require_records(seq, what: str):
    if not seq:
        raise InputUnknown(f"{what}: zero records where records are expected")
    return seq
