# BUILD_OUTLINE — b4him.com

*Born 2026-07-20 (laptop node, LAPTOP-3GLEQ7L1). Repo-at-birth: live GitHub verified first — no `b4him` repo existed under Sobevista at creation time (10 repos checked).*

## Thesis

Show the homework. Publish teachings, exercises, progression and work product free, fumbling included. Beacon = lighthouse, not pulpit.

## Scope ladder (locked 2026-07-18, restated here)

**v0 static** → **v1 embedded YouTube** → **v2 owned comments / Patreon**.
Only **v0** is in scope. See README for the gates.

---

## Phase 0 — Scope + decision session (CURRENT)

v0 does not get a line of code until this closes. Two halves:

### 0(a) Human-owned parameters — OPEN, awaiting Daniel

Nothing below is assumed by Claude. Each is a decision with real consequences downstream:

1. **Host** — GitHub Pages (fleet precedent: arcade-progression is already live on it, zero cost, custom domain supported) vs anything else.
2. **Domain wiring** — who holds the DNS for b4him.com, and does the apex point at Pages or does a `www` CNAME.
3. **Build step** — none (hand-written HTML, fleet precedent: one file, vanilla, zero deps) vs a static generator.
4. **Resources catalogue shape** — is the "browsable folder tree" generated from the repo's own files, or hand-curated.
5. **What is actually publishable on day one** — the catalogue is only as real as the files in it. Which teachings/exercises/work product are cleared to publish, and which are private.
6. **Games on the site** — embedded copies, or links out to the arcade Pages site. (Copies mean a second home for the same file; the drift law says pick one.)
7. **Tone floor** — how explicitly Christian is the copy on the landing page. "Ministry in the purpose sense" is the thesis; the page still has to choose words.

### 0(b) SCOPE with **visual criteria** — REQUIRED, not optional

Law applied from arcade rung 8 (2026-07-19): that build shipped 26 machine criteria and **zero visual ones**, on a project whose entire deliverable was fidelity — so nothing could fail on account of looking wrong, and it took four round-trips with human-supplied reference before the look was in the ballpark.

**A website's deliverable IS how it looks.** Same trap, wider blast radius. So v0's SCOPE must carry named, checkable visual criteria — palette, type scale, layout at named breakpoints, what the page looks like on a phone — and **must gather visual reference before code** (the first of the two laws proposed 2026-07-19 and still awaiting ruling; adopted here regardless, because this build cannot proceed honestly without it).

Reference to gather: sites Daniel considers the right register. Not described in prose — captured as images.

### 0(c) UX/legal research gate — OPEN, running 2026-07-20

Daniel paused development here. Build resumes when the research lands and its recommendations are ruled.

Scope sent to research: navigation/header UX (item count, label wording, sticky headers, mobile patterns, and whether "The Work" is insider language); the **text-alignment hypothesis** (Daniel's: *"everything aligned to the left is good for an engineer, bad for the masses"* — sent as a claim to be tested, not confirmed); footer composition; US legal requirements at the *required vs recommended* line (privacy policy thresholds, cookie consent, CAN-SPAM's mailing-address rule against a no-home-address constraint, ADA/WCAG exposure, copyright and licensing); nonprofit structure (private foundation vs public charity for a publishing ministry); the **easy-posting problem** for a blog on a no-build-step static site; dark-theme and gold-on-navy contrast; and what actually matters for a site with no traffic yet.

Scoping answers from Daniel, 2026-07-20: no entity filed, **intent is a private family foundation** `[flagged — may conflict with a publishing ministry that later solicits support; research to settle]`; money not at v0 but likely later; email list + analytics + contact form all wanted, on a **"begin with the end in mind"** basis (build the hooks now, fill later); **no physical address published**.

## Phase 0(d) — Extract the invariants of building a website

Standing instruction from Daniel, recorded so it does not evaporate: *"This is us building a website. Extracting the invariants of the build needs to be on the radar so the next one is more fluidly guided and a bit more plug and play."*

Same lens as the arcade ladder, same deliverable shape: the trove is the product. Target artifacts, to be written as the build teaches them rather than invented up front:

- **`WEB_INVARIANTS.md`** — laws that would be wrong to break on any site, each carrying the specific failure that bought it
- **`WEB_UX_DECISIONS.md`** — choices with their tradeoffs priced and an explicit re-pick trigger
- Routing rule, as on the arcade: **law vs choice vs history — nothing belongs in two places**

