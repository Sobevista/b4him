#!/usr/bin/env python3
"""Generate Beacon Ministries web assets from the source logos.

Sources (originals, kept as masters in this folder):
  - beacon-emblem-master.png  : the circular gold crest (2746x1568) -> marks/favicon
  - beacon-lockup-master.png  : the clean lighthouse lockup (1280x731) -> og:image

Run:  py assets/brand/make_assets.py   (needs Pillow; from the b4him repo root)
Outputs: assets/logo.png, assets/og.png, favicon.ico, apple-touch-icon.png.
Rerun anytime the source art changes -- this is the one place the sizes live.
"""

from pathlib import Path
from PIL import Image, ImageOps

REPO = Path(__file__).resolve().parents[2]
ASSETS = REPO / "assets"
BRAND = ASSETS / "brand"
DL = Path.home() / "Downloads"

# --- ingest + preserve masters -------------------------------------------
emblem = Image.open(DL / "b4him-logo.png.png").convert("RGBA")   # circular crest
lockup = Image.open(DL / "b4him-logo2.png.jpg").convert("RGB")    # clean lockup
BRAND.mkdir(parents=True, exist_ok=True)
emblem.save(BRAND / "beacon-emblem-master.png", optimize=True)
lockup.save(BRAND / "beacon-lockup-master.png", optimize=True)

# --- header mark + favicon: square crop around the circular crest ---------
# The crest sits ~centered; a generous square keeps a thin navy ring so a
# CSS border-radius:50% renders a clean medallion without clipping the circle.
cx, cy, side = 1373, 760, 1500
crest = emblem.crop((cx - side // 2, cy - side // 2, cx + side // 2, cy + side // 2))

crest.resize((256, 256), Image.LANCZOS).save(ASSETS / "logo.png", optimize=True)
crest.resize((180, 180), Image.LANCZOS).convert("RGB").save(
    REPO / "apple-touch-icon.png", optimize=True)
crest.resize((256, 256), Image.LANCZOS).save(
    REPO / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

# transparent gold watermark for the homepage (Option D). The source art is gold
# on navy; keying the navy OUT by luminance lets the crest float as gold linework
# on the PAGE's own navy -- no pasted disc, no halo (the "copy-paste photo" tell).
_wm = crest.convert("RGB").resize((480, 480), Image.LANCZOS)
# posterize trims the metallic-gradient entropy (invisible at watermark opacity)
# so the PNG compresses far smaller.
_wm = ImageOps.posterize(_wm, 5)
_lum = _wm.convert("L")
# alpha ramp: darker than LO -> transparent (the navy ground, ~p75 luma 64);
# brighter than HI -> opaque (gold linework/beam/stars, ~p90 luma 143); soft ramp
# between for clean edges. Cut sits in the luma valley between navy and gold.
LO, HI = 70, 135
_ramp = [0 if i < LO else (255 if i > HI else int((i - LO) / (HI - LO) * 255)) for i in range(256)]
_out = _wm.convert("RGBA")
_out.putalpha(_lum.point(_ramp))
_out.save(ASSETS / "crest-watermark.png", optimize=True)

# --- og:image 1200x630 from the lockup ------------------------------------
# Scale to width 1200 (keeps aspect), then center-crop the height to 630.
scaled = lockup.resize((1200, round(731 * 1200 / 1280)), Image.LANCZOS)
top = (scaled.height - 630) // 2
scaled.crop((0, top, 1200, top + 630)).save(ASSETS / "og.png", optimize=True)

print("assets written:",
      *(str(p.relative_to(REPO)) for p in
        [ASSETS / "logo.png", ASSETS / "og.png",
         REPO / "favicon.ico", REPO / "apple-touch-icon.png"]))
