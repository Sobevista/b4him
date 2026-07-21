# RESUME — b4him

*Entry point for a cold session. Read this, then `BUILD_OUTLINE.md`.*

## Where this stands

**v0 content complete and walkable — nothing deployed.** (Full detail in `BUILD_OUTLINE.md` STATE OF BUILD, 2026-07-21.)

Every nav room is real: **About** (eye-gate passed), **Games** (9 arcade rungs playable in-page via iframe), **Lessons** (a 13-module two-tier curriculum + a "find your door" quiz), **Writing** (the 8 web laws + arcade pointers), **Videos**/**Blog** (honest "coming" shells). Shared design system in `/style.css` + `/lesson.css`. Phase-0 parameters are effectively settled (M1–M5, D9/D10, and D11/D12 for the lessons).

**Blocking a real launch (Daniel's, not Claude's):**
1. **`assets/logo.png`** — the real logo binary. Until it lands, the header mark is a placeholder SVG and og:image/favicon wait on it.
2. **Deploy = Phase 4** — GitHub Pages + DNS. Not done; the site is local-only on localhost.

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

Get `assets/logo.png` from Daniel → wire the real mark + og:image + favicon → then Phase 4 (Pages + DNS) to take it live. Optionally: eyeball the five tier-2 lesson pages (verified by grep + serve + coherence-sample, not each individually), and decide whether the older n8n curriculum / glossary / flashcards join the shelf.
