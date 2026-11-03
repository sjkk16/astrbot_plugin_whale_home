from __future__ import annotations

import hashlib
import io
import re
import threading
import warnings
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError

from .rules import HomeError

MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
ASSET_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class Assets:
    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        self.write_lock = threading.Lock()

    def path(self, asset_id: str) -> Path:
        if not ASSET_PATTERN.fullmatch(asset_id):
            raise HomeError("无效的图片编号。")
        return self.directory / f"{asset_id}.webp"

    @staticmethod
    def validate_image(data: bytes) -> None:
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise HomeError("图片需小于 5 MB。")
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(io.BytesIO(data)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"}:
                        raise HomeError("只支持 PNG、JPEG 和 WebP 图片。")
                    if image.width * image.height > 16_000_000:
                        raise HomeError("图片像素过大，请先缩小到 1600 万像素以内。")
                    if getattr(image, "n_frames", 1) != 1:
                        raise HomeError("请使用静态图片。")
                    image.verify()
        except HomeError:
            raise
        except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning):
            raise HomeError("无法读取这张图片。") from None

    def import_image(self, data: bytes) -> str:
        self.validate_image(data)
        with Image.open(io.BytesIO(data)) as source:
            image = ImageOps.exif_transpose(source).convert("RGBA")
            image.thumbnail((2048, 2048), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="WEBP", quality=90, method=4)
        encoded = output.getvalue()
        asset_id = hashlib.sha256(encoded).hexdigest()
        self.persist(asset_id, encoded)
        return asset_id

    def persist(self, asset_id: str, data: bytes) -> None:
        destination = self.path(asset_id)
        with self.write_lock:
            if not destination.exists():
                temporary = destination.with_suffix(f".{uuid4().hex}.tmp")
                try:
                    temporary.write_bytes(data)
                    temporary.replace(destination)
                finally:
                    temporary.unlink(missing_ok=True)

    def validate_archived(self, asset_id: str, data: bytes) -> None:
        self.path(asset_id)
        self.validate_image(data)
        if hashlib.sha256(data).hexdigest() != asset_id:
            raise HomeError("图片摘要不匹配。")
        with Image.open(io.BytesIO(data)) as image:
            if (
                image.format != "WEBP"
                or max(image.size) > 2048
                or any(image.info.get(key) for key in ("exif", "icc_profile", "xmp"))
            ):
                raise HomeError("存档包含未标准化的图片。")

    def read(self, asset_id: str) -> bytes:
        path = self.path(asset_id)
        if not path.is_file():
            raise HomeError("图片文件不存在。", 404)
        return path.read_bytes()

    def validate_reference(self, asset_id: str | None) -> None:
        if asset_id is not None and not self.path(asset_id).is_file():
            raise HomeError("请先上传需要使用的图片。")

