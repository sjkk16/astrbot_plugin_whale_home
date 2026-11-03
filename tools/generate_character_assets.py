"""Development-only v0.2.1 artwork workflow; offline by default, no automatic retries.

A separate adapter was explicitly approved because the bundled tool cannot express
quality=max. Neither that tool nor the plugin runtime is modified by this adapter.
"""
from __future__ import annotations

import argparse
import base64
import binascii
import getpass
import hashlib
import io
import json
import os
import re
import sys
import warnings
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://fapi.leileihog.top/v1"
MODEL = "gpt-image-2.5-sunburst"
QUALITY = "max"
KEY_ENV = "WHALE_HOME_IMAGE_API_KEY"
MAX_REQUESTS = 3
MAX_RESPONSE_BYTES = 48 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
SOURCE = Path("art-sources/character-v021")
OUTPUT = Path("output/imagegen/character-v021")
BASE_OUTPUT = OUTPUT
HIGH_AUTHORIZATION = BASE_OUTPUT / "high-authorization.json"
CHECKS = ("framing", "identity", "clothing", "background", "feet_or_views")
THREE_VIEWS = (
    "角色设定图统一展示正面、侧面与背面全身视图，并辅以面部、发饰、裙摆和鲸尾细节；"
    "三视图保持同一套服装结构、配色与角色特征。"
)
SPRITE_CONSTRAINTS = (
    "用途：二次元游戏中的单人全身站立立绘，而不是设定图或场景插画。"
    "正面站立，手臂自然放松；画面中只有一个完整角色，没有额外人物或细节小窗。"
    "呆毛、耳鳍、长发、裙摆、鲸尾和两只鞋子均完整可见，四周保留少量透明空隙。"
    "两只鞋底在同一水平线上；鲸尾在身体侧面舒展，但所有尾鳍均高于鞋底。"
    "使用真正的透明背景和透明通道，不画棋盘格、底色、地面、投影或背景光晕。"
    "保留白色蕾丝、围裙和袜子，不将这些白色衣物当作透明区域。"
    "不增加原设定之外的服饰、道具、文字或水印。"
)


class ArtworkError(Exception):
    """Only fixed non-secret error codes may cross the CLI boundary."""

    def __init__(self, code: str, *, transport_kind: str | None = None):
        self.code = code
        self.transport_kind = transport_kind
        super().__init__(code)


@dataclass(frozen=True)
class Spec:
    name: str
    size: tuple[int, int]
    background: str


