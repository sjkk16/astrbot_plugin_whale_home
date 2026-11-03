import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from whale_home.models import SettingsRequest
from whale_home.runtime import HomeRuntime


class Clock:
    def __init__(self):
        self.time = datetime(2026, 10, 31, 8, tzinfo=timezone.utc)

    def __call__(self):
        return self.time

    def advance(self, **kwargs):
        self.time += timedelta(**kwargs)


class Gateway:
    def __init__(self):
        self.calls = []
        self.response = json.dumps({
            "speech": "我在看窗外。", "emotion": "happy", "action": {"type": "idle"}
        })
        self.error = None
        self.wait = None
        self.started = None

    async def providers(self):
        return [{"id": "test-model", "name": "Test model"}]

    async def generate(self, provider_id, system_prompt, prompt):
        self.calls.append((provider_id, system_prompt, prompt))
        if self.started:
            self.started.set()
        if self.wait:
            await self.wait.wait()
        if self.error:
            raise self.error
        return self.response


def request(runtime, cls, **kwargs):
    return cls(request_id=uuid4(), expected_version=runtime.state.version, **kwargs)


async def configure(runtime, **kwargs):
    settings = runtime.state.settings.model_copy(update={"provider_id": "test-model", **kwargs})
    return await runtime.mutate("settings", request(runtime, SettingsRequest, settings=settings))


@pytest.fixture
async def runtime(tmp_path):
    result = HomeRuntime(tmp_path, Gateway(), Clock())
    await result.start(background=False)
    yield result
    await result.close()

