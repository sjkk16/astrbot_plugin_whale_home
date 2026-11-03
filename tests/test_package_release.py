from __future__ import annotations

import hashlib
import json
import re
import shutil
import stat
import zipfile
from pathlib import Path

import pytest

from tools import package_plugin as package
from tools.verify_release import checked_member, extract_source


def test_release_versions_and_attribution_are_consistent():
    package.audit_versions()
    assert package.VERSION == "0.4.2"


def test_source_whitelist_includes_all_offline_test_inputs_and_no_local_data():
    runtime, source = package.collect_files()
    runtime_names = {p.relative_to(package.ROOT).as_posix() for p in runtime}
    source_names = {p.relative_to(package.ROOT).as_posix() for p in source}
    assert set(package.SOURCE_FILES) <= source_names
    assert {"RELEASE-V032.md", "RELEASE-V031.md", "SKILLS-PREVIEW.md",
            "whale_home/skills.py", "whale_home/astrbot_skills.py"} <= runtime_names
    assert "tests/fixtures/v1-home.json" in source_names
    assert "output/chibi-v20261102/chibi-front.webp" in source_names
    for required in ("appearance-reference-v1.png", "chibi-character-sheet-v1.png", "deepseek-v1.png"):
        assert f"art-sources/character-v021/reference/{required}" in source_names
    for names in (runtime_names, source_names):
        assert not any(Path(name).parts[0] in {".local", ".runtime", ".venv", "dist", "artifacts"}
                       for name in names)
        assert not any(name.endswith((".db", ".sqlite3", ".log", ".pyc")) for name in names)
        assert not any("authorization" in name or "test-credentials" in name for name in names)
    assert not any(name.startswith(("frontend/", "tests/", "tools/", "art-sources/", "output/"))
                   for name in runtime_names)
    assert {"views/home/index.html", "main.py", "requirements.txt", "asset-manifest.json"} <= runtime_names


@pytest.fixture
def tiny_project(tmp_path, monkeypatch):
    source = tmp_path / "main.py"
    source.write_text("# synthetic packaging fixture\n", encoding="utf-8")
    manifest = {"assets": []}
    (tmp_path / "asset-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(package, "audit_versions", lambda root: None)
    monkeypatch.setattr(package, "audit_assets", lambda root: manifest)
    monkeypatch.setattr(package, "collect_files", lambda root: ([source], [source]))
    return tmp_path


def test_build_is_deterministic_idempotent_and_has_separate_checksum_file(tiny_project):
    root = tiny_project
    output = root / "dist"
    hashes = package.build_packages(output, root)
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    assert package.build_packages(output, root) == hashes
    assert {p.name: p.read_bytes() for p in output.iterdir()} == before
    assert len(before) == 3
    for name, expected in hashes.items():
        assert hashlib.sha256(before[name]).hexdigest() == expected
        with zipfile.ZipFile(output / name) as archive:
            assert archive.namelist() == [f"{package.NAME}/main.py"]
            assert archive.testzip() is None
    checksums = before[f"SHA256SUMS-v{package.VERSION}.txt"].decode("ascii")
    assert all(f"{sha}  {name}\n" in checksums for name, sha in hashes.items())


def test_existing_release_conflict_is_rejected_before_any_new_file(tiny_project):
    output = tiny_project / "dist"
    output.mkdir()
    old = output / f"{package.NAME}-v{package.VERSION}-source.zip"
    old.write_bytes(b"keep-existing-release")
    with pytest.raises(RuntimeError, match="Existing release differs"):
        package.build_packages(output, tiny_project)
    assert list(output.iterdir()) == [old]
    assert old.read_bytes() == b"keep-existing-release"


def test_stale_manifest_prevents_output(tiny_project):
    (tiny_project / "asset-manifest.json").write_text('{"assets": [1]}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="manifest is stale"):
        package.build_packages(tiny_project / "dist", tiny_project)
    assert not (tiny_project / "dist").exists()


def test_output_cannot_escape_workspace(tiny_project):
    with pytest.raises(RuntimeError, match="stay inside"):
        package.build_packages(tiny_project / "../outside", tiny_project)


@pytest.mark.parametrize("name", [".env", "private.sqlite3", "access.log", "test-credentials.json"])
def test_unreviewed_files_inside_packaged_directories_fail_closed(tmp_path, name):
    folder = tmp_path / "tests"
    folder.mkdir()
    (folder / name).write_bytes(b"must-not-be-packaged")
    with pytest.raises(RuntimeError, match="Unreviewed package file"):
        package.files_under("tests", {".py", ".json"}, tmp_path)


def test_caches_are_not_packaged(tmp_path):
    folder = tmp_path / "tests"
    cache = folder / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "test.pyc").write_bytes(b"cache")
    keep = folder / "test_example.py"
    keep.write_bytes(b"# test")
    assert package.files_under("tests", {".py"}, tmp_path) == [keep]


@pytest.mark.parametrize("name", ["/absolute.py", "../outside.py", f"{package.NAME}/../outside.py",
                                  f"{package.NAME}/C:/outside.py", f"{package.NAME}\\outside.py"])
def test_unsafe_zip_members_are_rejected(name):
    with pytest.raises(ValueError, match="Unsafe archive member"):
        checked_member(zipfile.ZipInfo(name))


def test_symlink_zip_members_are_rejected():
    info = zipfile.ZipInfo(f"{package.NAME}/link")
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ValueError, match="Unsafe archive member"):
        checked_member(info)


