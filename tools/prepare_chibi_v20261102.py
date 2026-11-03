"""Source-specific extraction of the user-selected chibi front; no AI or network.

Only the connected canvas and inspected hair openings are removed. The opaque
face/costume pixels retain the JPEG's decoded RGB. Preparation never installs it.
"""
from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from tools.prepare_reference_chibi import connected, digest, image_bytes, matte_boundary, pixels

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("art-sources/chibi-v20261102/reference.jpg")
SOURCE_SHA256 = "12c5fd201fb65161b30d803a45b5fd29ff4ae6e02a3b1394d1a1c8fd86a75f5b"
OUTPUT = Path("output/chibi-v20261102")
CROP = (50, 60, 450, 590)
# Full-sheet coordinates: ahoge, three left hair loops, two right hair loops.
OPENINGS = ((194, 109), (124, 358), (119, 392), (109, 415), (407, 345), (413, 403))


def foreground_mask(image: Image.Image) -> Image.Image:
    if image.mode != "RGB" or image.size != (400, 530):
        raise ValueError("Mask requires the reviewed RGB crop.")
    width, height = image.size
    allowed = bytearray(min(rgb) >= 232 and max(rgb) - min(rgb) <= 30 for rgb in pixels(image))
    seeds = list(range(width)) + [(height - 1) * width + x for x in range(width)]
    seeds += [y * width for y in range(height)]
    seeds += [y * width + width - 1 for y in range(height)]
    seeds += [(y - CROP[1]) * width + x - CROP[0] for x, y in OPENINGS]
    if any(not allowed[(y - CROP[1]) * width + x - CROP[0]] for x, y in OPENINGS):
        raise ValueError("A reviewed opening is not background.")
    background = connected(allowed, width, height, seeds)
    foreground = connected(bytearray(not v for v in background), width, height,
                           [(320 - CROP[1]) * width + 245 - CROP[0]])
    return Image.frombytes("L", image.size, bytes(foreground))


def extract(content: bytes) -> tuple[Image.Image, Image.Image, dict]:
    if digest(content) != SOURCE_SHA256:
        raise ValueError("Reference changed; review the extraction mask first.")
    with Image.open(io.BytesIO(content)) as source:
        if source.format != "JPEG" or source.size != (1216, 668) or source.mode != "RGB":
            raise ValueError("Unexpected reference format or dimensions.")
        crop = source.crop(CROP)
    mask = foreground_mask(crop)
    rgba = matte_boundary(crop, mask)
    bounds = rgba.getchannel("A").getbbox()
    if bounds != (24, 26, 386, 508):
        raise ValueError("Extraction bounds differ from the reviewed front view.")
    result = rgba.crop(bounds)
    alpha = result.getchannel("A").tobytes()
    metadata = {
        "source": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
        "source_crop": list(CROP), "crop_alpha_bounds": list(bounds),
        "source_alpha_bounds": [bounds[0] + CROP[0], bounds[1] + CROP[1],
                                bounds[2] + CROP[0], bounds[3] + CROP[1]],
        "width": result.width, "height": result.height, "foot_anchor": [.5, 1.0],
        "reviewed_background_openings": list(OPENINGS),
        "opaque_pixels": sum(v == 255 for v in alpha),
        "partial_alpha_pixels": sum(0 < v < 255 for v in alpha),
        "resized": False, "redrawn": False, "network_requests": 0,
        "rights": "User-provided; author and redistribution rights unverified; personal preview only.",
        "method": "Left/front view; connected canvas and reviewed hair openings; one-pixel "
                  "boundary unmatting; native-size alpha crop. White costume preserved.",
        "eat_fallback": "Same neutral front, not a newly drawn eating pose.",
    }
    return result, mask, metadata


def prepare(root: Path = ROOT) -> dict:
    chibi, mask, metadata = extract((root / SOURCE).read_bytes())
    files = {
        "chibi-front.png": image_bytes(chibi),
        "chibi-front.webp": image_bytes(chibi, "WEBP", lossless=True, method=6),
        "source-mask.png": image_bytes(mask),
    }
    for name, color in (("preview-dark.png", (24, 32, 51, 255)),
                        ("preview-light.png", (240, 232, 219, 255))):
        preview = Image.new("RGBA", (chibi.width + 48, chibi.height + 48), color)
        preview.alpha_composite(chibi, (24, 24))
        files[name] = image_bytes(preview.convert("RGB"))
    metadata["outputs"] = {name: digest(data) for name, data in files.items()}
    files["extraction.provenance.json"] = (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode()
    folder = root / OUTPUT
    for name, data in files.items():
        target = folder / name
        if target.exists() and target.read_bytes() != data:
            raise ValueError(f"Existing extraction differs: {target}")
    folder.mkdir(parents=True, exist_ok=True)
    for name, data in files.items():
        (folder / name).write_bytes(data)
    return metadata


if __name__ == "__main__":
    print(json.dumps(prepare(), ensure_ascii=False, indent=2))
