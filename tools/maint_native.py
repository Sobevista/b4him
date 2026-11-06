#!/usr/bin/env python3
"""
maint_native.py: the maintenance calendar's only native code. It reads two facts about a running process (its image
path and its creation time) through kernel32, for tools/maint_run.py's run_start line (pid / proc_started).

It calls exactly five kernel32 functions: GetCurrentProcessId, OpenProcess (PROCESS_QUERY_LIMITED_INFORMATION only),
QueryFullProcessImageNameW, GetProcessTimes and CloseHandle. It starts nothing, writes nothing and changes no process.
No other tool imports ctypes; this file is kept minimal so it can be read whole.
"""
from __future__ import annotations

import datetime as dt

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000      # the narrowest right that reads an image name and process times
assert PROCESS_QUERY_LIMITED_INFORMATION == 0x1000


def process_info(pid: int | None = None) -> tuple[str | None, str | None]:
    """(image path, creation time ISO-8601 UTC) of `pid`, or of this process when None. (None, None) where the OS
    will not say (not Windows, the process is gone, access denied)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.windll.kernel32
        k32.GetCurrentProcessId.restype = wintypes.DWORD
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        k32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                   ctypes.POINTER(wintypes.DWORD)]
        k32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(wintypes.FILETIME)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.CloseHandle.argtypes = [wintypes.HANDLE]
        target = k32.GetCurrentProcessId() if pid is None else pid
        access = PROCESS_QUERY_LIMITED_INFORMATION
        assert access == PROCESS_QUERY_LIMITED_INFORMATION, "OpenProcess asks for query-limited access only"
        h = k32.OpenProcess(access, False, target)
        if not h:
            return None, None
        try:
            buf, size = ctypes.create_unicode_buffer(1024), wintypes.DWORD(1024)
            image = buf.value if k32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)) else None
            times = [wintypes.FILETIME() for _ in range(4)]
            if not k32.GetProcessTimes(h, *[ctypes.byref(t) for t in times]):
                return image, None
            ticks = (times[0].dwHighDateTime << 32) | times[0].dwLowDateTime      # 100 ns since 1601-01-01 UTC
            t = dt.datetime(1601, 1, 1, tzinfo=dt.timezone.utc) + dt.timedelta(microseconds=ticks // 10)
            return image, t.isoformat(timespec="seconds")
        finally:
            k32.CloseHandle(h)
    except (AttributeError, OSError, ImportError):
        return None, None
