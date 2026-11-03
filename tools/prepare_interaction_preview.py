"""Review/install real artwork locally. Never generates images or replaces stable/Q art."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from collections import deque
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "output/imagegen/interaction-v030"
OUT = SOURCE / "full-set/preview-ready"
INSTALL = ROOT / "frontend/preview-assets/art/interaction-v030"
REVIEW = SOURCE / "full-set/review-candidates"
NEW_VARIANTS = ("shy", "sad", "pet", "accept", "drink", "read", "play", "rest")
LABELS = {"happy": "俏皮笑", "thinking": "思考", "sleepy": "困倦", "shy": "害羞",
          "sad": "难过", "pet": "摸头", "accept": "收礼", "eat": "白饭进食",
          "drink": "饮茶", "read": "阅读", "play": "掌机游戏", "rest": "站立休息"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rgba(path: Path) -> Image.Image:
    with Image.open(path) as source:
        if source.mode != "RGBA" or source.width * source.height > 16_000_000:
            raise ValueError(f"Expected bounded transparent RGBA artwork: {path.name}")
        image = source.copy()
    counts = image.getchannel("A").histogram()
    if counts[0] < image.width * image.height * .03 or sum(counts[250:]) < 1000:
        raise ValueError("Image lacks meaningful alpha/foreground; do not auto-matte")
    return image


def store(path: Path, content: bytes, *, metadata: bool = False) -> None:
    if not any(path.resolve().is_relative_to(base.resolve()) for base in (OUT, INSTALL, REVIEW)):
        raise ValueError("Output is outside dedicated preview asset directories")
    if path.exists():
        if path.read_bytes() != content:
            if not metadata or path.name not in ("manifest.json", "contact-sheet.png"):
                raise FileExistsError(f"Refusing to overwrite a different existing file: {path}")
            old = path.read_bytes()
            history = OUT / "history" / f"{path.stem}-{hashlib.sha256(old).hexdigest()}{path.suffix}"
            store(history, old)
        else:
            return
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("xb") as handle:
        handle.write(content)
    temporary.replace(path)


def encoded(image: Image.Image, fmt: str) -> bytes:
    stream = io.BytesIO()
    image.save(stream, format=fmt, **({"lossless": True, "method": 6} if fmt == "WEBP" else {}))
    return stream.getvalue()


def expression(raw: Path) -> tuple[Image.Image, dict]:
    generated = rgba(raw)
    original = rgba(SOURCE / "reference/front-native.png")
    with Image.open(SOURCE / "reference/front-edit-target.png") as target:
        if generated.size != target.size:
            raise ValueError("Expression canvas changed; manual realignment required")
    plan = json.loads((SOURCE / "sample-plan.json").read_text(encoding="utf-8"))
    reference = plan["reference_preparation"]
    x, y = reference["offset"]
    box = (x, y, x + round(original.width * reference["uniform_scale"]), y + 1440)
    with Image.open(SOURCE / "reference/expression-edit-mask.png") as source:
        mask = ImageChops.invert(source.getchannel("A"))
    mask = mask.crop(box).resize(original.size, Image.Resampling.LANCZOS)
    mask = ImageChops.multiply(mask, mask.filter(ImageFilter.GaussianBlur(1.5)))
    face = generated.crop(box).resize(original.size, Image.Resampling.LANCZOS)
    face.putalpha(original.getchannel("A"))
    result = Image.composite(face, original, mask)
    outside = mask.point(lambda a: 255 if a == 0 else 0)
    for band in ImageChops.difference(result, original).split():
        if ImageChops.multiply(band, outside).getbbox():
            raise ValueError("Expression altered the body outside the facial mask")
    if result.getchannel("A").tobytes() != original.getchannel("A").tobytes():
        raise ValueError("Original alpha silhouette was not preserved")
    return result, {"method": "existing model-produced face blended into original portrait",
                    "edited_region": list(mask.getbbox()), "outside_face_changed_pixels": 0,
                    "original_alpha_preserved": True}


def foot_anchor(image: Image.Image) -> list[float]:
    """Use the shoe span, not arm/hair silhouette width, as the horizontal anchor."""
    lower = image.getchannel("A").crop((0, round(image.height * .92), image.width, image.height))
    box = lower.point(lambda value: 255 if value >= 128 else 0).getbbox()
    if box is None:
        raise ValueError("No visible standing feet at the bottom of the sprite")
    return [round((box[0] + box[2]) / (2 * image.width), 6), 1.0]


def action(raw: Path) -> tuple[Image.Image, dict]:
    """Remove detached low-alpha specks only; never color-key or repaint white fabric."""
    image = rgba(raw)
    if image.size != (1024, 1536):
        raise ValueError("Action canvas changed; review the framing manually")
    alpha = image.getchannel("A")
    values = alpha.tobytes()
    width, height = image.size
    allowed = bytearray(value >= 16 for value in values)
    foreground = bytearray(width * height)
    seed = 270 * width + 512
    if not allowed[seed]:
        raise ValueError("The reference face seed is outside the generated character")
    pending = deque([seed])
    allowed[seed] = 0
    while pending:
        index = pending.popleft()
        foreground[index] = 255
        x, y = index % width, index // width
        for neighbor in ((index - 1 if x else -1), (index + 1 if x < width - 1 else -1),
                         (index - width if y else -1), (index + width if y < height - 1 else -1)):
            if neighbor >= 0 and allowed[neighbor]:
                allowed[neighbor] = 0
                pending.append(neighbor)
    support = Image.frombytes("L", image.size, bytes(foreground)).filter(ImageFilter.MaxFilter(5))
    cleaned = ImageChops.multiply(alpha, support)
    removed = [before for before, after in zip(values, cleaned.tobytes()) if before != after]
    if any(value >= 250 for value in removed):
        raise ValueError("Cleanup would remove near-opaque pixels; manual review required")
    result = image.copy()
    result.putalpha(cleaned)
    if result.convert("RGB").tobytes() != image.convert("RGB").tobytes():
        raise ValueError("Cleanup changed original RGB colors")
    bounds = cleaned.getbbox()
    if not bounds or bounds[0] == 0 or bounds[1] == 0 or bounds[2] == width or bounds[3] == height:
        raise ValueError("Character touches canvas boundary; do not silently crop it")
    return result.crop(bounds), {
        "method": "Connected alpha >=16 with two-pixel edge support; transparent-margin crop",
        "crop_box": list(bounds), "face_seed": [512, 270],
        "alpha_noise_pixels_removed": len(removed), "near_opaque_pixels_changed": 0,
        "rgb_pixels_changed": 0, "remaining_subject_alpha_unchanged": True,
        "no_white_color_keying": True, "no_repainting_or_new_generation": True,
    }


def candidate(name: str) -> tuple[Image.Image, dict, Path]:
    if name not in NEW_VARIANTS:
        raise ValueError("Unknown new variant")
    raw = SOURCE / f"full-set/raw/{name}.png"
    image, checks = expression(raw) if name in ("shy", "sad") else action(raw)
    checks.update(source_sha256=digest(raw), width=image.width, height=image.height,
                  foot_anchor=foot_anchor(image))
    return image, checks, REVIEW / f"{name}-{checks['source_sha256'][:12]}"


def review(name: str) -> dict:
    """Produce real-alpha light/dark and labeled static-room reviews, without installing."""
    image, checks, directory = candidate(name)
    store(directory / "sprite.png", encoded(image, "PNG"))
    store(directory / "checks.json", (json.dumps(checks, indent=2) + "\n").encode())
    canvas = Image.new("RGB", (1080, 1090), "#162236")
    canvas.paste(Image.new("RGB", (540, 1090), "#f4f0e8"), (540, 0))
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 20) if font_path.exists() else ImageFont.load_default()
    draw = ImageDraw.Draw(canvas)
    figure = image.copy()
    figure.thumbnail((510, 990), Image.Resampling.LANCZOS)
    for x, color in ((0, "#eee3d4"), (540, "#182235")):
        draw.text((x + 20, 20), LABELS[name] + " · 深浅底检查", fill=color, font=font)
        canvas.paste(figure, (x + (540 - figure.width) // 2, 1050 - figure.height), figure)
    store(directory / "light-dark.png", encoded(canvas, "PNG"))
    with Image.open(ROOT / "frontend/public/art/night-room.webp") as background:
        room = background.convert("RGB")
    figure = image.copy()
    height = round(room.height * .64)
    figure = figure.resize((round(height * image.width / image.height), height), Image.Resampling.LANCZOS)
    room.paste(figure, (round(room.width * .54 - figure.width * checks["foot_anchor"][0]),
                        round(room.height * .93 - figure.height)), figure)
    ImageDraw.Draw(room).text((24, 20), LABELS[name] + " · 静态脚底合成（非应用截图）", fill="white", font=font)
    store(directory / "room-static.png", encoded(room, "PNG"))
    return {"directory": str(directory), **checks}


def request_records() -> list[dict]:
    ledger = SOURCE / "full-set/completion-requests.json"
    if not ledger.exists():
        return []
    data = json.loads(ledger.read_text(encoding="utf-8-sig"))
    records = data["requests"]
    if len(records) > 8 or len({row["id"] for row in records}) != len(records):
        raise ValueError("Generation ledger exceeds the approved invocation limit")
    if any(row["id"] not in NEW_VARIANTS or row["n"] != 1 for row in records):
        raise ValueError("Unexpected generation ledger entry")
    return records


def approve(name: str) -> dict:
    """Explicit local visual-review receipt bound to both the raw and processed image."""
    image, checks, directory = candidate(name)
    records = request_records()
    if not any(row["id"] == name and row["status"] == "reviewed"
               and row["raw_sha256"] == checks["source_sha256"] for row in records):
        raise ValueError("CLI output has not been explicitly reviewed")
    if not (directory / "light-dark.png").exists() or not (directory / "room-static.png").exists():
        raise ValueError("Create and inspect review composites first")
    checks.update(approved=True, processed_sha256=hashlib.sha256(encoded(image, "PNG")).hexdigest())
    store(directory / "approved.json", (json.dumps(checks, indent=2) + "\n").encode())
    return checks


def prepare() -> dict:
    records = request_records()
    approved = {}
    for row in records:
        if row["status"] != "reviewed":
            continue
        name = row["id"]
        image, checks, directory = candidate(name)
        receipt_path = directory / "approved.json"
        if not receipt_path.exists():
            continue
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if (not receipt.get("approved") or receipt["source_sha256"] != row["raw_sha256"]
                or receipt["source_sha256"] != checks["source_sha256"]
                or receipt["processed_sha256"] != hashlib.sha256(encoded(image, "PNG")).hexdigest()):
            raise ValueError(f"Reviewed artwork changed: {name}")
        approved[name] = (image, checks)
    variants = {}
    sources = [("happy", "sample-smile.png"), ("eat", "sample-eat.png"),
               ("thinking", "full-set/raw/thinking.png"), ("sleepy", "full-set/raw/sleepy.png")]
    sources += [(name, f"full-set/raw/{name}.png") for name in NEW_VARIANTS if name in approved]
    for name, filename in sources:
        source = SOURCE / filename
        if name in approved:
            image, checks = approved[name]
        elif name in ("thinking", "sleepy"):
            image, checks = expression(source)
        else:
            image, checks = rgba(source), {"method": "reuse existing reviewed sample unchanged"}
        png, webp = encoded(image, "PNG"), encoded(image, "WEBP")
        with Image.open(io.BytesIO(webp)) as decoded:
            # RGB under alpha=0 may be normalized by WebP; all visible pixels must match.
            diff = ImageChops.difference(decoded.convert("RGBA"), image)
            if any(ImageChops.multiply(band, image.getchannel("A")).getbbox()
                   for band in diff.split()):
                raise ValueError("Lossless WebP round-trip changed visible pixels")
        store(OUT / f"{name}.png", png)
        store(INSTALL / f"{name}.webp", webp)
        variants[name] = {"path": f"./art/interaction-v030/{name}.webp",
                          "source": source.relative_to(ROOT).as_posix(),
                          "source_sha256": digest(source), "sha256": hashlib.sha256(webp).hexdigest(),
                          "width": image.width, "height": image.height,
                          "foot_anchor": foot_anchor(image), **checks}
    missing = [name for name in LABELS if name not in variants]
    original = rgba(SOURCE / "reference/front-native.png")
    manifest = {"schema_version": 1,
                "status": "playable-preview-partial-artwork" if missing else "playable-preview-complete-artwork",
                "new_model_calls": len(records), "image_cli_invocations": len(records),
                "call_count_scope": "Remaining-eight completion ledger, including earlier sessions; excludes the four prior variants.",
                "sdk_transport_retry_default": 2, "http_attempt_count": "Not independently observed",
                "rights": "Personal preview only; source rights unverified.",
                "default_and_chibi_assets_replaced": False, "variants": variants,
                "reference": {"width": original.width, "height": original.height,
                              "foot_anchor": foot_anchor(original)},
                "pending_illustrations": missing,
                "pending_behavior": "Use available expression feedback, not a fabricated action illustration."}
    data = (json.dumps(manifest, ensure_ascii=False, indent=2) + "\n").encode()
    store(INSTALL / "manifest.json", data, metadata=True)
    store(OUT / "manifest.json", data, metadata=True)
    cards = [("原立绘 · 保留", original)]
    cards += [(label, rgba(OUT / f"{name}.png")) for name, label in LABELS.items() if name in variants]
    rows = (len(cards) + 4) // 5
    overview = Image.new("RGB", (1250, rows * 570 + 50), "#162236")
    font_path = Path("C:/Windows/Fonts/msyh.ttc")
    font = ImageFont.truetype(str(font_path), 20) if font_path.exists() else ImageFont.load_default()
    draw = ImageDraw.Draw(overview)
    for index, (label, image) in enumerate(cards):
        x, y = index % 5 * 250, index // 5 * 570
        draw.text((x + 26, y + 22), label, fill="#eee3d4", font=font)
        image.thumbnail((230, 500), Image.Resampling.LANCZOS)
        overview.paste(image, (x + (250 - image.width) // 2, y + 560 - image.height), image)
    caption = f"已审查接入 {len(variants)}/12 张差分；" + (f"仍缺 {len(missing)} 张。" if missing else "专用表情与动作图已齐。")
    draw.text((26, rows * 570 + 10), caption + " Q 版和默认图保留。", fill="#bac6d8", font=font)
    store(OUT / "contact-sheet.png", encoded(overview, "PNG"), metadata=True)
    return manifest


def verify_installed() -> dict:
    """Read-only acceptance: validate installed files without treating missing art as complete."""
    manifest = json.loads((INSTALL / "manifest.json").read_text(encoding="utf-8"))
    variants = manifest["variants"]
    if not set(variants) <= set(LABELS):
        raise ValueError("Unknown installed illustration")
    pending = [name for name in LABELS if name not in variants]
    status = "playable-preview-partial-artwork" if pending else "playable-preview-complete-artwork"
    if manifest["pending_illustrations"] != pending or manifest["status"] != status:
        raise ValueError("Artwork completeness claim does not match installed files")
    if {path.stem for path in INSTALL.glob("*.webp")} != set(variants):
        raise ValueError("Unlisted or missing installed illustration")
    for name, entry in variants.items():
        path = INSTALL / f"{name}.webp"
        if entry["path"] != f"./art/interaction-v030/{name}.webp" or digest(path) != entry["sha256"]:
            raise ValueError(f"Installed illustration changed: {name}")
        image = rgba(path)
        if list(image.size) != [entry["width"], entry["height"]] or foot_anchor(image) != entry["foot_anchor"]:
            raise ValueError(f"Incorrect sprite geometry: {name}")
    records = request_records()
    if manifest["image_cli_invocations"] != len(records):
        raise ValueError("CLI invocation count does not match its ledger")
    return {"valid": True, "complete": not pending, "installed": len(variants), "total": len(LABELS),
            "pending_illustrations": pending, "image_cli_invocations": len(records),
            "http_attempt_count": manifest["http_attempt_count"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--review", choices=NEW_VARIANTS, help="Prepare candidate review images only")
    group.add_argument("--approve", choices=NEW_VARIANTS, help="Record an explicit completed visual review")
    group.add_argument("--verify", action="store_true", help="Read-only installed-art validation")
    group.add_argument("--require-complete", action="store_true", help="Read-only validation; exit 1 unless all 12 illustrations exist")
    args = parser.parse_args()
    result = (verify_installed() if args.verify or args.require_complete else review(args.review)
              if args.review else approve(args.approve) if args.approve else prepare())
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.require_complete and not result["complete"]:
        raise SystemExit(1)
