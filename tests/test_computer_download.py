from __future__ import annotations

import asyncio
import json
import os
import sys
from uuid import uuid4

import pytest
from pydantic import ValidationError

from whale_home import computer_download as module
from whale_home.computer_download import ChromiumDownload, clean_output
from whale_home.computer_models import BrowserAction
from whale_home.errors import HomeError


@pytest.fixture
def installer(tmp_path):
    notices = []
    checks = []

    async def prepare():
        pass

    async def verify():
        checks.append(True)
        return {"download_available": True, "ready": len(checks) > 1}

    result = ChromiumDownload(tmp_path / "computer", lambda: notices.append(True), verify, prepare)
    result.checks = checks
    return result


class Process:
    def __init__(self, code=0, hold=False):
        self.stdout = asyncio.StreamReader()
        self.stdout.feed_data(b"Downloading Chromium 50%\rInstalling...\n")
        if not hold:
            self.stdout.feed_eof()
        self.returncode = None
        self.code = code
        self.pid = 99999999

    async def wait(self):
        self.returncode = self.code
        return self.code

    def kill(self):
        self.returncode = -1
        self.stdout.feed_eof()


def patch_spawn(monkeypatch, installer, *, code=0, hold=False):
    calls = []
    process = Process(code, hold)

    async def spawn(*args, **kwargs):
        calls.append((args, kwargs))
        return process

    async def kill():
        process.kill()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(installer, "kill", kill)
    return calls, process


async def test_requires_human_confirmation_and_not_model_action(installer):
    for value in (None, False, "true", 1):
        with pytest.raises(HomeError):
            await installer.start(confirmed=value)
    assert installer.task is None
    with pytest.raises(ValidationError):
        BrowserAction(action="download")


