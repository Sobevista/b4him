# Proposed update — 2026-08-16

> **RULED IN SESSION 2026-08-16. D13, D14, D15 and D16 are LOCKED in `DECISIONS.md`; D17 is
> still open.** This file is now the *record of the proposal*, not the live board — read
> `DECISIONS.md` for what is in force.
>
> Daniel: *"No more putting off things on a list that I can rule on now."* All four were ruled
> in the same session they were written, from the laptop, roughly an hour after the material
> was inventoried.
>
> | | ruling |
> |---|---|
> | **D13** cyber publishing | **`PUBLICATION_GATE.md` ADOPTED AS WRITTEN, in force.** Blue holds the gate, red never self-clears, per-piece rulings. P9 a named gap, not a blocker |
> | **D14** Guess & Click tier | **APPROVE** — convert from the recovered generators, not the `.docx`. Glossary first. D11 genericization + independent grep bind |
> | **D15** cadence | **APPROVE** — 2 pages/week, Tue + Fri, hard cap 2 per 7 days. Editorial rationale only; **no SEO claim** |
> | **D16** flashcards | **SPLIT** — run verification step 2 first, publish only verified cards, state the held count |
> | **D17** exercises | **OPEN** — printable / self-checked / storing nothing is proposed, not ruled |
>
> Still nothing built and nothing published: no page added, changed or removed by this pass.
> The rulings authorise the work; they are not the work.
>
> *Original proposal text follows unchanged, so the reasoning that was ruled on stays legible.*

---

## 0. The blocker that outranks everything else in this document

**`purple-team/PUBLICATION_GATE.md` line 3 reads:**

> *"DRAFT, 2026-08-15. **PENDING DANIEL'S RULING.** Nothing here is in force until he says so."*

He asked for *"this work here for cyber repackaged"* as part of this update. **The gate that
decides whether cyber work may be published at all is a draft he wrote and never ruled.**
Publishing into that would be acting ahead of a gate that exists — the exact inversion of
*ruled is not applied*, and worse, because here the ruling was never made rather than never
applied.

**So the cyber material is inventoried below and deliberately NOT scheduled.** It sits behind
**D13**, and D13 is not mine to answer. Everything else in this proposal can proceed without
it.

---

## 1. The produced bucket, counted

Every number here carries where it came from. Nothing is an estimate.

| Source | What it is | Count | State |
|---|---|---|---|
| **b4him, live now** | published lesson pages | **14** (13 lessons + `find-your-door`) | shipped |
| **Harness `Knowledge_Base/Teaching/`** | teaching modules | **23** | 13 published under D11/D12; **~10 held** (D11 held Tiers 2–3 as mesh/CAS-heavy) |
| **Guess & Click, recovered 2026-08-16** | curriculum `.docx` | **18** | **never published, never on the site, and until today not in any repo** |
| ″ | generator scripts (`.js`) | **19** | the machine that builds the above |
| **purple-team rung 1** | findings from today's lap | **10** (`F1`–`F10`) | **blocked on D13** |
| **purple-team `teaching/flashcards/`** | extracted cards | **197** | **step 2 unverified** — see D16 |

**The recovered Guess & Click set is the headline.** It was named as missing from the entire
estate, found this morning in an app cache, and it includes material the site has nothing
comparable to:

- `The_5System_Curriculum.docx` — **the entire advanced tier**, "Orchestration through
  Handoff, peer-level tone"
- `Companion_Workbook_Beginner.docx` — **34 exercises**
- `Companion_Workbook_Advanced.docx` — **25 exercises**
- `Automation_Vocabulary_Glossary.docx` — **20 terms, tiered by level**
- plus `The_5Primitive_Curriculum`, `Cognitive_Profile_System`, `Module_1_The_Atom`, six
  `Practice_Day*` docs and `Practice_Reps_5Builds`

D12 already established Tier 2 was *"sourced from the Drive `Guess and Click` Chassis
Curriculum."* **This is the rest of that source, including the tier that was never available
when D12 was locked.**

---

## 2. D13 — May the cyber work be published at all?

**What this is to the build.** Rung 1 of the purple-team range produced ten findings and four
principles that generalise past the app: *the client is a suggestion, the server is the
authority* · *failure is loud, successful abuse is silent* · *a log's event vocabulary maps
what the developer thought about* · *confirming a silent act is what makes it loud*. As
teaching material it is the strongest thing produced this month.

**Why this decision exists.** `PUBLICATION_GATE.md` is a draft awaiting his ruling, and it
exists precisely because offensive-security writing has a publication question that curriculum
material does not. Scheduling this content before he rules would answer his own gate for him.

**What changes if approved.** Roughly 3–5 lesson pages become available. **What does not
change:** the target app is ours, on `127.0.0.1`, so there is no third-party disclosure
question — the gate is about *what teaching offensive technique in public does*, not about a
victim.

**What it does to the aggregate.** It changes what b4him *is*. Today it reads as "an honest
person showing their homework about building software." Adding an offensive-security track
makes it partly a security site. That is a positioning decision, not a content decision, and
it is the reason this is D13 rather than a scheduling line.

**Cross-checked by.** Nobody. The gate is unruled and I have not read it beyond its status
line and headings, deliberately — reading it closely and then arguing for publication would be
me building the case I want.

**Recommendation.** **Rule `PUBLICATION_GATE.md` first, as its own sitting, before any cyber
content is drafted.** Then a narrow first step: publish the *defensive* half only — the
detection-vs-logging-gap distinction, which is genuinely valuable and teaches nothing about
how to attack. If that reads right, revisit the red half.

---

