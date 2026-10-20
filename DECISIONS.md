# DECISIONS — b4him.com / Beacon Ministries

*Locked parameters. Fleet convention (see `Sobevista/GC_Junior`): human-owned decisions get a file, a date, and — where a rider is assumed rather than verified — an explicit `[ASSUMED]` tag.*

**Decision session: 2026-07-20** (LAPTOP-3GLEQ7L1). Ruled by Daniel unless marked otherwise.

---

## D0 — The name

**Beacon Ministries.** `b4him.com` is the address; **Beacon Ministries** is the thing.

The metaphor is load-bearing, not decorative. A lighthouse both *gathers* attention and *throws* light. Daniel's framing: *"somewhere to shine their focus, that will in turn empower them to shine their shine outward."* Light received → light given, same motion in both directions. Any design that treats "beacon" as a logo idea rather than as the site's organizing principle has missed it.

## D1 — Voice

**First person singular. Daniel's own homework.** "I built this, here's what broke."

Family and collaborators appear inside the story, not as co-authors of the site. *(Consequence: no contributor infrastructure at v0. See D7 — this must not be architected away either.)*

## D2 — Tone floor

**Implicit. Mantras only.** No scripture on the landing page, no explicit faith framing in the copy. The name and the work carry it.

A curious visitor with no faith background must never feel preached at. Ministry in the *purpose* sense, not the preachy one.

Mantras: **MBS** (Mind / Body / Spirit) · progress over perfection · 1% better every day · be intentional with your suffering · seek failure.

## D3 — Audience

**Anyone looking for somewhere to shine their focus.** Explicitly not builders-only.

Reading level and framing must carry a non-technical visitor all the way in. The games are a hook for anyone; the homework is the substance for whoever wants it. No assumed competence.

## D4 — Feel

**It should feel like home.** Daniel's words, and the sharpest constraint in this document.

Named here because the default for "a builder publishing his work" is a clean technical docs layout — correct, and cold. That is a library, not a home. **A design that is merely tidy has failed this criterion.** Warmth is a pass/fail attribute of v0, not a nice-to-have.

## D5 — What gets housed

**Everything produced, eventually — v0's job is to build the shelf, not to argue about what goes on it.**

Daniel's framing: *"No one is going to go to it yet, so it is more about setting the baseline. Where will they be housed, how will it flow."* v0 is therefore an **information-architecture** deliverable first and a content deliverable second.

Known content classes: learning modules · glossaries · flashcards · games · videos · work product / progression.

## D6 — Video

**v1, per the ladder — but the shelf gets its place at v0.**

Videos of Daniel doing the work are explicitly planned. Embedded YouTube at v1 (free player, free comments, and the cross-posting happens anyway). Self-hosting before anyone is watching is rent on an empty theater. **The v0 IA must have a slot video drops into without a redesign.**

## D7 — Community

**Not built at v0. Not foreclosed either.**

Daniel: *"Whatever it turns into is part of the fun... a community will grow and develop together."* v0 architects no comment system, no accounts, no contributor flow — and makes no structural choice that would have to be torn out to add them.

## D9 — Visual identity: LOCKED 2026-07-20

**Direction A ("Hearth") chosen, recolored to the logo.** Daniel supplied the Beacon Ministries logo as reference — the first real visual reference this project has had, and exactly what the Phase 0(b) gate was waiting for.

**Palette, taken from the logo:**

| Token | Value | Role |
|---|---|---|
| `--navy-900` | `#0f1729` | deepest ground |
| `--navy-800` | `#152039` | page background |
| `--navy-700` | `#1c2b4a` | raised surfaces, hover |
| `--gold` | `#d8b45c` | primary accent, rules, marks |
| `--gold-bright` | `#f2dda0` | the beam / emphasis |
| `--gold-dim` | `#8d7434` | quiet metadata |
| `--ink` | `#e7e3d8` | body text |
| `--muted` | `#9aa4ba` | secondary text |

