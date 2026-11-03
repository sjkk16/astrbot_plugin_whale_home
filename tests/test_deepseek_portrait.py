from __future__ import annotations

import shutil

import pytest
from PIL import Image, ImageChops

from tools import prepare_deepseek_portrait as extraction


@pytest.fixture(scope="module")
def prepared():
    content = (extraction.ROOT / extraction.SOURCE).read_bytes()
    return content, extraction.extract(content)


def test_wrong_reference_and_crop_are_rejected():
    with pytest.raises(ValueError, match="Reference changed"):
        extraction.extract(b"not the supplied reference")
    with pytest.raises(ValueError, match="reviewed RGB crop"):
        extraction.foreground_mask(Image.new("RGB", (543, 1024)))


def test_face_apron_socks_and_highlights_are_not_removed_or_repainted(prepared):
    _, (portrait, _, metadata) = prepared
    x, y, _, _ = metadata["source_alpha_bounds"]
    with Image.open(extraction.ROOT / extraction.SOURCE) as source:
        for box in ((252, 145, 328, 190), (250, 410, 335, 540),
                    (247, 905, 261, 936), (323, 905, 337, 936)):
            a, b, c, d = box
            actual = portrait.crop((a-x, b-y, c-x, d-y))
            assert actual.getchannel("A").getextrema() == (255, 255)
            assert ImageChops.difference(actual.convert("RGB"), source.crop(box)).getbbox() is None


@pytest.mark.parametrize("point", extraction.OPENINGS + ((246, 35), (289, 915), (30, 600)))
def test_background_and_reviewed_hair_openings_are_transparent(prepared, point):
    _, (portrait, mask, metadata) = prepared
    x, y, _, _ = metadata["source_alpha_bounds"]
    a, b = point
    assert mask.getpixel(point) == 0
    if x <= a < x + portrait.width and y <= b < y + portrait.height:
        assert portrait.getpixel((a-x, b-y))[3] == 0


def test_all_opaque_rgb_is_identical_and_full_front_is_preserved(prepared):
    _, (portrait, _, metadata) = prepared
    assert portrait.size == (500, 991)
    assert metadata["network_requests"] == 0
    assert metadata["face_and_costume_repainted"] is False
    with Image.open(extraction.ROOT / extraction.SOURCE) as original:
        original = original.crop(tuple(metadata["source_alpha_bounds"]))
        opaque = 0
        for actual, source in zip(extraction.pixels(portrait), extraction.pixels(original), strict=True):
            if actual[3] == 255:
                assert actual[:3] == source
                opaque += 1
        assert opaque > 250_000
    x, y, _, _ = metadata["source_alpha_bounds"]
    for a, b in ((65, 515), (520, 521), (253, 980), (326, 980), (273, 18)):
        assert portrait.getpixel((a-x, b-y))[3] > 0


def test_preparation_is_lossless_idempotent_and_does_not_touch_defaults(tmp_path, prepared):
    path = tmp_path / extraction.SOURCE
    path.parent.mkdir(parents=True)
    shutil.copyfile(extraction.ROOT / extraction.SOURCE, path)
    for name in ("portrait.webp", "scene-portrait.webp", "chibi-neutral.webp", "scene-chibi-eat.webp"):
        target = tmp_path / "frontend/public/art" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"existing default")
    first = extraction.prepare(tmp_path)
    assert extraction.prepare(tmp_path) == first
    assert path.read_bytes() == prepared[0]
    for target in (tmp_path / "frontend/public/art").iterdir():
        assert target.read_bytes() == b"existing default"
    with Image.open(tmp_path / extraction.OUTPUT / "portrait-deepseek-v1.png") as png:
        with Image.open(tmp_path / extraction.OUTPUT / "portrait-deepseek-v1.webp") as webp:
            assert png.size == webp.size == (500, 991)
            rgba, decoded = png.convert("RGBA"), webp.convert("RGBA")
            assert rgba.getchannel("A").tobytes() == decoded.getchannel("A").tobytes()
            for expected, actual in zip(extraction.pixels(rgba), extraction.pixels(decoded), strict=True):
                if expected[3]:
                    assert expected == actual


def test_conflicting_output_is_rejected_before_writing(tmp_path):
    path = tmp_path / extraction.SOURCE
    path.parent.mkdir(parents=True)
    shutil.copyfile(extraction.ROOT / extraction.SOURCE, path)
    target = tmp_path / extraction.OUTPUT / "portrait-deepseek-v1.png"
    target.parent.mkdir(parents=True)
    target.write_bytes(b"previous-file")
    with pytest.raises(ValueError, match="Existing extraction differs"):
        extraction.prepare(tmp_path)
    assert target.read_bytes() == b"previous-file"
    assert not (target.parent / "portrait-deepseek-v1.webp").exists()


def test_adult_defaults_and_archived_previous_q_assets_keep_their_hashes():
    root = extraction.ROOT
    original, _, _ = extraction.extract((root / extraction.SOURCE).read_bytes())
    expected_bytes = (root / "frontend/public/art/portrait.webp").read_bytes()
    for name, expected in CHIBI_HASHES.items():
        assert extraction.digest((root / "art-sources/chibi-v20261102/previous-defaults" / name).read_bytes()) == expected
    for folder in ("frontend/public/art", "views/home/art"):
        for name in ("portrait.webp", "scene-portrait.webp"):
            assert (root / folder / name).read_bytes() == expected_bytes
            with Image.open(root / folder / name) as image:
                rgba = image.convert("RGBA")
                assert rgba.size == original.size
                assert rgba.getchannel("A").tobytes() == original.getchannel("A").tobytes()
                for actual, source in zip(extraction.pixels(rgba), extraction.pixels(original), strict=True):
                    if source[3]:
                        assert actual == source


def test_new_portrait_attribution_is_consistent_with_the_audited_build():
    import json

    from tools.package_plugin import audit_assets

    audited = audit_assets()
    recorded = json.loads((extraction.ROOT / "asset-manifest.json").read_text(encoding="utf-8"))
    assert audited == recorded
    for entry in audited["assets"]:
        if "portrait" in entry["file"]:
            assert entry["license"] == "LicenseRef-User-Confirmed-Distribution"
            assert entry["source_sha256"] == extraction.SOURCE_SHA256


CHIBI_HASHES = {
    "chibi-eat.webp": "175c47e9267dad1023d230ef9b21c58ef9592b42bd83a8e7ef737d4d8aafc815",
    "chibi-neutral.webp": "4197b84f4d298a5ea02d22c4a92a503ffa0528e62c0bba6c563e481cbe7b8047",
    "scene-chibi-eat.webp": "6a99687aaa23703eea5af042926e2a81f9d0ca796d97b53420fe2bf7dc80d596",
    "scene-chibi-neutral.webp": "5eb7787600304e4b2e595c65ca07c9d8381368ac3f6768617d67f16271c1542e"
}

