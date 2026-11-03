"""Extract the user-confirmed front view locally, without any image API request.

This is a source-specific foreground mask, not blanket white removal: background
is traced from the canvas and reviewed openings, the face-connected foreground
is retained, and enclosed white clothing stays opaque. Only a one-pixel matte
boundary is decontaminated. Original facial/clothing detail is never repainted.
"""
from __future__ import annotations

import hashlib
import io
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path("art-sources/character-v021/reference/appearance-reference-v1.png")
SOURCE_SHA256 = "1debce40cf05ef1b6ee1ec138595036d55667224cb1306e3f4d77de0e2b0b97e"
OUTPUT = Path("output/imagegen/character-v021/reference-extracted")
CROP = (0, 0, 420, 1086)
FACE_SEED = (210, 180)
# Reviewed background openings between hair strands, inside the ahoge and between legs.
# These are not highlights, costume panels, eyes, lace or white socks.
OPENINGS = (
    (172, 21), (196, 814), (45, 488), (332, 240), (376, 310), (68, 366),
    (341, 466), (83, 277), (79, 449), (319, 233), (125, 209), (111, 223),
    (55, 293), (364, 297), (368, 513), (94, 241), (367, 334), (93, 408),
    (81, 387), (69, 316), (339, 404), (50, 331), (74, 395), (122, 120),
)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def pixels(image: Image.Image) -> list:
    return list(getattr(image, "get_flattened_data", image.getdata)())


def connected(allowed: bytearray, width: int, height: int, seeds: list[int]) -> bytearray:
    result = bytearray(width * height)
    queue = deque(seeds)
    while queue:
        index = queue.popleft()
        if result[index] or not allowed[index]:
            continue
        result[index] = 255
        x, y = index % width, index // width
        if x:
            queue.append(index - 1)
        if x < width - 1:
            queue.append(index + 1)
        if y:
            queue.append(index - width)
        if y < height - 1:
            queue.append(index + width)
    return result


def foreground_mask(image: Image.Image) -> Image.Image:
    width, height = image.size
    if (width, height) != (420, 1086):
        raise ValueError("Mask coordinates are specific to the approved reference crop.")
    allowed = bytearray(width * height)
    for index, color in enumerate(pixels(image)):
        light = min(color) >= 232 and max(color) - min(color) <= 21
        # Only the source's floor-shadow band is eligible for the broader gray range.
        floor = index // width >= 987 and min(color) >= 177 and max(color) - min(color) <= 38
        allowed[index] = light or floor
    seeds = list(range(width)) + [(height - 1) * width + x for x in range(width)]
    seeds += [y * width for y in range(height)]
    seeds += [y * width + width - 1 for y in range(height)]
    seeds += [y * width + x for x, y in OPENINGS]
    background = connected(allowed, width, height, seeds)
    foreground = connected(bytearray(not value for value in background), width, height,
                           [FACE_SEED[1] * width + FACE_SEED[0]])
    return Image.frombytes("L", (width, height), bytes(foreground))


def matte_boundary(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Recover antialiasing only at the mask boundary; keep all interior RGB intact."""
    width, height = image.size
    original = pixels(image)
    selected = mask.tobytes()
    core = mask.filter(ImageFilter.MinFilter(3)).tobytes()
    result = image.convert("RGBA")
    rgba = pixels(result)
    offsets = [(dx, dy) for dy in range(-4, 5) for dx in range(-4, 5) if dx or dy]
    offsets.sort(key=lambda point: point[0] ** 2 + point[1] ** 2)
    for index, color in enumerate(original):
        if not selected[index]:
            rgba[index] = (0, 0, 0, 0)
            continue
        if core[index]:
            continue
        x, y = index % width, index // width
        reference = None
        for dx, dy in offsets:
            xx, yy = x + dx, y + dy
            if 0 <= xx < width and 0 <= yy < height and core[yy * width + xx]:
                reference = original[yy * width + xx]
                break
        if reference is None:
            continue
        direction = [252 - channel for channel in reference]
        denominator = sum(channel ** 2 for channel in direction)
        if denominator < 200:
            continue
        amount = max(0, min(1, sum((252 - channel) * delta
                                  for channel, delta in zip(color, direction, strict=True))
                            / denominator))
        if amount < .035:
            rgba[index] = (0, 0, 0, 0)
        elif amount < .985:
            corrected = tuple(max(0, min(255, round((channel - 252 * (1 - amount)) / amount)))
                              for channel in color)
            rgba[index] = corrected + (round(amount * 255),)
    result.putdata(rgba)
    return result


def extract(content: bytes) -> tuple[Image.Image, Image.Image, dict]:
    if digest(content) != SOURCE_SHA256:
        raise ValueError("Reference changed; review the mask before processing another image.")
    with Image.open(io.BytesIO(content)) as source:
        if source.size != (1448, 1086) or source.format != "PNG":
            raise ValueError("Unexpected reference format or dimensions.")
        crop = source.convert("RGB").crop(CROP)
    mask = foreground_mask(crop)
    portrait = matte_boundary(crop, mask)
    box = portrait.getchannel("A").getbbox()
    if box is None or box[0] < 1 or box[2] >= crop.width or box[3] >= crop.height:
        raise ValueError("Unexpected extraction boundary; do not publish.")
    metadata = {
        "source_crop": list(CROP), "source_alpha_bounds": list(box),
        "width": box[2] - box[0], "height": box[3] - box[1],
        "network_requests": 0, "face_and_costume_repainted": False,
        "transform": "Connected-background mask, reviewed holes, floor-shadow removal, "
                     "one-pixel matte decontamination, alpha-bounds crop; no resizing.",
    }
    return portrait.crop(box), mask, metadata


def checked_path(root: Path, relative: Path) -> Path:
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("Output must stay inside the workspace.")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Linked output path is not allowed.")
    return path


def prepare(root: Path = ROOT) -> dict:
    source = checked_path(root, SOURCE)
    content = source.read_bytes()
    portrait, mask, details = extract(content)
    files = {}
    for filename, image, fmt, options in (
        ("portrait-reference-v1.png", portrait, "PNG", {}),
        ("portrait-reference-v1.webp", portrait, "WEBP", {"lossless": True, "method": 6}),
        ("source-mask.png", mask, "PNG", {}),
    ):
        buffer = io.BytesIO()
        image.save(buffer, fmt, **options)
        files[filename] = buffer.getvalue()
    # The uploaded sheet already supplies the intended full design; never regenerate it silently.
    files["reference-sheet-original.png"] = content
    manifest = {
        "schema_version": 1, "workflow": "local-reference-extraction", "source": SOURCE.as_posix(),
        "source_sha256": SOURCE_SHA256, "requested_model": None, "generation_quality": None,
        "generation_prompt": None, "status": "prepared-not-integrated",
        "source_role": "User-confirmed left/front character; appearance kept, background removed.",
        "license": "LicenseRef-User-Provided-Unverified",
        "rights_note": "Reference origin and redistribution rights unverified; personal preview only.",
        "outputs": {name: digest(data) for name, data in files.items()}, **details,
    }
    files["extraction.provenance.json"] = (
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    # Refuse conflicting outputs before creating any file. Source bytes are never changed.
    for name, data in files.items():
        path = checked_path(root, OUTPUT / name)
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Existing extraction differs; use a new reviewed version, not overwrite.")
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