**Why A survives the recolor rather than being replaced by it:** A's organizing idea was already light thrown into darkness — a glow from above, content lit rather than colored. The logo makes that literal (a lighthouse beam over a dark sea). Gold-on-navy *is* A, corrected to the real identity.

**MEASURED CONTRAST — added 2026-07-20 after the dark-theme research run.** WCAG 2.x ratios against `#152039`, computed and independently re-measured live in the browser:

| Colour | Ratio | AA normal (4.5:1) | AAA normal (7:1) | Use |
|---|---|---|---|---|
| `--ink` `#e7e3d8` | **12.62:1** | pass | pass | body text |
| `--gold-bright` `#f2dda0` | **12.04:1** | pass | pass | emphasis |
| `--gold` `#d8b45c` | **8.17:1** | pass | pass | accent, small labels — safe at any size |
| `--muted` `#9aa4ba` | **6.47:1** | pass | **fail** | secondary text |
| `--gold-dim` `#8d7434` | **3.61:1** | **FAIL** | fail | **large text (≥24px, or ≥18.66px bold) or non-text UI ONLY** |

Large-scale text is normatively ≥18pt (~24px) or ≥14pt bold (~18.5–18.67px). **Letter-spacing and uppercasing do not enter that test** — an 11px wide-tracked uppercase label is normal text and bound by 4.5:1.

Two real AA failures were found in shipped code and fixed the same day: the "Coming" label used `--gold-dim` (3.61:1) and the footer used an undeclared `#68738c` (3.41:1) — a colour invented outside the palette and never measured. Both now use `--muted`. **Live audit after the fix: 21 text elements, 0 failures, lowest ratio 6.47:1.** An audit script, not an opinion.

The earlier worry that small gold metadata was under-contrast was **wrong**: `#d8b45c` at 8.17:1 clears AA *and* AAA at any size. The residual risk there is typographic — stroke weight and x-height at 11px — and no verified source supplies a size floor for it.

**Standing rule:** any new colour gets measured before it ships. The footer failure existed because a colour was written straight into a rule instead of taken from the token table.

**Logo asset:** `assets/logo.png` — to be supplied by Daniel from the source image. Until it lands, the header carries an inline SVG lighthouse mark drawn in the same gold, explicitly a **placeholder** `[ASSUMED stand-in]`, not a substitute for the real mark.

Directions **B (Daybreak)** and **C (Workbench)** are rejected and their files deleted. B was bright warm paper with dawn light — welcoming but generic. C was a paper workbench with numbered sections — the most literal "show the homework" and, as predicted in D4, the coldest. Recorded here so neither is rebuilt from scratch by a future session.

## D10 — Mantras are pillars, not decoration

**RULED: the mantras come off the landing page.**

Daniel: *"The mantras should not just be sitting there over everything. They are the core pillars of how we approach things. They seem just tossed in over the play/watch nodes."*

He is right, and the diagnosis is sharper than the fix: a strip of five aphorisms above the navigation reads as ornament — the visual language of a banner, applied to the thing that is supposed to be load-bearing. Putting them everywhere made them mean nothing.

**Where they go instead:**

1. **An About page carries them properly**, with room to say what each one actually means in practice.
2. **Used inline around the site, they are bolded** — a mantra appears where it is doing work (in a module, on a build note, next to a failure), set in bold so it reads as a pillar being invoked rather than a slogan being displayed.
3. **The landing page does not list them.** It links to About.

This supersedes the mantra strip present in all three v0 direction mockups.

## D8 — Family names in public work

**RULED: leave them. This is deliberate, not an oversight.**

Raised 2026-07-20 when a content survey found Daniel's son named with his age in the public `arcade-progression` repo — 15 occurrences across 8 files, four of them inside game HTML that GitHub Pages serves live, one carrying his verbatim quote. Surfaced for a decision precisely because it had happened by accumulation rather than by choice, and because a site under Daniel's own name changes what a first name links to.

Daniel's ruling, in his words:

> "Leave it, but I want my words as to why. I am putting my work, my wife's work, and eventually the children's work on the internet to help people. This is our family business now, this is our ministry. I don't need to make him a focal point, but this is also about authenticity. If anyone wanted to figure out my family and their names it wouldn't take long. So leave it, it is real."

