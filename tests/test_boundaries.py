import asyncio
import io
import json

import aiosqlite
import pytest
from PIL import Image

from whale_home.api import HomeAPI
from whale_home.assets import Assets
from whale_home.models import (
    AddItemRequest,
    ChatRequest,
    DeleteDefinitionRequest,
    InteractRequest,
    ItemDefinition,
    ItemEditRequest,
)
from whale_home.rules import HomeError
from whale_home.runtime import HomeRuntime

from .conftest import Gateway, configure, request


async def test_custom_definition_deletion_removes_instances_not_history(runtime):
    definition = ItemDefinition(
        id="custom-chair", name="旧日椅子", category="furniture", usage="rest"
    )
    await runtime.mutate("items/edit", request(runtime, ItemEditRequest, definition=definition))
    await runtime.mutate("items/add", request(runtime, AddItemRequest, definition_id=definition.id))
    await runtime.mutate("items/delete-definition", request(
        runtime, DeleteDefinitionRequest, definition_id=definition.id
    ))
    assert not any(item.id == definition.id for item in runtime.state.definitions)
    assert not any(item.definition_id == definition.id for item in runtime.state.instances)
    assert any("旧日椅子" in row["text"] for row in await runtime.store.rows("events"))


async def test_cannot_delete_builtins(runtime):
    with pytest.raises(HomeError, match="自定义"):
        await runtime.mutate("items/delete-definition", request(
            runtime, DeleteDefinitionRequest, definition_id="book"
        ))


async def test_archive_cannot_replace_builtin_definitions(runtime):
    archive = json.loads(await runtime.export_archive())
    archive["state"]["definitions"][0]["name"] = "changed"
    with pytest.raises(HomeError, match="存档格式"):
        await runtime.import_archive(json.dumps(archive).encode())


async def test_initialize_is_idempotent(runtime):
    database = runtime.store.db
    await runtime.start(background=False)
    assert runtime.store.db is database


async def test_future_database_is_rejected_without_downgrading(runtime):
    directory = runtime.store.directory
    await runtime.close()
    async with aiosqlite.connect(directory / "home.sqlite3") as db:
        await db.execute("PRAGMA user_version=9")
        await db.commit()
    other = HomeRuntime(directory, Gateway())
    with pytest.raises(RuntimeError, match="newer"):
        await other.start(background=False)
    assert other.store.db is None
    async with aiosqlite.connect(directory / "home.sqlite3") as db:
        assert (await (await db.execute("PRAGMA user_version")).fetchone())[0] == 9


async def test_inflight_shutdown_does_not_replay_paid_call(runtime):
    await configure(runtime)
    runtime.gateway.started = asyncio.Event()
    runtime.gateway.wait = asyncio.Event()
    req = request(runtime, ChatRequest, message="hi")
    task = asyncio.create_task(runtime.turn(req))
    await runtime.gateway.started.wait()
    directory, clock = runtime.store.directory, runtime.clock
    await runtime.close()
    assert task.cancelled()
    replacement = HomeRuntime(directory, Gateway(), clock)
    await replacement.start(background=False)
    try:
        with pytest.raises(HomeError):
            await replacement.turn(req)
        assert not replacement.gateway.calls
        assert (await replacement.snapshot())["usage"]["chat"] == 1
    finally:
        await replacement.close()


async def test_model_calls_are_serialized(runtime):
    await configure(runtime)
    runtime.gateway.started = asyncio.Event()
    runtime.gateway.wait = asyncio.Event()
    task = asyncio.create_task(runtime.turn(request(runtime, ChatRequest, message="first")))
    await runtime.gateway.started.wait()
    try:
        with pytest.raises(HomeError, match="正在想"):
            await runtime.turn(request(runtime, ChatRequest, message="second"))
    finally:
        runtime.gateway.wait.set()
        await task
    assert len(runtime.gateway.calls) == 1


async def test_identical_experiences_do_not_fill_long_term_memory(runtime):
    await runtime.mutate("interact", request(runtime, InteractRequest, instance_id="initial-book"))
    await runtime.mutate("interact", request(runtime, InteractRequest, instance_id="initial-book"))
    assert len(await runtime.store.rows("events")) == 2
    assert len(await runtime.store.rows("memories")) == 1


