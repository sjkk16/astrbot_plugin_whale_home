"""Inspect release ZIPs and optionally extract source into a new isolated directory."""
from __future__ import annotations

import argparse
import hashlib
import json
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.package_plugin import (  # noqa: E402
    NAME,
    VERSION,
    audit_assets,
    checked_path,
    collect_files,
    digest,
)


def checked_member(info: zipfile.ZipInfo) -> PurePosixPath:
    path = PurePosixPath(info.filename)
    raw = info.orig_filename  # ZipInfo normalizes backslashes on Windows.
    if (path.is_absolute() or ".." in path.parts or "\\" in raw or "\x00" in raw
            or ":" in info.filename or not path.parts or path.parts[0] != NAME
            or info.is_dir() or stat.S_ISLNK(info.external_attr >> 16)):
        raise ValueError(f"Unsafe archive member: {info.filename}")
    return path


def inspect_packages(directory: Path, root: Path = ROOT) -> dict:
    root = root.resolve()
    directory = checked_path(root, directory)
    manifest = audit_assets(root)
    runtime, source = collect_files(root)
    sums = directory / f"SHA256SUMS-v{VERSION}.txt"
    expected_sums = []
    reports = {}
    for suffix, files in (("", runtime), ("-source", source)):
        name = f"{NAME}-v{VERSION}{suffix}.zip"
        file = checked_path(root, directory / name)
        expected = {f"{NAME}/{p.relative_to(root).as_posix()}": p for p in files}
        with zipfile.ZipFile(file) as archive:
            infos = archive.infolist()
            names = [str(checked_member(info)) for info in infos]
            if len(set(names)) != len(names) or set(names) != set(expected):
                raise ValueError(f"Package file list differs from reviewed whitelist: {name}")
            if archive.testzip() is not None:
                raise ValueError(f"ZIP CRC failed: {name}")
            for member in names:
                actual = hashlib.sha256(archive.read(member)).hexdigest()
                if actual != digest(expected[member]):
                    raise ValueError(f"Stale or changed packaged file: {member}")
            for asset in manifest["assets"]:
                data = archive.read(f"{NAME}/{asset['file']}")
                if hashlib.sha256(data).hexdigest() != asset["sha256"]:
                    raise ValueError(f"Packaged asset mismatch: {asset['file']}")
        sha = digest(file)
        expected_sums.append(f"{sha}  {name}\n")
        reports[name] = {"sha256": sha, "bytes": file.stat().st_size, "files": len(expected)}
    if sums.read_text(encoding="ascii") != "".join(expected_sums):
        raise ValueError("SHA-256 file does not match the two verified ZIPs.")
    return {"version": VERSION, "archives": reports, "artwork_count": len(manifest["assets"]),
            "whitelist_verified": True, "zip_crc_verified": True, "checksums_verified": True}


def extract_source(directory: Path, destination: Path, root: Path = ROOT) -> Path:
    root = root.resolve()
    directory = checked_path(root, directory)
    destination = checked_path(root, destination)
    if not destination.resolve().is_relative_to((root / ".local").resolve()):
        raise ValueError("Source test extraction must stay inside .local.")
    if destination.exists():
        raise ValueError("Use a new empty source-test path; existing data is never replaced.")
    source_zip = directory / f"{NAME}-v{VERSION}-source.zip"
    with zipfile.ZipFile(source_zip) as archive:
        infos = archive.infolist()
        paths = [checked_member(info) for info in infos]
        if sum(info.file_size for info in infos) > 256 * 1024 * 1024:
            raise ValueError("Unexpected source archive size.")
        for path in paths:
            checked_path(root, destination.joinpath(*path.parts))
        destination.mkdir(parents=True)
        for info, relative in zip(infos, paths, strict=True):
            path = destination.joinpath(*relative.parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as stream:
                stream.write(archive.read(info))
    return destination / NAME


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=ROOT / "dist")
    parser.add_argument("--extract-source", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    report = inspect_packages(args.directory)
    if args.extract_source:
        report["extracted_source"] = str(extract_source(args.directory, args.extract_source))
    if args.report:
        target = checked_path(ROOT, args.report)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
