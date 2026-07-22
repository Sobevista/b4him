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
from PIL import Image

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

# large crest for the homepage watermark (Option D ambient treatment).
# JPEG, not PNG: it sits on navy and is CSS-clipped to a circle, so it needs no
# transparency -- and JPEG is ~6x lighter than PNG for this textured art.
crest.convert("RGB").resize((600, 600), Image.LANCZOS).save(
    ASSETS / "crest-lg.jpg", quality=82, optimize=True)

# --- og:image 1200x630 from the lockup ------------------------------------
# Scale to width 1200 (keeps aspect), then center-crop the height to 630.
scaled = lockup.resize((1200, round(731 * 1200 / 1280)), Image.LANCZOS)
top = (scaled.height - 630) // 2
scaled.crop((0, top, 1200, top + 630)).save(ASSETS / "og.png", optimize=True)

print("assets written:",
      *(str(p.relative_to(REPO)) for p in
        [ASSETS / "logo.png", ASSETS / "og.png",
         REPO / "favicon.ico", REPO / "apple-touch-icon.png"]))