**Operative constraints this ruling carries — these bind the site's design:**

1. **No amplification.** "I don't need to make him a focal point" is a working constraint, not a sentiment. Credit stays where it was earned (his reach-defect catch is the best entry in `UX_DECISIONS.md` and it keeps his name); the site does not build features, headings, or navigation *around* the children.
2. **Authenticity is a stated value of this ministry**, and sanitized work would contradict the thesis. The fumbling is the point; so are the people.
3. This is a **family business and a family ministry.** Wife's and children's work is expected on the site over time. See D1 — voice stays first-person singular *today*, but D7's "do not foreclose" now explicitly covers contributors who are family.

**Not to be re-litigated.** A future session finding a name in a public repo should read this entry and move on, not re-raise it.

---

## Mechanical parameters — recommended by Claude, standing unless vetoed

| # | Parameter | Ruling | Why |
|---|---|---|---|
| M1 | Host | **GitHub Pages** | Fleet precedent live and verified (arcade-progression serving byte-identical files). Free, custom domain, push-to-deploy, verification is one HTTP check. |
| M2 | DNS | **apex + `www` CNAME → Pages** | Four A records at the registrar. Daniel's hands, not Claude's. `[ASSUMED]` — registrar not yet named; Phase 4 concern, does not block v0. |
| M3 | Build step | **None.** Hand-written HTML/CSS, zero deps | Same as every game on the arcade ladder. A generator buys nothing at v0 and costs a permanent dependency. |
| M4 | Catalogue | **Hand-curated** | Generating from repo files couples "in the repo" to "published." Automate when the list gets long enough to hurt. |
| M5 | Games | **Linked, not copied** | Copying a game's `index.html` here creates a second home for one file; dual-home drift has bitten this fleet twice (harness R2, Lab `invaders/`). `[ASSUMED]` — iframe touch/keyboard focus on mobile is untested; to be verified in the browser pane, not assumed. |

---

## The visual gate — method, ruled 2026-07-20

Phase 0(b) requires visual reference before code. Daniel's pushback on the first framing was correct: *"2-3 screenshots? Of what?"* — asking him to source reference for a site that does not exist yet is asking him to do the design work.

**Inverted:** Claude produces the candidate directions as real rendered HTML, screenshots them, and Daniel picks by eye. His eye remains the gate — that is the part arcade rung 8 lacked — but sourcing the candidates is Claude's work.

Rejected directions are **named in the STATE OF BUILD log and their files deleted**; only the chosen direction persists, as the reference the SCOPE's visual criteria are written against. (Nothing is allowed to just sit — `Claude\Lab\` teardown law, applied by analogy.)

---

## D11 — Publishing the Lessons: curated + genericized. LOCKED 2026-07-21

**What ships:** teaching modules from the (private) harness + Drive curricula, published as public HTML lessons. Not wholesale — **curated**, and every real name **genericized**.

- **Curated starter = Tier 1 "The Honest Machine" (8 modules).** Reviewed all 16 harness Teaching modules; the beginner tier is self-contained (its own Graduation Build) and Chelsie-level. Tiers 2–3 of the harness set (mesh/CAS-heavy) were held.
- **Genericization is a hard rule, applied consistently.** Product/project names → generic: LiftLens → "a tool I built". Collaborator → generic: Chelsie → "a teammate". Machine/repo/person from the Drive set: `Sobevista-mesh` → "a dedicated machine account", `Pong_Tower` → "a game repo of mine", Daniel → first person. **The one non-negotiable line: the real client's name never appears** (and is not written into this planning doc either) — it becomes "a real local business" wherever the source named it. Rationale (Daniel): *consistency lets us track deviation* — a real name showing up anywhere is then a detectable anomaly.
- **Verification law:** a published lesson is not done until an **independent grep** (not the author/render-agent's self-report — M5's witness principle) confirms zero forbidden tokens. Kept illustrative, non-secret material: model slugs, env-var *names*, `gh`/code identifiers, public third-party tools (Siteliner, Rich Results Test).
- **Repo-docs note:** the client name is NOT in this repo's planning docs (sight corrected the reconstruction). Remaining names there are Daniel's own projects (LiftLens/CAS) + Chelsie — Chelsie stays per D8; the project names are an optional targeted redaction, not urgent. Decision records are not gutted to genericize.