## 3. D14 — Publish the recovered Guess & Click tier

**What this is to the build.** The advanced tier, two workbooks (59 exercises) and a 20-term
glossary — the material D12's Tier 2 was already drawn from, now complete.

**Why this decision exists.** D11 locked Tier 1 at 8 modules and held Tiers 2–3 as "mesh/CAS-
heavy." **That reasoning does not apply to this set** — Guess & Click is generic automation
teaching with no harness internals, which is why it survived genericization once already.

**What changes if approved.** A third tier on `/lessons/`, plus the first *exercises* the site
has ever carried. **What does not change:** Tier 1 and 2 are untouched; a non-technical visitor
still lands on The Honest Machine (D3, D12).

**What it does to the aggregate.** 14 pages → roughly 25–30. **That is the largest single
expansion the site has had, and it is what makes the cadence question in D15 real.** The site
stops being "a dozen lessons" and becomes a curriculum, which is a different promise to a
reader and should be made deliberately.

**Cross-checked by.** The source documents themselves, recovered and now tracked at
`Knowledge_Base/Teaching/_laptop_recovered/`. Their generators are recovered too, so the
`.docx` can be regenerated rather than transcribed — **the conversion should run from the
generators, not from the Word files**, which is cheaper and reproducible.

**Recommendation.** **Approve, subject to D11's genericization rule and its verification law**
— an *independent* grep for forbidden tokens, not the rendering agent's self-report. The
glossary is the cheapest high-value first ship: 20 self-contained terms, no dependencies, and
it gives every other lesson something to link to.

---

## 4. D15 — The release cadence

**What this is to the build.** How ~15 new pages reach the site over time.

**Why this decision exists.** Daniel: *"a progressive update schedule so we show frequency of
severity thus mitigating any sort of spammy behavior issues."* Publishing 15 pages in one day
reads as a dump.

**What changes if approved.** A fixed publishing rhythm instead of ad-hoc pushes.

**Proposal: two pages per week, fixed days, one tier at a time.**

| | |
|---|---|
| Cadence | **Tuesday and Friday**, one page each |
| Order | glossary (1) → advanced tier (~8) → workbooks (~4, as exercise pages) → cyber (**only if D13**) |
| Duration | ~7 weeks for the Guess & Click set |
| Hard cap | **never more than 2 pages in any 7-day window**, even when a batch is ready |

**Cross-checked by.** **Nothing, and this is the honest part.** I have *no evidence* about what
search engines treat as a spam signal, and I am not going to assert a threshold I cannot
source — that would be `INV-W6` (a widely-repeated fact with no primary source is a belief) on
the site whose own laws include it. **The argument I can actually make is editorial:** a steady
cadence reads as a person still working, a dump reads as an archive drop, and the site's whole
premise is ongoing homework. If he wants the indexing question answered properly, that is a
research task with a real source requirement, not a line in this proposal.

**Recommendation.** **Approve the cadence on the editorial argument; do not claim an SEO
rationale for it in public copy.**

---

## 5. D16 — The flashcards

**What this is to the build.** 197 cards in `purple-team/teaching/flashcards/terms.jsonl`,
extracted deterministically from the corpus, with `cards_3x5.html` and `cards_P3.html`
renderers. Daniel: *"we have some flashcards we need to look good."*

**Why this decision exists.** Two blockers, and one is a quality gate he already wrote.
`OBJECTIVES.md` carries **"Flashcards step 2 — verify each against an outside definition
(`VERIFY_CONTRACT.md`)" as UNCHECKED**, and `NEEDS_DEFINITION.md` is 166 lines. **Publishing
197 unverified definitions on a site whose entire premise is honesty is the wrong trade.**

**What changes if approved.** A `/lessons/flashcards/` page. **What does not change:** the
underlying set — the fix is verification, not restyling.

**What it does to the aggregate.** This is the item most likely to damage the site if rushed. A
wrong definition on a page that looks authoritative is worse than no page.

**Cross-checked by.** `terms.jsonl` carries a `verification` field, so the set already knows
which cards are verified. **That field should drive what publishes** — verified cards ship,
the rest stay back and the page says how many are held.

**Recommendation.** **Split it.** Run step 2 first as its own task; publish only the verified
subset; state the held count on the page. "Looking good" is a rendering job of maybe an hour
once the content is trustworthy, and doing it in the other order builds a nice-looking wrong
thing.

---

## 6. D17 — Where the exercises live

**What this is to the build.** The workbooks are **59 exercises**, and no b4him page is
currently shaped like an exercise — every lesson is a read.

**Why this decision exists.** `INV-W3` says *collection is the trigger, not audience*, and
`find-your-door` was built to collect nothing and send nothing. **An exercise page invites an
answer, which is the first thing on this site a visitor could be tempted to submit.**

**Recommendation.** **Exercises are printable / self-checked, in-browser only, storing nothing**
— same posture as the quiz. If any future exercise wants a submitted answer, that is a new
decision under `INV-W3`, not an implementation detail.

---

## 7. What I did not do

- **Wrote no site copy.** The house voice is first-person, warm, fumbling included; the About
  draft passed on exactly that. Drafting 15 pages of it before the tier is approved would be
  work thrown away, and voice is the part worth doing slowly.
- **Converted no documents.** The generators should do it, and that waits on D14.
- **Read `PUBLICATION_GATE.md` closely** — status line and headings only, on purpose (see D13).
- **Ran no genericization grep.** D11 requires an *independent* check; the agent proposing the
  publication should not also be the one certifying it clean.
- **Touched nothing else in this repo.** No pages added, changed or removed.