async def test_import_keeps_call_counts(runtime):
    await configure(runtime)
    archive = await runtime.export_archive()
    await runtime.turn(request(runtime, ChatRequest, message="hi"))
    assert (await runtime.snapshot())["usage"]["chat"] == 1
    await runtime.import_archive(archive)
    assert (await runtime.snapshot())["usage"]["chat"] == 1


async def test_api_round_trip_and_pagination(runtime):
    api = HomeAPI(runtime)
    assert (await api.get("state"))["home"]["schema_version"] == 2
    assert (await api.get("providers"))[0]["id"] == "test-model"
    req = request(runtime, InteractRequest, instance_id="initial-rice")
    result = await api.post("interact", req.model_dump(mode="json"))
    assert result["home"]["character"]["activity"] == "eat"
    events = await api.get("events/history", {"limit": "1"})
    assert len(events["items"]) == 1
    assert not (await api.get("events/history", {"before": events["items"][0]["id"]}))["items"]


async def test_api_upload_and_restore(runtime):
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (20, 160, 120, 128)).save(buffer, "PNG")
    api = HomeAPI(runtime)
    result = await api.upload("assets/upload", buffer.getvalue())
    assert (await api.get(f"assets/{result['asset_id']}"))["data_url"].startswith("data:image/webp;")
    result = await api.upload("archives/import", await runtime.export_archive())
    assert not result["home"]["settings"]["autonomous_enabled"]


def test_animated_image_rejected(tmp_path):
    buffer = io.BytesIO()
    frames = [Image.new("RGBA", (16, 16), color) for color in ("red", "blue")]
    frames[0].save(buffer, "PNG", save_all=True, append_images=frames[1:], duration=100)
    with pytest.raises(HomeError, match="静态"):
        Assets(tmp_path).import_image(buffer.getvalue())


async def test_parallel_uploads_of_same_image_are_safe(runtime):
    buffer = io.BytesIO()
    Image.new("RGBA", (16, 16), (2, 3, 4, 120)).save(buffer, "PNG")
    ids = await asyncio.gather(*[
        asyncio.to_thread(runtime.assets.import_image, buffer.getvalue()) for _ in range(4)
    ])
    assert len(set(ids)) == 1
    assert runtime.assets.read(ids[0])


async def test_cancellation_during_commit_keeps_state_and_idempotency(runtime, monkeypatch):
    db = runtime.store.db
    original_commit = db.commit
    started, release = asyncio.Event(), asyncio.Event()

    async def delayed_commit():
        await original_commit()
        started.set()
        await release.wait()

    monkeypatch.setattr(db, "commit", delayed_commit)
    req = request(runtime, InteractRequest, instance_id="initial-rice")
    task = asyncio.create_task(runtime.mutate("interact", req))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(db, "commit", original_commit)
    assert next(item.quantity for item in runtime.state.instances if item.id == "initial-rice") == 4
    await runtime.mutate("interact", req)
    assert next(item.quantity for item in runtime.state.instances if item.id == "initial-rice") == 4


async def test_cancellation_after_model_commit_does_not_invent_failure(runtime, monkeypatch):
    await configure(runtime)
    runtime.gateway.response = '{"speech":"好呀","action":{"type":"eat","target_id":"initial-rice"}}'
    db = runtime.store.db
    original_commit = db.commit
    started, release = asyncio.Event(), asyncio.Event()
    commits = 0

    async def delayed_commit():
        nonlocal commits
        commits += 1
        await original_commit()
        if commits == 2:
            started.set()
            await release.wait()

    monkeypatch.setattr(db, "commit", delayed_commit)
    req = request(runtime, ChatRequest, message="吃饭")
    task = asyncio.create_task(runtime.turn(req))
    await started.wait()
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    monkeypatch.setattr(db, "commit", original_commit)
    assert next(item.quantity for item in runtime.state.instances if item.id == "initial-rice") == 4
    assert not any(event["kind"] == "system" for event in await runtime.store.rows("events"))
    await runtime.turn(req)
    assert len(runtime.gateway.calls) == 1