## D12 — Two-tier curriculum + the door-finder quiz. LOCKED 2026-07-21

- **Two tiers, clearly separated so a non-technical visitor is never dropped into infrastructure (D3):** Tier 1 **The Honest Machine** — the principles; Tier 2 **Building the Machine** — the hands-on track (Mail Slot / Depth Chart / Fuse Box / First Lap / Kill Test), sourced from the Drive `Guess and Click` Chassis Curriculum. Tier 2 is more technical and builds on Tier 1; the index says so.
- **"Find your door" quiz** (`/lessons/find-your-door/`): the Cognitive Profile diagnostic (10 forced-choice Qs → Builder/Architect/Translator/Validator, the same four doors every lesson offers) as a client-side interactive. **It collects nothing and sends nothing** — pure in-browser tally (INV-W3: nothing to take, no obligation incurred). Older curriculum machinery in the source doc (n8n, Compass/Maverick tracks, Exit Benchmarks) was dropped; only the four-door core was kept.
- **Consistency over source fidelity of format:** the Drive modules used a richer "cognitive entry points / five primitives" layout; they were **normalized to the identical b4him lesson template** so all 13 lessons look like one system.

## D13 — The cyber track may publish, through the gate. LOCKED 2026-08-16

**Ruled in session.** `purple-team/PUBLICATION_GATE.md` was **ADOPTED AS WRITTEN** and is in
force. It had been a draft since 2026-08-15 and was already blocking real work, which is the
cheapest possible proof that an unruled gate is not a neutral state.

- **What it means for b4him:** a rung write-up is publishable when it is about a **class**, not
  a target; when the reader leaves with **understanding** rather than a bare capability; and
  when it would survive being read back by the owner of the system it describes. Our own rung
  is a target we own, so its full write-up — flaw *and* fix — qualifies. That is the b4him
  promise: show the homework, fumbling included.
- **Every cyber piece ships with its blue half attached.** A break published without its
  detection is half a lesson and the wrong half.
- **The blue seat holds the gate; red may not self-clear.** Same never-self-grade law as the
  rest of the system, and it makes governance a seat rather than a title.
- **Daniel rules per-piece.** Not delegated, not inherited from a previous approval.
- **P9 (coordinated disclosure / CVD / safe-harbour) is a named gap, not a blocker.** He was
  offered the option of holding the whole track behind that research and declined it. Until it
  lands, "we found something real" routes to him rather than being improvised.

## D14 — Publish the recovered Guess & Click tier. LOCKED 2026-08-16

**What ships:** the advanced tier (`The_5System_Curriculum`), the two companion workbooks
(**59 exercises**) and the **20-term** automation glossary — recovered 2026-08-16 from an app
cache after being named missing from the entire estate, now tracked at
`Knowledge_Base/Teaching/_laptop_recovered/` in the harness.

- ~~**D11 held Tiers 2–3 as "mesh/CAS-heavy." That reasoning does not apply here.** Guess &
  Click is generic automation teaching with no harness internals.~~ **CORRECTED 2026-08-16, same
  day: that argument was made from filenames.** Opening the documents shows **all four are
  n8n-specific** — the glossary is subtitled *"n8n Terms"*, the advanced tier is *"n8n
  Automation — From Workflows to Systems"*, and 34 of the 59 exercises name n8n nodes. **D12
  had already dropped exactly this machinery** when it built Tier 2 from the same source. The
  approval stands, but on **D18's** reasoning rather than this one. *Recorded rather than
  rewritten: a decision argued from a document instead of from the thing itself is the house
  defect, and hiding the correction would waste the lesson.*
- **Convert from the generators, not the Word files.** All 19 build scripts were recovered
  alongside the documents. Regenerating is cheaper than transcribing and it is reproducible.
