/* ===========================================================================
   contrast-audit.js — measure every text element on a page against WCAG 2.x
   ---------------------------------------------------------------------------
   Born 2026-07-20 in the b4him build, after this logic was written inline three
   times in one session and after it caught two real AA failures that a research
   pass could not have caught (see WEB_INVARIANTS INV-W1, INV-W2).

   HOW TO RUN
     Browser console:  paste this whole file, press enter.
     Re-run any time:  contrastAudit()
     Quiet object:     contrastAudit({ log: false })

   WHAT IT CHECKS
     SC 1.4.3 Contrast (Minimum), Level AA:
       normal text  >= 4.5:1
       large text   >= 3:1   where "large" is >= 24px, or >= 18.66px when bold
     Reports AAA (SC 1.4.6: 7:1 / 4.5:1) as information, never as failure.

   WHAT IT CANNOT SEE  — read this before trusting a pass
     1. BACKGROUND IMAGES AND GRADIENTS. It resolves the nearest ancestor with a
        non-transparent background COLOR. A gradient, a photo, or an overlay
        (b4him's own radial "beam" is one) is invisible to it. Where a glow
        lightens the backdrop under light text, the true ratio is WORSE than
        reported. Text over imagery must be judged another way.
     2. ALPHA. Semi-transparent text or backgrounds are not composited.
     3. State. Only what is rendered now — not :hover, :focus, or open menus.
     4. Non-text contrast (SC 1.4.11, 3:1 for UI parts and meaningful graphics)
        is NOT checked. Borders, icons and focus rings need their own pass.

     A clean run means "no failures on the axis this measures." It is silent on
     every other axis, and silence reads exactly like success. (INV-W5.)
   =========================================================================== */

