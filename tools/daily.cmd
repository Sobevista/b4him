@echo off
rem b4him daily run (Windows Task Scheduler "b4him-daily-release", 08:30 every day).
rem 1. turn Daniel's taps in the harness app into racked rows; 2. publish today's slot, if it is one.
rem Every day logs a line in release_log.jsonl: a non-release day logs SKIP, so a day with no line means this did
rem not run. A FAIL raises a tile in the harness app (release_alarm.md).
cd /d C:\Users\dansl\b4him
py tools\approvals.py apply
py tools\release.py --apply --push --verify-live