- **D11's genericization rule and its verification law both bind**, unchanged: an
  **independent** grep confirms zero forbidden tokens, never the rendering agent's self-report.
- **The glossary ships first** — 20 self-contained terms, no dependencies, and it gives every
  other lesson something to link to.

## D15 — Release cadence: two pages a week. LOCKED 2026-08-16

> **Superseded 2026-10-15 by Daniel's ruling E00568** (B4-CADENCE, ruled from the app): "Make the
> change to once weekly. It is better to have more work time between and if production hit our
> target then we can then increase after review. So once weekly is the tempo on Tuesdays." Now:
> **one page a week, Tuesday, hard cap 1 in any 7 days** (`tools/production_board.py`, build
> `b4him-weekly-cadence`). The text below is kept as the record of the earlier ruling.

**Tuesday and Friday, one page each. Hard cap: never more than 2 pages in any 7-day window,
even when a batch is ready.** Order: glossary → advanced tier → workbook exercises → cyber.
Roughly seven weeks for the Guess & Click set.

- **The rationale is editorial and is stated as such.** A steady cadence reads as a person still
  working; a bulk drop reads as an archive dump, and the site's whole premise is ongoing
  homework.
- **No SEO or spam-threshold claim is made, in this file or in public copy.** We hold no sourced
  evidence about what search engines treat as a spam signal, and asserting one would be `INV-W6`
  — *a widely-repeated fact with no primary source is a belief* — committed on the site whose
  own laws contain it. If the indexing question is ever worth answering, it is a research task
  with a source requirement, not a sentence in a decision record.

## D16 — Flashcards: verify first, publish only the verified. LOCKED 2026-08-16

197 cards exist in `purple-team/teaching/flashcards/terms.jsonl`. **Step 2 — verify each
against an outside definition per `VERIFY_CONTRACT.md` — is unchecked**, and
`NEEDS_DEFINITION.md` runs to 166 lines.

- **Run step 2 as its own task before any rendering work.** Daniel's ask was that they "look
  good"; doing the styling first builds a nice-looking wrong thing.
- **`terms.jsonl` already carries a `verification` field — that field decides what publishes.**
  Verified cards ship; the rest are held.
- **The page states the held count.** A partial set that says so is honest; a partial set that
  looks complete is not.
- **Publishing 197 unverified definitions on a site whose premise is honesty was the option
  declined.**

## D17 — Where exercises live. OPEN, not yet ruled

The 59 workbook exercises would be the first thing on this site that invites an answer.
`INV-W3` says *collection is the trigger, not audience*, and `find-your-door` was deliberately
built to collect nothing and send nothing.

**Proposal awaiting Daniel:** exercises are printable / self-checked, in-browser only, storing
nothing — the same posture as the quiz. Any future exercise wanting a submitted answer is a new
decision under `INV-W3`, not an implementation detail.

## D17 — Exercises are printable, self-checked, and store nothing. LOCKED 2026-08-16

The 59 workbook exercises would be the first thing on this site that invites an answer.
`INV-W3` says **collection is the trigger, not audience**, and `find-your-door` was built to
collect nothing and send nothing.

- **Pure in-browser. Nothing stored, nothing transmitted, no accounts, no progress sync** —
  the same posture as the quiz.
- **Printable is a first-class output, not a fallback.** A workbook is a thing you write on.
- Local-only saved progress was offered and **declined**: it is state we do not currently keep,
  and `INV-W3` deserves a fresh look before that changes.
- Any future exercise wanting a submitted answer is **a new decision under `INV-W3`**, never an
  implementation detail.

## D18 — We teach the tool AND the invariant under it. LOCKED 2026-08-16

*The answer to "does b4him teach a tool?", and it is bigger than the question. Daniel's words:*

> *"Yes we teach specific tools as they were learned by me, but then we also extract what
> universal first principle / invariants we can extract from them. Building n8n to networks to
> all of it touching the same foundational principles. We label the separate track while on the
> teaching side ensuring we are reinforcing the foundations in form and manner."*

