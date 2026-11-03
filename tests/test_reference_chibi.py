from __future__ import annotations

import hashlib
import json
import re
import shutil
import socket
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageFilter

from tools import prepare_reference_chibi as extraction


@pytest.fixture(scope="module")
def extracted():
    content = (extraction.ROOT / extraction.SOURCE).read_bytes()
    return content, extraction.extract(content)


@pytest.fixture
def workspace(tmp_path):
    for relative in (extraction.SOURCE, extraction.BACKGROUND):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(extraction.ROOT / relative, target)
    for relative in ("frontend/public/art/scene-chibi-neutral.webp", "views/home/index.html",
                     "metadata.yaml", "dist/old-install.zip", "home.sqlite3"):
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"existing-user-data-do-not-change")
    return tmp_path


def snapshot(root: Path) -> dict:
    return {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in root.rglob("*") if path.is_file()}


def test_unknown_reference_is_rejected():
    with pytest.raises(ValueError, match="Reference changed"):
        extraction.extract(b"not the approved Q-version sheet")


@pytest.mark.parametrize("mode,size", [("RGBA", (548, 625)), ("RGB", (420, 1086))])
def test_mask_refuses_mature_portrait_coordinates_or_wrong_mode(mode, size):
    with pytest.raises(ValueError, match="approved RGB Q-version crop"):
        extraction.foreground_mask(Image.new(mode, size))


def test_face_white_costume_and_eye_highlights_keep_original_pixels(extracted):
    _, (chibi, _, details) = extracted
    x, y, _, _ = details["source_alpha_bounds"]
    regions = (
        (178, 230, 310, 307),  # Face, eyes, blush and mouth.
        (209, 59, 237, 72),  # White headband, directly below the ahoge opening.
        (188, 410, 291, 476),  # White apron and whale emblem.
        (222, 523, 246, 542),  # Skirt lace.
        (187, 559, 216, 568), (296, 555, 320, 568),  # Both white socks.
        (198, 246, 202, 250), (284, 238, 288, 242),  # Both eye highlights.
    )
    with Image.open(extraction.ROOT / extraction.SOURCE) as source:
        for a, b, c, d in regions:
            actual = chibi.crop((a - x, b - y, c - x, d - y))
            assert actual.getchannel("A").getextrema() == (255, 255)
            assert ImageChops.difference(actual.convert("RGB"),
                                         source.crop((a, b, c, d))).getbbox() is None


def test_all_opaque_rgb_and_mask_interior_are_unchanged(extracted):
    _, (chibi, mask, details) = extracted
    box = tuple(details["source_alpha_bounds"])
    core = mask.filter(ImageFilter.MinFilter(3)).crop(box).tobytes()
    with Image.open(extraction.ROOT / extraction.SOURCE) as source:
        original = extraction.pixels(source.crop(box))
    count = 0
    for actual, before, inside in zip(extraction.pixels(chibi), original, core, strict=True):
        if inside:
            assert actual == before + (255,)
        if actual[3] == 255:
            assert actual[:3] == before
            count += 1
    assert count == details["opaque_pixels"] > 185_000
    assert details["partial_alpha_pixels"] > 0


def test_background_openings_and_floor_removed_with_complete_character(extracted):
    _, (chibi, _, details) = extracted
    x, y, _, _ = details["source_alpha_bounds"]
    alpha = chibi.getchannel("A")
    clear = (*extraction.OPENINGS, (250, 574), (252, 601), (140, 601), (390, 601), (1, 1))
    for a, b in clear:
        if x <= a < x + chibi.width and y <= b < y + chibi.height:
            assert alpha.getpixel((a - x, b - y)) == 0
    for a, b in ((230, 25), (72, 242), (442, 246), (250, 260),
                 (480, 471), (210, 602), (300, 602)):
        assert alpha.getpixel((a - x, b - y)) == 255
    # The narrow original hair tip remains soft, not a solid white speck.
    assert 0 < alpha.getpixel((48 - x, 463 - y)) < 150
    assert details["resized"] is False
    assert details["face_and_costume_repainted"] is False
    assert details["network_requests"] == 0


def test_native_bounds_and_single_connected_front_view(extracted):
    _, (chibi, mask, details) = extracted
    assert chibi.size == (526, 600)
    assert mask.size == (548, 625)
    assert details["source_alpha_bounds"] == [11, 12, 537, 612]
    assert chibi.getchannel("A").getbbox() == (0, 0, chibi.width, chibi.height)
    visible = bytearray(bool(value) for value in chibi.getchannel("A").tobytes())
    x, y, _, _ = details["source_alpha_bounds"]
    seed = (extraction.FACE_SEED[1] - y) * chibi.width + extraction.FACE_SEED[0] - x
    component = extraction.connected(visible, chibi.width, chibi.height, [seed])
    assert all(bool(a) == bool(b) for a, b in zip(visible, component, strict=True))


