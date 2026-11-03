"""Offline-only tests. Synthetic PNG fixtures are never used as character artwork."""
from __future__ import annotations

import base64
import io
import json
import shutil
import warnings

import httpx
import pytest
from PIL import Image, ImageDraw

from tools import generate_character_assets as art

DUMMY_KEY = "unit-test-credential-not-a-real-api-key"


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(art, "QUALITY", "max")
    monkeypatch.setattr(art, "OUTPUT", art.BASE_OUTPUT)
    source = tmp_path / art.SOURCE / "prompts"
    source.parent.mkdir(parents=True)
    shutil.copytree(art.ROOT / art.SOURCE / "prompts", source)
    return tmp_path


def sample_png(spec, *, transparent=True, edge=False, color=(20, 70, 180, 255)):
    background = (0, 0, 0, 0) if spec.background == "transparent" and transparent else "white"
    image = Image.new("RGBA", spec.size, background)
    draw = ImageDraw.Draw(image)
    width, height = spec.size
    draw.rectangle((0 if edge else width // 4, height // 10,
                    width * 3 // 4, height * 9 // 10), fill=color)
    draw.rectangle((width // 3, height // 2, width * 2 // 3, height * 2 // 3), fill="white")
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


@pytest.fixture(scope="module")
def samples():
    return {spec.name: sample_png(spec) for spec in art.SPECS}


def factory(handler):
    return lambda: httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=False)


def success_handler(workspace, samples, calls):
    def respond(request):
        index = len(calls)
        spec = art.SPECS[index]
        calls.append(request)
        journal = json.loads((workspace / art.OUTPUT / "generation.json").read_text())
        assert journal["attempts"][index]["status"] == "submitted"
        assert len(journal["attempts"]) == index + 1
        payload = json.loads(request.content)
        assert request.method == "POST"
        assert str(request.url) == art.BASE_URL + "/images/generations"
        assert request.headers["Authorization"] == "Bearer " + DUMMY_KEY
        assert payload["model"] == art.MODEL
        assert payload["quality"] == art.QUALITY
        assert payload["n"] == 1
        assert payload["size"] == f"{spec.size[0]}x{spec.size[1]}"
        assert payload["background"] == spec.background
        return httpx.Response(200, json={
            "data": [{"b64_json": base64.b64encode(samples[spec.name]).decode()}],
            "model": art.MODEL, "quality": art.QUALITY, "background": spec.background,
            "usage": {"input_tokens": 10, "output_tokens": 20, "unsafe": DUMMY_KEY},
        }, headers={"x-request-id": "req_unit_test"})
    return respond


def make_generated(workspace, samples):
    calls = []
    journal = art.generate(workspace, DUMMY_KEY,
                           factory(success_handler(workspace, samples, calls)), lambda _: None)
    return journal, calls


def assert_no_credential_files(workspace):
    for path in workspace.rglob("*"):
        if path.is_file():
            assert DUMMY_KEY.encode() not in path.read_bytes(), path


def test_plan_preserves_originals_and_splits_three_views(workspace):
    plan = art.prepare_plan(workspace)
    payloads = art.make_requests(workspace)
    assert plan["maximum_generation_requests"] == 3
    assert plan["automatic_retries"] == 0
    assert art.THREE_VIEWS not in payloads["portrait"]["prompt"]
    assert art.THREE_VIEWS in payloads["reference-sheet"]["prompt"]
    assert "深蓝短裙" in payloads["chibi"]["prompt"]
    assert "小腿中段" in payloads["portrait"]["prompt"]
    for name in ("portrait", "chibi"):
        assert (workspace / art.OUTPUT / f"original-{name}.txt").read_bytes() == (
            workspace / art.SOURCE / "prompts" / f"original-{name}.txt").read_bytes()
    assert art.prepare_plan(workspace) == plan
    assert not (workspace / art.OUTPUT / "generation.json").exists()


def test_default_command_never_calls_network_or_prints_key(workspace, monkeypatch, capsys):
    monkeypatch.setattr(art, "ROOT", workspace)
    monkeypatch.setenv(art.KEY_ENV, DUMMY_KEY)
    monkeypatch.setattr(art, "make_client", lambda: pytest.fail("Network not allowed"))
    assert art.main([]) == 0
    assert DUMMY_KEY not in capsys.readouterr().out
    assert_no_credential_files(workspace)


def test_execute_flag_required_before_secret_input(workspace, monkeypatch, capsys):
    monkeypatch.setattr(art, "ROOT", workspace)
    monkeypatch.setattr(art, "read_temporary_key", lambda: pytest.fail("Must not prompt"))
    assert art.main(["generate", "--temporary-key"]) == 2
    assert "explicit_execute_flag_required" in capsys.readouterr().err


@pytest.mark.parametrize("key", ["", " padded ", "bad\nkey", "\u4e2d\u6587"])
def test_missing_or_invalid_key_never_creates_attempt(workspace, key):
    with pytest.raises(art.ArtworkError, match="dedicated_key_missing_or_invalid"):
        art.generate(workspace, key, lambda: pytest.fail("Network not allowed"))
    assert not (workspace / art.OUTPUT / "generation.json").exists()


def test_generation_exactly_three_and_reentry_does_not_resubmit(workspace, samples):
    journal, calls = make_generated(workspace, samples)
    assert len(calls) == 3
    assert [item["asset"] for item in journal["attempts"]] == [spec.name for spec in art.SPECS]
    assert all(item["status"] == "generated" for item in journal["attempts"])
    assert art.generate(workspace, "", lambda: pytest.fail("Must not resubmit")) == journal
    assert_no_credential_files(workspace)
    assert not (workspace / "frontend/public/art").exists()


@pytest.mark.parametrize("status", [301, 400, 401, 429, 500, 503])
def test_http_failure_stops_after_one_and_never_retries(workspace, status):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(status, json={"error": DUMMY_KEY},
                              headers={"location": "https://example.invalid/collect"})

    with pytest.raises(art.ArtworkError, match=f"http_{status}_no_retry") as error:
        art.generate(workspace, DUMMY_KEY, factory(respond), lambda _: None)
    assert DUMMY_KEY not in str(error.value)
    assert len(calls) == 1
    with pytest.raises(art.ArtworkError, match="previous_attempt_unresolved"):
        art.generate(workspace, DUMMY_KEY, lambda: pytest.fail("Must not retry"))
    assert_no_credential_files(workspace)


def test_timeout_consumes_attempt_and_sanitizes_exception(workspace):
    calls = []

    def respond(request):
        calls.append(request)
        raise httpx.ReadTimeout(DUMMY_KEY, request=request)

    with pytest.raises(art.ArtworkError, match="transport_failure_no_retry") as error:
        art.generate(workspace, DUMMY_KEY, factory(respond), lambda _: None)
    assert DUMMY_KEY not in str(error.value)
    assert len(calls) == 1
    journal = art.load_journal(workspace, art.prepare_plan(workspace))
    assert journal["attempts"][0]["status"] == "failed"
    assert journal["attempts"][0]["transport_kind"] == "ReadTimeout"
    assert "finished_at" in journal["attempts"][0]
    assert_no_credential_files(workspace)


@pytest.mark.parametrize("body", [[], {"data": []}, {"data": [{"url": "https://example.invalid/image"}]},
                                      {"data": [{"b64_json": "not-base64!"}]}])
def test_malformed_response_does_not_download_or_retry(workspace, body):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json=body)

    with pytest.raises(art.ArtworkError):
        art.generate(workspace, DUMMY_KEY, factory(respond), lambda _: None)
    assert len(calls) == 1


def test_model_downgrade_is_rejected_but_received_image_retained(workspace, samples):
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"quality": "high", "model": art.MODEL,
            "data": [{"b64_json": base64.b64encode(samples["portrait"]).decode()}]})

    with pytest.raises(art.ArtworkError, match="provider_reported_different_parameters"):
        art.generate(workspace, DUMMY_KEY, factory(respond), lambda _: None)
    assert len(calls) == 1
    assert (workspace / art.OUTPUT / "portrait.png").read_bytes() == samples["portrait"]
    assert art.load_journal(workspace, art.prepare_plan(workspace))["attempts"][0]["status"] == "rejected"