Zero-waste principle: the research being run for this site is the first deposit. It is not a one-off cost if it is written down as reusable law.

### 0(e) — b4him's role inside LiftLens (recorded 2026-07-20)

Not a new idea — the missing half of one already written down. `Sobevista/LiftLens` → `VISION_SCOPE.md` names **b4him as one of three ground-truth control properties**: the *free sandbox* — "apply fixes and measure with zero consequence; also home base for the 'teach the masses' angle." LiftLens (scoped 2026-07-08) was designed to audit b4him; b4him (born 2026-07-20) is the site it audits. This note is the b4him-side pointer so a future session doesn't rediscover the link cold.

**Same chassis, two programs.** LiftLens and b4him run the identical doctrine:

| LiftLens | b4him (this session) |
|---|---|
| `PROPOSED_INVARIANTS.md` — agent proposes laws, human enacts | `WEB_INVARIANTS.md` — laws bought by a failure |
| "flagged, not scored" until a citable study lands | research tagged verified/refuted; nothing scored on vibes |
| conformance vs authoritative tools — "where they disagree, LiftLens is wrong" | `tools/contrast-audit.js` vs WCAG's own formula; 30+ claims refuted against primary sources |
| kill-gate: a non-technical reader must understand every finding | D3/D4 — audience non-technical, warmth is pass/fail |

**Two prospective moves, neither a v0 task (build the pages first, grade them second):**
1. Once b4him has ~5 real crawlable pages, make it LiftLens's first live conformance run — serves LiftLens Phase 2 *and* b4him's quality gate in one action.
2. `contrast-audit.js` is a candidate for LiftLens's **missing 8th module (accessibility/WCAG)** — LiftLens's seven-module table has none. Caveat: the audit is browser JS (WCAG contrast needs the *rendered* page); LiftLens probes are Python, so this is a port/headless-browser proposal for LiftLens's `PROPOSED_INVARIANTS.md` flow — **Daniel's to enact, not to be pushed into that CI-locked repo from here.**

**Scope trap named:** this connection tempts instrumenting b4him with SEO tooling before it has a finished page. Backwards. LiftLens is the brake pedal on b4him's web quality, not a v0 feature.

## Phase 1 — v0 static, landing page

Mantras + MBS. Passes the Phase 0(b) visual gate before it counts as done.

## Phase 2 — v0 static, resources catalogue

Browsable tree of the publishable work product.

## Phase 3 — v0 static, games in-page

DELIVERANCE first.

## Phase 4 — domain live

DNS cut over, verified by sight (HTTP 200 + markers in the live bytes, per fleet practice).

---

## STATE OF BUILD

*Append-only. Newest at the bottom.*

### 2026-07-20 — repo born
Repo created (`Sobevista/b4him`, public) after verifying live GitHub showed no existing b4him repo. Chassis seeded at birth: README, this outline, RESUME, CLAUDE.md, `.gitattributes` (LF everywhere — CRLF-churn law, 2026-07-17). CLAUDE.md seeded **at birth** rather than retrofitted, closing the Terminology Canon's fleet gap for this repo on day one.
Ruled the same session: b4him is a **project, not a Lab experiment** — it has a name, an owned domain, a locked tier ladder and a first resident, and no kill condition. The Lab is for disposable runs with pass criteria locked before the run; this is not that.
Status: **Phase 0 open.** No code until 0(a) is ruled and 0(b) has visual reference in hand.

### 2026-07-20 — Phase 0(b) CLOSED, then development paused at 0(c)
Daniel supplied the Beacon Ministries logo — the first real visual reference the project has had, and precisely what the 0(b) gate was built to wait for. **Direction A ("Hearth") chosen and recolored to the logo's gold-on-navy** (D9, full palette table); B and C rejected, files deleted, both described in DECISIONS so neither is rebuilt from scratch. **Mantras came off the landing page** (D10) — pillars, not ornament; they go on About and are bolded when invoked inline. `index.html` shipped and verified in the browser pane at 1280px and narrow: four cards, no overlap, no horizontal overflow, palette matching the locked tokens.