def test_preparation_is_lossless_local_only_and_preserves_existing_files(workspace, monkeypatch):
    before = snapshot(workspace)

    def forbidden_network(*args, **kwargs):
        raise AssertionError("Reference extraction must not open any network connection")

    monkeypatch.setattr(socket, "socket", forbidden_network)
    manifest = extraction.prepare(workspace)
    after = snapshot(workspace)
    assert all(after[path] == digest for path, digest in before.items())
    directory = workspace / extraction.OUTPUT
    with Image.open(directory / "chibi-reference-v1.png") as png:
        with Image.open(directory / "chibi-reference-v1.webp") as webp:
            assert png.mode == webp.mode == "RGBA"
            assert png.size == webp.size == (526, 600)
            for a, b in zip(extraction.pixels(png), extraction.pixels(webp), strict=True):
                assert a[3] == b[3]
                if a[3]:
                    assert a == b
    assert (directory / "reference-sheet-original.png").read_bytes() == (
        workspace / extraction.SOURCE).read_bytes()
    for name, digest in manifest["outputs"].items():
        assert extraction.digest((directory / name).read_bytes()) == digest
    assert manifest["status"] == "prepared-not-integrated"
    assert manifest["requested_model"] is manifest["generation_prompt"] is None
    assert manifest["network_requests"] == 0
    assert manifest["default_assets_changed"] is False
    allowed = {str(extraction.OUTPUT / name).replace("\\", "/")
               for name in (*manifest["outputs"], "extraction.provenance.json")}
    allowed.add(extraction.SOURCE.with_suffix(".provenance.json").as_posix())
    assert after.keys() - before.keys() == allowed


def test_preparation_is_idempotent(workspace):
    first = extraction.prepare(workspace)
    before = snapshot(workspace)
    assert extraction.prepare(workspace) == first
    assert snapshot(workspace) == before
    manifest = json.loads((workspace / extraction.OUTPUT / "extraction.provenance.json").read_bytes())
    assert manifest == first


@pytest.mark.parametrize("filename", ["chibi-reference-v1.png", "room-static-preview.png"])
def test_conflicting_output_is_rejected_before_any_other_write(workspace, filename):
    target = workspace / extraction.OUTPUT / filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-result-must-not-be-replaced")
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="Existing extraction differs"):
        extraction.prepare(workspace)
    assert snapshot(workspace) == before


def test_changed_source_stops_without_outputs(workspace):
    (workspace / extraction.SOURCE).write_bytes(b"changed-source")
    before = snapshot(workspace)
    with pytest.raises(ValueError, match="Reference changed"):
        extraction.prepare(workspace)
    assert snapshot(workspace) == before
    assert not (workspace / extraction.OUTPUT).exists()


def test_output_path_cannot_leave_workspace(tmp_path):
    with pytest.raises(ValueError, match="stay inside the workspace"):
        extraction.checked_path(tmp_path, Path("../outside.png"))


def test_room_preview_matches_current_scale_anchor_and_background(extracted):
    _, (chibi, _, _) = extracted
    source = (extraction.ROOT / "frontend/src/components/RoomScene.vue").read_text(encoding="utf8")
    match = re.search(r"isChibi\.value\s*\?\s*(\.?\d+(?:\.\d+)?)\s*:\s*1", source)
    assert match and float(match.group(1)) == extraction.CHIBI_SCALE
    background = (extraction.ROOT / extraction.BACKGROUND).read_bytes()
    preview, details = extraction.room_preview(chibi, background)
    assert details["kind"] == "static-composite-not-app-screenshot"
    assert details["sprite_size"] == [232, 265]
    assert details["sprite_top_left"] == [787, 610]
    assert details["foot_baseline_y"] == 875
    assert preview.size == (1672, 999)
    with Image.open(extraction.ROOT / extraction.BACKGROUND) as room:
        # Untouched room region; the label is outside the original 1672x941 frame.
        box = (0, 0, 700, 941)
        assert ImageChops.difference(preview.crop(box), room.crop(box)).getbbox() is None
    assert "STATIC COMPOSITE" in (extraction.ROOT / "tools/prepare_reference_chibi.py").read_text(encoding="utf8")


def test_inspection_previews_do_not_scale_or_tint_asset(extracted):
    _, (chibi, _, _) = extracted
    rgba = extraction.pixels(chibi)
    for dark in (False, True):
        preview = extraction.inspection_preview(chibi, dark)
        actual = extraction.pixels(preview.crop((48, 72, 48 + chibi.width, 72 + chibi.height)))
        assert preview.size == (622, 720)
        for expected, color in zip(rgba, actual, strict=True):
            if expected[3] == 255:
                assert expected[:3] == color
