from __future__ import annotations

import json
import shutil

import pytest
from PIL import Image, ImageChops

from tools import prepare_chibi_v20261102 as art


@pytest.fixture(scope="module")
def prepared():
    return art.extract((art.ROOT / art.SOURCE).read_bytes())


def test_unknown_source_and_crop_fail_closed():
    with pytest.raises(ValueError, match="Reference changed"):
        art.extract(b"other artwork")
    with pytest.raises(ValueError, match="reviewed RGB crop"):
        art.foreground_mask(Image.new("RGB", (401, 530)))


@pytest.mark.parametrize("point", art.OPENINGS + ((60, 100), (245, 550)))
def test_background_and_hair_openings_are_transparent(prepared, point):
    chibi, mask, metadata = prepared
    x, y = point
    assert mask.getpixel((x - art.CROP[0], y - art.CROP[1])) == 0
    a, b, c, d = metadata["source_alpha_bounds"]
    if a <= x < c and b <= y < d:
        assert chibi.getpixel((x - a, y - b))[3] == 0


@pytest.mark.parametrize("box", ((222, 320, 257, 345), (224, 427, 262, 445),
                                 (212, 538, 227, 543), (207, 305, 210, 310)))
def test_face_white_apron_socks_and_eye_highlights_stay_opaque(prepared, box):
    chibi, _, metadata = prepared
    x, y, _, _ = metadata["source_alpha_bounds"]
    a, b, c, d = box
    actual = chibi.crop((a - x, b - y, c - x, d - y))
    with Image.open(art.ROOT / art.SOURCE) as source:
        assert actual.getchannel("A").getextrema() == (255, 255)
        assert ImageChops.difference(actual.convert("RGB"), source.crop(box)).getbbox() is None


def test_native_size_and_all_opaque_rgb_preserved(prepared):
    chibi, _, metadata = prepared
    assert chibi.size == (362, 482)
    assert chibi.getchannel("A").getbbox() == (0, 0, 362, 482)
    assert metadata["opaque_pixels"] > 115_000
    assert metadata["network_requests"] == 0
    assert metadata["resized"] is metadata["redrawn"] is False
    with Image.open(art.ROOT / art.SOURCE) as source:
        original = source.crop(metadata["source_alpha_bounds"])
        for actual, expected in zip(art.pixels(chibi), art.pixels(original), strict=True):
            if actual[3] == 255:
                assert actual[:3] == expected


def test_prepare_is_lossless_idempotent_and_does_not_install(tmp_path):
    source = tmp_path / art.SOURCE
    source.parent.mkdir(parents=True)
    shutil.copyfile(art.ROOT / art.SOURCE, source)
    public = tmp_path / "frontend/public/art/chibi-neutral.webp"
    public.parent.mkdir(parents=True)
    public.write_bytes(b"do not overwrite")
    first = art.prepare(tmp_path)
    assert art.prepare(tmp_path) == first
    assert public.read_bytes() == b"do not overwrite"
    with Image.open(tmp_path / art.OUTPUT / "chibi-front.png") as png:
        with Image.open(tmp_path / art.OUTPUT / "chibi-front.webp") as webp:
            a, b = png.convert("RGBA"), webp.convert("RGBA")
            assert a.getchannel("A").tobytes() == b.getchannel("A").tobytes()
            for expected, actual in zip(art.pixels(a), art.pixels(b), strict=True):
                if expected[3]:
                    assert actual == expected


def test_conflicting_output_rejected_before_any_write(tmp_path):
    source = tmp_path / art.SOURCE
    source.parent.mkdir(parents=True)
    shutil.copyfile(art.ROOT / art.SOURCE, source)
    output = tmp_path / art.OUTPUT
    output.mkdir(parents=True)
    (output / "chibi-front.webp").write_bytes(b"keep")
    with pytest.raises(ValueError, match="Existing extraction differs"):
        art.prepare(tmp_path)
    assert not (output / "chibi-front.png").exists()
    assert (output / "chibi-front.webp").read_bytes() == b"keep"


def test_all_runtime_aliases_use_same_new_front_and_motion_metadata_matches(prepared):
    expected = (art.ROOT / art.OUTPUT / "chibi-front.webp").read_bytes()
    for folder in ("frontend/public/art", "views/home/art"):
        for name in ("chibi-neutral", "chibi-eat", "scene-chibi-neutral", "scene-chibi-eat"):
            assert (art.ROOT / folder / f"{name}.webp").read_bytes() == expected
    manifest = json.loads((art.ROOT / "frontend/preview-assets/art/character-motion/manifest.json").read_text())
    for frame in manifest["characters"]["chibi"]["frames"].values():
        assert (frame["static"]["width"], frame["static"]["height"]) == prepared[0].size
        assert frame["static"]["sha256"] == art.digest(expected)
        assert frame["webp"] is None  # Never fall back to animations of the old character.


def test_new_chibi_attribution_is_not_old_mit_and_source_is_bundled():
    from tools.package_plugin import audit_assets, collect_files

    manifest = audit_assets()
    for entry in manifest["assets"]:
        if "chibi" in entry["file"]:
            assert entry["license"] == "LicenseRef-User-Confirmed-Distribution"
            assert entry["source_sha256"] == art.SOURCE_SHA256
    _, source_files = collect_files()
    assert art.ROOT / art.SOURCE in source_files