def test_missing_alpha_retains_rejected_output_and_stops(workspace):
    data = sample_png(art.SPECS[0], transparent=False)
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={"data": [{"b64_json": base64.b64encode(data).decode()}]})

    with pytest.raises(art.ArtworkError, match="genuine_transparency_missing"):
        art.generate(workspace, DUMMY_KEY, factory(respond), lambda _: None)
    assert len(calls) == 1
    assert (workspace / art.OUTPUT / "portrait.png").read_bytes() == data


def test_size_crop_and_empty_image_validation(samples):
    with pytest.raises(art.ArtworkError, match="dimensions"):
        art.validate_png(samples["chibi"], art.SPECS[0])
    with pytest.raises(art.ArtworkError, match="touches_canvas_edge"):
        art.validate_png(sample_png(art.SPECS[0], edge=True), art.SPECS[0])
    empty = io.BytesIO()
    Image.new("RGBA", art.SPECS[0].size).save(empty, "PNG")
    with pytest.raises(art.ArtworkError, match="empty_image"):
        art.validate_png(empty.getvalue(), art.SPECS[0])


def test_workspace_escape_and_existing_lock_are_rejected(workspace):
    with pytest.raises(art.ArtworkError, match="path_outside_workspace"):
        art.safe_path(workspace, "../outside.png")
    with art.workflow_lock(workspace):
        with pytest.raises(art.ArtworkError, match="workflow_locked"):
            art.generate(workspace, DUMMY_KEY, lambda: pytest.fail("Must not send"))


