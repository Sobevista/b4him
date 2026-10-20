# PRODUCTION BOARD

*Generated 2026-10-20 by `tools/production_board.py` from `production_queue.jsonl`. **Never hand-edit — re-run the generator.** Doctrine: `PRODUCTION_PLAN.md`.*

**RUNWAY: 14.0 weeks** — healthy  
*(target 6w · floor 3w · 14 piece(s) at stage ≥ PREVIEWED ÷ 1/week)*

26 in the pipeline · 5 published · cadence Tuesday only, hard cap 1 per 7 days

*Two lines (`PRODUCTION_PLAN` §3): the **content line** above and below; the **patch line** (1 open, 0 racked) runs outside that cadence — see its own section.*

## ⚠ CHANGED SINCE DANIEL'S APPROVAL

*RULED and PREVIEWED cover the bytes he saw (`approved_blobs`). These files changed after that, so the piece holds no slot until he rules and previews it again (`PRODUCTION_PLAN` §2: never inherited from a previous yes). A **live** piece listed here means the site no longer serves what he approved.*

- **live** Site patch - Title Case every published heading (D21): lessons/index.html (approved 0b478c9a58de, now c949e035d96d)

## Waiting on Daniel

*Nothing. Every piece is blocked on someone else or already through his gates.*

## The content line: the next 12 slots

*A piece must be at **PREVIEWED** by **T-7 days** to hold a slot (`PRODUCTION_PLAN` §3). An empty slot skips and says so.*

| slot | piece | review by | note |
|---|---|---|---|
| **2026-10-27** Tue | Glossary II - Intermediate terms | 2026-10-20 |  |
| **2026-11-03** Tue | Glossary III - Advanced terms | 2026-10-27 |  |
| **2026-11-10** Tue | Silence Is Not a Grade - the gate that fails open | 2026-11-03 |  |
| **2026-11-17** Tue | A Convention Without Enforcement Is a Preference | 2026-11-10 |  |
| **2026-11-24** Tue | The Tripod - three kinds of checking | 2026-11-17 |  |
| **2026-12-01** Tue | The Second Oracle - green proves you met your criteria | 2026-11-24 |  |
| **2026-12-08** Tue | Ask What It Optimised For - archaeology before inheritance | 2026-12-01 |  |
| **2026-12-15** Tue | Math on the Table - locking parameters before the machine runs | 2026-12-08 |  |
| **2026-12-22** Tue | Success for Doing Nothing | 2026-12-15 |  |
| **2026-12-29** Tue | Ruled Is Not Applied | 2026-12-22 |  |
| **2027-01-05** Tue | A Null Result Is Only as Strong as the Search Behind It | 2026-12-29 |  |
| **2027-01-12** Tue | The Instrument Measures You First | 2027-01-05 |  |

## The patch line

*Fixes to published pages and site furniture (`kind: patch`). Outside the content cadence: no Tuesday rule, no 7-day cap, no content slot, no runway. A tapped patch publishes on the next release run (the daily 08:30 job), exact pinned bytes only, logged with lane `patch`.*

