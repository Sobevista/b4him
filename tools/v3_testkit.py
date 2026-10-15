"""Test helper: give a fixture queue row a real v3 binding (production-boundary-v1).

bind(row) makes, in the scratch repo pb.REPO points at, a commit that holds exactly the row's approved blobs (built
with a throwaway index, so the working tree and branch are untouched), tags it approved/<id> the way
approvals.apply does, records approved_commit, and writes row["binding"]. That is the same evidence a real tap leaves.
"""
import os
import subprocess
import tempfile

import binding
import production_board as pb


def _git(env, *args, input=None):
    p = subprocess.run(["git", "-C", str(pb.REPO), *args], capture_output=True, env=env, input=input)
    if p.returncode:
        raise RuntimeError(f"git {args}: {p.stderr.decode()}")
    return p.stdout.decode().strip()


def bind(row: dict) -> dict:
    blobs = row.get("approved_blobs")
    if not blobs:
        return row
    with tempfile.TemporaryDirectory() as td:
        env = {**os.environ, "GIT_INDEX_FILE": os.path.join(td, "idx"), "GIT_AUTHOR_NAME": "t",
               "GIT_AUTHOR_EMAIL": "t@example.invalid", "GIT_COMMITTER_NAME": "t",
               "GIT_COMMITTER_EMAIL": "t@example.invalid"}
        for rel, blob in blobs.items():
            if subprocess.run(["git", "-C", str(pb.REPO), "cat-file", "-e", f"{blob}^{{blob}}"]).returncode:
                f = pb.REPO / rel          # a pin computed from a working-tree file: put those bytes in the store
                if f.exists() and pb.blob_sha(f) == blob:
                    _git(env, "hash-object", "-w", str(f))
            _git(env, "update-index", "--add", "--cacheinfo", f"100644,{blob},{rel}")
        tree = _git(env, "write-tree")
        commit = _git(env, "commit-tree", tree, "-m", f"the bytes Daniel saw for {row['id']}")
    _git(os.environ.copy(), "tag", "-f", f"approved/{row['id']}", commit)
    row["approved_commit"] = commit
    row["binding"] = binding.make(row)
    return row
