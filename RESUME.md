# RESUME — b4him

*Entry point for a cold session. Read this, then `BUILD_OUTLINE.md`.*

**Historical attention test (2026-10-15):** The file-based Claude handoff was a test, now closed. See `BUILD_OUTLINE.md` → **2026-10-15 — B4-DEDUP handoff to Claude** for its result and the separate editorial finding; no acknowledgment is owed for the test.

## Where this stands

**v0 content complete, walkable, and DEPLOYED LIVE at https://b4him.com since 2026-07-22** (GitHub Pages / main-root + DNS + custom domain, HTTPS enforced; re-verified live 2026-09-28, HTTP 200). Publishing has started: the first piece went out 2026-10-20 (`3c0d59b`). Counts and the rack live in `BUILD_OUTLINE.md` STATE OF BUILD and the queue, not here.

Every nav room is real: **About** (eye-gate passed), **Games** (9 arcade rungs playable in-page via iframe), **Lessons** (a 13-module two-tier curriculum + a "find your door" quiz), **Writing** (the 8 web laws + arcade pointers), **Videos**/**Blog** (honest "coming" shells). Shared design system in `/style.css` + `/lesson.css`. Phase-0 parameters are effectively settled (M1–M5, D9/D10, and D11/D12 for the lessons).

**Publishing is now automatic after Daniel's one tap (ruled 2026-10-13, ledger E00472; `PRODUCTION_PLAN.md` §2-3 amended).** The rack: his approval pins exact bytes (`approved_blobs` + the index furniture and entry hash) on main's queue, the bytes wait in git under an `approved/<id>` tag, and `tools/release.py` publishes them on their Tuesday slot (once weekly since E00568, 2026-10-15), pushes, and checks the live bytes. `tools/approvals.py` turns his tap in the harness app (`boards/APPROVALS_OWED.md`) into a racked row. Both were attacked by an independent breaker (11 real defects found, all closed; `tools/test_release_breaker.py`). Every `--apply` run logs to `release_log.jsonl` (local, ignored).

**Glossary I (GC-GLOSS-1) published on its Tue 2026-10-20 slot** (`3c0d59b`). Since 2026-10-20 the production line runs two lines — content and patches, on separate schedules (`7e5a0d5`; see STATE OF BUILD 2026-10-20). Headings are Title Case (D21, `ba4970b`). What is racked or awaiting a tap is in the queue and `boards/APPROVALS_OWED.md`, not restated here.

**Still blocked outside the machine:** rung 1 (CY-RED-1) needs Chelsie's blue-seat review (E00189: red never self-clears). PT-6 is NOT owed — ruled 2026-09-07 (E00213/E00227): "Purple Foundations", tier three, "the break-and-detect track"; its two naming edits (rung01 hero label, `lessons/index.html` tier-three heading) are still undone. CY-BLUE-1/2 and CY-JARGON-1 wait on the external cross; CY-BLUE-2 also rests on claim X7, which the seat cross refuted (purple-team `NEXT_SESSION.md`).

Phone previews: never one full-page screenshot. Chromium wraps past 16,384 device pixels (harness LESSONS L-012). Capture tiles and check them against the page.

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

The site is live (deploy done 2026-07-22). The open work is PUBLISHING, not building. Current next actions live in the newest `BUILD_OUTLINE.md` STATE OF BUILD entry (2026-10-20); runway is computed from the queue (floor 3 weeks), not written here.
- Glossary II/III (E00473) were REJECTED 2026-10-20 (E00615/E00616, "Title Case all headings") and are back to redraft (`6245a98`).
- Harness Modules 9–22 are written and not on b4him; converting them is the fastest runway. The scars inventory (26 candidates) is the next source after that.
- `tools/preview.py` exists (`b8a306b`): the rendered proof Daniel approves from.