Known-not-done, on the face of it: `about.html` is linked twice and does not exist (both links 404); the header mark is an inline SVG `[ASSUMED stand-in]` awaiting `assets/logo.png`; small gold metadata text has **not** been contrast-measured (sent to research as 0(c) item 7).

**Then Daniel paused the build for research** — see 0(c). His instruction was explicit: go and do the research, do not assume. The scope grew past the landing page: a real header across all pages, a legal-complete footer, a blog with easy posting, and the alignment question. Also opened **0(d)** — extract the invariants of website-building so the next site is more plug-and-play.

### 2026-07-21 — the home built out end to end (laptop session, LAPTOP-3GLEQ7L1)
Daniel's framing: *"we need a home for all of this work."* Went from a local landing shell to a full, walkable site in one session. **Nothing deployed — all local (localhost:8000).**

**Infrastructure:** shared `/style.css` (the design system in ONE home — palette, beam, header + footer chrome; `index.html` refactored onto it, killing the copy-paste-into-every-page drift before it started — INV-W1's family) + `/lesson.css`.

**Rooms built — the nav now fully resolves:**
- `about/` — D1 first-person, D10 mantras as the five pillars. **Daniel's eye-gate PASSED** (his wife read it as his voice; he teared up reading it). Exactly the visual gate D9 was built to wait for.
- `games/` — the 9 arcade rungs, **playable in-page** via a lazy iframe player (progressive enhancement: real links with JS off; in-page overlay + `#slug` deep-links with JS on). **M5's open `[ASSUMED]` resolved: GitHub Pages sends no `X-Frame-Options`/CSP, so embedding works** — verified live (open→play→close→deep-link, zero console errors). Single-home preserved (iframes the live arcade, copies nothing). Residual: real-device touch/keyboard inside the frame not tested (can't, through automation).
- `writing/` — the 8 `WEB_INVARIANTS` rendered reader-facing (the homework of building this very site) + pointers to the public arcade trove.
- `videos/`, `blog/` — honest "coming" shells (D6: the shelf gets its place at v0; blog's easy-posting problem stays open).
- `lessons/` — a **13-module, two-tier curriculum + an interactive quiz** (below).

**Lessons — the centerpiece.** Reviewed all 16 harness Teaching modules; published **Tier 1 "The Honest Machine" (8)** as the curated starter set (self-contained, Chelsie-level). A Drive discovery pass (`Guess and Click / Dan - Teaching`) surfaced more homework → **Tier 2 "Building the Machine" (5)**: Mail Slot → Depth Chart → Fuse Box → First Lap → Kill Test (capstone) — the hands-on infra track, normalized to the same template. **"Find your door" quiz** built from the Cognitive Profile diagnostic (10 Qs → Builder/Architect/Translator/Validator; scoring tested; collects/sends nothing — INV-W3). Graduation Builds on both tiers.

**Genericization (Daniel's rulings):** publish the modules but genericize product/client names — LiftLens → "a tool I built"; the real client's name → "a real local business" (hard line, non-negotiable — the name is not written here either); Chelsie → "a teammate"; `Sobevista-mesh`/`Pong_Tower`/Daniel → generic / first-person. Applied consistently ("consistency lets us track deviation"). **Independent grep across all 13 modules = zero forbidden tokens** — the witness check (M5), run on our own terms, not the render-agents' self-reports. Sight corrected a reconstruction: the client name was never in the repo docs at all (the earlier flag was the broad pattern matching LiftLens/CAS/Chelsie).

**Method:** tier-1 modules 2–8 and all 5 tier-2 modules were fanned out to parallel subagents against a Daniel-approved Module-1 exemplar; every output grep-gated + eye-sampled before acceptance. Show-one-before-eight, then verify.

Status: **v0 content complete and walkable; nothing deployed.** Next: Daniel's `assets/logo.png` (unblocks header mark + og:image + favicon), then Phase 4 (Pages + DNS). Un-added from discovery (Daniel's call): the older n8n curriculum, glossary, flashcards.

### 2026-07-22 - DEPLOYED LIVE + visual identity landed
b4him.com is live (GitHub Pages main/root + DNS + custom domain; all pages HTTP 200; HTTPS cert auto-provisioning - tick Enforce HTTPS when it finishes). Real logo wired site-wide: gold crest -> header mark on all 21 pages + root favicon.ico/apple-touch-icon.png; lockup -> assets/og.png (1200x630 social). Masters + assets/brand/make_assets.py preserved.
Visual identity (homepage-approved, then rolled out site-wide): Fraunces self-hosted via /style.css (INV-W9 - type is part of the message); Option D transparent-crest watermark on the homepage hero (keyed off the navy to kill the pasted-disc halo); title-case applied to all 21 H1s; hero leans into failure; invitation kept but demoted to a quiet second beat.
Open (Daniel's): Enforce HTTPS when the cert lands; watermark could extend to section-landing heroes if wanted.

### 2026-10-15 — B4-DEDUP handoff to Claude

**From:** Codex, at Daniel's explicit request in the B4him review chat. This is a handoff and attention test, not a new human approval tile or a claim that the fix is implemented.

**Daniel's concern:** "Do we have a cross reference to make sure the suggested content is not duplicate in some way? That would seem to also be a filter that would minimize waste". He then asked: "try to ping claudes attention to this oversight from here, or setting in a file to see if it gets his attention type thing".

**Finding:** Mythos explicitly proposed a registry comparing candidates with published, rejected and open material, folding duplicates into evidence. In the v3 plan and umbrella contract inspected by Codex, that editorial gate was not explicit. The B4him release check preventing two publications on one day is not content deduplication. Codex also missed this omission in its initial v3 review. Recheck current files before acting; another session may have advanced them.

**Evidence (harness root: `C:/Users/dansl/Claude/Projects/Data Import/Connection`):**
- `Knowledge_Base/Research_Corpus/2026-10-13_b4him-2026-10-13-mythos-production-line-design/DELEGATE_REPORT.md`, line 170: registry against published / rejected / open; line 350: over-folding risk; line 398: breaker should try to pitch a duplicate.
- `_briefs/2026-10-15_PRODUCTION_LINE_PLAN_V3.md` and `tools/build_gate/contracts/production-line-v3.md`: reviewed for the missing requirement.

**Requested follow-through:** Acknowledge this handoff below. Reconcile the requirement into the plan and the lesson-trial contract through the existing production process, before scaling. Compare each candidate against published lessons, queued drafts, open pitches and rejected pitches before it reaches Daniel. Show the closest existing piece and what the candidate adds. Suppress the same takeaway in new wording; attach corroborating incidents as evidence; distinguish substantive updates/corrections and distinct follow-ups. Do not reject solely because two pieces discuss the same topic, or permanently suppress a rejected pitch when new evidence changes its case. Test both paraphrased duplicates and legitimate distinct lessons on the same topic. This note proposes the implementation direction; it does not certify a deployed filter.

**Attention-test receipt:** PENDING — Claude has not acknowledged this note to Codex. When read, append the acknowledgment time, session identity, and disposition (including the contract/build reference or reason for deferral). File delivery alone is not evidence of attention.

**Test closure — 2026-10-15:** Daniel reported "Didnt work, haha it was worth a shot" and requested this clarification. The file placement above was an experiment in attracting the active Claude session's attention, not a delivered message or a standing acknowledgment obligation. CLOSED: no acknowledgment observed/reported; the exact reason was not established. This closure supersedes the PENDING receipt and the request to acknowledge. Do not revive the notification test or treat it as a new assignment. The editorial deduplication finding remains a separate recommendation; this test neither implements nor resolves it. A later reader encountering this note is not evidence that the original live-session notification worked.

### 2026-10-20 — first piece published; production line v2; two patches offered

**Published:** GC-GLOSS-1 (Glossary I) on its Tue slot — the first published piece (`3c0d59b`).

**Daniel's taps applied:** REJECT GC-GLOSS-2/3 (E00615/E00616; his note: Title Case all headings). APPROVE T4-L1..L6 at `bc31405` and T5-L1..L6 at `2dffd67` (ledger rows in the APPROVED commits, e.g. `0d7d78d`). `6245a98`: T5 stage-2 name check recorded PASS after the fact (T5 was tapped before it ran); stale T4 tap labels cleared; GC-GLOSS-2 back to redraft with his note.

**Production line v2** (`7e5a0d5`, fast-forward of `integrate/2026-10-20`; merge `45dcccf`): REJECT carries Daniel's note and requeues; release refuses an open `blocked_on` or an unapplied ruling; a PATCH LINE separate from content (Daniel: patches move outside the queue — two schedules, content and patches); stage 2 runs before the tap as a record bound to blobs; furniture re-pin on a tapped patch; five breaker rounds. **D21:** headings are Title Case (`ba4970b`).

**Offered for his tap:** GC-GLOSS-1-R1 (Glossary I fold + open-all, his request; `1a82b36`) and SITE-PATCH-HEADINGS-1 (79 headings on 21 pages; `485751b`). Proof: https://claude.ai/artifact/CB1BNZ67JUM4Lj8LciU53Q. **The headings patch must be tapped before 2026-10-27** — T4-L1 rewrites `lessons/index.html`.

**Not yet ruled:** research commission b4him-site-operations (harness `Knowledge_Base/Research_Corpus/2026-10-20_b4him-site-operations/RECOMMENDATION.md`): two lines, a roster of seats, a maintenance calendar.

**Known gaps:** `data/people_names.local.json` is absent, so the registry's known-name check cannot run (UNKNOWN, not PASS). Cycle run `b4him-gloss-r1-20261020-e66ba1` parked: orient gate UNKNOWN; the fix is harness-owned.

**Next:**
- Daniel taps the two patches (headings before 2026-10-27).
- In flight: n8n track heading patch; reduced-motion patch; approvals hint fix; Glossary II/III fold.
- 44 off-rule headings on the racked T4/T5 pages: patch each page after it publishes.
- Supply `data/people_names.local.json` so the known-name check can run.

### 2026-11-07 — the maintenance calendar is on a clock; catch-up, missed-start and the 07:30 release time
Written from the Glitch calibration session (the harness's record of the same day: `research/2026-11-07_calibration.md` in Daniel's Glitch vault).
Since 2026-10-20: cadence moved to one page a week, Tuesday (E00568, 2026-10-15); first piece GC-GLOSS-1 published 2026-10-20 (`3c0d59b`); GC-GLOSS-2 refused twice on dead links (10-27, 11-03), GC-GLOSS-3 rejected (E01363, the two glossaries link to each other); SITE-PATCH-SERVE-1 published 2026-11-06 (`3a2ff9b`, the site serves only the site: 35 paths 200, 6 internal paths 404); **the maintenance calendar merged to main 2026-11-06 (`e474a31`, 1262 passed, 1 skipped)** and `b4him-maint-run` registered the same day (daily 10:35); GC-GLOSS-2 re-offered with its links fixed and APPROVED 2026-11-07 (`a77b2bc`, E01459) for the 11-10 slot; SITE-PATCH-SHELF-1 published 2026-11-07 (`ddc1997`).
**Today:** the PC slept through 10:35 with StartWhenAvailable off (event 153, Last Result 0x800710E0); Daniel set the flag by hand and ran the task at 13:09 (exit 0; first receipts in `.maint/`, D1 D2 D3 only, because the clock made only the daily rows due on a Saturday). Two changes on main, ruled by Daniel in chat (CAL-2, CAL-4): a never-receipted row is due on the next run (25 rows had never run; the quarterly, half-yearly and annual ones would first have run 2027-01-04), and `maint_schedule.py` keeps StartWhenAvailable and WakeToRun on a re-register.
**Owed, found today:** D1 reads the release at 08:30 (`maint_watch.RELEASE_RUN_AT`, calendar row D1 "daily 08:30 + 2 h"), but the release task's trigger is stored at a fixed -05:00 offset and has fired at 07:30 local since DST ended 2026-11-01, so D1 writes "MISSING: no line from the 08:30 run by 10:30 (later: 07:31 PUBLISHED …)" every day and D3 sends `/fail`. A one-constant fix was tried and reverted: `_maint_cites/test_row_cites.py` pins the 08:25–10:30 window as the calendar's law, so the change is a calendar-row change (maint_rows.json D1 `at`, the cites, the MISSING wording, `daily.cmd`'s "08:30"), to be made as one piece with its tests. Until then D1 and D3 alarm falsely each morning.
Known: `rack_backup.py` says weekly on Task Scheduler but no such task exists (last bundle 2026-10-20); Q6 (the fire drill) is held out of catch-up and runs by hand on a watched day.
**Next:** tomorrow's 10:35 run executes 28 rows for the first time on the clock; the harness counts each from its first time-triggered receipt (`delivered.py`, 9 of 39 at 13:12 today); 11-10 publishes GC-GLOSS-2 or the log says why not.
