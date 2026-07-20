# WEB CHASSIS — what the next site inherits

*Born 2026-07-20 from the b4him build. The point of the trove is that site #2 starts here instead of at zero. Copy this file's blocks; read `WEB_INVARIANTS.md` for why each exists.*

**Nothing in here is a framework.** It is a short list of things that (a) are settled enough not to re-litigate, (b) cost minutes, and (c) were each paid for by a real failure or a verified source.

---

## 1. The `<head>` block

Copy, then change the five obvious strings. Every line earns its place; nothing here is cargo.

```html
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SITE NAME</title>
<meta name="description" content="One sentence. Shown in search results and link previews.">

<!-- Social preview. For a site whose growth comes from personal sharing rather
     than search, these four tags outrank every SEO task. og:title, og:type,
     og:image and og:url are the protocol's required set. -->
<meta property="og:title" content="SITE NAME">
<meta property="og:type" content="website">
<meta property="og:url" content="https://EXAMPLE.com/">
<meta property="og:description" content="One sentence.">
<meta property="og:site_name" content="SITE NAME">
<meta name="twitter:card" content="summary">
<!-- Add og:image (1200x630) ONLY once the file exists, then switch
     twitter:card to summary_large_image. A tag pointing at a missing
     file is worse than no tag. -->

<!-- SVG icons are never auto-requested, so this link is required.
     On a CUSTOM DOMAIN, /favicon.ico and /apple-touch-icon.png are fetched
     from the root automatically and need no markup. That does NOT hold for a
     user.github.io/repo/ project site, where the probe hits the origin root. -->
<link rel="icon" href="/icon.svg" type="image/svg+xml">
```

**Favicon set, 2026:** three files, not twenty. `favicon.ico` (32×32), `icon.svg`, `apple-touch-icon.png` (180×180). PWA icons only if you actually want a PWA.

## 2. The contrast audit

`tools/contrast-audit.js`. Paste into the browser console; it runs on load and exposes `contrastAudit()` for re-runs.

Checks SC 1.4.3 AA — 4.5:1 normal, 3:1 large, where large is ≥24px or ≥18.66px bold. Reports AAA as information, never as failure.

**It flags what it cannot verify.** Text over a background image, gradient, or pseudo-element overlay gets grouped and reported by source, because a full-viewport overlay is one fact, not one-per-element. It does not check non-text contrast (SC 1.4.11), hover/focus states, or alpha compositing. **A clean run means "no failures on the axis this measures."**

## 3. Colour tokens — the discipline, not the palette

Declare every colour once as a custom property. **Never write a colour literal into a rule.**

This is INV-W1, and it was bought here: a footer shipped at 3.41:1 because the colour was typed inline. It wasn't in the palette sent for review, so review couldn't catch it, and it survived until the page itself was measured.

Measure each token against its background *when you declare it*, and record the ratio next to it. A token table with ratios in it is a contract.

## 4. Navigation — settled, don't re-litigate

- **Labels are concrete nouns.** Vague verbs — Learn, Explore, Discover, Play, Watch — are the documented failure mode. A label must predict its destination. Boring beats clever.
- **Never hide navigation on desktop.** Visible links, all sections.
- **Wordmark top-left, and it links home.** Unopposed convention; treat as strong, not proven.
- **Utility links go in the footer** — contact, privacy, terms — whether or not they also appear at the top.
- **"7±2" is a misapplication.** Menus use recognition, not recall. Item count needs no defence.

## 5. What is deliberately NOT here

For a new site with no traffic, these were checked and judged premature: structured data / schema, Core Web Vitals work (a no-JS static site passes by construction and can't generate field data without visitors), analytics, JSON Feed, ActivityPub, and most technical SEO. Google's own docs: *"You usually don't need to do anything except publish your site on the web."*

**One carve-out worth knowing:** that guidance assumes an inbound crawl path. A site with zero backlinks and zero social presence may have none — which is the case Google's "usually" is covering. Submit a sitemap at launch, not before.

RSS earns its place once there is a blog, because it doubles as newsletter infrastructure.

## 6. Legal — posture, not advice

Verified 2026-07-20 for a one-person US site with no commerce. **Not legal advice; re-check before relying on it.**

- No US state comprehensive privacy law reaches hobby scale (lowest threshold found: 35,000 consumers).
- No cookie banner if you don't target or monitor EEA residents.
- CAN-SPAM's postal-address mandate attaches only to **commercially**-purposed mail; the test is content, not sender identity.
- Copyright notice is conventional, not required. Creative Commons is **irrevocable** — use CC for prose, MIT/Apache for code.
- **COPPA is the one with no size floor.** It triggers on *collecting* personal information, including persistent identifiers. If a site has children's games, the cheapest safe posture is to collect nothing on those pages.
