"""Extract the approved Q-version front view locally; never generate or redraw it.

This source-specific mask is independent of the mature portrait mask. Only the
canvas, reviewed openings, and floor-shadow band are background candidates.
White clothing/highlights and every opaque interior pixel retain their RGB.
"""
from __future__ import annotations

import hashlib
import io
import json
import sys
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from whale_home.scene import SCENE  # noqa: E402

SOURCE = Path("art-sources/character-v021/reference/chibi-character-sheet-v1.png")
SOURCE_SHA256 = "539548dbdf78a6488b9baca3af07521fe422c62bd8dee6e5664a1880754325b6"
OUTPUT = Path("output/imagegen/character-v021/chibi-reference-extracted")
BACKGROUND = Path("frontend/public/art/night-room.webp")
CROP = (0, 0, 548, 625)
FACE_SEED = (250, 260)
CHIBI_SCALE = 0.44
FLOOR_START = 585
# Source coordinates reviewed against the original sheet, NOT costume highlights.
# Ahoge, left/right hair loops, hair-to-tail gap, lower curls, and the leg opening.
OPENINGS = (
    (203, 45), (449, 321), (457, 487), (78, 326), (485, 402), (25, 401),
    (132, 541), (95, 521), (413, 503), (107, 531), (277, 556),
)


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def pixels(image: Image.Image) -> list:
    return list(getattr(image, "get_flattened_data", image.getdata)())


