# Approvals owed — b4him

*Written by `tools/approvals.py offer`; read by the harness app, which records your tap in the ledger. One tap is RULED + PREVIEWED together (E00472): **Approve publishes exactly the bytes at the commit in the title** on the first Tue/Fri slot at least 7 days out. `tools/approvals.py apply` puts it on the rack; `tools/release.py` publishes it. Any edit after that pulls it and comes back here as a new tile.*

### APPROVE GC-GLOSS-2 at bb19ba5 — Glossary II - Intermediate terms

- **What this is to the build.** Glossary II - Intermediate terms (n8n track), drafted 2026-10-13 on `draft/gc-gloss-2`. The invariant it teaches: *same*. **The rendered proof: https://claude.ai/artifact/SVFG9PFVakJrMbD3A6xvqJ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/glossary-intermediate/index.html` = blob `482185838757`; `tools/tracks/n8n.html` = blob `9b614213d119`. The lessons index gains: **Glossary II — Intermediate Terms** — Twenty words for a workflow that has to hold — and the failures you cannot see from the green tick.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the page (own scanner, 26/26 planted tokens caught; 0 forbidden names; 9 terms source-checked): FAIL on one technical error (Error Trigger is attached per workflow, not instance-wide; n8n docs). Fixed in 8c5bdf0 by the orchestrating seat, with 4 advisories on this page; the reviewer's own scanner re-run on the fixed bytes: 0 hits (3 advisory CSS-comment hits shared with Glossary I's template). The fix itself has NOT had a second independent read.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE GC-GLOSS-3 at bb19ba5 — Glossary III - Advanced terms

- **What this is to the build.** Glossary III - Advanced terms (n8n track), drafted 2026-10-13 on `draft/gc-gloss-2`. The invariant it teaches: *same*. **The rendered proof: https://claude.ai/artifact/SVFG9PFVakJrMbD3A6xvqJ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/glossary-advanced/index.html` = blob `eeb7029b9df8`; `tools/tracks/n8n.html` = blob `9b614213d119`. The lessons index gains: **Glossary III — Advanced Terms** — Twenty words for when it isn't one workflow anymore: contracts, monitors, and the checks that check the checks.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the page (own scanner, 26/26 planted tokens caught; 0 forbidden names; sources spot-checked): PASS. 4 advisories then fixed in 8c5bdf0 (fire-and-forget error path, circuit-breaker half-open, untrusted-input overclaim, meta-monitoring cross-link); reviewer's scanner re-run on the fixed bytes: 0 hits.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_
