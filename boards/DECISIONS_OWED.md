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

**DANIEL:** APPROVE — ruled from the app 2026-10-15 15:54 (ledger E00567). Built in plan v3 phase 6 (footer) and phase 2 (two sentences with each pitch yes).

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

**DANIEL:** REJECT — ruled from the app 2026-10-15 15:54 (ledger E00568). His note: "Make the change to once weekly. It is better to have more work time between and if production hit our target then we can then increase after review. So once weekly is the tempo on Tuesdays." Applied by build `b4him-weekly-cadence` (Tuesday only, 1 per 7 days), in progress at the build gate.

### B4-UNATTENDED — may an unattended job push to the public site?

- **What this is to the build.** The daily 08:30 task (`tools/daily.cmd`) pushes approved, byte-pinned pieces to the
  public b4him repo, which publishes them. You ruled one-tap auto-publish (E00472).
- **Why this decision exists.** `STANDING_AUTHORITY.md` §4 says unattended jobs hold no outward capability:
  external contact is "excluded from every clock forever, by his ruling." E00472 was never ruled against that line;
  the session that built the job did not read it until afterwards.
- **What changes if you approve.** (a) b4him only, narrowly: the job may push, and only bytes your tap pinned (as
  built; it refuses everything else). If you reject: (b) the 08:30 job prepares the release and raises a tile, and the
  push stays your one command each Tue/Fri.
- **What it does to the aggregate, measured.** (a) zero clicks per release; (b) one command per release, about twice a
  week.
- **Cross-checked by, including where it is weak.** The release code is going through the build gate tonight
  (`b4him-release-cockpit`, independent Fable breaker). Not yet reviewed by an outside model family.
- **Recommendation.** Approve (a), b4him only, pinned bytes only, as a written exception to §4.

**DANIEL:** APPROVE — ruled from the app 2026-10-15 15:54 (ledger E00569): (a), b4him only, pinned bytes only.

### B4-INBOX — where pitches reach you

- **What this is to the build.** The planned transcript runner proposes up to five lessons a week. You asked for them
  to "drop … at my email."
- **Why this decision exists.** Your harness app is the canonical decision surface (DOC-2), and §4 bars unattended
  outward contact. An email to yourself may or may not count.
- **What changes if you approve.** Pitches land as tiles in the app (the same way approvals do), plus a short email
  notice to you ("4 pitches waiting") from the weekly run.
- **What it does to the aggregate, measured.** One email a week, always sent, even on a quiet week, so silence never
  looks like a dead runner.
- **Cross-checked by, including where it is weak.** Mythos proposed email as the full decision channel; this narrows
  it to a notice. Not yet outside-reviewed.
- **Recommendation.** Approve: tiles plus a self-addressed notice, with the notice ruled not to be "external
  contact."

**DANIEL:** APPROVE — ruled from the app 2026-10-15 15:54 (ledger E00570): pitch tiles plus a self-addressed notice, not external contact. Whether it also covers the morning decision message is B4-MORNING below.

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

**DANIEL:** APPROVE — ruled from the app 2026-10-15 15:54 (ledger E00571). Built as the people registry the plan v3 program enforces before any model call and before publication.

### B4-MORNING — may the morning decision message be emailed to you?

- **What this is to the build.** Plan v3 phase 4 compiles one morning message from the app: every decision blocked on
  you, with proof links, what moved yesterday, and what failed or did not run. You answer in the app, never by reply.
- **Why this decision exists.** B4-INBOX (E00570) approved a self-addressed notice about pitches. GPT's review of v3
  (deposit 69c43598adcd) pointed out that stretching it to the full morning message widens what is sent; that is yours
  to rule, not ours to assume.
- **What changes if you approve.** One self-addressed email each morning, sent by a script to your address only,
  carrying decision titles, links and status (no transcript text), and pitch notices folded into it so it stays one
  email. If you reject: the morning sheet lives in the app only, and the pitch notice stays the only email.
- **What it does to the aggregate, measured.** Not measured. One email a day, always sent, even to say a job failed.
- **Cross-checked by, including where it is weak.** GPT (v3 review) recommends keeping it in the app until you rule.
  Proof links only open from your desk until private phone access exists.
- **Recommendation.** Approve: one self-addressed morning email, links and titles only, ruled not to be external
  contact.

**DANIEL:** _pending_
