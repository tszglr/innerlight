"""InnerLight scene generator.

Creates new calm background variants from the founder's own photos in
scenes/ — the same gardens and skies he photographed, gently re-graded to
read as a different time of day (dawn, golden hour, dusk, moonlight, or a
soft dreamy version of the same moment).

Nothing is invented: every output pixel comes from the founder's original
photograph. The script only adjusts light and color, the way a careful
photo editor would.

Usage:
    python core/scene_generator.py            # generate the curated batch
    python core/scene_generator.py --list     # show the planned batch
    python core/scene_generator.py photo_1_rosemary.jpg golden
                                              # one photo, one treatment

Outputs land in scenes/ as gen_<basename>_<treatment>.jpg plus a
scenes/generated_manifest.json describing every generated file.
Originals are never modified.
"""

from __future__ import annotations

import json
import os
import sys

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

SCENES_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scenes")
MAX_LONG_EDGE = 2200
JPEG_QUALITY = 85


# ---------------------------------------------------------------------------
# Low-level helpers (all operate on / return PIL RGB images)
# ---------------------------------------------------------------------------

def load_photo(path: str) -> Image.Image:
    """Open a source photo, respect EXIF rotation, cap the long edge."""
    img = Image.open(path)
    img = ImageOps.exif_transpose(img)
    img = img.convert("RGB")
    long_edge = max(img.size)
    if long_edge > MAX_LONG_EDGE:
        scale = MAX_LONG_EDGE / long_edge
        new_size = (round(img.width * scale), round(img.height * scale))
        img = img.resize(new_size, Image.LANCZOS)
    return img


def channel_balance(img: Image.Image, r: float = 1.0, g: float = 1.0, b: float = 1.0) -> Image.Image:
    """Gentle white-balance shift by scaling channels (clipped)."""
    arr = np.asarray(img).astype(np.float32)
    arr[..., 0] *= r
    arr[..., 1] *= g
    arr[..., 2] *= b
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def tone_curve(img: Image.Image, black_lift: float = 0.0, gamma: float = 1.0,
               highlight_rolloff: float = 0.0) -> Image.Image:
    """Apply one smooth luminosity curve to all channels.

    black_lift: 0..~0.10 raises the black point softly (misty, filmic feel).
    gamma:      <1 brightens mids, >1 darkens mids.
    highlight_rolloff: 0..~0.15 pulls the very top down to avoid clipping.
    """
    x = np.linspace(0.0, 1.0, 256)
    y = x ** gamma
    if black_lift > 0:
        y = black_lift + (1.0 - black_lift) * y
    if highlight_rolloff > 0:
        y = y * (1.0 - highlight_rolloff * y ** 3)
    lut = np.clip(y * 255.0, 0, 255).astype(np.uint8)
    return img.point(list(lut) * 3)


def warm_split_tone(img: Image.Image, highlight_warmth: float = 0.0,
                    shadow_warmth: float = 0.0) -> Image.Image:
    """Add warmth weighted by luminosity: cream highlights, amber shadows.

    Positive warmth nudges red up and blue down; kept small so skin of the
    photo stays believable. Values are fractions like 0.04.
    """
    arr = np.asarray(img).astype(np.float32) / 255.0
    lum = arr[..., 0] * 0.299 + arr[..., 1] * 0.587 + arr[..., 2] * 0.114
    hi = lum ** 2  # weight toward highlights
    lo = (1.0 - lum) ** 2  # weight toward shadows
    warm = highlight_warmth * hi + shadow_warmth * lo
    arr[..., 0] = arr[..., 0] * (1.0 + warm)
    arr[..., 2] = arr[..., 2] * (1.0 - warm * 0.9)
    # tiny green support so the warmth reads amber/cream, never magenta
    arr[..., 1] = arr[..., 1] * (1.0 + warm * 0.35)
    return Image.fromarray(np.clip(arr * 255.0, 0, 255).astype(np.uint8))


