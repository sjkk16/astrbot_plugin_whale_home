"""Extract only the front adult portrait from the user's deepseek.png, locally.

The mask is bound to a reviewed source digest. Never remove all white pixels:
white costume, socks, and highlights remain opaque. Q-version assets are not read
or written. Preparing is separate from installing the new default portrait.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.prepare_reference_portrait import (  # noqa: E402
    checked_path,
    connected,
    digest,
    matte_boundary,
    pixels,
)

SOURCE = Path("art-sources/character-v021/reference/deepseek-v1.png")
SOURCE_SHA256 = "f1dfef333d337cf949aa295b56b7ce985c4628ac9bc7ad5ede95575db6bf9e14"
OUTPUT = Path("output/imagegen/character-v021/deepseek-front-extracted")
CROP = (0, 0, 544, 1024)
FACE_SEED = (291, 158)
# Reviewed holes behind the ear/hair and between hair loops and sleeves.
# The ahoge and leg gap already connect to the outer canvas, so need no seed.
OPENINGS = (
    (373, 182), (204, 211), (377, 207), (394, 217), (190, 221), (166, 244),
    (431, 251), (146, 260), (403, 271), (410, 283), (173, 278), (462, 285),
    (122, 303), (164, 293), (446, 300), (467, 328), (486, 342), (80, 345),
    (462, 353), (109, 365), (97, 407), (462, 415), (424, 458), (165, 461),
)


def foreground_mask(image: Image.Image) -> Image.Image:
    if image.size != (544, 1024) or image.mode != "RGB":
        raise ValueError("Mask coordinates require the reviewed RGB crop.")
    width, height = image.size
    allowed = bytearray(min(c) >= 232 and max(c) - min(c) <= 21 for c in pixels(image))
    seeds = list(range(width)) + [(height - 1) * width + x for x in range(width)]
    seeds += [y * width for y in range(height)]
    seeds += [y * width + width - 1 for y in range(height)]
    seeds += [y * width + x for x, y in OPENINGS]
    background = connected(allowed, width, height, seeds)
    foreground = connected(bytearray(not value for value in background), width, height,
                           [FACE_SEED[1] * width + FACE_SEED[0]])
    return Image.frombytes("L", image.size, bytes(foreground))


def extract(content: bytes) -> tuple[Image.Image, Image.Image, dict]:
    if digest(content) != SOURCE_SHA256:
        raise ValueError("Reference changed; review the mask before processing another image.")
    with Image.open(io.BytesIO(content)) as source:
        if source.size != (1536, 1024) or source.format != "PNG":
            raise ValueError("Unexpected reference format or dimensions.")
        crop = source.convert("RGB").crop(CROP)
    mask = foreground_mask(crop)
    portrait = matte_boundary(crop, mask)
    box = portrait.getchannel("A").getbbox()
    if box is None or box[0] < 1 or box[1] < 1 or box[2] >= crop.width or box[3] >= crop.height:
        raise ValueError("Unexpected extraction boundary; do not install.")
    details = {
        "source_crop": list(CROP), "source_alpha_bounds": list(box),
        "width": box[2] - box[0], "height": box[3] - box[1],
        "network_requests": 0, "face_and_costume_repainted": False,
        "transform": "Front view only; connected-canvas and 24 reviewed hair-gap removals; "
                     "one-pixel matte decontamination; alpha-bounds crop; no resize or redraw.",
    }
    return portrait.crop(box), mask, details


def prepare(root: Path = ROOT) -> dict:
    content = checked_path(root, SOURCE).read_bytes()
    portrait, mask, details = extract(content)
    files = {}
    for name, image, fmt, options in (
        ("portrait-deepseek-v1.png", portrait, "PNG", {}),
        ("portrait-deepseek-v1.webp", portrait, "WEBP", {"lossless": True, "method": 6}),
        ("source-mask.png", mask, "PNG", {}),
    ):
        buffer = io.BytesIO()
        image.save(buffer, fmt, **options)
        files[name] = buffer.getvalue()
    for label, color in (("dark", "#172438"), ("light", "#f4f0eb")):
        preview = Image.new("RGBA", (portrait.width + 48, portrait.height + 48), color)
        preview.alpha_composite(portrait, (24, 24))
        buffer = io.BytesIO()
        preview.convert("RGB").save(buffer, "PNG")
        files[f"preview-{label}.png"] = buffer.getvalue()
    manifest = {
        "schema_version": 1, "workflow": "local-reference-extraction",
        "source": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
        "source_role": "User-provided deepseek.png; left/front adult character only.",
        "license": "LicenseRef-User-Provided-Unverified",
        "rights_note": "Author and redistribution rights unverified; personal preview only. "
                       "Not covered by the code MIT or the previous portrait's CC license.",
        "default_assets_changed_by_this_tool": False, "chibi_changed": False,
        "outputs": {name: digest(data) for name, data in files.items()}, **details,
    }
    files["extraction.provenance.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    for name, data in files.items():
        path = checked_path(root, OUTPUT / name)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Existing extraction differs; use a new reviewed version.")
    for name, data in files.items():
        path = checked_path(root, OUTPUT / name)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
    return manifest


if __name__ == "__main__":
    result = prepare()
    print(json.dumps({"output": str(ROOT / OUTPUT), "size": [result["width"], result["height"]],
                      "network_requests": 0, "default_assets_changed": False}, indent=2))
