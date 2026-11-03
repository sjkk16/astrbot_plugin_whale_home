"""Audit a fixed set of artwork and build installable/source archives without local data."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "astrbot_plugin_whale_home"
VERSION = "0.4.2"
ART = ROOT / "frontend" / "public" / "art"
SUTERA_COMMIT = "236245f30f7938dd6b509b5ece227e4136bab3e3"
GALLERY_COMMIT = "e93bc6ec7c8c179437d6dc4d270604ac4149ced1"

THIRD_PARTY = {
    'chibi-neutral.webp': {
        "author": "Unknown; user-provided chibi reference (2026-11-02)",
        "license": "LicenseRef-User-Confirmed-Distribution",
        "source": "art-sources/chibi-v20261102/reference.jpg",
        "source_sha256": "12c5fd201fb65161b30d803a45b5fd29ff4ae6e02a3b1394d1a1c8fd86a75f5b",
        "modifications": "Left/front view; reviewed canvas/hair-gap mask; one-pixel edge unmatting; alpha-trimmed lossless WebP; no resize/redraw.",
        "distribution": "Public distribution confirmed by the user on 2026-11-03; authorship and underlying permissions not independently verified.",
        "license_status": "Not covered by the code MIT or the previous chibi artwork license.",
        "expected_sha256": "ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1"
    },
    'chibi-eat.webp': {
        "author": "Unknown; user-provided chibi reference (2026-11-02)",
        "license": "LicenseRef-User-Confirmed-Distribution",
        "source": "art-sources/chibi-v20261102/reference.jpg",
        "source_sha256": "12c5fd201fb65161b30d803a45b5fd29ff4ae6e02a3b1394d1a1c8fd86a75f5b",
        "modifications": "Left/front view; reviewed canvas/hair-gap mask; one-pixel edge unmatting; alpha-trimmed lossless WebP; no resize/redraw. Neutral static fallback; no eating pose provided.",
        "distribution": "Public distribution confirmed by the user on 2026-11-03; authorship and underlying permissions not independently verified.",
        "license_status": "Not covered by the code MIT or the previous chibi artwork license.",
        "expected_sha256": "ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1"
    },
    "portrait.webp": {
        "author": "Unknown; user-provided reference deepseek.png",
        "license": "LicenseRef-User-Confirmed-Distribution",
        "source": "art-sources/character-v021/reference/deepseek-v1.png",
        "source_sha256": "f1dfef333d337cf949aa295b56b7ce985c4628ac9bc7ad5ede95575db6bf9e14",
        "modifications": "Left/front adult view only; reviewed canvas/hair-gap mask; "
                         "one-pixel matte correction; alpha-trimmed lossless WebP, no resize/redraw.",
        "distribution": "Public distribution confirmed by the user on 2026-11-03; authorship and underlying permissions not independently verified.",
        "license_status": "Not covered by the code MIT or the previous portrait's CC license.",
    },
}
# Cropped sprites remain under their original artwork licenses, not the code license.
for original_name in ("portrait", "chibi-neutral", "chibi-eat"):
    entry = dict(THIRD_PARTY[f"{original_name}.webp"])
    entry.pop("expected_sha256", None)
    entry["modifications"] += " Alpha-bounds crop for scene foot anchoring; lossless WebP."
    entry["source_file"] = f"frontend/public/art/{original_name}.webp"
    THIRD_PARTY[f"scene-{original_name}.webp"] = entry
THIRD_PARTY["night-room.webp"] = {
    "author": "AI-generated concept from the local project; underlying model unverified",
    "license": "LicenseRef-User-Confirmed-Distribution",
    "source": "art-sources/night-room-v1.png; original provider provenance preserved alongside it",
    "source_sha256": "3272ec74b024ffdb179e89ee3f6888e3c6999af65af2ce74824d717a71e87ef7",
    "modifications": "Full original frame, no resize or crop; RGB WebP quality 95.",
    "distribution": "Public distribution confirmed by the user on 2026-11-03; underlying permissions not independently verified.",
    "license_status": "User confirmation is not an independent rights audit or a commercial-use grant.",
}

INTERACTION_NAMES = ("happy", "thinking", "sleepy", "shy", "sad", "pet", "accept",
                     "eat", "drink", "read", "play", "rest")
INTERACTION_ART = "frontend/preview-assets/art/interaction-v030"
INTERACTION_SOURCE = "output/imagegen/interaction-v030"

OWN_ART = {"room.svg"} | {
    f"items/{name}.svg"
    for name in ("rice", "tea", "cookie", "book", "game", "pillow", "plant", "table",
                 "chair", "bed", "lamp", "rug")
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit_interaction_assets(root: Path = ROOT) -> list[dict]:
    art = root / INTERACTION_ART
    manifest_path = checked_path(root, art / "manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    variants = manifest["variants"]
    if set(variants) != set(INTERACTION_NAMES) or manifest["pending_illustrations"]:
        raise RuntimeError("Release requires all 12 reviewed interaction illustrations.")
    expected = {"manifest.json"} | {f"{name}.webp" for name in INTERACTION_NAMES}
    if {path.name for path in art.iterdir()} != expected:
        raise RuntimeError("Unreviewed or missing interaction artwork.")
    published = root / "views/home/art/interaction-v030"
    if not published.is_dir() or {path.name for path in published.iterdir()} != expected:
        raise RuntimeError("Published interaction assets are out of date; rebuild.")
    if digest(checked_path(root, published / "manifest.json")) != digest(manifest_path):
        raise RuntimeError("Published interaction manifest is out of date; rebuild.")
    assets = []
    for name in sorted(INTERACTION_NAMES):
        entry = variants[name]
        source = (f"{INTERACTION_SOURCE}/sample-{'smile' if name == 'happy' else 'eat'}.png"
                  if name in ("happy", "eat") else f"{INTERACTION_SOURCE}/full-set/raw/{name}.png")
        if entry["path"] != f"./art/interaction-v030/{name}.webp" or entry["source"] != source:
            raise RuntimeError(f"Unreviewed interaction source/path: {name}")
        sha = digest(checked_path(root, art / f"{name}.webp"))
        if sha != entry["sha256"] or digest(checked_path(root, root / source)) != entry["source_sha256"]:
            raise RuntimeError(f"Interaction artwork/source digest mismatch: {name}")
        if digest(checked_path(root, published / f"{name}.webp")) != sha:
            raise RuntimeError(f"Published interaction artwork is out of date: {name}")
        assets.append({"file": f"views/home/art/interaction-v030/{name}.webp", "sha256": sha,
                       "author": "AI-derived from user-provided deepseek.png; source author unverified",
                       "license": "LicenseRef-User-Confirmed-Distribution", "source": source,
                       "source_sha256": entry["source_sha256"], "modifications": entry["method"],
                       "distribution": "Public distribution confirmed by the user on 2026-11-03; underlying permissions not independently verified.",
                       "width": entry["width"], "height": entry["height"],
                       "foot_anchor": entry["foot_anchor"]})
    return assets


def audit_assets(root: Path = ROOT) -> dict:
    assets = []
    art = root / "frontend/public/art"
    names = {path.relative_to(art).as_posix() for path in art.rglob("*") if path.is_file()}
    if names != set(THIRD_PARTY) | OWN_ART:
        raise RuntimeError("Unreviewed or missing artwork; update attribution before packaging.")
    original = root / "art-sources" / "shijiemao-maid.webp"
    if digest(original) != "245759a66ce45505be3a6cee3cd8dd0275bee2d545e076cec94176347d143aa3":
        raise RuntimeError("The attributed portrait source has changed.")
    if digest(root / "art-sources/night-room-v1.png") != THIRD_PARTY["night-room.webp"]["source_sha256"]:
        raise RuntimeError("The personally selected background source has changed.")
    portrait = THIRD_PARTY["portrait.webp"]
    if digest(root / portrait["source"]) != portrait["source_sha256"]:
        raise RuntimeError("The user-provided adult portrait reference has changed.")
    chibi = THIRD_PARTY["chibi-neutral.webp"]
    if digest(root / chibi["source"]) != chibi["source_sha256"]:
        raise RuntimeError("The user-provided chibi reference has changed.")
    for name in sorted(names):
        path = art / name
        entry = dict(THIRD_PARTY[name]) if name in THIRD_PARTY else {
            "author": "Whale Home Contributors", "license": "MIT",
            "source": "original code-drawn game artwork", "modifications": "original",
        }
        sha = digest(path)
        if "expected_sha256" in entry and sha != entry.pop("expected_sha256"):
            raise RuntimeError(f"Upstream asset hash mismatch: {name}")
        published_path = root / "views" / "home" / "art" / name
        if not published_path.is_file() or digest(published_path) != sha:
            raise RuntimeError(f"Frontend assets are out of date; rebuild: {name}")
        assets.append({"file": f"views/home/art/{name}", "sha256": sha, **entry})
    assets.extend(audit_interaction_assets(root))
    try:
        from tools.character_motion import audit as audit_motion
    except ModuleNotFoundError:  # Direct script invocation without project on sys.path.
        from character_motion import audit as audit_motion

    motion = audit_motion(root, published=True)
    published_art = root / "views/home/art"
    expected = {entry["file"] for entry in assets} | {"views/home/art/interaction-v030/manifest.json"}
    expected.update(record["file"] for record in motion["files"])
    actual = {path.relative_to(root).as_posix() for path in published_art.rglob("*") if path.is_file()}
    if actual != expected:
        raise RuntimeError("Unreviewed or missing published artwork.")
    return {
        "schema_version": 1,
        "package_audience": "public-release",
        "distribution_confirmation": {
            "date": "2026-11-03", "basis": "user-confirmation", "independently_verified": False,
        },
        "assets": assets, "character_motion": motion,
    }


# Runtime assets are prebuilt. Development references never enter the install ZIP.
RUNTIME_FILES = (
    "main.py", "metadata.yaml", "requirements.txt", "README.md", "ASSETS.md", "LICENSE",
    "asset-manifest.json", "VERIFICATION.md", "PERSONAL-USE-NOTICE.md", "CHARACTER-V021.md",
    "COMPUTER.md", "RELEASE-V042.md", "RELEASE-V041.md", "RELEASE-V040.md", "RELEASE-V030.md", "RELEASE-V031.md", "RELEASE-V032.md", "SKILLS-PREVIEW.md",
    "INTERACTION-PREVIEW.md", "INTERACTION-VERIFICATION.md", "CHARACTER-MOTION.md",
)
RUNTIME_DIRS = {
    "whale_home": {".py"},
    "views": {".html", ".js", ".mjs", ".css", ".webp", ".svg", ".json", ".png", ".txt"},
    ".astrbot-plugin": {".json"},
    "licenses": {".txt"},
}
SOURCE_FILES = (
    "art-sources/portrait-animation/source-check.json",
    "output/portrait-idle-v1/generate_idle.py",
    "output/portrait-idle-v1/prepare_reference_lashes.py",
    "output/portrait-idle-v1/test_idle.py",
    "output/portrait-idle-v1/audit_animation.py",
    "output/portrait-idle-v1/analyze_native_capture.py",
    "output/portrait-idle-v1/inspection-pet-eyes.png",
    "output/portrait-idle-v1/assets/lash-placement.json",
    "output/portrait-idle-v1/assets/left-reference-lash.png",
    "output/portrait-idle-v1/assets/right-reference-lash.png",
    "output/portrait-idle-v1/keyframes/open.png",
    "output/portrait-idle-v1/keyframes/half-closed.png",
    "output/portrait-idle-v1/keyframes/closed.png",
    "output/portrait-idle-v1/keyframes/half-open.png",
    "output/portrait-idle-v1/keyframes/inhale.png",
    "output/portrait-idle-v1/keyframes/exhale.png",
    "output/portrait-idle-v1/qa/decoded-audit.json",
    "output/portrait-idle-v1/qa/native-playback-report.json",
    "output/portrait-idle-v1/qa/browser-decoder-playback.json",
    "output/portrait-idle-v1/SOURCE-README.md",
    "pyproject.toml", "uv.lock", ".gitignore", ".gitattributes",
    "frontend/package.json", "frontend/package-lock.json", "frontend/tsconfig.json",
    "frontend/vite.config.ts", "frontend/playwright.config.ts", "frontend/index.html",
    "art-sources/chibi-v20261102/reference.jpg",
    "output/chibi-v20261102/extraction.provenance.json",
    "output/chibi-v20261102/chibi-front.webp",
    "art-sources/chibi-v20261102/previous-defaults/chibi-neutral.webp",
    "art-sources/chibi-v20261102/previous-defaults/chibi-eat.webp",
    "art-sources/chibi-v20261102/previous-defaults/scene-chibi-neutral.webp",
    "art-sources/chibi-v20261102/previous-defaults/scene-chibi-eat.webp",
    "art-sources/shijiemao-maid.webp", "art-sources/night-room-v1.png",
    "art-sources/night-room-v1.prompt.txt", "art-sources/night-room-v1.provenance.json",
    "art-sources/character-v021/reference/deepseek-v1.png",
    "art-sources/character-v021/reference/appearance-reference-v1.png",
    "art-sources/character-v021/reference/appearance-reference-v1.provenance.json",
    "art-sources/character-v021/reference/chibi-character-sheet-v1.png",
    "art-sources/character-v021/reference/chibi-character-sheet-v1.provenance.json",
    "art-sources/character-v021/prompts/original-portrait.txt",
    "art-sources/character-v021/prompts/original-chibi.txt",
    "art-sources/character-v021/previous-defaults-v020/portrait.webp",
    "art-sources/character-v021/previous-defaults-v020/scene-portrait.webp",
    "art-sources/character-v021/previous-defaults-v020/README.txt",
    "output/imagegen/character-v021/deepseek-front-extracted/extraction.provenance.json",
    "output/imagegen/interaction-v030/sample-smile.png",
    "output/imagegen/interaction-v030/sample-eat.png",
    "output/imagegen/interaction-v030/sample-plan.json",
    "output/imagegen/interaction-v030/reference/front-native.png",
    "output/imagegen/interaction-v030/reference/front-edit-target.png",
    "output/imagegen/interaction-v030/reference/expression-edit-mask.png",
    "output/imagegen/interaction-v030/full-set/completion-requests.json",
    "output/imagegen/interaction-v030/full-set/raw/thinking.png",
    "output/imagegen/interaction-v030/full-set/raw/sleepy.png",
    "output/imagegen/interaction-v030/full-set/raw/shy.png",
    "output/imagegen/interaction-v030/full-set/raw/sad.png",
    "output/imagegen/interaction-v030/full-set/raw/pet.png",
    "output/imagegen/interaction-v030/full-set/raw/accept.png",
    "output/imagegen/interaction-v030/full-set/raw/drink.png",
    "output/imagegen/interaction-v030/full-set/raw/read.png",
    "output/imagegen/interaction-v030/full-set/raw/play.png",
    "output/imagegen/interaction-v030/full-set/raw/rest.png",
    "output/imagegen/interaction-v030/full-set/review-candidates/accept-d8345112d247/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/drink-3eb1b294d319/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/pet-5aab0b4c5720/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/play-dcd5fbd178d5/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/read-528b491daeff/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/rest-2e391842f001/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/sad-a854bc33ebee/approved.json",
    "output/imagegen/interaction-v030/full-set/review-candidates/shy-c303abe37b53/approved.json",
    "output/imagegen/interaction-v030/full-set/prompts/accept.txt",
    "output/imagegen/interaction-v030/full-set/prompts/drink.txt",
    "output/imagegen/interaction-v030/full-set/prompts/pet.txt",
    "output/imagegen/interaction-v030/full-set/prompts/play.txt",
    "output/imagegen/interaction-v030/full-set/prompts/read.txt",
    "output/imagegen/interaction-v030/full-set/prompts/rest.txt",
    "output/imagegen/interaction-v030/full-set/prompts/sad.txt",
    "output/imagegen/interaction-v030/full-set/prompts/shy.txt",
    "output/imagegen/interaction-v030/full-set/prompts/sleepy.txt",
    "output/imagegen/interaction-v030/full-set/prompts/thinking.txt",
)
SOURCE_DIRS = {
    "frontend/src": {".ts", ".vue", ".css"},
    "frontend/public": {".webp", ".svg"},
    # Build inputs; verified copies are included under views/home in the install ZIP.
    "frontend/preview-assets": {".webp", ".json", ".png", ".js", ".mjs", ".txt"},
    "frontend/tests": {".ts"},
    "tests": {".py", ".json"},
    "tools": {".py", ".js", ".mjs"},
}
SKIP_DIRS = {
    "__pycache__", "node_modules", ".npm-cache", "test-results", "playwright-report",
    ".pytest_cache", ".ruff_cache", ".git",
}
REQUIRED_LICENSES = (
    "Sutera-Diffusus-MIT.txt", "CC-BY-NC-SA-4.0.txt", "Vue-MIT.txt", "Lucide-ISC-MIT.txt",
    "Personal-Preview-Artwork.txt", "USER-CONFIRMED-DISTRIBUTION.txt",
)


def checked_path(root: Path, path: Path) -> Path:
    root = root.resolve()
    path = path.absolute()
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise RuntimeError("Package paths must stay inside a workspace subdirectory.")
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink() or parent.is_junction():
            raise RuntimeError("Linked package paths are not allowed.")
    return path


def files_under(directory: str, extensions: set[str], root: Path = ROOT) -> list[Path]:
    base = checked_path(root, root / directory)
    if not base.is_dir():
        raise RuntimeError(f"Missing package directory: {directory}")
    files = []
    for current, dirs, names in os.walk(base, followlinks=False):
        dirs[:] = [name for name in dirs if name not in SKIP_DIRS]
        for name in dirs:
            checked_path(root, Path(current) / name)
        for name in names:
            if name.endswith(".pyc"):
                continue
            path = checked_path(root, Path(current) / name)
            if path.suffix.lower() not in extensions or name.startswith(".env") or any(
                word in name.lower() for word in ("credentials", "authorization", "secrets")
            ):
                raise RuntimeError(f"Unreviewed package file: {path.relative_to(root)}")
            files.append(path)
    return sorted(files)


def collect_files(root: Path = ROOT) -> tuple[list[Path], list[Path]]:
    runtime = [root / name for name in RUNTIME_FILES]
    for directory, extensions in RUNTIME_DIRS.items():
        runtime.extend(files_under(directory, extensions, root))
    source = list(runtime) + [root / name for name in SOURCE_FILES]
    for directory, extensions in SOURCE_DIRS.items():
        source.extend(files_under(directory, extensions, root))
    for path in source:
        checked_path(root, path)
        if not path.is_file():
            raise RuntimeError(f"Missing package input: {path.relative_to(root)}")
    for license_name in REQUIRED_LICENSES:
        if root / "licenses" / license_name not in runtime:
            raise RuntimeError(f"Missing license: {license_name}")
    return sorted(set(runtime)), sorted(set(source))


def audit_versions(root: Path = ROOT) -> None:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    lock = tomllib.loads((root / "uv.lock").read_text(encoding="utf-8"))
    python_lock = next(p for p in lock["package"] if p["name"] == project["project"]["name"])
    package = json.loads((root / "frontend/package.json").read_text(encoding="utf-8"))
    npm_lock = json.loads((root / "frontend/package-lock.json").read_text(encoding="utf-8"))
    metadata = (root / "metadata.yaml").read_text(encoding="utf-8")
    match = re.search(r"^version:\s*v?([\d.]+)\s*$", metadata, flags=re.MULTILINE)
    versions = [project["project"]["version"], python_lock["version"], package["version"],
                npm_lock["version"], npm_lock["packages"][""]["version"], match[1] if match else None]
    if any(version != VERSION for version in versions):
        raise RuntimeError(f"Inconsistent release versions: {versions}")
    app = (root / "frontend/src/App.vue").read_text(encoding="utf-8")
    if app.count(f"v{VERSION}") != 2:
        raise RuntimeError("Both visible frontend version labels must match the package.")
    if "立绘及其衍生：CC BY-NC-SA 4.0" in app:
        raise RuntimeError("The new portrait must not inherit the old portrait's license.")


def archive_bytes(root: Path, files: list[Path]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for file in files:
            checked_path(root, file)
            # Fixed metadata makes rebuilds byte-for-byte reproducible across checkouts.
            info = zipfile.ZipInfo(f"{NAME}/{file.relative_to(root).as_posix()}", (2026, 10, 31, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, file.read_bytes(), compresslevel=9)
    return buffer.getvalue()


def build_packages(output: Path | None = None, root: Path = ROOT) -> dict[str, str]:
    root = root.resolve()
    output = checked_path(root, output or root / "dist")
    audit_versions(root)
    manifest = audit_assets(root)
    recorded = json.loads((root / "asset-manifest.json").read_text(encoding="utf-8"))
    if recorded != manifest:
        raise RuntimeError("Asset manifest is stale; review and update it before packaging.")
    runtime, source = collect_files(root)
    payloads = {}
    hashes = {}
    for suffix, files in (("", runtime), ("-source", source)):
        name = f"{NAME}-v{VERSION}{suffix}.zip"
        payloads[name] = archive_bytes(root, files)
        if len(payloads[name]) > 120 * 1024 * 1024:
            raise RuntimeError("Release exceeds the 120 MiB upload-safe budget; do not embed browser binaries.")
        hashes[name] = hashlib.sha256(payloads[name]).hexdigest()
    payloads[f"SHA256SUMS-v{VERSION}.txt"] = (
        "".join(f"{sha}  {name}\n" for name, sha in hashes.items()).encode("ascii"))
    # Preflight all outputs before writing. Never silently overwrite an existing release.
    for name, content in payloads.items():
        destination = checked_path(root, output / name)
        if destination.exists() and destination.read_bytes() != content:
            raise RuntimeError(f"Existing release differs; use a new staging directory: {name}")
    output.mkdir(parents=True, exist_ok=True)
    for name, content in payloads.items():
        destination = output / name
        if not destination.exists():
            with destination.open("xb") as stream:
                stream.write(content)
        print(f"{name}: {len(content):,} bytes")
    print(f"Audited {len(manifest['assets'])} artwork files. No user data included.")
    return hashes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist",
                        help="Workspace-local staging/output directory; defaults to dist")
    arguments = parser.parse_args()
    build_packages(arguments.output)
