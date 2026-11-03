"""Audit transparent raster animation and its reviewed provenance."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = "frontend/preview-assets/art/character-motion"
PREFIX = "./art/character-motion/"
PORTRAIT_FRAMES = {
    "neutral",
    "happy",
    "thinking",
    "sleepy",
    "shy",
    "sad",
    "pet",
    "accept",
    "eat",
    "drink",
    "read",
    "play",
    "rest",
}
ONCE = {"pet", "accept", "eat", "drink"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def checked_file(base: Path, relative: str) -> Path:
    if (
        not relative
        or not re.fullmatch(r"[A-Za-z0-9_./-]+", relative)
        or any(part in {"", ".", ".."} for part in relative.split("/"))
    ):
        raise ValueError("Unsafe character asset path")
    target = base / relative
    if target.resolve() != target.absolute() or not target.resolve().is_relative_to(base.resolve()):
        raise ValueError("Linked or escaped character asset")
    if not target.is_file() or target.stat().st_size > 64 * 1024 * 1024:
        raise ValueError(f"Missing or oversized character asset: {relative}")
    return target


def asset_file(root: Path, url: str) -> Path:
    if not isinstance(url, str) or not url.startswith(PREFIX):
        raise ValueError("Character resource must be local")
    return checked_file(root / DIRECTORY, url[len(PREFIX) :])


def visible_pixels(frame: Image.Image) -> bytes:
    # Premultiplied pixels ignore RGB hidden behind zero alpha, while retaining
    # real changes in opacity. Raw RGB differences can approve invisible noise.
    return frame.convert("RGBA").convert("RGBa").tobytes()


def audit_animation(
    image: Image.Image,
    *,
    size: tuple[int, int],
    loop: bool,
    duration_ms: int,
    frame_count: int | None = None,
    fps: int | None = None,
) -> int:
    if (
        image.format != "WEBP"
        or image.n_frames < 2
        or image.size != size
        or (frame_count is not None and image.n_frames != frame_count)
        or image.info.get("loop") != (0 if loop else 1)
    ):
        raise ValueError("Invalid multi-frame WebP / playback mode")
    first, changed, duration = None, False, 0
    for index in range(image.n_frames):
        image.seek(index)
        frame = image.convert("RGBA")  # loads frame and its duration metadata
        low, high = frame.getchannel("A").getextrema()
        if low == 255 or high == 0:
            raise ValueError(f"Expected a visible transparent character in frame {index}")
        pixels = visible_pixels(frame)
        if first is None:
            first = pixels
        else:
            changed |= pixels != first
        frame_duration = image.info.get("duration", 0)
        if frame_duration <= 0:
            raise ValueError("Invalid WebP frame duration")
        if fps is not None and frame_duration != round((index + 1) * 1000 / fps) - round(
            index * 1000 / fps
        ):
            raise ValueError("WebP frame timing differs from declared fps")
        duration += frame_duration
    if not changed:
        raise ValueError("Animation contains only identical visible frames")
    if duration != duration_ms:
        raise ValueError("WebP duration differs from fixed-step metadata")
    return image.n_frames


def audit(root: Path = ROOT, *, complete: bool = False, published: bool = False) -> dict:
    root = root.resolve()
    directory = root / DIRECTORY
    file = checked_file(directory, "manifest.json")
    manifest = json.loads(file.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 2 or "sdk" in manifest:
        raise ValueError("Unsupported raster manifest")
    if set(manifest["characters"]) != {"portrait", "chibi"}:
        raise ValueError("Both character styles must be declared")
    files = manifest["files"]
    records = [{"file": "views/home/art/character-motion/manifest.json", "sha256": sha256(file)}]
    for url, digest in files.items():
        path = asset_file(root, url)
        if not re.fullmatch(r"[a-f0-9]{64}", digest) or sha256(path) != digest:
            raise ValueError("Character asset digest mismatch")
        suffixes = {".json", ".png", ".webp"}
        if path.suffix not in suffixes:
            raise ValueError("Unreviewed character asset extension")
        records.append({"file": "views/home/" + url[2:], "sha256": digest})
    expected = {"manifest.json"} | {url[len(PREFIX) :] for url in files}
    actual = {p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()}
    if expected != actual:
        raise ValueError("Unreviewed or missing character motion files")
    animations = 0
    for style, character in manifest["characters"].items():
        if set(character) != {"frames"}:
            raise ValueError("Unknown character fields")
        frames = character["frames"]
        if set(frames) != (PORTRAIT_FRAMES if style == "portrait" else {"neutral", "eat"}):
            raise ValueError("Expected all 15 existing character presentations")
        for name, frame in frames.items():
            static = frame["static"]
            source = static["path"]
            if not source.startswith("./art/"):
                raise ValueError("Invalid static fallback path")
            base = root / (
                "frontend/preview-assets" if "interaction-v030/" in source else "frontend/public"
            )
            fallback = checked_file(base, source[2:])
            with Image.open(fallback) as image:
                if image.size != (static["width"], static["height"]) or image.n_frames != 1:
                    raise ValueError("Static fallback dimensions / frames differ")
            if sha256(fallback) != static["sha256"]:
                raise ValueError("Static fallback digest mismatch")
            anchor = static["foot_anchor"]
            if len(anchor) != 2 or not 0 <= anchor[0] <= 1 or anchor[1] != 1:
                raise ValueError("Expected foot-aligned artwork")
            if frame["loop"] != (name not in ONCE) or not 0 < frame["duration_seconds"] <= 10:
                raise ValueError("Invalid animation timing")
            if set(frame) != {"static", "webp", "loop", "duration_seconds"}:
                raise ValueError("Unknown frame fields")
            webp = frame["webp"]
            if not webp:
                continue
            if set(webp) != {
                "path",
                "width",
                "height",
                "foot_anchor",
                "sha256",
                "reviewed",
                "fps",
                "frame_count",
                "duration_ms",
                "source",
            }:
                raise ValueError("Unknown animation fields")
            if (
                type(webp["reviewed"]) is not bool
                or type(webp["fps"]) is not int
                or type(webp["frame_count"]) is not int
                or not 2 <= webp["frame_count"] <= 600
                or not 0 < webp["duration_ms"] <= 10000
            ):
                raise ValueError("Invalid animation metadata")
            provenance = webp.get("source")
            raster = isinstance(provenance, dict) and provenance.get("kind") == "local-raster"
            if not raster:
                raise ValueError("Unknown animation source")
            if raster:
                if webp["fps"] != 20:
                    raise ValueError("Local raster animation must be 20 fps")
                if provenance.get("static_sha256") != static["sha256"]:
                    raise ValueError("Raster animation source differs from static fallback")
                recipe_url = provenance.get("recipe")
                if (
                    recipe_url not in files
                    or not recipe_url.endswith(".json")
                    or files[recipe_url] != provenance.get("recipe_sha256")
                ):
                    raise ValueError("Undeclared raster recipe")
                recipe = json.loads(asset_file(root, recipe_url).read_text(encoding="utf-8"))
                if (
                    recipe.get("kind") != "local-raster"
                    or recipe.get("schema_version") != 1
                    or recipe.get("static_sha256") != static["sha256"]
                    or recipe.get("output_sha256") != webp["sha256"]
                    or recipe.get("fps") != webp["fps"]
                    or recipe.get("frame_count") != webp["frame_count"]
                    or recipe.get("duration_ms") != webp["duration_ms"]
                ):
                    raise ValueError("Stale raster recipe")
            if webp["path"] not in files or webp["sha256"] != files[webp["path"]]:
                raise ValueError("Undeclared animated WebP")
            if (webp["width"], webp["height"], webp["foot_anchor"]) != (
                static["width"],
                static["height"],
                anchor,
            ):
                raise ValueError("Animation geometry differs from fallback")
            with Image.open(asset_file(root, webp["path"])) as image:
                audit_animation(
                    image,
                    size=(webp["width"], webp["height"]),
                    loop=frame["loop"],
                    duration_ms=webp["duration_ms"],
                    frame_count=webp["frame_count"],
                    fps=webp["fps"],
                )
            if webp["duration_ms"] != round(frame["duration_seconds"] * 1000):
                raise ValueError("WebP duration differs from the mapped motion")
            if webp["reviewed"]:
                animations += 1
    ready = animations == 15
    if complete and not ready:
        raise ValueError(f"Not complete: reviewed animations={animations}/15")
    if manifest["status"] == "complete" and not ready:
        raise ValueError("Manifest falsely claims completion")
    if published:
        for record in records:
            if sha256(checked_file(root, record["file"])) != record["sha256"]:
                raise ValueError("Published character assets are out of date")
    return {"complete": ready, "reviewed_animations": animations, "files": records}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--complete", action="store_true")
    parser.add_argument("--published", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            audit(complete=args.complete, published=args.published), ensure_ascii=False, indent=2
        )
    )
