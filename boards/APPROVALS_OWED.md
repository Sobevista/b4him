# Approvals owed — b4him

*Written by `tools/approvals.py offer`; read by the harness app, which records your tap in the ledger. One tap is RULED + PREVIEWED together (E00472): **Approve publishes exactly the bytes at the commit in the title** on the first Tuesday slot at least 7 days out (once weekly, E00568). `tools/approvals.py apply` puts it on the rack; `tools/release.py` publishes it. Any edit after that pulls it and comes back here as a new tile.*

### APPROVE GC-GLOSS-2 at bb19ba5 — Glossary II - Intermediate terms

- **What this is to the build.** Glossary II - Intermediate terms (n8n track), drafted 2026-10-13 on `draft/gc-gloss-2`. The invariant it teaches: *same*. **The rendered proof: https://claude.ai/artifact/SVFG9PFVakJrMbD3A6xvqJ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/glossary-intermediate/index.html` = blob `482185838757`; `tools/tracks/n8n.html` = blob `9b614213d119`. The lessons index gains: **Glossary II — Intermediate Terms** — Twenty words for a workflow that has to hold — and the failures you cannot see from the green tick.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the page (own scanner, 26/26 planted tokens caught; 0 forbidden names; 9 terms source-checked): FAIL on one technical error (Error Trigger is attached per workflow, not instance-wide; n8n docs). Fixed in 8c5bdf0 by the orchestrating seat, with 4 advisories on this page; the reviewer's own scanner re-run on the fixed bytes: 0 hits (3 advisory CSS-comment hits shared with Glossary I's template). The fix itself has NOT had a second independent read.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** [RULED 2026-10-20 REJECT · ledger E00615 · applied by tools/approvals.py]

### APPROVE GC-GLOSS-3 at bb19ba5 — Glossary III - Advanced terms

- **What this is to the build.** Glossary III - Advanced terms (n8n track), drafted 2026-10-13 on `draft/gc-gloss-2`. The invariant it teaches: *same*. **The rendered proof: https://claude.ai/artifact/SVFG9PFVakJrMbD3A6xvqJ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/glossary-advanced/index.html` = blob `eeb7029b9df8`; `tools/tracks/n8n.html` = blob `9b614213d119`. The lessons index gains: **Glossary III — Advanced Terms** — Twenty words for when it isn't one workflow anymore: contracts, monitors, and the checks that check the checks.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the page (own scanner, 26/26 planted tokens caught; 0 forbidden names; sources spot-checked): PASS. 4 advisories then fixed in 8c5bdf0 (fire-and-forget error path, circuit-breaker half-open, untrusted-input overclaim, meta-monitoring cross-link); reviewer's scanner re-run on the fixed bytes: 0 hits.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** [RULED 2026-10-20 REJECT · ledger E00616 · applied by tools/approvals.py]

### APPROVE T4-L1 at bc31405 — Silence Is Not a Grade - the gate that fails open