def encoded(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def connected(allowed: bytearray, width: int, height: int, seeds: list[int]) -> bytearray:
    selected = bytearray(width * height)
    queue = deque(seeds)
    while queue:
        index = queue.popleft()
        if selected[index] or not allowed[index]:
            continue
        selected[index] = 255
        x, y = index % width, index // width
        if x:
            queue.append(index - 1)
        if x < width - 1:
            queue.append(index + 1)
        if y:
            queue.append(index - width)
        if y < height - 1:
            queue.append(index + width)
    return selected


def foreground_mask(image: Image.Image) -> Image.Image:
    if image.mode != "RGB" or image.size != (548, 625):
        raise ValueError("Mask coordinates require the approved RGB Q-version crop.")
    width, height = image.size
    allowed = bytearray(width * height)
    for index, color in enumerate(pixels(image)):
        light = min(color) >= 232 and max(color) - min(color) <= 21
        floor = (index // width >= FLOOR_START
                 and min(color) >= 177 and max(color) - min(color) <= 38)
        allowed[index] = light or floor
    seeds = list(range(width)) + [(height - 1) * width + x for x in range(width)]
    seeds += [y * width for y in range(height)]
    seeds += [y * width + width - 1 for y in range(height)]
    seeds += [y * width + x for x, y in OPENINGS]
    background = connected(allowed, width, height, seeds)
    foreground = connected(bytearray(not value for value in background), width, height,
                           [FACE_SEED[1] * width + FACE_SEED[0]])
    return Image.frombytes("L", image.size, bytes(foreground))


def matte_boundary(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Unmatte only the one-pixel boundary; do not repaint or recolor the interior."""
    width, height = image.size
    original = pixels(image)
    selected = mask.tobytes()
    core = mask.filter(ImageFilter.MinFilter(3)).tobytes()
    result = image.convert("RGBA")
    rgba = pixels(result)
    # A longer inward search preserves thin, antialiased hair tips without white dots.
    offsets = [(dx, dy) for dy in range(-16, 17) for dx in range(-16, 17) if dx or dy]
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
        raise ValueError("Reference changed; review the Q-version mask before processing.")
    with Image.open(io.BytesIO(content)) as source:
        if source.size != (1448, 1086) or source.format != "PNG" or source.mode != "RGB":
            raise ValueError("Unexpected Q-version reference format or dimensions.")
        crop = source.crop(CROP)
    mask = foreground_mask(crop)
    rgba = matte_boundary(crop, mask)
    box = rgba.getchannel("A").getbbox()
    if box != (11, 12, 537, 612):
        raise ValueError("Extraction bounds differ from the reviewed front view; do not publish.")
    alpha = rgba.getchannel("A").tobytes()
    metadata = {
        "source_crop": list(CROP), "source_alpha_bounds": list(box),
        "width": box[2] - box[0], "height": box[3] - box[1],
        "reviewed_background_openings": [list(point) for point in OPENINGS],
        "floor_shadow_band_start": FLOOR_START,
        "opaque_pixels": sum(value == 255 for value in alpha),
        "partial_alpha_pixels": sum(0 < value < 255 for value in alpha),
        "resized": False, "face_and_costume_repainted": False, "network_requests": 0,
        "transform": "Connected background and reviewed openings; source floor-shadow removal; "
                     "one-pixel boundary unmatting; alpha-bounds crop. No resizing or redraw.",
    }
    return rgba.crop(box), mask, metadata


def image_bytes(image: Image.Image, fmt: str = "PNG", **options) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, fmt, **options)
    return buffer.getvalue()


def inspection_preview(chibi: Image.Image, dark: bool) -> Image.Image:
    background = (20, 29, 49) if dark else (240, 232, 214)
    text = (221, 231, 249) if dark else (45, 58, 82)
    canvas = Image.new("RGBA", (chibi.width + 96, chibi.height + 120), background + (255,))
    canvas.alpha_composite(chibi, (48, 72))
    draw = ImageDraw.Draw(canvas)
    draw.text((32, 20), "Q VERSION / FRONT", fill=text, font=ImageFont.load_default(size=21))
    draw.text((32, 47), f"Native {chibi.width} x {chibi.height} | original appearance",
              fill=text, font=ImageFont.load_default(size=14))
    draw.text((32, canvas.height - 28), "LOCAL EXTRACTION / NO REDRAW / NOT INTEGRATED",
              fill=text, font=ImageFont.load_default(size=12))
    return canvas.convert("RGB")


def room_preview(chibi: Image.Image, background: bytes) -> tuple[Image.Image, dict]:
    with Image.open(io.BytesIO(background)) as source:
        if source.size != (SCENE["width"], SCENE["height"]):
            raise ValueError("Room background does not match the current scene geometry.")
        room = source.convert("RGBA")
    anchor = SCENE["locations"]["window"]
    height = round(room.height * anchor["height"] * CHIBI_SCALE)
    width = round(height * chibi.width / chibi.height)
    left = round(room.width * anchor["x"] - width / 2)
    bottom = round(room.height * anchor["y"])
    top = bottom - height
    sprite = chibi.resize((width, height), Image.Resampling.LANCZOS)
    # Preview-only approximate night lighting. Exported character pixels are untouched.
    rgb = ImageEnhance.Brightness(sprite.convert("RGB")).enhance(.86)
    lit = ImageEnhance.Color(rgb).enhance(.84).convert("RGBA")
    lit.putalpha(sprite.getchannel("A"))
    shadow = Image.new("RGBA", room.size)
    ImageDraw.Draw(shadow).ellipse(
        (left + width * .18, bottom - height * .042,
         left + width * .83, bottom + height * .008), fill=(6, 13, 35, 166))
    room.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3)))
    room.alpha_composite(lit, (left, top))
    # Label outside the room, preserving its full aspect ratio and furniture framing.
    canvas = Image.new("RGB", (room.width, room.height + 58), (15, 22, 38))
    canvas.paste(room.convert("RGB"), (0, 0))
    draw = ImageDraw.Draw(canvas)
    draw.text((24, room.height + 10),
              "STATIC COMPOSITE | WINDOW POSITION | NOT AN APP SCREENSHOT",
              fill=(235, 239, 250), font=ImageFont.load_default(size=18))
    draw.text((24, room.height + 34),
              "Current Q scale and foot baseline; approximate night tint; defaults unchanged.",
              fill=(169, 187, 215), font=ImageFont.load_default(size=13))
    return canvas, {
        "kind": "static-composite-not-app-screenshot", "scene_id": SCENE["id"],
        "location": "window", "anchor": dict(anchor), "chibi_scale": CHIBI_SCALE,
        "room_size": list(room.size), "sprite_size": [width, height],
        "sprite_top_left": [left, top], "foot_baseline_y": bottom,
        "background": BACKGROUND.as_posix(), "background_sha256": digest(background),
        "sprite_lighting": "Preview-only brightness 0.86 and Pillow color saturation 0.84.",
        "contact_shadow": "New scene-only contact shadow, not the removed source shadow.",
    }


def checked_path(root: Path, relative: Path) -> Path:
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root):
        raise ValueError("Output must stay inside the workspace.")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise ValueError("Linked source or output path is not allowed.")
    return path


def prepare(root: Path = ROOT) -> dict:
    content = checked_path(root, SOURCE).read_bytes()
    chibi, mask, details = extract(content)
    background = checked_path(root, BACKGROUND).read_bytes()
    room, room_details = room_preview(chibi, background)
    files = {
        "chibi-reference-v1.png": image_bytes(chibi),
        "chibi-reference-v1.webp": image_bytes(chibi, "WEBP", lossless=True, method=6),
        "source-mask.png": image_bytes(mask),
        "reference-sheet-original.png": content,
        "chibi-preview-light.png": image_bytes(inspection_preview(chibi, dark=False)),
        "chibi-preview-dark.png": image_bytes(inspection_preview(chibi, dark=True)),
        "room-static-preview.png": image_bytes(room),
    }
    source_record = {
        "schema_version": 1, "source_filename": "dafeiyu-chibi-character-sheet.png",
        "source_sha256": SOURCE_SHA256, "archive": SOURCE.as_posix(),
        "source_role": "User-provided character sheet; only upper-left/front view extracted.",
        "source_unchanged": True, "license": "LicenseRef-User-Provided-Unverified",
        "rights_note": "用户提供图片不等于公开再分发授权，仅供个人预览。",
    }
    readme = f"""# Q 版正面透明素材（已准备，尚未接入）

仅提取用户设定图左上角正面。无绘图 API、无重绘、无放大；PNG/WebP 为原生 {chibi.width}×{chibi.height}。
深浅底预览保持素材原生尺寸。房间图是窗边静态合成，不是实际应用截图；
仅预览按现有 Q 版 0.44 比例缩小，使用近似夜景色调与新的接地阴影。
素材本体不含原图地面投影。现有默认角色、成熟版、存档、版本号和安装包未修改。

- `chibi-reference-v1.png` / `.webp`：透明成品，WebP 无损。
- `chibi-preview-light.png` / `chibi-preview-dark.png`：检查白色衣物和轮廓。
- `room-static-preview.png`：有明确标注的静态房间合成。
- `reference-sheet-original.png`：完整原图，包含未单独处理的侧面、背面与细节。
- `source-mask.png`：对应原图左上角 548×625 区域的二值前景遮罩。
- `extraction.provenance.json`：来源摘要、遮罩坐标、处理方式、预览几何与产物摘要。

原图 SHA-256：`{SOURCE_SHA256}`。不对公开再分发权利作承诺，保持个人预览范围。
"""
    files["README.md"] = readme.encode()
    manifest = {
        "schema_version": 1, "workflow": "local-chibi-reference-extraction",
        "source": SOURCE.as_posix(), "source_sha256": SOURCE_SHA256,
        "source_record": SOURCE.with_suffix(".provenance.json").as_posix(),
        "status": "prepared-not-integrated", "source_role": source_record["source_role"],
        "requested_model": None, "generation_quality": None, "generation_prompt": None,
        "license": source_record["license"], "rights_note": source_record["rights_note"],
        "default_assets_changed": False, "room_preview": room_details,
        "outputs": {name: digest(data) for name, data in files.items()}, **details,
    }
    files["extraction.provenance.json"] = encoded(manifest)
    targets = {OUTPUT / name: data for name, data in files.items()}
    targets[SOURCE.with_suffix(".provenance.json")] = encoded(source_record)
    # Validate every path and conflict before creating any outputs. Never overwrite.
    validated = [(checked_path(root, relative), data) for relative, data in targets.items()]
    for path, data in validated:
        if path.exists() and path.read_bytes() != data:
            raise ValueError("Existing extraction differs; use a new reviewed version, not overwrite.")
    for path, data in validated:
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("xb") as stream:
                stream.write(data)
    return manifest


if __name__ == "__main__":
    result = prepare()
    print(json.dumps({"output": str(ROOT / OUTPUT), "size": [result["width"], result["height"]],
                      "network_requests": 0, "default_assets_changed": False}, indent=2))
