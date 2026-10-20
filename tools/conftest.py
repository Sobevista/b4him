"""Shared test setup for tools/.

The release tests written before production-boundary-v1 drive release.apply() directly and build GC-GLOSS-1 rows
from fixture blobs. They are not about the boundary, so they run as if inside the scheduled entry and with a
legacy-exception file whose byte pin is faked (bytes_digest is patched; the pin itself is still required). tools/test_production_boundary.py is ABOUT the
boundary: it opts out and tests the real thing (no entry open, the real exception file).
"""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

BOUNDARY_MODULES = {"test_production_boundary", "test_boundary_breaker"}


@pytest.fixture(autouse=True)
def _no_real_ledger(monkeypatch):
    """Every test is hermetic about the harness ledger: release.run reads owed rulings (production-line-v2 round 4)
    from release.OWED_SOURCE, which defaults to the REAL ledger. Tests see none unless they set their own."""
    import release
    monkeypatch.setattr(release, "OWED_SOURCE", lambda: [])


@pytest.fixture(autouse=True)
def _as_if_scheduled(request, tmp_path_factory, monkeypatch):
    if request.module.__name__.split(".")[-1] in BOUNDARY_MODULES:
        return
    import binding
    import release
    legacy = tmp_path_factory.mktemp("legacy") / "legacy.json"
    legacy.write_text(json.dumps({"exceptions": [{"id": "GC-GLOSS-1", "approved_digest": "fixture-pin"}]}), encoding="utf-8")
    monkeypatch.setattr(binding, "LEGACY_FILE", legacy)
    # the digest is required; fixture rows are built from fixture blobs, so every fixture row "holds the pinned bytes"
    monkeypatch.setattr(binding, "bytes_digest", lambda row: "fixture-pin")
    monkeypatch.setattr(release, "_ENTRY", {"today": None})