- **What this is to the build.** Silence Is Not a Grade - the gate that fails open (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *A gate whose miss looks like a pass fails open: every check must say PASSED, SKIPPED or REFUSED where the human can see it.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/silence-is-not-a-grade/index.html` = blob `5e0a043dccb7`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **Silence Is Not a Grade: The Gate That Fails Open** — A check that misses its trigger waves the work through ungraded. Every checkpoint has to say out loud whether it passed, skipped, or refused.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T4-L2 at bc31405 — A Convention Without Enforcement Is a Preference

- **What this is to the build.** A Convention Without Enforcement Is a Preference (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *When you introduce a shared contract, introduce the thing that fails when a member skips it, in the same change.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/convention-without-enforcement/index.html` = blob `55756beb3b7c`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **A Convention Without Enforcement Is a Preference** — A rule everyone agreed to and nothing checks is a wish. Ship the checker that fails in the same change as the rule.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T4-L3 at bc31405 — The Tripod - three kinds of checking

- **What this is to the build.** The Tripod - three kinds of checking (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *Three kinds of checking fail differently. A finding that carries its evidence stops the need for a fourth.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/the-tripod/index.html` = blob `43001d2b6e0d`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **The Tripod: Why Three Kinds of Checking, and Why the Regress Stops There** — The author, an outside reviewer, and a machine each miss different things. Findings that carry their evidence are why you can stop at three.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T4-L4 at bc31405 — The Second Oracle - green proves you met your criteria

- **What this is to the build.** The Second Oracle - green proves you met your criteria (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *A green suite proves you met your criteria, not that your criteria were right. Only someone doing the real task can find the rest.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/second-oracle/index.html` = blob `f8cb8430059b`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **The Second Oracle: Green Proves You Met Your Criteria, Not That They Were Right** — The checks gave the game a green light and it was still wrong. Your own tests check your own questions; only someone doing the real task checks the answers.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T4-L5 at bc31405 — Ask What It Optimised For - archaeology before inheritance

- **What this is to the build.** Ask What It Optimised For - archaeology before inheritance (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *Every inherited design encodes someone else's goal. Recover the goal before you copy the design.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/what-it-optimised-for/index.html` = blob `d601ffd0bc2a`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **Ask What It Optimised For: Archaeology Before Inheritance** — An old arcade credit was tuned to end in three minutes by an accountant. Find out what a design was for before you copy it.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T4-L6 at bc31405 — Math on the Table - locking parameters before the machine runs

- **What this is to the build.** Math on the Table - locking parameters before the machine runs (tier4 track), drafted 2026-10-13 on `draft/tier4`. The invariant it teaches: *A parameter is closed by a dated ruling whose math anyone can recompute, never by a feeling.*. **The rendered proof: https://claude.ai/artifact/NWEfZyacamzsvV9tFqNKVs**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/math-on-the-table/index.html` = blob `d41ef9debe6b`; `tools/tracks/tier4.html` = blob `a7b479c3b251`. The lessons index gains: **Math on the Table: Locking Parameters Before the Machine Runs** — A number you defend with 'seems about right' is a mood. Show the arithmetic, rule on it, date it, and start anything irreversible at zero.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.** 2026-10-13 - stage 2 by a seat that neither wrote nor rendered the pages (own scanner, every planted category caught; client names 0, children's ages 0, the son's name only on second-oracle; word-level fidelity diff against each harness source; template + invariant 6/6): PASS on all six. Its three recommended edits and two source-level accuracy notes (L1 'I called it the seam' -> 'the seam'; L6 six parameters restored; L4 Breakout named in the story, 'digit for digit' -> within half a point; L4 blurb 'Every test passed' -> 'Every check came back green') were applied after review by the orchestrating seat and were not independently re-read. | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against 0e11830 and the diaries: no fact changed, invariant blocks byte-identical, every attribution held; PASS 3, PASS-WITH-FLAGS 3; its flags fixed by the orchestrating seat (L3 near-miss given back to the machine, L4 pasted 'seek failure' cut and 'start to finish' softened, L1 invented lesson-order motive cut), not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L1 at 2dffd67 — Success for Doing Nothing

- **What this is to the build.** Success for Doing Nothing (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *if a step cannot see its own effect, its "success" means nothing: assert the effect, not the exit code*. **The rendered proof: https://claude.ai/artifact/U2qonaGzzoFT6cEepD73HZ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/success-for-doing-nothing/index.html` = blob `03630b53e44c`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **Success for Doing Nothing** — A step that can't see its own effect reports success for doing nothing. Ask what it would print if it had done nothing at all.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L2 at 2dffd67 — Ruled Is Not Applied

- **What this is to the build.** Ruled Is Not Applied (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *a ruling with nothing that carries it is a preference, and a page that regenerates is not a home*. **The rendered proof: https://claude.ai/artifact/U2qonaGzzoFT6cEepD73HZ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/ruled-is-not-applied/index.html` = blob `28eafe65661d`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **Ruled Is Not Applied** — A decision that lives only on a page that rebuilds itself is a decision with a countdown on it.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L3 at 2dffd67 — A Null Result Is Only as Strong as the Search Behind It

- **What this is to the build.** A Null Result Is Only as Strong as the Search Behind It (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *"I didn't find it" is a fact about where you looked: a null ships with its search log*. **The rendered proof: https://claude.ai/artifact/U2qonaGzzoFT6cEepD73HZ**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/null-result/index.html` = blob `3447770151b5`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **A Null Result Is Only as Strong as the Search Behind It** — "We couldn't find anything" is a sentence about the search. Ask what would have found it, and whether that ran.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L4 at 2dffd67 — The Instrument Measures You First

- **What this is to the build.** The Instrument Measures You First (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *before you compare things you did not build, subtract your own apparatus*. **The rendered proof: https://claude.ai/artifact/9azvBdcePjfhnXRGATahhX**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/instrument-measures-you/index.html` = blob `0abde004ddbe`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **The Instrument Measures You First** — Rank things you didn't build and the first thing you measure is your own rig. Zero the scale before you read it.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L5 at 2dffd67 — Grade Each Leg Only on the Axis It Can Carry

- **What this is to the build.** Grade Each Leg Only on the Axis It Can Carry (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *ask one question per comparison, and a gate everyone passes has stopped measuring*. **The rendered proof: https://claude.ai/artifact/9azvBdcePjfhnXRGATahhX**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/grade-each-leg/index.html` = blob `2aa0490eaf0f`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **Grade Each Leg Only on the Axis It Can Carry** — One question per comparison — and a test everyone passes has quietly stopped measuring anything.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_

### APPROVE T5-L6 at 2dffd67 — The Law Writer's Own Laws

- **What this is to the build.** The Law Writer's Own Laws (tier5 track), drafted 2026-10-13 on `draft/tier5`. The invariant it teaches: *self-reported compliance is not evidence: the layer that writes the rules needs a checker that can refuse it too*. **The rendered proof: https://claude.ai/artifact/9azvBdcePjfhnXRGATahhX**
- **Why this decision exists.** It is your one tap (E00472): the words and the rendered page together. Nothing publishes that you have not seen.
- **What changes if you approve.** These exact bytes go on the rack: `lessons/law-writers-own-laws/index.html` = blob `033bd23061ef`; `tools/tracks/tier5.html` = blob `e4c34bcd9943`. The lessons index gains: **The Law Writer's Own Laws** — The rules nobody checks are the ones the rule-makers follow. Find yours, and give it a checker that can say no.. It takes the first open slot on or after 2026-10-20.
- **What it does to the aggregate, measured.** Runway rises by 0.5 weeks (one piece ÷ 2 a week).
- **Cross-checked by, including where it is weak.**  | 2026-10-13 - the pages were then RE-VOICED into Daniel's first person (E00480) and re-read by an independent Fable seat against d50b52c and the diaries: invariant blocks byte-identical; PASS 4, PASS-WITH-FLAGS 1 (L1 habit line, left for Daniel), FAIL 1 (L3: who ran the two legs). The L3 fix (the two legs were outside AIs put the same ten questions; the language hole was in our threads, found by the searching outside AI) and advisories (L4 'with me', L5 'my comparisons') applied by the orchestrating seat, not re-read. voice_check PASS 6/6.
- **Recommendation.** Approve if the proof reads and looks right. Reject or Later with a note if not; a rejected piece goes back to drafting and returns here as a new commit.

**DANIEL:** _pending_