**This supersedes the reasoning in D12 that dropped n8n machinery as noise.** The tool is the
**vehicle**; the invariant is the **cargo**. Stripping the tool removes the evidence that the
principle was ever learned rather than asserted — and *"as they were learned by me"* is the b4him
promise, not a stylistic note.

**Three things this binds:**

1. **Tool tracks are labelled, not hidden.** Tier 1 and Tier 2 stay tool-agnostic and remain the
   front door (D3, D12) — a non-technical visitor is never dropped into infrastructure. A reader
   chooses the n8n track.
2. **Every tool lesson names the invariant it instantiates**, explicitly, on the page. n8n,
   networks and the cyber rungs are different windows onto the same foundations, and the page has
   to say which foundation it is showing or the claim is decoration.
3. **The form reinforces the foundation.** *"…in form and manner."* The lesson template carries
   the invariant as a **structural row**, not a closing remark.

**The template already exists and is proven.** `purple-team/ranges/rung01_access_control/laps/
FINDINGS.md` runs *What I did · What came back · Noise · **The invariant** · Why it matters*, and
describes that row as **"the link from my one lap to the field."** That is D18 in working form.
**The n8n track and the cyber track therefore share one lesson shape**, which is also why the two
tracks reinforce each other instead of reading as two sites.

## D19 — Publish the two tracks that exist and say so. LOCKED 2026-08-16

The advanced tier ships **Builder and Architect only**. The site offers four doors and
`find-your-door` routes readers to all four.

- **Publish the two, and state plainly on the page that Translator and Validator are not yet
  written.** A reader who took the quiz and got Translator finds an honest absence rather than a
  silent one.
- **Writing the missing two was declined**: that is Claude authoring curriculum Daniel never
  approved, and it would delay the tier by weeks.
- Consistent with the site's premise — show the homework, fumbling included, gaps visible.

## D20 — The glossary ships as two pages. LOCKED 2026-08-16

20 terms, ~2,590 words, each carrying **TECHNICAL / PLAIN / ANALOGY / COMMON MISTAKE**.

- **Split Beginner terms from Intermediate & Advanced** — it matches the tiering the document
  already declares, fills two slots, and avoids one very long scroll.
- **The ANALOGY row is already speaking the site's language**: the source says it is
  *"especially useful for Translator-profile learners."* That is a four-door hook the glossary
  brought with it, and it is the cheapest possible link between the tool track and Tier 1.
- **Drafting is approved and starts now.** The glossary is the first piece into the pipeline
  because it is self-contained and gives every other lesson something to link to.

## D21 — Headings are Title Case. LOCKED 2026-10-20

Daniel, rejecting Glossary II (ledger E00615): *"The titles need Sentence Structure or whatever it
is for instance the heading 'The twenty' should read 'The Twenty'."* And on 2026-10-20: *"The
redraft needs to look at all the headings ... headings as a whole"*; *"change the headings."* So
the rule is site-wide, not a Glossary fix.

**Headings use Title Case (Chicago):**

- Capitalise the **first and last word**, the **first word after a colon, dash or "·"**, and
  **every major word** — pronouns, verbs, *Is*, *That*, and both parts of a hyphenated word
  (*Bottom-Up*, *Hands-On*).
- Lowercase **articles** (a, an, the), **coordinating conjunctions** (and, but, or, nor, for, so,
  yet), **"to"**, and **prepositions of four letters or fewer** (at, by, for, from, in, into, of,
  off, on, over, per, up, via, with) — unless first or last.
- **Code terms and acronyms as written**: n8n, JSON, AI, Run_ID.
- **Covers** `<title>`, h1–h6, track and section labels, table headers, nav and pager link titles.
- **Does not cover** body sentences and blurbs: they stay sentence case. A heading that is a
  **full sentence ending in a period** stays sentence case (the Writing page's laws).

The word-level list is the working spec Claude applied to his instruction, standing unless he
vetoes it. First applied by SITE-PATCH-HEADINGS-1 to every published page except Glossary I
(patched separately) and pages racked for release (patching those would void their approvals).