async def test_fixed_command_private_destination_no_global_env_mutation(installer, monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_DOWNLOAD_HOST", "https://untrusted.invalid")
    monkeypatch.setenv("NODE_OPTIONS", "--require arbitrary.js")
    before = dict(os.environ)
    calls, _ = patch_spawn(monkeypatch, installer)
    await installer.start(confirmed=True)
    await installer.task
    assert installer.state["status"] == "completed" and len(installer.checks) == 2
    args, kwargs = calls[0]
    assert args == (sys.executable, "-m", "playwright", "install", "chromium")
    assert kwargs["env"]["PLAYWRIGHT_BROWSERS_PATH"] == str(installer.browsers)
    assert "PLAYWRIGHT_DOWNLOAD_HOST" not in kwargs["env"] and "NODE_OPTIONS" not in kwargs["env"]
    assert "shell" not in kwargs and dict(os.environ) == before
    assert kwargs.get("creationflags", kwargs.get("start_new_session"))


@pytest.mark.parametrize("code,ready", [(1, True), (0, False)])
async def test_download_or_launch_failure_is_not_success(installer, monkeypatch, code, ready):
    patch_spawn(monkeypatch, installer, code=code)

    async def verify():
        return {"download_available": True, "ready": ready, "reason": "launch denied"}

    installer.verify = verify
    await installer.start(confirmed=True)
    await installer.task
    assert installer.state["status"] == "failed"


async def test_missing_python_dependency_no_install_process(installer, monkeypatch):
    calls, _ = patch_spawn(monkeypatch, installer)

    async def verify():
        return {"download_available": False, "reason": "Playwright missing"}

    installer.verify = verify
    await installer.start(confirmed=True)
    await installer.task
    assert calls == [] and installer.state["status"] == "failed"


async def test_duplicate_cancel_old_id_and_retry(installer, monkeypatch):
    calls, _ = patch_spawn(monkeypatch, installer, hold=True)
    await installer.start(confirmed=True)
    while not calls:
        await asyncio.sleep(0)
    with pytest.raises(HomeError):
        await installer.start(confirmed=True)
    with pytest.raises(HomeError):
        await installer.cancel("old-id")
    await installer.cancel(installer.state["id"])
    await installer.cancel(installer.state["id"])
    await installer.task
    assert installer.state["status"] == "cancelled" and len(calls) == 1
    patch_spawn(monkeypatch, installer)
    await installer.start(confirmed=True)
    await installer.task
    assert installer.state["status"] == "completed"


async def test_immediate_cancel_and_close(installer, monkeypatch):
    patch_spawn(monkeypatch, installer, hold=True)
    await installer.start(confirmed=True)
    await installer.close()
    assert installer.task.done() and not installer.active


async def test_timeout_kills_no_replay(installer, monkeypatch):
    calls, process = patch_spawn(monkeypatch, installer, hold=True)
    monkeypatch.setattr(module, "TIMEOUT_SECONDS", 0.01)
    await installer.start(confirmed=True)
    await installer.task
    assert installer.state["status"] == "failed" and process.returncode == -1
    assert len(calls) == 1


async def test_cancel_during_spawn_reaps_process(installer, monkeypatch):
    entered = asyncio.Event()
    release = asyncio.Event()
    process = Process(hold=True)

    async def spawn(*args, **kwargs):
        entered.set()
        await release.wait()
        return process

    async def kill():
        process.kill()

    monkeypatch.setattr(module.asyncio, "create_subprocess_exec", spawn)
    monkeypatch.setattr(installer, "kill", kill)
    await installer.start(confirmed=True)
    await entered.wait()
    await installer.cancel(installer.state["id"])
    release.set()
    await installer.task
    assert process.returncode == -1 and installer.state["status"] == "cancelled"


def test_restart_marks_interrupted_never_resumes(installer):
    installer.update(id="previous", status="downloading", progress=20)
    new = ChromiumDownload(installer.directory, lambda: None, None, None)
    new.load()
    assert new.state["status"] == "interrupted" and new.task is None
    assert new.state["version"] > 1


async def test_logs_bounded_and_redacted(installer, monkeypatch):
    _, process = patch_spawn(monkeypatch, installer, hold=True)
    process.stdout.feed_data(
        ("\x1b[31mhttps://user:password@host/file?token=secret 70%\r" * 100).encode()
    )
    process.stdout.feed_eof()
    await installer.start(confirmed=True)
    await installer.task
    text = json.dumps(installer.state)
    assert "password" not in text and "secret" not in text and len(installer.state["lines"]) <= 15
    assert len(clean_output("x" * 10000)) == 350


async def test_api_download_idempotency_progress_not_world_version(runtime, monkeypatch):
    c = runtime.computer
    calls, _ = patch_spawn(monkeypatch, c.download, hold=True)

    async def prepare():
        pass

    async def verify():
        return {"download_available": True, "ready": False}

    c.download.prepare, c.download.verify = prepare, verify
    before = runtime.state.world_version
    payload = {"request_id": str(uuid4()), "confirm_download": True}
    first = await c.post("download", payload)
    second = await c.post("download", payload)
    assert first["download"]["id"] == second["download"]["id"]
    while not calls:
        await asyncio.sleep(0)
    assert len(calls) == 1 and runtime.state.world_version == before
    for endpoint in ("start", "takeover", "manual", "resume", "clear-browser"):
        with pytest.raises(HomeError) as error:
            await c.post(endpoint, {"request_id": str(uuid4()), "expected_version": c.version})
        assert error.value.code == "download_busy"
    with pytest.raises(HomeError):
        await c.start("AI cannot bypass", "autonomy")
    await c.post(
        "cancel-download", {"request_id": str(uuid4()), "download_id": first["download"]["id"]}
    )
    await c.download.task
    assert c.download.state["status"] == "cancelled"


@pytest.mark.parametrize(
    "extra", [{"command": "shell"}, {"url": "http://127.0.0.1"}, {"path": "C:/"}]
)
async def test_api_rejects_arbitrary_download_parameters(runtime, extra):
    c = runtime.computer
    with pytest.raises(HomeError):
        await c.post("download", {"request_id": str(uuid4()), "confirm_download": True, **extra})
    assert c.download.task is None


async def test_active_browser_must_be_stopped(runtime):
    c = runtime.computer
    c.current = c.new_task("manual", "manual")
    c.current["status"] = "paused"
    with pytest.raises(HomeError) as error:
        await c.post("download", {"request_id": str(uuid4()), "confirm_download": True})
    assert error.value.code == "computer_busy" and c.download.task is None
    c.current = None


async def test_state_reads_and_environment_checks_never_install(runtime, monkeypatch):
    c = runtime.computer
    calls, _ = patch_spawn(monkeypatch, c.download)

    class Browser:
        async def call(self, op, **kwargs):
            assert op == "environment"
            return {"ready": False, "download_available": True}

        async def close(self):
            pass

    c.browser = Browser()
    await c.get("state")
    await c.get("environment")
    assert c.download.task is None and calls == []


async def test_write_failure_keeps_terminal_state(installer, monkeypatch):
    from pathlib import Path

    patch_spawn(monkeypatch, installer, code=1)

    def failure(*args, **kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", failure)
    await installer.start(confirmed=True)
    await installer.task
    assert installer.state["status"] == "failed" and not installer.active
    assert installer.state["persistence_error"]
