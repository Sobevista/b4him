# BUILD CONTRACT — approvals-refusal-safe-v2  (2026-10-23)

Successor to `approvals-refusal-safe` (harness contract, opened 2026-10-15, never closed: its first independent
breaker died in the 2026-10-16 machine restart and left nothing). That build's fix, b4him cb88137, sits on
`build/approvals-refusal-safe`, branched from c14252b, 59 commits behind main 3d08c51, merged with the unmerged
proving ground. This build ports ONLY the approvals fix onto today's main, without the proving ground.

The defect, on main 3d08c51 (`tools/approvals.py` 571-573, the apply path the 08:30 daily job runs): on any
refusal, apply() runs `git reset -q -- .` then `git checkout -- .`, which discards EVERY uncommitted change to
tracked files in the b4him checkout, not only what approvals wrote. Found by the proving ground on its first run
(build `proving-ground-v1`): tap APPROVE, edit a tracked file, advance one day; 88 of 200 seeded runs on ec95cb0.

Done means: a refused or failed apply restores exactly what approvals itself wrote in that attempt (its board, its
queue, PRODUCTION_BOARD, and the approved/<id> tag) and nothing else; every other uncommitted change and untracked
file in the tree survives byte-identical, and the ruling stays OWED.

Dropped from the predecessor, with the reason: its third property cited the proving ground's harvested regression
(`tools/proving_ground/regressions/...`), which does not exist on main and is out of this build's scope. When
proving-ground-v1 merges after this fix, that regression's strict-xfail marker must be removed in the same merge
(cb88137 removed it), or it will XPASS and fail the suite.

Verify/close target: `--worktree-of` the build's own worktree (the gate reads that tree's HEAD), not the live
`C:\Users\dansl\b4him` checkout, which stays on main and is never touched by this build.

## Property: a-refusal-never-touches-work-that-is-not-its-own
- criterion: With uncommitted edits to tracked files and untracked files present, every approvals refusal (dirty tree, not on main, missing commit, bad tile, injected refusal mid-apply, unexpected crash mid-apply) leaves those edits and files byte-for-byte as they were and nothing staged. cite: tools/test_approvals.py::test_a_refusal_never_touches_work_that_is_not_its_own

## Property: a-refusal-undoes-its-own-partial-work
- criterion: A refusal after approvals has itself written to the queue or the boards (APPROVE and REJECT) leaves the tree and the approved/<id> tag as they were before that attempt (its own writes undone, nothing else touched), and the ruling stays OWED. cite: tools/test_approvals.py::test_a_refusal_undoes_its_own_partial_work_and_the_ruling_stays_owed

## Out of scope
Any change to release.py, the cadence, the binding or the registry. Changing when the daily job runs. The proving
ground. What happens when the ledger append fails AFTER approvals' own commit landed (the commit stands; unchanged
from main).