def test_source_extract_refuses_existing_destination(tiny_project):
    destination = tiny_project / ".local/existing"
    destination.mkdir(parents=True)
    (destination / "keep.txt").write_bytes(b"existing-data")
    with pytest.raises(ValueError, match="existing data is never replaced"):
        extract_source(tiny_project / "dist", destination, tiny_project)
    assert (destination / "keep.txt").read_bytes() == b"existing-data"


def test_release_contains_all_interaction_assets_and_offline_review_inputs():
    runtime, source = package.collect_files()
    runtime_names = {p.relative_to(package.ROOT).as_posix() for p in runtime}
    source_names = {p.relative_to(package.ROOT).as_posix() for p in source}
    assert "views/home/art/interaction-v030/manifest.json" in runtime_names
    for name in package.INTERACTION_NAMES:
        assert f"views/home/art/interaction-v030/{name}.webp" in runtime_names
    assert "output/imagegen/interaction-v030/full-set/completion-requests.json" in source_names
    assert len(package.audit_assets()["assets"]) == 32
    assert not any("output/imagegen/interaction-v030" in name for name in runtime_names)


@pytest.fixture
def interaction_project(tmp_path):
    art = package.ROOT / package.INTERACTION_ART
    manifest = json.loads((art / "manifest.json").read_text(encoding="utf-8"))
    shutil.copytree(art, tmp_path / package.INTERACTION_ART)
    shutil.copytree(art, tmp_path / "views/home/art/interaction-v030")
    for entry in manifest["variants"].values():
        destination = tmp_path / entry["source"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(package.ROOT / entry["source"], destination)
    return tmp_path


def test_release_rejects_partial_interaction_artwork(interaction_project):
    file = interaction_project / package.INTERACTION_ART / "manifest.json"
    manifest = json.loads(file.read_text(encoding="utf-8"))
    manifest["variants"].pop("rest")
    file.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RuntimeError, match="all 12"):
        package.audit_interaction_assets(interaction_project)


@pytest.mark.parametrize("relative", [
    "frontend/preview-assets/art/interaction-v030/rest.webp",
    "output/imagegen/interaction-v030/full-set/raw/rest.png",
    "views/home/art/interaction-v030/rest.webp",
    "views/home/art/interaction-v030/manifest.json",
])
def test_release_rejects_stale_or_tampered_interaction_inputs(interaction_project, relative):
    (interaction_project / relative).write_bytes(b"tampered")
    with pytest.raises(RuntimeError, match="mismatch|out of date"):
        package.audit_interaction_assets(interaction_project)