- Site patch - home shelf cards open their rooms (were href=#) (`SITE-PATCH-SHELF-1`) — **BLOCKED: PRE-TAP: Daniel's review and preview (his one tap on the rendered proof, patch line)** (release will refuse)
- Glossary I revision - fold each word's four rows so the page is shorter (`GC-GLOSS-1-R1`) — published 2026-10-20
- Site patch - Title Case every published heading (D21) (`SITE-PATCH-HEADINGS-1`) — published 2026-10-20
- Site patch - Title Case the n8n track heading (D21) (`SITE-PATCH-HEADINGS-2`) — published 2026-10-20
- Site patch - honour reduced motion site-wide (no animated jump scroll) (`SITE-PATCH-MOTION-1`) — published 2026-10-20

## The pipeline, by stage

**SOURCE** (build session) — 12
  - Advanced 1 - Orchestration · source: `Knowledge_Base/Teaching/_laptop_recovered/The_5System_Curriculum.docx`
  - Advanced 2 - Resilience · source: `Knowledge_Base/Teaching/_laptop_recovered/The_5System_Curriculum.docx`
  - Advanced 3 - Instrumentation · source: `Knowledge_Base/Teaching/_laptop_recovered/The_5System_Curriculum.docx`
  - Advanced 4 - Customization · source: `Knowledge_Base/Teaching/_laptop_recovered/The_5System_Curriculum.docx`
  - Advanced 5 - Handoff + the Graduation Build · source: `Knowledge_Base/Teaching/_laptop_recovered/The_5System_Curriculum.docx`
  - Detection gap vs logging gap - the distinction no rule can fix · source: `purple-team teaching/Module_02_Seeing_It.md (written 2026-08-16 from the lap that earned it)` · **BLOCKED: RUNG1_CROSS.md - the whole rung is reviewed by a family that is not its author before any of it is taught publicly**
  - Rung 1 write-up - broken access control, flaw and fix · source: `purple-team ranges/rung01_access_control/laps/FINDINGS.md F1-F10` · **BLOCKED: blue-seat review (red never self-clears) + Daniel's per-piece ruling**
  - Workbook exercises - beginner (34) · source: `Knowledge_Base/Teaching/_laptop_recovered/Companion_Workbook_Beginner.docx`
  - Workbook exercises - advanced (25) · source: `Knowledge_Base/Teaching/_laptop_recovered/Companion_Workbook_Advanced.docx`
  - Flashcards - the verified subset · source: `purple-team teaching/flashcards/terms.jsonl` · **BLOCKED: verification step 2 (VERIFY_CONTRACT.md) - 197 cards, none verified yet**
  - The two numbers - why a detection that cries wolf catches nothing · source: `purple-team teaching/Module_02_Seeing_It.md + detections/cross_owner_note_read.yml v1 vs v2` · **BLOCKED: RUNG1_CROSS.md**
  - Blue team words, four ways each · source: `purple-team teaching/Module_02_Seeing_It.md section 'The jargon, four ways'` · **BLOCKED: RUNG1_CROSS.md**

**DRAFTED** (Claude) — 0

**REVIEWED** (the other seat) — 0

**RULED** (DANIEL) — 0

**PREVIEWED** (DANIEL) — 14
  - Glossary II - Intermediate terms · source: `harness Knowledge_Base/Teaching/Glossary_Tiers_II_III_terms.md (term list, per-term sources)`
  - Glossary III - Advanced terms · source: `harness Knowledge_Base/Teaching/Glossary_Tiers_II_III_terms.md (term list, per-term sources)`
  - Silence Is Not a Grade - the gate that fails open · source: `Knowledge_Base/Teaching/Module_09_Silence_Is_Not_A_Grade.md`
  - A Convention Without Enforcement Is a Preference · source: `Knowledge_Base/Teaching/Module_15_A_Convention_Without_Enforcement.md`
  - The Tripod - three kinds of checking · source: `Knowledge_Base/Teaching/Module_11_The_Tripod.md`
  - The Second Oracle - green proves you met your criteria · source: `Knowledge_Base/Teaching/Module_13_The_Second_Oracle.md`
  - Ask What It Optimised For - archaeology before inheritance · source: `Knowledge_Base/Teaching/Module_14_Ask_What_It_Optimised_For.md`
  - Math on the Table - locking parameters before the machine runs · source: `Knowledge_Base/Teaching/Module_12_Math_On_The_Table.md`
  - Success for Doing Nothing · source: `Knowledge_Base/Teaching/Module_21_Success_For_Doing_Nothing.md`
  - Ruled Is Not Applied · source: `Knowledge_Base/Teaching/Module_20_Ruled_Is_Not_Applied.md`
  - A Null Result Is Only as Strong as the Search Behind It · source: `Knowledge_Base/Teaching/Module_18_A_Null_Result_Is_Only_As_Strong_As_The_Search.md`
  - The Instrument Measures You First · source: `Knowledge_Base/Teaching/Module_17_The_Instrument_Measures_You_First.md`
  - Grade Each Leg Only on the Axis It Can Carry · source: `Knowledge_Base/Teaching/Module_19_Grade_Each_Leg_On_The_Axis_It_Can_Carry.md`
  - The Law Writer's Own Laws · source: `Knowledge_Base/Teaching/Module_22_The_Law_Writers_Own_Laws.md`

**SCHEDULED** (the board) — 0

## Maintenance due

*Published pages are re-checked every 90 days (`PRODUCTION_PLAN` §5). Corrections publish immediately and outside the cadence.*

*Nothing due.*

---

**This board publishes nothing, advances no stage, and infers no review from the passage of time.** Stages RULED and PREVIEWED move only on Daniel's explicit word.
