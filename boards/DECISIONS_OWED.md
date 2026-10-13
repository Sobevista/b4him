# Decisions owed — b4him

*Read by the harness app (review_inbox scans b4him). Each block is one decision with a recommendation; APPROVE
adopts the Recommendation line. Raised 2026-10-13 from an isolated design read of the transcript-to-inbox production
line (claude-mythos-5-1, max effort; response in session 1b87b74c's scratchpad `mythos/RESPONSE.md`).*

### B4-AUTHORSHIP — what the site says about how its pages are made

- **What this is to the build.** Every lesson says "I". The pages are drafted by AI from your sessions, reviewed by a
  second model, and read in full and approved by you. Today nothing on the site says so.
- **Why this decision exists.** The voice audit measured the drafts at 1–4 first-person words per 1,000 against 27 on
  your About page. A page that says "I" and was never in your voice is a quiet lie on a site whose value is honesty.
- **What changes if you approve.** A short site-wide note on how pages are made, plus a one-line provenance footer per
  page ("from my session of <date>; drafted with Claude; reviewed by a second AI; read in full and approved by me on
  <date>"). And with each yes to a pitch you give two sentences in your own words, which seed the draft.
- **What it does to the aggregate, measured.** Not measured. Cost on your side: about two sentences per approved
  piece.
- **Cross-checked by, including where it is weak.** Only one outside model's view (Mythos), not yet a second family.
  The footer wording is a proposal.
- **Recommendation.** Approve both: the disclosure plus footer, and two sentences in your words with each yes.

**DANIEL:** _pending_

### B4-CADENCE — cadence against honesty

- **What this is to the build.** The plan's target is two posts a week and six weeks of runway. Climbing from half a
  week to six means several full page reads a week for about two months.
- **Why this decision exists.** Runway pressure is the force most likely to lower the bar: padding slots with weak
  pieces.
- **What changes if you approve.** The bar never moves for runway. A slot with nothing good stays empty (the release
  job already skips and logs it). Small forms (glossary terms, corrections, law cards) may take the second weekly slot.
- **What it does to the aggregate, measured.** With today's 14 tiles approved, runway is about 7 weeks without
  lowering anything.
- **Cross-checked by, including where it is weak.** Mythos plus PRODUCTION_PLAN §3 ("not backfilled"). Not tested
  against a real dry spell yet.
- **Recommendation.** Approve: an empty slot over a weak page, and small forms allowed in slot two.

**DANIEL:** _pending_

### B4-PEOPLE — the standing people policy

- **What this is to the build.** Transcripts contain your wife, your children, a business partner and a client. Today
  each case is ruled piece by piece (Module 13 kept your son's name and dropped the ages).
- **Why this decision exists.** An automated runner needs a standing rule it can enforce. It must refuse any name it
  does not know rather than guess.
- **What changes if you approve.** A registry: client never, not even unnamed if you say so; business partner by role
  only; children by first name only with your per-piece yes, never ages; wife by role only. Plus whether scars where the
  fault was your own directing are fair game.
- **What it does to the aggregate, measured.** Not measured.
- **Cross-checked by, including where it is weak.** D8, D11 and the Module 13 ruling are the precedents. The specific
  defaults are proposals, not measurements.
- **Recommendation.** Approve the registry above, and yes, scars of your own directing are fair game ("fumbling
  included").

**DANIEL:** _pending_