SPECS = (
    Spec("portrait", (1024, 1536), "transparent"),
    Spec("chibi", (1024, 1024), "transparent"),
    Spec("reference-sheet", (1536, 1024), "opaque"),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


def now() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def safe_path(root: Path, relative: Path | str) -> Path:
    root = root.resolve()
    path = root / relative
    if not path.resolve().is_relative_to(root) or path.resolve() == root:
        raise ArtworkError("path_outside_workspace")
    for part in (path, *path.parents):
        if part == root:
            break
        if part.is_symlink() or part.is_junction():
            raise ArtworkError("linked_artifact_path")
    return path


def write_new(path: Path, data: bytes) -> None:
    if path.exists():
        if path.read_bytes() != data:
            raise ArtworkError("refusing_to_overwrite_existing_artifact")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def write_state(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        with temp.open("xb") as stream:
            stream.write(encoded(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


@contextmanager
def workflow_lock(root: Path):
    path = safe_path(root, BASE_OUTPUT / ".workflow.lock")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = path.open("x", encoding="utf-8")
    except FileExistsError:
        raise ArtworkError("workflow_locked_review_before_removing_stale_lock") from None
    try:
        with stream:
            stream.write(str(os.getpid()))
        yield
    finally:
        path.unlink(missing_ok=True)


def high_authorization(root: Path) -> dict:
    """A new high revision must retain the failed max attempt in its total budget."""
    try:
        authorization = json.loads(safe_path(root, HIGH_AUTHORIZATION).read_text(encoding="utf-8"))
        prior_plan = safe_path(root, BASE_OUTPUT / "plan.json").read_bytes()
        prior_record = safe_path(root, BASE_OUTPUT / "generation.json").read_bytes()
        history = json.loads(prior_record)["attempts"]
        if (authorization["schema_version"] != 1 or authorization["authorized"] is not True
            or authorization["requested_quality"] != "high"
            or authorization["requested_model"] != MODEL
            or authorization["maximum_total_generation_requests"] != 4
            or authorization["maximum_new_generation_requests"] != MAX_REQUESTS
            or authorization["previous_attempt_count"] != 1
            or len(history) != 1 or history[0]["asset"] != "portrait"
            or history[0]["status"] != "failed"
            or authorization["prior_plan_sha256"] != sha(prior_plan)
            or authorization["prior_generation_record_sha256"] != sha(prior_record)):
            raise ValueError
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        raise ArtworkError("high_revision_authorization_missing_or_history_changed") from None
    return authorization


def configure_revision(root: Path, revision: str) -> None:
    # This is a single-run command-line tool, never imported by the plugin runtime.
    global QUALITY, OUTPUT
    if revision == "original":
        QUALITY, OUTPUT = "max", BASE_OUTPUT
    elif revision == "high":
        high_authorization(root)
        QUALITY, OUTPUT = "high", BASE_OUTPUT / "high"
    else:
        raise ArtworkError("unknown_generation_revision")


def make_requests(root: Path) -> dict[str, dict]:
    originals = {
        name: safe_path(root, SOURCE / "prompts" / f"original-{name}.txt")
        .read_text(encoding="utf-8").strip()
        for name in ("portrait", "chibi")
    }
    if originals["portrait"].count(THREE_VIEWS) != 1 or not originals["chibi"]:
        raise ArtworkError("original_prompt_changed_review_required")
    prompts = {
        "portrait": originals["portrait"].replace(THREE_VIEWS, "") + "\n\n" + SPRITE_CONSTRAINTS,
        "chibi": originals["chibi"] + "\n\n" + SPRITE_CONSTRAINTS,
        "reference-sheet": originals["portrait"] + "\n\n" + (
            "用途：横向角色设定图。纯白色不透明背景，三个主要视图为同一位成年角色的"
            "正面、侧面和背面，均完整展示头顶至鞋底，并有面部、发饰、裙摆和鲸尾细节。"
            "三个全身视图等比例排列，服装结构、长裙长度、发色渐变和饰品保持一致。"
            "不增加原设定之外的服饰或道具，不添加文字、标签或水印；不裁切完整视图。"
        ),
    }
    return {
        spec.name: {
            "model": MODEL, "quality": QUALITY, "size": f"{spec.size[0]}x{spec.size[1]}",
            "background": spec.background, "output_format": "png", "n": 1,
            "prompt": prompts[spec.name],
        }
        for spec in SPECS
    }


def prepare_plan(root: Path) -> dict:
    requests = make_requests(root)
    plan = {
        "schema_version": 1, "workflow": "character-v021", "base_url": BASE_URL,
        "endpoint": "/images/generations", "requested_model": MODEL,
        "requested_quality": QUALITY, "maximum_generation_requests": MAX_REQUESTS,
        "automatic_retries": 0, "job_order": [spec.name for spec in SPECS],
        "requests": {name: sha(encoded(payload)) for name, payload in requests.items()},
        "original_prompts": {},
    }
    if QUALITY == "high":
        authorization = high_authorization(root)
        if plan["requests"] != authorization["requests"]:
            raise ArtworkError("high_revision_requests_differ_from_authorization")
        plan.update(revision="high", prior_generation_requests=authorization["previous_attempt_count"],
                    maximum_total_generation_requests=authorization["maximum_total_generation_requests"],
                    authorization_sha256=sha(safe_path(root, HIGH_AUTHORIZATION).read_bytes()))
    for name in ("portrait", "chibi"):
        content = safe_path(root, SOURCE / "prompts" / f"original-{name}.txt").read_bytes()
        plan["original_prompts"][name] = sha(content)
        write_new(safe_path(root, OUTPUT / f"original-{name}.txt"), content)
    for name, payload in requests.items():
        write_new(safe_path(root, OUTPUT / f"{name}.prompt.txt"), (payload["prompt"] + "\n").encode())
        write_new(safe_path(root, OUTPUT / f"{name}.request.json"), encoded(payload))
    write_new(safe_path(root, OUTPUT / "plan.json"), encoded(plan))
    return plan


def load_journal(root: Path, plan: dict) -> dict:
    path = safe_path(root, OUTPUT / "generation.json")
    if not path.exists():
        return {"schema_version": 1, "plan_sha256": sha(encoded(plan)), "attempts": []}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if value["schema_version"] != 1 or value["plan_sha256"] != sha(encoded(plan)):
            raise ValueError
        attempts = value["attempts"]
        if not isinstance(attempts, list) or len(attempts) > MAX_REQUESTS:
            raise ValueError
        for attempt, spec in zip(attempts, SPECS, strict=False):
            if (attempt["asset"] != spec.name
                or attempt["status"] not in {"submitted", "generated", "failed", "rejected"}
                or attempt["request_sha256"] != plan["requests"][spec.name]):
                raise ValueError
    except (ValueError, KeyError, TypeError):
        raise ArtworkError("invalid_or_changed_generation_journal") from None
    return value


def validate_png(content: bytes, spec: Spec) -> dict:
    if not content or len(content) > MAX_IMAGE_BYTES:
        raise ArtworkError("invalid_image_length")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as image:
                if image.format != "PNG" or image.size != spec.size:
                    raise ArtworkError("unexpected_image_format_or_dimensions")
                if getattr(image, "n_frames", 1) != 1:
                    raise ArtworkError("animated_image_not_allowed")
                image.verify()
            with Image.open(io.BytesIO(content)) as source:
                rgba = source.convert("RGBA")
        alpha = rgba.getchannel("A")
        box = alpha.getbbox()
        if not box:
            raise ArtworkError("empty_image")
        if spec.background == "transparent":
            histogram = alpha.histogram()
            if histogram[0] < spec.size[0] * spec.size[1] * .05 or alpha.getextrema()[1] < 200:
                raise ArtworkError("genuine_transparency_missing")
            x0, y0, x1, y1 = box
            if min(x0, y0, spec.size[0] - x1, spec.size[1] - y1) < 8:
                raise ArtworkError("silhouette_touches_canvas_edge")
        else:
            if alpha.getextrema() != (255, 255):
                raise ArtworkError("reference_sheet_must_be_opaque")
            corners = [(0, 0), (spec.size[0] - 1, 0),
                       (0, spec.size[1] - 1), (spec.size[0] - 1, spec.size[1] - 1)]
            if any(min(rgba.getpixel(point)[:3]) < 245 for point in corners):
                raise ArtworkError("reference_sheet_background_not_white")
    except ArtworkError:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError,
            Image.DecompressionBombWarning):
        raise ArtworkError("unreadable_png") from None
    return {"width": spec.size[0], "height": spec.size[1], "alpha_bbox": list(box),
            "sha256": sha(content), "bytes": len(content), "technical_validation": "passed"}


def safe_response_fields(data: dict) -> dict:
    result = {}
    allowed = {"model": {MODEL}, "quality": {"low", "medium", "high", "xhigh", "max", "auto"},
               "background": {"transparent", "opaque", "auto"},
               "output_format": {"png", "jpeg", "webp"}}
    for name, permitted in allowed.items():
        value = data.get(name)
        result[name] = value if isinstance(value, str) and value in permitted else (
            "not_returned" if value is None else "unrecognized"
        )
    usage = data.get("usage")
    if isinstance(usage, dict):
        result["usage"] = {name: usage[name] for name in ("input_tokens", "output_tokens", "total_tokens")
                           if type(usage.get(name)) is int and 0 <= usage[name] <= 1_000_000_000}
    return result


def decode_response(data: dict) -> bytes:
    try:
        items = data["data"]
        if not isinstance(items, list) or len(items) != 1 or not isinstance(items[0], dict):
            raise ValueError
        value = items[0]["b64_json"]
        if not isinstance(value, str) or len(value) > MAX_RESPONSE_BYTES:
            raise ValueError
        return base64.b64decode(value, validate=True)
    except (ValueError, KeyError, TypeError, binascii.Error):
        raise ArtworkError("expected_one_base64_image_no_download_or_retry") from None


def make_client() -> httpx.Client:
    return httpx.Client(
        transport=httpx.HTTPTransport(retries=0, trust_env=False),
        timeout=httpx.Timeout(connect=30, read=600, write=60, pool=30),
        follow_redirects=False, trust_env=False,
    )


def post_once(client: httpx.Client, payload: dict, key: str) -> tuple[dict, str | None]:
    try:
        with client.stream("POST", BASE_URL + "/images/generations", json=payload,
                           headers={"Authorization": "Bearer " + key}) as response:
            if response.status_code != 200:
                raise ArtworkError(f"http_{response.status_code}_no_retry")
            chunks, count = [], 0
            for chunk in response.iter_bytes():
                count += len(chunk)
                if count > MAX_RESPONSE_BYTES:
                    raise ArtworkError("response_too_large_no_retry")
                chunks.append(chunk)
            try:
                data = json.loads(b"".join(chunks))
                if not isinstance(data, dict):
                    raise ValueError
            except (ValueError, UnicodeError):
                raise ArtworkError("invalid_json_no_retry") from None
            request_id = response.headers.get("x-request-id", "")
            if not re.fullmatch(r"req_[A-Za-z0-9_-]{1,100}", request_id) or key in request_id:
                request_id = None
            return data, request_id
    except ArtworkError:
        raise
    except Exception as error:
        # Record only an allowlisted class, never exception bodies or provider headers.
        known = (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.WriteTimeout,
                 httpx.ConnectError, httpx.ReadError, httpx.WriteError,
                 httpx.RemoteProtocolError, httpx.DecodingError)
        kind = next((cls.__name__ for cls in known if isinstance(error, cls)), "OtherTransportError")
        raise ArtworkError("transport_failure_no_retry_request_may_have_been_billed",
                           transport_kind=kind) from None


def verified_existing(root: Path, journal: dict) -> None:
    for attempt, spec in zip(journal["attempts"], SPECS, strict=False):
        if attempt["status"] != "generated":
            raise ArtworkError("previous_attempt_unresolved_no_resubmission")
        path = safe_path(root, OUTPUT / f"{spec.name}.png")
        try:
            metadata = validate_png(path.read_bytes(), spec)
        except FileNotFoundError:
            raise ArtworkError("previous_output_missing_no_resubmission") from None
        if metadata["sha256"] != attempt.get("sha256"):
            raise ArtworkError("previous_output_changed_no_resubmission")


def generate(root: Path, key: str, client_factory=make_client, report=print) -> dict:
    with workflow_lock(root):
        plan = prepare_plan(root)
        journal = load_journal(root, plan)
        verified_existing(root, journal)
        if len(journal["attempts"]) == MAX_REQUESTS:
            return journal
        if not key or key.strip() != key or any(ord(char) < 33 or ord(char) > 126 for char in key):
            raise ArtworkError("dedicated_key_missing_or_invalid")
        for spec in SPECS[len(journal["attempts"]):]:
            if any(safe_path(root, OUTPUT / f"{spec.name}.{extension}").exists()
                   for extension in ("png", "provenance.json")):
                raise ArtworkError("orphaned_output_no_resubmission")
        requests = make_requests(root)
        with client_factory() as client:
            for spec in SPECS[len(journal["attempts"]):]:
                prior_count = plan.get("prior_generation_requests", 0)
                total_limit = plan.get("maximum_total_generation_requests", MAX_REQUESTS)
                if prior_count + len(journal["attempts"]) >= total_limit:
                    raise ArtworkError("authorized_total_request_limit_exhausted")
                attempt = {"asset": spec.name, "status": "submitted", "submitted_at": now(),
                           "request_sha256": plan["requests"][spec.name]}
                journal["attempts"].append(attempt)
                # Count every attempt BEFORE I/O, including requests with ambiguous outcomes.
                write_state(safe_path(root, OUTPUT / "generation.json"), journal)
                overall = prior_count + len(journal["attempts"])
                report(f"Submitting {spec.name}: {overall}/{total_limit} overall; "
                       f"quality={QUALITY}; no retries.")
                try:
                    data, request_id = post_once(client, requests[spec.name], key)
                    content = decode_response(data)
                    if len(content) > MAX_IMAGE_BYTES:
                        raise ArtworkError("decoded_image_too_large")
                    write_new(safe_path(root, OUTPUT / f"{spec.name}.png"), content)
                    returned = safe_response_fields(data)
                    provenance = {
                        "schema_version": 1, "file": f"{spec.name}.png", "sha256": sha(content),
                        "recorded_at": now(), "workflow": "user-approved independent Images API adapter",
                        "base_url": BASE_URL, "endpoint": "/images/generations", "request_id": request_id,
                        "requested_model": MODEL, "requested_quality": QUALITY,
                        "requested_size": requests[spec.name]["size"],
                        "requested_background": spec.background, "requested_image_count": 1,
                        "prompt_file": f"{spec.name}.prompt.txt",
                        "request_sha256": plan["requests"][spec.name], "returned": returned,
                        "underlying_model_independently_verified": False,
                        "automatic_retries": 0, "credential_values_recorded": False,
                        "distribution": "Personal preview only; redistribution rights unverified.",
                    }
                    write_new(safe_path(root, OUTPUT / f"{spec.name}.provenance.json"), encoded(provenance))
                    for field, expected in (("model", MODEL), ("quality", QUALITY),
                                            ("background", spec.background), ("output_format", "png")):
                        if returned[field] not in {expected, "not_returned"}:
                            raise ArtworkError("provider_reported_different_parameters")
                    metadata = validate_png(content, spec)
                    attempt.update(status="generated", sha256=metadata["sha256"], finished_at=now())
                    write_state(safe_path(root, OUTPUT / "generation.json"), journal)
                    report(f"Saved {spec.name}; technical checks passed; visual review still required.")
                except BaseException as error:
                    attempt["error_code"] = (
                        error.code if isinstance(error, ArtworkError)
                        else "interrupted_or_local_failure_no_retry"
                    )
                    attempt["finished_at"] = now()
                    if isinstance(error, ArtworkError) and error.transport_kind:
                        attempt["transport_kind"] = error.transport_kind
                    attempt["status"] = (
                        "rejected" if safe_path(root, OUTPUT / f"{spec.name}.png").exists() else "failed"
                    )
                    write_state(safe_path(root, OUTPUT / "generation.json"), journal)
                    raise ArtworkError(attempt["error_code"]) from None
    return journal


def approved_generation(root: Path) -> tuple[dict, dict]:
    plan = prepare_plan(root)
    journal = load_journal(root, plan)
    verified_existing(root, journal)
    if len(journal["attempts"]) != MAX_REQUESTS:
        raise ArtworkError("all_three_images_required_before_integration")
    return plan, journal


def record_review(root: Path, name: str, checks: list[str], note: str) -> dict:
    if name not in {spec.name for spec in SPECS} or set(checks) != set(CHECKS):
        raise ArtworkError("all_visual_checks_must_be_explicitly_confirmed")
    if not note.strip() or len(note) > 1200 or "sk-" in note.lower():
        raise ArtworkError("invalid_or_credential_like_review_note")
    with workflow_lock(root):
        _, journal = approved_generation(root)
        attempt = next(item for item in journal["attempts"] if item["asset"] == name)
        review = {"schema_version": 1, "asset": name, "sha256": attempt["sha256"],
                  "approved": True, "checked": list(CHECKS), "note": note,
                  "reviewed_at": now()}
        write_state(safe_path(root, OUTPUT / f"{name}.review.json"), review)
        return review


def prepare_assets(root: Path) -> dict:
    with workflow_lock(root):
        plan, journal = approved_generation(root)
        prepared = {}
        sources = {}
        assets = {}
        for spec, attempt in zip(SPECS, journal["attempts"], strict=True):
            try:
                review = json.loads(safe_path(root, OUTPUT / f"{spec.name}.review.json")
                                    .read_text(encoding="utf-8"))
                if (review["approved"] is not True or review["sha256"] != attempt["sha256"]
                    or review["asset"] != spec.name or set(review["checked"]) != set(CHECKS)):
                    raise ValueError
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                raise ArtworkError("missing_or_stale_visual_approval") from None
            for extension in ("png", "prompt.txt", "request.json", "provenance.json", "review.json"):
                name = f"{spec.name}.{extension}"
                prepared[safe_path(root, SOURCE / name)] = safe_path(root, OUTPUT / name).read_bytes()
            raw = prepared[safe_path(root, SOURCE / f"{spec.name}.png")]
            provenance = json.loads(prepared[safe_path(root, SOURCE / f"{spec.name}.provenance.json")])
            if (provenance.get("sha256") != sha(raw)
                or provenance.get("request_sha256") != plan["requests"][spec.name]):
                raise ArtworkError("provenance_mismatch")
            sources[f"{spec.name}.png"] = sha(raw)
            if spec.background != "transparent":
                continue
            with Image.open(io.BytesIO(raw)) as source:
                rgba = source.convert("RGBA")
            box = rgba.getchannel("A").getbbox()
            sprite = rgba.crop(box)
            content = io.BytesIO()
            sprite.save(content, "WEBP", lossless=True, method=6)
            data = content.getvalue()
            if len(data) > 5 * 1024 * 1024:
                raise ArtworkError("derived_sprite_exceeds_upload_limit")
            filename = f"scene-{spec.name}-v021.webp"
            prepared[safe_path(root, Path("frontend/public/art") / filename)] = data
            prepared[safe_path(root, OUTPUT / filename)] = data
            assets[filename] = {
                "sha256": sha(data), "source_file": (SOURCE / f"{spec.name}.png").as_posix(),
                "source_sha256": sha(raw), "width": sprite.width, "height": sprite.height,
                "alpha_bbox": list(box), "modifications": "Alpha-bounds crop; lossless WebP; no resizing.",
                "license": "LicenseRef-Personal-Preview-Unverified",
                "author": "AI-generated from the user's character descriptions; underlying model unverified",
                "distribution": "Personal installation only; redistribution rights unverified.",
            }
        if QUALITY == "high":
            prepared[safe_path(root, SOURCE / "high-authorization.json")] = safe_path(
                root, HIGH_AUTHORIZATION).read_bytes()
            for name in ("plan.json", "generation.json"):
                prepared[safe_path(root, SOURCE / "history" / f"max-{name}")] = safe_path(
                    root, BASE_OUTPUT / name).read_bytes()
        prepared[safe_path(root, SOURCE / "plan.json")] = encoded(plan)
        prepared[safe_path(root, SOURCE / "generation.json")] = encoded(journal)
        manifest = {"schema_version": 1, "version": "0.2.1", "status": "visually-approved",
                    "requested_model": MODEL, "requested_quality": QUALITY,
                    "underlying_model_independently_verified": False,
                    "sources": sources, "assets": assets}
        prepared[safe_path(root, SOURCE / "release.json")] = encoded(manifest)
        # Check every collision before writing anything to frontend/public.
        for path, data in prepared.items():
            if path.exists() and path.read_bytes() != data:
                raise ArtworkError("refusing_to_overwrite_approved_source_or_asset")
        for path, data in prepared.items():
            write_new(path, data)
        return manifest


def read_temporary_key() -> str:
    # Never allow getpass to fall back to echoing the credential on a pipe.
    with warnings.catch_warnings():
        warnings.simplefilter("error", getpass.GetPassWarning)
        try:
            return getpass.getpass("Temporary credential (hidden; memory only): ")
        except (getpass.GetPassWarning, EOFError):
            raise ArtworkError("secure_console_input_unavailable_use_dedicated_environment") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", nargs="?", default="plan",
                        choices=("plan", "status", "generate", "review", "prepare-assets"))
    parser.add_argument("--revision", choices=("original", "high"), default="original",
                        help="High requires the new four-total-request authorization record.")
    parser.add_argument("--execute", action="store_true", help="Explicitly enable paid generation.")
    parser.add_argument("--temporary-key", action="store_true",
                        help="Read a user-authorized temporary key without echoing or saving it.")
    parser.add_argument("--asset", choices=[spec.name for spec in SPECS])
    parser.add_argument("--checked", action="append", choices=CHECKS, default=[])
    parser.add_argument("--note", default="")
    args = parser.parse_args(argv)
    try:
        configure_revision(ROOT, args.revision)
        if args.command == "generate":
            if not args.execute:
                raise ArtworkError("explicit_execute_flag_required")
            key = read_temporary_key() if args.temporary_key else os.environ.get(KEY_ENV, "")
            try:
                journal = generate(ROOT, key, client_factory=make_client)
            finally:
                key = ""
            print(f"Generation attempts recorded: {len(journal['attempts'])}/{MAX_REQUESTS}.")
        elif args.command == "review":
            record_review(ROOT, args.asset, args.checked, args.note)
            print(f"Recorded hash-bound visual approval for {args.asset}.")
        elif args.command == "prepare-assets":
            manifest = prepare_assets(ROOT)
            print(f"Prepared {len(manifest['assets'])} approved sprites; defaults not switched here.")
        elif args.command == "status":
            path = safe_path(ROOT, OUTPUT / "plan.json")
            if not path.exists():
                print(json.dumps({"offline": True, "prepared": False,
                                  "requested_quality": QUALITY, "network_requests_this_run": 0}))
                return 0
            plan = json.loads(path.read_text(encoding="utf-8"))
            journal = load_journal(ROOT, plan)
            print(json.dumps({"offline": True, "requested_quality": QUALITY,
                "attempts": journal["attempts"],
                "overall_attempts": plan.get("prior_generation_requests", 0) + len(journal["attempts"]),
                "authorized_total_limit": plan.get("maximum_total_generation_requests", MAX_REQUESTS),
                "network_requests_this_run": 0}, ensure_ascii=True, indent=2))
        else:
            with workflow_lock(ROOT):
                plan = prepare_plan(ROOT)
                journal = load_journal(ROOT, plan)
            print(json.dumps({
                "offline": True, "requested_model": MODEL, "requested_quality": QUALITY,
                "jobs": [spec.name for spec in SPECS], "attempts": journal["attempts"],
                "key_configured": bool(os.environ.get(KEY_ENV)), "network_requests_this_run": 0,
                "output": str(ROOT / OUTPUT),
                "overall_attempts": plan.get("prior_generation_requests", 0) + len(journal["attempts"]),
                "authorized_total_limit": plan.get("maximum_total_generation_requests", MAX_REQUESTS),
            }, ensure_ascii=True, indent=2))
    except ArtworkError as error:
        print(f"Stopped: {error.code}. No automatic retries or fallback requests.", file=sys.stderr)
        return 2
    except Exception:
        # Do not expose unexpected exception bodies that might contain credentials.
        print("Stopped: local_operation_failed. No automatic retries.", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
