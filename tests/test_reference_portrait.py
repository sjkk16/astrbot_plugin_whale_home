from __future__ import annotations

import shutil

import pytest
from PIL import Image, ImageChops

from tools import prepare_reference_portrait as extraction


@pytest.fixture(scope="module")
def prepared():
    source = extraction.ROOT / extraction.SOURCE
    return source.read_bytes(), extraction.extract(source.read_bytes())


def test_wrong_reference_is_rejected_before_processing():
    with pytest.raises(ValueError, match="Reference changed"):
        extraction.extract(b"not the approved image")


def test_original_face_and_white_costume_are_unchanged(prepared):
    _, (portrait, _, metadata) = prepared
    x, y, _, _ = metadata["source_alpha_bounds"]
    with Image.open(extraction.ROOT / extraction.SOURCE) as source:
        for box in ((153, 121, 269, 198), (166, 301, 273, 336), (150, 550, 283, 577)):
            a, b, c, d = box
            actual = portrait.crop((a-x, b-y, c-x, d-y))
            assert actual.getchannel("A").getextrema() == (255, 255)
            assert ImageChops.difference(actual.convert("RGB"), source.crop(box)).getbbox() is None


def test_white_openings_and_ground_shadow_removed_but_shoes_preserved(prepared):
    _, (portrait, _, metadata) = prepared
    x, y, _, _ = metadata["source_alpha_bounds"]
    alpha = portrait.getchannel("A")
    for a, b in ((170, 29), (192, 881), (80, 1021), (300, 1015), (410, 550)):
        assert not (x <= a < x+portrait.width and y <= b < y+portrait.height) or alpha.getpixel((a-x, b-y)) == 0
    for a, b in ((210, 180), (195, 450), (164, 998), (190, 1024)):
        assert alpha.getpixel((a-x, b-y)) == 255
    assert metadata["network_requests"] == 0
    assert metadata["face_and_costume_repainted"] is False


def test_all_fully_opaque_pixels_keep_the_source_color(prepared):
    _, (portrait, _, metadata) = prepared
    with Image.open(extraction.ROOT / extraction.SOURCE) as original:
        original = original.crop(tuple(metadata["source_alpha_bounds"]))
        count = 0
        for actual, source in zip(extraction.pixels(portrait), extraction.pixels(original), strict=True):
            if actual[3] == 255:
                assert actual[:3] == source
                count += 1
        assert count > 140_000


def test_preparation_is_idempotent_and_does_not_change_defaults(tmp_path, prepared):
    path = tmp_path / extraction.SOURCE
    path.parent.mkdir(parents=True)
    shutil.copyfile(extraction.ROOT / extraction.SOURCE, path)
    before = path.read_bytes()
    first = extraction.prepare(tmp_path)
    assert extraction.prepare(tmp_path) == first
    assert path.read_bytes() == before == prepared[0]
    assert not (tmp_path / "frontend").exists()
    with Image.open(tmp_path / extraction.OUTPUT / "portrait-reference-v1.png") as png:
        with Image.open(tmp_path / extraction.OUTPUT / "portrait-reference-v1.webp") as webp:
            assert png.size == webp.size == (first["width"], first["height"])
            assert ImageChops.difference(png.convert("RGBA"), webp.convert("RGBA")).getbbox() is None


def test_conflicting_output_does_not_overwrite_existing_files(tmp_path):
    path = tmp_path / extraction.SOURCE
    path.parent.mkdir(parents=True)
    shutil.copyfile(extraction.ROOT / extraction.SOURCE, path)
    target = tmp_path / extraction.OUTPUT / "portrait-reference-v1.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-file")
    with pytest.raises(ValueError, match="Existing extraction differs"):
        extraction.prepare(tmp_path)
    assert target.read_bytes() == b"previous-file"
    assert not (target.parent / "portrait-reference-v1.webp").exists()
