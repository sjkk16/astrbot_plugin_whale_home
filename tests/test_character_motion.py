from __future__ import annotations

import json
import shutil

import pytest
from PIL import Image

from tools.character_motion import DIRECTORY, ROOT, audit


@pytest.fixture
def motion_project(tmp_path):
    for directory in (
        DIRECTORY,
        "frontend/public/art",
        "frontend/preview-assets/art/interaction-v030",
    ):
        shutil.copytree(ROOT / directory, tmp_path / directory)
    return tmp_path


def change_manifest(root, change):
    path = root / DIRECTORY / "manifest.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_partial_raster_manifest():
    result = audit()
    assert not result["complete"] and result["reviewed_animations"] == 1
    data = json.loads((ROOT / DIRECTORY / "manifest.json").read_text(encoding="utf-8"))
    assert data["schema_version"] == 2 and "sdk" not in data
    assert sum(len(c["frames"]) for c in data["characters"].values()) == 15
    assert set(data["characters"]["portrait"]) == {"frames"}


@pytest.mark.parametrize(
    "mutation",
    [
        lambda m: m.update(schema_version=1),
        lambda m: m["characters"]["portrait"].update(model="anything"),
        lambda m: m["characters"]["portrait"]["frames"]["neutral"]["static"].update(width=1),
        lambda m: m["characters"]["portrait"]["frames"]["eat"].update(loop=True),
        lambda m: m["files"].update({"./art/character-motion/../escape.txt": "0" * 64}),
    ],
)
def test_invalid_raster_manifest(motion_project, mutation):
    change_manifest(motion_project, mutation)
    with pytest.raises(ValueError):
        audit(motion_project)


def test_unlisted_asset(motion_project):
    (motion_project / DIRECTORY / "unreviewed.txt").write_text("no")
    with pytest.raises(ValueError, match="Unreviewed"):
        audit(motion_project)


@pytest.mark.parametrize("alpha", [0, 255])
def test_webp_audit_checks_every_frame_not_only_first(tmp_path, alpha):
    from tools.character_motion import audit_animation

    first = Image.new("RGBA", (8, 8))
    first.putpixel((2, 3), (0, 100, 230, 255))
    second = Image.new("RGBA", (8, 8), (255, 0, 0, alpha))
    output = tmp_path / "invalid.webp"
    first.save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=[83, 84],
        loop=0,
        lossless=True,
    )
    with Image.open(output) as image:
        with pytest.raises(ValueError, match="visible transparent character in frame 1"):
            audit_animation(image, size=(8, 8), loop=True, duration_ms=167)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("fps", 12, "20 fps"),
        ("fps", True, "metadata"),
        ("frame_count", 119, "Stale raster recipe"),
        ("duration_ms", 5999, "Stale raster recipe"),
        ("reviewed", "true", "metadata"),
    ],
)
def test_local_raster_rejects_invalid_metadata(motion_project, field, value, match):
    change_manifest(
        motion_project,
        lambda m: m["characters"]["portrait"]["frames"]["neutral"]["webp"].update({field: value}),
    )
    with pytest.raises(ValueError, match=match):
        audit(motion_project)


@pytest.mark.parametrize(
    "field,value,match",
    [
        ("kind", "unknown-format", "Unknown animation source"),
        ("static_sha256", "0" * 64, "source differs"),
        ("recipe", "./art/character-motion/portrait/missing.json", "Undeclared raster recipe"),
        ("recipe_sha256", "0" * 64, "Undeclared raster recipe"),
    ],
)
def test_local_raster_rejects_stale_provenance(motion_project, field, value, match):
    change_manifest(
        motion_project,
        lambda m: m["characters"]["portrait"]["frames"]["neutral"]["webp"]["source"].update(
            {field: value}
        ),
    )
    with pytest.raises(ValueError, match=match):
        audit(motion_project)


def test_raster_requires_explicit_source(motion_project):
    change_manifest(
        motion_project,
        lambda m: m["characters"]["portrait"]["frames"]["neutral"]["webp"].pop("source"),
    )
    with pytest.raises(ValueError, match="Unknown animation fields"):
        audit(motion_project)