(function (global) {
  'use strict';

  // sRGB -> relative luminance, per WCAG. Threshold is 0.04045 (the corrected
  // value); the pre-2021 0.03928 differs only in the 8th decimal for 8-bit input.
  function channel(c) {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
  }

  function luminance(rgb) {
    return 0.2126 * channel(rgb[0]) + 0.7152 * channel(rgb[1]) + 0.0722 * channel(rgb[2]);
  }

  function parseColor(str) {
    if (!str) return null;
    var n = str.match(/[\d.]+/g);
    if (!n || n.length < 3) return null;
    var rgb = [ +n[0], +n[1], +n[2] ];
    var alpha = n.length > 3 ? +n[3] : 1;
    return { rgb: rgb, alpha: alpha };
  }

  function ratio(fg, bg) {
    var a = luminance(fg), b = luminance(bg);
    var hi = Math.max(a, b), lo = Math.min(a, b);
    return (hi + 0.05) / (lo + 0.05);
  }

  // Walk up until we find a background colour that is actually painted.
  // Returns the colour plus whether anything on the way up had a background
  // IMAGE — if so, the number is untrustworthy and we say so rather than
  // reporting a confident pass.
  function backdrop(el) {
    var node = el, imaged = false, imagedBy = null;
    while (node && node !== document.documentElement.parentNode) {
      var cs = getComputedStyle(node);
      var tag = node.tagName ? node.tagName.toLowerCase() : String(node);
      if (cs.backgroundImage && cs.backgroundImage !== 'none') {
        imaged = true; imagedBy = imagedBy || tag;
      }
      // Pseudo-elements paint too, and getComputedStyle(el) does not report them.
      // b4him's own "beam" is a ::before gradient on <body> — without this check
      // the tool would report confident numbers for text sitting under it.
      var before = getComputedStyle(node, '::before').backgroundImage;
      var after = getComputedStyle(node, '::after').backgroundImage;
      if (before && before !== 'none') { imaged = true; imagedBy = imagedBy || tag + '::before'; }
      if (after && after !== 'none') { imaged = true; imagedBy = imagedBy || tag + '::after'; }
      var c = parseColor(cs.backgroundColor);
      if (c && c.alpha > 0) return { rgb: c.rgb, imaged: imaged, imagedBy: imagedBy, from: node };
      node = node.parentElement;
    }
    return { rgb: [255, 255, 255], imaged: imaged, imagedBy: imagedBy, from: null };
  }

  function ownText(el) {
    var t = '';
    for (var i = 0; i < el.childNodes.length; i++) {
      if (el.childNodes[i].nodeType === 3) t += el.childNodes[i].textContent;
    }
    return t.trim();
  }

  function contrastAudit(opts) {
    opts = opts || {};
    var log = opts.log !== false;
    var root = opts.root || document.body;

    var rows = [];
    var all = root.querySelectorAll('*');

    for (var i = 0; i < all.length; i++) {
      var el = all[i];
      var text = ownText(el);
      if (!text) continue;

      var cs = getComputedStyle(el);
      if (cs.visibility === 'hidden' || cs.display === 'none' || +cs.opacity === 0) continue;
      var box = el.getBoundingClientRect();
      if (!box.width || !box.height) continue;

      var fg = parseColor(cs.color);
      if (!fg) continue;
      var bg = backdrop(el);

      var px = parseFloat(cs.fontSize);
      var weight = parseInt(cs.fontWeight, 10) || 400;
      // WCAG large-scale text: >= 18pt (24px), or >= 14pt bold (~18.66px).
      var large = px >= 24 || (weight >= 700 && px >= 18.66);
      var need = large ? 3 : 4.5;
      var needAAA = large ? 4.5 : 7;
      var r = ratio(fg.rgb, bg.rgb);

      rows.push({
        text: text.length > 30 ? text.slice(0, 30) + '…' : text,
        selector: el.tagName.toLowerCase() + (el.className && typeof el.className === 'string'
          ? '.' + el.className.trim().split(/\s+/).join('.') : ''),
        px: Math.round(px * 10) / 10,
        weight: weight,
        large: large,
        color: cs.color,
        background: 'rgb(' + bg.rgb.join(', ') + ')',
        ratio: Math.round(r * 100) / 100,
        AA: r >= need,
        AAA: r >= needAAA,
        overImage: bg.imaged,
        overlaySource: bg.imagedBy,
        translucentText: fg.alpha < 1
      });
    }

    var failures = rows.filter(function (r) { return !r.AA; });
    var suspect = rows.filter(function (r) { return r.AA && (r.overImage || r.translucentText); });
    var lowest = rows.reduce(function (m, r) { return r.ratio < m ? r.ratio : m; }, Infinity);

    var report = {
      checked: rows.length,
      failures: failures,
      passingButUnverifiable: suspect,
      lowestRatio: rows.length ? lowest : null,
      allRows: rows
    };

    if (log && global.console) {
      console.log('%ccontrast-audit', 'font-weight:bold',
        '— ' + rows.length + ' text elements, ' + failures.length + ' AA failures, lowest ' + lowest + ':1');
      if (failures.length) {
        console.warn('AA FAILURES (' + failures.length + '):');
        console.table(failures.map(function (r) {
          return { text: r.text, selector: r.selector, px: r.px, ratio: r.ratio, needs: r.large ? 3 : 4.5 };
        }));
      } else {
        console.log('%cNo AA failures on the axis this measures.', 'color:#3a3');
      }
      if (suspect.length) {
        // Group by what is painting over them. A full-viewport overlay affects
        // everything, and reporting that once is a fact; reporting it per element
        // is noise that trains you to ignore the warning.
        var bySource = {};
        suspect.forEach(function (r) {
          var k = r.overlaySource || (r.translucentText ? 'translucent text' : 'unknown');
          bySource[k] = (bySource[k] || 0) + 1;
        });
        console.warn('PASSING, BUT THE NUMBER IS NOT THE RENDERED CONTRAST (' + suspect.length + '):');
        Object.keys(bySource).forEach(function (k) {
          console.warn('  ' + bySource[k] + ' element(s) painted over by ' + k);
        });
        console.warn('  Where a light overlay sits on a dark backdrop under light text, ' +
          'true contrast is LOWER than reported. Judge these by eye.');
      }
      console.log('Not checked: non-text contrast (SC 1.4.11), hover/focus states, alpha compositing.');
    }

    return report;
  }

  global.contrastAudit = contrastAudit;
  if (global.document && global.document.readyState !== 'loading') contrastAudit();
})(typeof window !== 'undefined' ? window : this);
