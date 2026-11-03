from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops, ImageDraw

from tools import prepare_interaction_preview as preparation

ROOT = Path(__file__).resolve().parents[1]
ART = ROOT / "frontend/preview-assets/art/interaction-v030"
MANIFEST = json.loads((ART / "manifest.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", list(MANIFEST["variants"]))
def test_only_real_reviewed_preview_variants_are_installed(name):
    manifest = json.loads((ART / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["variants"][name]
    path = ART / f"{name}.webp"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]
    with Image.open(path) as image:
        assert image.mode == "RGBA"
        assert image.size == (entry["width"], entry["height"])
        low, high = image.getchannel("A").getextrema()
        assert low == 0 and high >= 250  # The reviewed rice sample has native max alpha 254.
    assert manifest["image_cli_invocations"] == manifest["new_model_calls"] == len(preparation.request_records())
    assert manifest["http_attempt_count"] == "Not independently observed"
    assert entry["foot_anchor"][1] == 1
    assert .3 < entry["foot_anchor"][0] < .7


@pytest.mark.parametrize("name", ["happy", "thinking", "sleepy", "shy", "sad"])
def test_expression_variants_preserve_original_body_and_alpha(name):
    with Image.open(ROOT / "frontend/public/art/scene-portrait.webp") as source:
        original = source.convert("RGBA")
    with Image.open(ART / f"{name}.webp") as source:
        variant = source.convert("RGBA")
    assert variant.size == original.size == (500, 991)
    assert variant.getchannel("A").tobytes() == original.getchannel("A").tobytes()
    outside = Image.new("L", original.size, 255)
    ImageDraw.Draw(outside).rectangle((205, 103, 305, 190), fill=0)
    outside = ImageChops.multiply(outside, original.getchannel("A"))
    for band in ImageChops.difference(original, variant).split():
        assert ImageChops.multiply(band, outside).getbbox() is None


@pytest.mark.parametrize("name", [name for name in ("pet", "accept", "drink", "read", "play", "rest")
                                  if name in MANIFEST["variants"]])
def test_action_cleanup_keeps_visible_rgb_and_near_opaque_white_fabric(name):
    manifest = json.loads((ART / "manifest.json").read_text(encoding="utf-8"))
    entry = manifest["variants"][name]
    with Image.open(ROOT / entry["source"]) as image:
        original = image.convert("RGBA").crop(entry["crop_box"])
    with Image.open(ART / f"{name}.webp") as image:
        variant = image.convert("RGBA")
    assert original.size == variant.size
    visible = variant.getchannel("A").point(lambda value: 255 if value else 0)
    for band in ImageChops.difference(original, variant).split():
        assert ImageChops.multiply(band, visible).getbbox() is None
    opaque = original.getchannel("A").point(lambda value: 255 if value >= 250 else 0)
    assert ImageChops.multiply(ImageChops.difference(original.getchannel("A"), variant.getchannel("A")), opaque).getbbox() is None
    assert entry["no_white_color_keying"]
    assert entry["near_opaque_pixels_changed"] == entry["rgb_pixels_changed"] == 0


def test_review_receipts_bind_installed_new_outputs_and_respect_eight_invocation_cap():
    records = preparation.request_records()
    assert len(records) <= 8
    for row in records:
        if row["id"] not in MANIFEST["variants"]:
            continue
        image, checks, directory = preparation.candidate(row["id"])
        receipt = json.loads((directory / "approved.json").read_text(encoding="utf-8"))
        assert row["status"] == "reviewed"
        assert row["raw_sha256"] == checks["source_sha256"] == receipt["source_sha256"]
        assert receipt["processed_sha256"] == hashlib.sha256(preparation.encoded(image, "PNG")).hexdigest()


def test_metadata_updates_preserve_history_but_cannot_replace_artwork(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "OUT", tmp_path)
    path = tmp_path / "manifest.json"
    preparation.store(path, b"first")
    preparation.store(path, b"second", metadata=True)
    assert path.read_bytes() == b"second"
    assert (tmp_path / "history" / f"manifest-{hashlib.sha256(b'first').hexdigest()}.json").read_bytes() == b"first"
    artwork = tmp_path / "portrait.webp"
    preparation.store(artwork, b"original")
    with pytest.raises(FileExistsError):
        preparation.store(artwork, b"different", metadata=True)
    with pytest.raises(ValueError):
        preparation.store(tmp_path.parent / "outside.json", b"outside")


def test_interaction_release_assets_and_separately_reviewed_q_defaults_match():
    assert not (ROOT / "frontend/public/art/interaction-v030").exists()
    release = ROOT / "views/home/art/interaction-v030"
    assert (release / "manifest.json").read_bytes() == (ART / "manifest.json").read_bytes()
    for name in MANIFEST["variants"]:
        assert (release / f"{name}.webp").read_bytes() == (ART / f"{name}.webp").read_bytes()
    expected = {"scene-chibi-neutral.webp": "ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1",
                "scene-chibi-eat.webp": "ff0cff01c5b2790b6a9d50699411691b58f6b18d86d0e3b4d11f63aa6e6a59a1"}
    for name, sha in expected.items():
        for directory in ("frontend/public/art", "views/home/art"):
            assert hashlib.sha256((ROOT / directory / name).read_bytes()).hexdigest() == sha


def test_partial_manifest_is_honest_and_never_installs_placeholders():
    report = preparation.verify_installed()
    missing = [name for name in preparation.LABELS if name not in MANIFEST["variants"]]
    assert report["pending_illustrations"] == MANIFEST["pending_illustrations"] == missing
    assert report["complete"] is (not missing)
    assert report["installed"] + len(missing) == report["total"] == 12
    assert set(MANIFEST["variants"]) == {p.stem for p in ART.glob("*.webp")}
    assert MANIFEST["status"] == ("playable-preview-partial-artwork" if missing else "playable-preview-complete-artwork")


def test_strict_twelve_illustration_gate_cannot_pass_a_partial_preview():
    result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/prepare_interaction_preview.py"),
                             "--require-complete"], capture_output=True, text=True, encoding="utf-8", check=False)
    report = json.loads(result.stdout)
    assert result.returncode == (1 if MANIFEST["pending_illustrations"] else 0)
    assert report["complete"] is (not MANIFEST["pending_illustrations"])
    assert report["pending_illustrations"] == MANIFEST["pending_illustrations"]


def test_verification_rejects_false_complete_claims(tmp_path, monkeypatch):
    monkeypatch.setattr(preparation, "INSTALL", tmp_path)
    value = json.loads(json.dumps(MANIFEST))
    value["variants"].pop("eat")
    value["pending_illustrations"] = []
    value["status"] = "playable-preview-complete-artwork"
    (tmp_path / "manifest.json").write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="completeness claim"):
        preparation.verify_installed()
