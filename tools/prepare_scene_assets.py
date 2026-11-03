"""Deterministic local derivatives, no image generation or network calls."""
from __future__ import annotations

import hashlib
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "frontend/public/art"
SOURCE = ROOT / "art-sources/night-room-v1.png"
EXPECTED = "3272ec74b024ffdb179e89ee3f6888e3c6999af65af2ce74824d717a71e87ef7"


def main():
    if hashlib.sha256(SOURCE.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError("The selected room source has changed; review its provenance first.")
    with Image.open(SOURCE) as image:
        image.convert("RGB").save(ART / "night-room.webp", "WEBP", quality=95, method=6)
    for name in ("portrait", "chibi-neutral", "chibi-eat"):
        with Image.open(ART / f"{name}.webp") as image:
            rgba = image.convert("RGBA")
            box = rgba.getchannel("A").getbbox()
            rgba.crop(box).save(ART / f"scene-{name}.webp", "WEBP", lossless=True, method=6)
    print("Prepared full-frame room and alpha-trimmed character sprites without resizing.")


if __name__ == "__main__":
    main()