def test_release_rejects_unreviewed_interaction_file(interaction_project):
    (interaction_project / "views/home/art/interaction-v030/unreviewed.webp").write_bytes(b"no")
    with pytest.raises(RuntimeError, match="out of date"):
        package.audit_interaction_assets(interaction_project)


def test_release_includes_approved_idle_and_reproducible_source_inputs():
    runtime, source = package.collect_files()
    runtime_names = {p.relative_to(package.ROOT).as_posix() for p in runtime}
    source_names = {p.relative_to(package.ROOT).as_posix() for p in source}
    base = "views/home/art/character-motion/portrait/"
    assert {base + "idle-v1.webp", base + "idle-v1.recipe.json"} <= runtime_names
    recipe = json.loads((package.ROOT / (base + "idle-v1.recipe.json")).read_text(encoding="utf-8"))
    for name, sha in {**recipe["source_files"], **recipe["verification_files"]}.items():
        rel = recipe["source_directory"] + "/" + name
        assert rel in source_names
        assert package.digest(package.ROOT / rel) == sha
    assert "art-sources/portrait-animation/source-check.json" in source_names
    assert recipe["source_check"]["path"] in source_names
    assert package.digest(package.ROOT / recipe["source_check"]["path"]) == recipe["source_check"]["sha256"]
    for name in ("open", "half-closed", "closed", "half-open", "inhale", "exhale"):
        assert f"output/portrait-idle-v1/keyframes/{name}.png" in source_names
    assert not any("portrait-idle-v1" in name for name in runtime_names)


def test_source_extract_rejects_oversized_archive(tiny_project):
    output = tiny_project / "dist"
    output.mkdir()
    name = output / f"{package.NAME}-v{package.VERSION}-source.zip"
    with zipfile.ZipFile(name, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        with archive.open(f"{package.NAME}/oversized.bin", "w") as stream:
            for _ in range(257):
                stream.write(b"\0" * (1024 * 1024))
    destination = tiny_project / ".local/oversized"
    with pytest.raises(ValueError, match="Unexpected source archive size"):
        extract_source(output, destination, tiny_project)
    assert not destination.exists()


def test_v042_packages_exclude_browser_binaries_and_obsolete_bundler():
    runtime, source = package.collect_files()
    for path in runtime + source:
        assert path.suffix not in {".exe", ".dll"}
        assert "browser-runtime" not in path.parts and "browsers" not in path.parts
        assert path.name not in {"computer_engine.py", "package_bundled_chromium.py"}
    assert "computer_download.py" in {path.name for path in runtime}


def test_public_manifest_records_confirmation_without_relicensing_third_party_art():
    manifest = package.audit_assets()
    assert manifest["package_audience"] == "public-release"
    assert manifest["distribution_confirmation"] == {
        "date": "2026-11-03", "basis": "user-confirmation", "independently_verified": False,
    }
    confirmed = [a for a in manifest["assets"] if a.get("license") == "LicenseRef-User-Confirmed-Distribution"]
    assert confirmed
    assert all("confirmed by the user" in a["distribution"] for a in confirmed)
    assert any(a.get("license") == "MIT" for a in manifest["assets"])
    assert "USER-CONFIRMED-DISTRIBUTION.txt" in package.REQUIRED_LICENSES


def test_public_packages_do_not_overwrite_historical_personal_archives(tiny_project):
    output = tiny_project / "dist"
    output.mkdir()
    historical = output / f"{package.NAME}-v{package.VERSION}-personal.zip"
    historical.write_bytes(b"historical-personal-archive")
    package.build_packages(output, tiny_project)
    assert historical.read_bytes() == b"historical-personal-archive"
    assert (output / f"{package.NAME}-v{package.VERSION}.zip").exists()


def test_npm_lock_uses_valid_semver_and_official_registry():
    lock = json.loads((package.ROOT / "frontend/package-lock.json").read_text(encoding="utf-8"))
    for entry in lock["packages"].values():
        assert re.fullmatch(r"(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)\.(?:0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?", entry["version"])
        if "resolved" in entry:
            assert entry["resolved"].startswith("https://registry.npmjs.org/")