def test_changed_prompts_and_orphaned_outputs_block_generation(workspace, samples):
    art.prepare_plan(workspace)
    (workspace / art.OUTPUT / "portrait.png").write_bytes(samples["portrait"])
    with pytest.raises(art.ArtworkError, match="orphaned_output"):
        art.generate(workspace, DUMMY_KEY, lambda: pytest.fail("Must not send"))
    with (workspace / art.SOURCE / "prompts/original-chibi.txt").open("a", encoding="utf-8") as stream:
        stream.write("Changed prompt")
    with pytest.raises(art.ArtworkError, match="refusing_to_overwrite"):
        art.prepare_plan(workspace)


def test_incomplete_attempt_or_tampered_journal_prevents_resubmission(workspace):
    plan = art.prepare_plan(workspace)
    journal = art.load_journal(workspace, plan)
    journal["attempts"].append({"asset": "portrait", "status": "submitted",
                                 "request_sha256": plan["requests"]["portrait"]})
    path = workspace / art.OUTPUT / "generation.json"
    art.write_state(path, journal)
    with pytest.raises(art.ArtworkError, match="previous_attempt_unresolved"):
        art.generate(workspace, DUMMY_KEY, lambda: pytest.fail("Must not send"))
    journal["attempts"] *= 4
    art.write_state(path, journal)
    with pytest.raises(art.ArtworkError, match="invalid_or_changed_generation_journal"):
        art.generate(workspace, DUMMY_KEY, lambda: pytest.fail("Must not send"))


