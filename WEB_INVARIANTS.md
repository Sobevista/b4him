# WEB_INVARIANTS — laws of building a website

*Born 2026-07-20, during the b4him build. Same doctrine as the arcade trove: **the trove is the deliverable.** The point is that the next site is more plug-and-play than this one.*

## Routing rule — nothing belongs in two places

| Kind | Home | Test |
|---|---|---|
| **Law** — would be wrong to break on any site | **this file** | "would I want this true on a site I haven't imagined yet?" |
| **Choice** — priced, with a re-pick trigger | `DECISIONS.md` | "a different project could rationally decide the opposite" |
| **Sourced fact** — perishable, dated, cited | `RESEARCH_*.md` | "this could be false next year without anyone lying" |

**An invariant must carry the specific failure that bought it.** A law that never cost anything is an opinion in a nice font. Entries below are seeded from failures inside this build — not harvested from the research reports, which are facts, not laws.

---

## INV-W1 — A colour written outside the token table is a colour nobody measured

**Bought:** the b4him footer shipped at `#68738c` on `#152039` — **3.41:1, a WCAG AA failure.** It was invented inline in a CSS rule instead of taken from the palette. When the palette was sent for contrast research, this colour *wasn't in it* — so the research couldn't have caught it, and didn't. It was found only by auditing the rendered page.

**The law generalizes past colour:** any value that bypasses the declared system also bypasses every check built around that system. The check isn't wrong; it was never pointed at the value.

## INV-W2 — Measure the whole surface, not the part you suspect

**Bought:** the same session. I predicted the small gold metadata text was under-contrast and flagged it for research. It measured **8.17:1** — passing AA *and* AAA. Meanwhile two colours I never suspected were failing. My suspicion was the least informative thing in the process.

**Corollary:** re-measure after the fix, with the same instrument. "I fixed it" is a claim, not a result.

## INV-W3 — Collection is the trigger, not audience

**Bought:** the COPPA finding. The instinct is "are children the audience?" — but the statutory duty attaches to *collecting personal information*, including persistent identifiers. A page that collects nothing is a far smaller target regardless of who visits.

**Generalizes:** before asking "who is this for," ask "what does this take from them." Obligations follow the data, not the demographic.

## INV-W4 — A navigation label must predict its destination

**Bought:** b4him shipped **Learn / Play / Watch / The Work**. I audited that nav, flagged "The Work" as insider language, and passed the other three — which turned out to be the *exact* vague-verb pattern the usability guidance names by example. I caught the one that felt clever and missed three that felt natural.

**The tell:** familiarity is not the same as clarity. A label that reads naturally *to the person who built the thing* is the hardest failure to self-detect.

## INV-W5 — A stage that reports "partial results" may have found the answers and discarded them

**Bought:** the first research run returned five of eight sections empty. It looked like a search failure. It wasn't — the sources were fetched, the claims were extracted, and a global ranking with no per-topic quota **threw them away unverified**. The answers existed and were dropped by arithmetic.

**Generalizes:** when a pipeline reports failure, distinguish *failed to find* from *failed to keep*. Read the stage boundaries, not the summary. This is the same shape as a test suite reporting success on the one axis it measures and silence on every other — the instrument was cheap precisely because it dropped the hard part.

## INV-W6 — A widely-repeated fact with no primary source is a belief

**Bought:** thirteen claims died under adversarial verification across three runs, and none were obscure. "WCAG mandates an 80-character line length" — it does not. "Uppercase harms readability" — refuted. The halation/astigmatism story cited in nearly every dark-mode article — **no peer-reviewed support found at all.**

**Practice:** trace to the primary source or tag the claim `[ASSUMED]`. A citation chain that terminates in another blog post is not a citation chain.

## INV-W7 — The author of a competing tool is not a neutral source about the tool it competes with

**Bought:** the entire "WCAG 2.x can't be trusted for dark mode" argument was refuted. It traces to the author of the replacement algorithm. The *arithmetic* properties survived verification — a verifier recomputed them independently — but the *perceptual-superiority* claims did not.

**The distinction worth keeping:** an interested party's checkable claims can be checked. Their judgment calls carry their interest. Separate the two rather than discarding or swallowing the source whole.

---

## Candidate laws — not yet earned

Held here deliberately rather than promoted, because nothing has paid for them yet in this build:

- *Visual reference before code; a fidelity build is not done until a side-by-side against reference passes.* — Bought on the arcade ladder (rung 8), and it **held** here: b4him wrote zero page code until the logo arrived. Promote once it has cost or saved something on a second site.
- *Do not architect for a scale you do not have.* — the v0/v1/v2 ladder is behaving, but the temptation has not yet actually been tested.