def vignette(img: Image.Image, strength: float = 0.2, softness: float = 2.4) -> Image.Image:
    """Darken corners very gently. strength 0..1 is max corner darkening."""
    w, h = img.size
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    # normalized radial distance, 1.0 at the farthest corner
    r = np.sqrt(((xx - cx) / cx) ** 2 + ((yy - cy) / cy) ** 2) / np.sqrt(2.0)
    mask = 1.0 - strength * np.clip(r, 0, 1) ** softness
    arr = np.asarray(img).astype(np.float32) * mask[..., None]
    return Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))


def orton_glow(img: Image.Image, radius_frac: float = 0.012, opacity: float = 0.22,
               glow_brightness: float = 1.03) -> Image.Image:
    """Very subtle Orton effect: a soft luminous blur breathed over the photo."""
    radius = max(2, round(max(img.size) * radius_frac))
    blurred = img.filter(ImageFilter.GaussianBlur(radius))
    blurred = ImageEnhance.Brightness(blurred).enhance(glow_brightness)
    # screen blend brightens where the glow is bright, then keep only a whisper
    a = np.asarray(img).astype(np.float32) / 255.0
    b = np.asarray(blurred).astype(np.float32) / 255.0
    screen = 1.0 - (1.0 - a) * (1.0 - b)
    out = a * (1.0 - opacity) + screen * opacity
    return Image.fromarray(np.clip(out * 255.0, 0, 255).astype(np.uint8))


def haze(img: Image.Image, amount: float = 0.10, tint=(255, 246, 232)) -> Image.Image:
    """Lay a faint cream mist over the image (low-contrast atmospheric lift)."""
    overlay = Image.new("RGB", img.size, tint)
    return Image.blend(img, overlay, amount)


