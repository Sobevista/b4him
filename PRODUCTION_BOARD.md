# PRODUCTION BOARD

*Generated 2026-10-20 by `tools/production_board.py` from `production_queue.jsonl`. **Never hand-edit — re-run the generator.** Doctrine: `PRODUCTION_PLAN.md`.*

**RUNWAY: 12.0 weeks** — healthy  
*(target 6w · floor 3w · 12 piece(s) at stage ≥ PREVIEWED ÷ 1/week)*

26 in the pipeline · 0 published · cadence Tuesday only, hard cap 1 per 7 days

## Waiting on Daniel

*Nothing. Every piece is blocked on someone else or already through his gates.*

## The next 12 slots

*A piece must be at **PREVIEWED** by **T-7 days** to hold a slot (`PRODUCTION_PLAN` §3). An empty slot skips and says so.*

| slot | piece | review by | note |
|---|---|---|---|
| **2026-10-27** Tue | Glossary I - Beginner terms | 2026-10-20 |  |
| **2026-11-03** Tue | Silence Is Not a Grade - the gate that fails open | 2026-10-27 |  |
| **2026-11-10** Tue | A Convention Without Enforcement Is a Preference | 2026-11-03 |  |
| **2026-11-17** Tue | The Tripod - three kinds of checking | 2026-11-10 |  |
| **2026-11-24** Tue | The Second Oracle - green proves you met your criteria | 2026-11-17 |  |
| **2026-12-01** Tue | Ask What It Optimised For - archaeology before inheritance | 2026-11-24 |  |
| **2026-12-08** Tue | Math on the Table - locking parameters before the machine runs | 2026-12-01 |  |
| **2026-12-15** Tue | Success for Doing Nothing | 2026-12-08 |  |
| **2026-12-22** Tue | Ruled Is Not Applied | 2026-12-15 |  |
| **2026-12-29** Tue | A Null Result Is Only as Strong as the Search Behind It | 2026-12-22 |  |
| **2027-01-05** Tue | The Instrument Measures You First | 2026-12-29 |  |
| **2027-01-12** Tue | Grade Each Leg Only on the Axis It Can Carry | 2027-01-05 |  |

## The pipeline, by stage

**SOURCE** (build session) — 14
  - Glossary II - Intermediate & Advanced terms · source: `Knowledge_Base/Teaching/_laptop_recovered/Automation_Vocabulary_Glossary.docx`
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
  - Glossary I revision - fold each word's four rows so the page is shorter · source: `Daniel, 2026-10-13, approving Glossary I` · **BLOCKED: DEFERRED by Daniel (on his calendar) - not before GC-GLOSS-1 is published. An edit to the page before then voids its approval (approved_blobs) and the board pulls it from its slot.**

**DRAFTED** (Claude) — 0

**REVIEWED** (the other seat) — 0

**RULED** (DANIEL) — 0

**PREVIEWED** (DANIEL) — 12
  - Glossary I - Beginner terms · source: `Knowledge_Base/Teaching/_laptop_recovered/generators/build_glossary.js`
  - Silence Is Not a Grade - the gate that fails open · source: `Knowledge_Base/Teaching/Module_09_Silence_Is_Not_A_Grade.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - A Convention Without Enforcement Is a Preference · source: `Knowledge_Base/Teaching/Module_15_A_Convention_Without_Enforcement.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - The Tripod - three kinds of checking · source: `Knowledge_Base/Teaching/Module_11_The_Tripod.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - The Second Oracle - green proves you met your criteria · source: `Knowledge_Base/Teaching/Module_13_The_Second_Oracle.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - Ask What It Optimised For - archaeology before inheritance · source: `Knowledge_Base/Teaching/Module_14_Ask_What_It_Optimised_For.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - Math on the Table - locking parameters before the machine runs · source: `Knowledge_Base/Teaching/Module_12_Math_On_The_Table.md` · **BLOCKED: Daniel's one tap on the rendered proof (E00472)**
  - Success for Doing Nothing · source: `Knowledge_Base/Teaching/Module_21_Success_For_Doing_Nothing.md` · **BLOCKED: stage 2: independent name check by a seat that did not write the page**
  - Ruled Is Not Applied · source: `Knowledge_Base/Teaching/Module_20_Ruled_Is_Not_Applied.md` · **BLOCKED: stage 2: independent name check by a seat that did not write the page**
  - A Null Result Is Only as Strong as the Search Behind It · source: `Knowledge_Base/Teaching/Module_18_A_Null_Result_Is_Only_As_Strong_As_The_Search.md` · **BLOCKED: stage 2: independent name check by a seat that did not write the page**
  - The Instrument Measures You First · source: `Knowledge_Base/Teaching/Module_17_The_Instrument_Measures_You_First.md` · **BLOCKED: stage 2: independent name check by a seat that did not write the page**
  - Grade Each Leg Only on the Axis It Can Carry · source: `Knowledge_Base/Teaching/Module_19_Grade_Each_Leg_On_The_Axis_It_Can_Carry.md` · **BLOCKED: stage 2: independent name check by a seat that did not write the page**

**SCHEDULED** (the board) — 0

## Maintenance due

*Published pages are re-checked every 90 days (`PRODUCTION_PLAN` §5). Corrections publish immediately and outside the cadence.*

*Nothing published yet, so nothing to maintain.*

---

**This board publishes nothing, advances no stage, and infers no review from the passage of time.** Stages RULED and PREVIEWED move only on Daniel's explicit word.