def test_visual_approval_gate_and_lossless_white_clothing(workspace, samples):
    make_generated(workspace, samples)
    with pytest.raises(art.ArtworkError, match="missing_or_stale_visual_approval"):
        art.prepare_assets(workspace)
    assert not (workspace / "frontend/public/art").exists()
    with pytest.raises(art.ArtworkError, match="explicitly_confirmed"):
        art.record_review(workspace, "portrait", ["framing"], "Synthetic test only")
    for spec in art.SPECS:
        art.record_review(workspace, spec.name, list(art.CHECKS), "Synthetic unit test approval, not artwork")
    old = workspace / "frontend/public/art/portrait.webp"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"legacy asset must remain unchanged")
    manifest = art.prepare_assets(workspace)
    assert manifest["status"] == "visually-approved"
    assert len(manifest["assets"]) == 2
    assert old.read_bytes() == b"legacy asset must remain unchanged"
    assert art.prepare_assets(workspace) == manifest
    for name, metadata in manifest["assets"].items():
        with Image.open(workspace / "frontend/public/art" / name) as sprite:
            assert sprite.format == "WEBP"
            assert sprite.convert("RGBA").getpixel((sprite.width // 2, sprite.height // 2)) == (255, 255, 255, 255)
            assert list(sprite.size) == [metadata["width"], metadata["height"]]
    assert_no_credential_files(workspace)


def test_stale_visual_review_prevents_public_assets(workspace, samples):
    make_generated(workspace, samples)
    for spec in art.SPECS:
        art.record_review(workspace, spec.name, list(art.CHECKS), "Synthetic unit test only")
    review_path = workspace / art.OUTPUT / "chibi.review.json"
    review = json.loads(review_path.read_text())
    review["sha256"] = "0" * 64
    art.write_state(review_path, review)
    with pytest.raises(art.ArtworkError, match="missing_or_stale_visual_approval"):
        art.prepare_assets(workspace)
    assert not (workspace / "frontend/public/art").exists()


def test_response_fields_do_not_persist_arbitrary_provider_strings():
    fields = art.safe_response_fields({"model": DUMMY_KEY, "quality": DUMMY_KEY,
        "usage": {"input_tokens": DUMMY_KEY, "output_tokens": 40, "total_tokens": True}})
    assert DUMMY_KEY not in json.dumps(fields)
    assert fields["usage"] == {"output_tokens": 40}


def test_temporary_key_refuses_echo_fallback(monkeypatch):
    def warning_input(prompt):
        warnings.warn("No secure terminal", art.getpass.GetPassWarning)
        return DUMMY_KEY

    monkeypatch.setattr(art.getpass, "getpass", warning_input)
    with pytest.raises(art.ArtworkError, match="secure_console_input_unavailable"):
        art.read_temporary_key()


@pytest.fixture
def authorized_high(workspace):
    with pytest.raises(art.ArtworkError, match="http_500_no_retry"):
        art.generate(workspace, DUMMY_KEY, factory(lambda _: httpx.Response(500)), lambda _: None)
    old_plan = (workspace / art.BASE_OUTPUT / "plan.json").read_bytes()
    old_record = (workspace / art.BASE_OUTPUT / "generation.json").read_bytes()
    high_requests = {name: art.sha(art.encoded(dict(payload, quality="high")))
                     for name, payload in art.make_requests(workspace).items()}
    authorization = {
        "schema_version": 1, "authorized": True, "requested_quality": "high",
        "requested_model": art.MODEL, "maximum_total_generation_requests": 4,
        "maximum_new_generation_requests": 3, "previous_attempt_count": 1,
        "prior_plan_sha256": art.sha(old_plan),
        "prior_generation_record_sha256": art.sha(old_record), "requests": high_requests,
    }
    art.write_new(workspace / art.HIGH_AUTHORIZATION, art.encoded(authorization))
    return workspace, old_plan, old_record


def test_high_requires_authorization_before_new_requests(workspace):
    with pytest.raises(art.ArtworkError, match="high_revision_authorization_missing"):
        art.configure_revision(workspace, "high")
    assert art.QUALITY == "max"
    assert not (workspace / art.BASE_OUTPUT / "high").exists()


def test_high_three_new_images_plus_one_failed_max_never_exceeds_four(authorized_high, samples):
    root, old_plan, old_record = authorized_high
    art.configure_revision(root, "high")
    plan = art.prepare_plan(root)
    assert plan["prior_generation_requests"] == 1
    assert plan["maximum_total_generation_requests"] == 4
    assert plan["requested_quality"] == "high"
    journal, calls = make_generated(root, samples)
    assert len(calls) + plan["prior_generation_requests"] == 4
    assert art.generate(root, "", lambda: pytest.fail("Must not send again")) == journal
    assert (root / art.BASE_OUTPUT / "plan.json").read_bytes() == old_plan
    assert (root / art.BASE_OUTPUT / "generation.json").read_bytes() == old_record
    for spec in art.SPECS:
        art.record_review(root, spec.name, list(art.CHECKS), "Synthetic unit test only")
    manifest = art.prepare_assets(root)
    assert manifest["requested_quality"] == "high"
    assert (root / art.SOURCE / "history/max-generation.json").read_bytes() == old_record
    assert (root / art.SOURCE / "high-authorization.json").exists()
    assert_no_credential_files(root)


def test_high_failure_still_stops_without_another_automatic_retry(authorized_high):
    root, _, original = authorized_high
    art.configure_revision(root, "high")
    calls = []

    def respond(request):
        calls.append(request)
        return httpx.Response(503)

    with pytest.raises(art.ArtworkError, match="http_503_no_retry"):
        art.generate(root, DUMMY_KEY, factory(respond), lambda _: None)
    with pytest.raises(art.ArtworkError, match="previous_attempt_unresolved"):
        art.generate(root, DUMMY_KEY, lambda: pytest.fail("Must not retry"))
    assert len(calls) == 1
    assert (root / art.BASE_OUTPUT / "generation.json").read_bytes() == original


def test_high_rechecks_history_before_every_run(authorized_high):
    root, _, original = authorized_high
    art.configure_revision(root, "high")
    (root / art.BASE_OUTPUT / "generation.json").write_bytes(original + b" ")
    with pytest.raises(art.ArtworkError, match="history_changed"):
        art.generate(root, DUMMY_KEY, lambda: pytest.fail("Must not send"))


def test_high_rejects_unauthorized_budget_or_prompt_changes(authorized_high):
    root, _, _ = authorized_high
    path = root / art.HIGH_AUTHORIZATION
    authorization = json.loads(path.read_text())
    authorization["maximum_total_generation_requests"] = 5
    art.write_state(path, authorization)
    with pytest.raises(art.ArtworkError, match="authorization_missing_or_history_changed"):
        art.configure_revision(root, "high")
    authorization["maximum_total_generation_requests"] = 4
    authorization["requests"]["portrait"] = "0" * 64
    art.write_state(path, authorization)
    art.configure_revision(root, "high")
    with pytest.raises(art.ArtworkError, match="requests_differ_from_authorization"):
        art.generate(root, DUMMY_KEY, lambda: pytest.fail("Must not send"))


def test_status_is_read_only_and_available_during_generation(workspace, monkeypatch, capsys):
    art.prepare_plan(workspace)
    monkeypatch.setattr(art, "ROOT", workspace)
    before = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    with art.workflow_lock(workspace):
        assert art.main(["status"]) == 0
    after = {p.relative_to(workspace): p.read_bytes() for p in workspace.rglob("*") if p.is_file()}
    assert before == after
    assert '"network_requests_this_run": 0' in capsys.readouterr().out