def saturation(img: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Color(img).enhance(factor)


def contrast(img: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Contrast(img).enhance(factor)


def brightness(img: Image.Image, factor: float) -> Image.Image:
    return ImageEnhance.Brightness(img).enhance(factor)


# ---------------------------------------------------------------------------
# Treatments — each takes and returns a PIL RGB image
# ---------------------------------------------------------------------------

def treat_golden(img: Image.Image) -> Image.Image:
    """Golden hour: gentle warm tone, softly lifted shadows, quiet glow."""
    out = tone_curve(img, black_lift=0.03, gamma=0.96, highlight_rolloff=0.05)
    out = channel_balance(out, r=1.045, g=1.005, b=0.925)
    out = warm_split_tone(out, highlight_warmth=0.05, shadow_warmth=0.02)
    out = saturation(out, 1.04)
    out = contrast(out, 1.02)
    return out


def treat_dawn(img: Image.Image) -> Image.Image:
    """Dawn: soft pastel light, faint cream mist, lifted and quiet."""
    out = tone_curve(img, black_lift=0.06, gamma=0.92, highlight_rolloff=0.06)
    out = saturation(out, 0.86)
    out = contrast(out, 0.93)
    out = channel_balance(out, r=1.01, g=1.0, b=1.0)
    out = haze(out, amount=0.07)
    out = brightness(out, 1.03)
    return out


def treat_dusk(img: Image.Image) -> Image.Image:
    """Dusk: deeper amber warmth, gently darkened, soft vignette."""
    out = tone_curve(img, black_lift=0.025, gamma=1.06, highlight_rolloff=0.04)
    out = channel_balance(out, r=1.06, g=0.995, b=0.905)
    out = warm_split_tone(out, highlight_warmth=0.06, shadow_warmth=0.03)
    out = brightness(out, 0.92)
    out = saturation(out, 1.03)
    out = vignette(out, strength=0.22, softness=2.6)
    return out


def treat_dream(img: Image.Image) -> Image.Image:
    """Soft-dream: subtle Orton glow, a breath of warmth, nothing loud."""
    out = orton_glow(img, radius_frac=0.012, opacity=0.20, glow_brightness=1.03)
    out = warm_split_tone(out, highlight_warmth=0.025, shadow_warmth=0.01)
    out = tone_curve(out, black_lift=0.02, gamma=0.98, highlight_rolloff=0.04)
    out = saturation(out, 0.97)
    return out


def treat_moonlight(img: Image.Image) -> Image.Image:
    """Moonlight: hushed silver-blue night. Only for photos that read as night."""
    out = saturation(img, 0.55)
    out = tone_curve(out, black_lift=0.0, gamma=1.18, highlight_rolloff=0.03)
    out = channel_balance(out, r=0.955, g=0.985, b=1.035)
    out = brightness(out, 0.86)
    out = contrast(out, 1.03)
    out = vignette(out, strength=0.16, softness=2.8)
    return out


TREATMENTS = {
    "golden": treat_golden,
    "dawn": treat_dawn,
    "dusk": treat_dusk,
    "dream": treat_dream,
    "moonlight": treat_moonlight,
}


# ---------------------------------------------------------------------------
# Curated batch: which of the founder's photos suit which light
# ---------------------------------------------------------------------------
# (source filename, treatment, human label)
BATCH = [
    ("photo_1_rosemary.jpg", "golden", "Rosemary blossoms in golden-hour light"),
    ("photo_1_rosemary.jpg", "dawn", "Rosemary blossoms at first light"),
    ("photo_1_rosemary.jpg", "dream", "Rosemary blossoms, soft as a memory"),
    ("photo_5_sunflower.jpg", "golden", "Sunflower in warm evening sun"),
    ("photo_5_sunflower.jpg", "dusk", "Sunflower as the day settles"),
    ("photo_5_sunflower.jpg", "dream", "Sunflower in a gentle haze"),
    ("photo_6_golden_horizon.jpg", "dawn", "The horizon at daybreak"),
    ("photo_6_golden_horizon.jpg", "dusk", "The horizon as evening deepens"),
    ("photo_6_golden_horizon.jpg", "dream", "Golden horizon, softly glowing"),
    ("photo_7_moon_leaves.jpg", "moonlight", "Moon through the leaves, deep night"),
    ("photo_7_moon_leaves.jpg", "dream", "Moon through the leaves, dreaming"),
    ("photo_4_moon_day.jpg", "moonlight", "The moon as night settles in"),
    ("photo_4_moon_day.jpg", "dawn", "Morning moon in a pale sky"),
    ("photo_9_wave.jpg", "dawn", "The sea at first light"),
    ("photo_9_wave.jpg", "dream", "The sea, softly dreaming"),
    ("photo_10_pepper.jpg", "golden", "Pepper plant in golden-hour light"),
    ("photo_10_pepper.jpg", "dream", "Pepper plant, garden daydream"),
    ("photo_12_sunflowers.jpg", "golden", "Sunflowers in warm evening sun"),
    ("photo_12_sunflowers.jpg", "dusk", "Sunflowers at dusk"),
]


def output_name(source: str, treatment: str) -> str:
    base = os.path.splitext(source)[0]
    return f"gen_{base}_{treatment}.jpg"


def generate_one(source: str, treatment: str) -> str:
    src_path = os.path.join(SCENES_DIR, source)
    if not os.path.exists(src_path):
        raise FileNotFoundError(src_path)
    if treatment not in TREATMENTS:
        raise KeyError(f"Unknown treatment '{treatment}'. Choose from: {', '.join(TREATMENTS)}")
    img = load_photo(src_path)
    out = TREATMENTS[treatment](img)
    out_path = os.path.join(SCENES_DIR, output_name(source, treatment))
    out.save(out_path, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return out_path


def generate_batch() -> None:
    manifest = []
    for source, treatment, label in BATCH:
        out_path = generate_one(source, treatment)
        print(f"  {os.path.basename(out_path)}  <-  {source}  [{treatment}]")
        manifest.append({
            "file": os.path.basename(out_path),
            "source": source,
            "treatment": treatment,
            "label": label,
        })
    manifest_path = os.path.join(SCENES_DIR, "generated_manifest.json")
    with open(manifest_path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"\nWrote {len(manifest)} scenes and {manifest_path}")


def main(argv) -> int:
    if len(argv) == 1:
        generate_batch()
        return 0
    if argv[1] == "--list":
        for source, treatment, label in BATCH:
            print(f"{output_name(source, treatment):55s} {label}")
        return 0
    if len(argv) == 3:
        path = generate_one(argv[1], argv[2])
        print(path)
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
