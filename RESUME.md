# RESUME — b4him

*Entry point for a cold session. Read this, then `BUILD_OUTLINE.md`.*

## Where this stands

**v0 content complete, walkable, and DEPLOYED LIVE at https://b4him.com since 2026-07-22** (GitHub Pages / main-root + DNS + custom domain, HTTPS enforced; re-verified live 2026-09-28, HTTP 200). What has NOT happened is publishing — the content pipeline has shipped 0 pieces. (Full detail in `BUILD_OUTLINE.md` STATE OF BUILD.)

Every nav room is real: **About** (eye-gate passed), **Games** (9 arcade rungs playable in-page via iframe), **Lessons** (a 13-module two-tier curriculum + a "find your door" quiz), **Writing** (the 8 web laws + arcade pointers), **Videos**/**Blog** (honest "coming" shells). Shared design system in `/style.css` + `/lesson.css`. Phase-0 parameters are effectively settled (M1–M5, D9/D10, and D11/D12 for the lessons).

**The real blocker is no longer deploy (done 2026-07-22) — it is PUBLISHING (Daniel's gate, not Claude's):**
1. **Blue-seat review** — rung 1 is written + previewed in `purple-team/publications/` but cannot cross the publication gate: ruling E00189 forbids the red seat self-clearing, so it needs Chelsie's blue-seat review.
2. **PT-6 — the cyber tier name** — owed by Daniel. Per `PRODUCTION_BOARD.md` (2026-08-31): runway 0.0 weeks, 12 pieces at SOURCE, 0 published.

**2026-10-13: the first piece is through Daniel's gates, on a branch.** Glossary I (GC-GLOSS-1, `lessons/glossary-beginner/`):
- Local branch `draft/gc-gloss-1` at `cde8b20` (origin has `832daba`). Daniel RULED it ("Approval on the Glossary as is") and PREVIEWED it ("Previewed and approved"), harness ledger E00470 and E00471. That branch's board gives it **Tue 2026-10-20**. Publishing that day is merging the branch into main, then Daniel's push. Main's `PRODUCTION_BOARD.md` cannot see the branch's queue until then: it still shows GC-GLOSS-1 at SOURCE.
- **Do not edit `lessons/glossary-beginner/index.html` before it publishes.** The approval is pinned to its bytes (`approved_blobs` in the queue row). An edit pulls it from its slot and needs a new RULED and PREVIEWED. Daniel's idea to fold each word's four rows is queued as GC-GLOSS-1-R1, deferred by him until after publication.
- The board generator now gives a piece the first slot whose review-by date it met, and pulls a piece whose approved bytes changed (`tools/test_production_board.py`). These fixes are on main too.
- Phone previews: never one full-page screenshot. Chromium wraps past 16,384 device pixels, and the 10-12 proof repeated the page (harness LESSONS L-012). Capture tiles and check them against the page.

**Un-added from the Drive discovery (Daniel's call):** the older n8n curriculum, glossary, flashcards.

## The law this build was born under

Arcade rung 8 (2026-07-19) shipped with 26 machine criteria and zero visual ones, on a project whose deliverable was fidelity. It passed its own tests while looking wrong, and took four round-trips with human-supplied reference screenshots to correct. Root cause: the archaeology brief never asked what the thing *looked like*.

A website's deliverable is how it looks. So:

- **visual reference is gathered before code** — images, not prose descriptions
- **the SCOPE carries named visual criteria** (palette, type scale, layout at named breakpoints, phone view)
- **"done" requires a side-by-side against reference**, checked against an image, not against the author's own tests

## Scope discipline

v0 static only. v1 (embedded YouTube) and v2 (owned comments/Patreon) are written down in the README so they stop being tempting. Self-hosting video before anyone is watching is rent on an empty theater.

## Next action

The site is live (deploy done 2026-07-22). The open work is PUBLISHING, not building.
- Glossary I publishes Tue 2026-10-20: merge `draft/gc-gloss-1`, then Daniel pushes.
- Drain the SOURCE queue so the runway climbs: Glossary II (GC-GLOSS-2) is next in order, from the same source and template, with D20 locked. Draft it on its own branch through the same stages.
- Unblock rung 1: blue-seat review, and the PT-6 cyber tier name.
- Optionally, decide whether the older n8n curriculum, glossary and flashcards join the shelf.
