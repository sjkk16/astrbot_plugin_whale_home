import base64
import json
import sqlite3
from pathlib import Path
from uuid import uuid4

import pytest

from whale_home.api import HomeAPI
from whale_home.migration import load_state
from whale_home.models import Action, InteractRequest, SceneInteractRequest, SettingsRequest
from whale_home.rules import HomeError, apply_action
from whale_home.runtime import HomeRuntime
from whale_home.store import Store

from .conftest import Clock, Gateway, configure, request
from .test_home import image_bytes


def legacy_state():
    return json.loads((Path(__file__).parent / "fixtures/v1-home.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("spot,action,location", [
    ("bookshelf", "read", "desk"), ("desk", "play", "desk"),
    ("window", "move", "window"), ("bed", "rest", "bedside"),
])
async def test_scene_interaction_is_real_and_model_free(runtime, spot, action, location):
    req = request(runtime, SceneInteractRequest, spot_id=spot, action=action)
    before = [i.model_dump() for i in runtime.state.instances]
    result = await HomeAPI(runtime).post("scene/interact", req.model_dump(mode="json"))
    assert result["home"]["character"]["location"] == location
    assert result["home"]["character"]["activity"] == action
    assert result["events"][0]["details"]["spot_id"] == spot
    assert result["memories"][0]["source"] == "event"
    assert result["messages"][-1]["source"] == "interaction"
    assert before == [i.model_dump() for i in runtime.state.instances]
    assert not runtime.gateway.calls
    assert result["usage"]["chat"] == result["usage"]["autonomy"] == 0
    await runtime.mutate("scene/interact", req)
    assert len(await runtime.store.rows("events")) == 1


@pytest.mark.parametrize("body", [
    {"spot_id": "outside", "action": "move"},
    {"spot_id": "bed", "action": "read"},
    {"spot_id": "desk", "action": "eat"},
    {"spot_id": "window", "action": "move", "position": {"x": 1, "y": 1}},
])
async def test_bad_scene_requests_do_not_write(runtime, body):
    before = runtime.state.model_dump_json()
    with pytest.raises(HomeError):
        await HomeAPI(runtime).post("scene/interact", {
            "request_id": str(uuid4()), "expected_version": runtime.state.version, **body,
        })
    assert runtime.state.model_dump_json() == before
    assert await runtime.store.rows("events") == []


async def test_layout_endpoint_rejects_even_empty_body(runtime):
    with pytest.raises(HomeError, match="不支持自由布置"):
        await HomeAPI(runtime).post("layout", {})


async def test_foreground_path_and_scene_model_contract(runtime):
    apply_action(runtime.state, Action(type="read", spot_id="bookshelf"))
    apply_action(runtime.state, Action(type="rest", spot_id="bed"))
    assert runtime.state.character.last_path == ["desk", "window", "bedside"]
    await configure(runtime)
    runtime.gateway.response = '{"speech":"一起读书吧","action":{"type":"read","spot_id":"bookshelf"}}'
    from whale_home.models import ChatRequest
    await runtime.turn(request(runtime, ChatRequest, message="一起读书"))
    world = json.loads(runtime.gateway.calls[0][2])
    assert len(world["available_spots"]) == 4
    assert "room_items" not in world and "room_size" not in world
    assert all("position" not in item for item in world["inventory"])
    assert runtime.state.character.activity == "read"


async def test_inventory_gift_and_exhaustion(runtime):
    await runtime.mutate("interact", request(runtime, InteractRequest,
                                             instance_id="initial-plant", mode="gift"))
    assert "礼物" in (await runtime.store.rows("events"))[0]["text"]
    for _ in range(5):
        await runtime.mutate("interact", request(runtime, InteractRequest,
                                                 instance_id="initial-rice"))
    before = runtime.state.model_dump_json()
    with pytest.raises(HomeError, match="用完"):
        await runtime.mutate("interact", request(runtime, InteractRequest,
                                                 instance_id="initial-rice"))
    assert runtime.state.model_dump_json() == before


async def test_appearance_persists_and_arbitrary_background_change_is_blocked(runtime):
    settings = runtime.state.settings.model_copy(update={"character_style": "chibi"})
    await runtime.mutate("settings", request(runtime, SettingsRequest, settings=settings))
    assert json.loads(await runtime.export_archive())["state"]["settings"]["character_style"] == "chibi"
    settings = settings.model_copy(update={"room_asset": runtime.assets.import_image(image_bytes())})
    with pytest.raises(HomeError, match="不支持更换背景"):
        await runtime.mutate("settings", request(runtime, SettingsRequest, settings=settings))


async def seed_v1(directory):
    store = Store(directory)
    await store.open()
    asset_id = HomeRuntime(directory, Gateway()).assets.import_image(image_bytes())
    old = legacy_state()
    old["settings"].update(provider_id="test-model", autonomous_enabled=True, room_asset=asset_id)
    old["definitions"].append({"id": "custom-kept", "name": "老相册", "category": "book",
                               "usage": "read", "asset_id": asset_id})
    old["instances"].append({"id": "custom-instance", "definition_id": "custom-kept",
                             "position": None, "quantity": 1})
    await store.event("2026-10-30T00:00:00Z", "action", "曾经的日记")
    await store.message("2026-10-30T00:00:00Z", "user", "chat", "以前的聊天")
    await store.memory("2026-10-30T00:00:00Z", "user", "喜欢月光")
    await store.db.execute("INSERT INTO calls(day,mode,created_at,outcome) VALUES(?,?,?,?)",
                           ("2026-10-31", "chat", "2026-10-31T00:00:00Z", "ok"))
    await store.db.execute("INSERT INTO requests VALUES(?,?,?,?,?)",
                           (str(uuid4()), "kept-fingerprint", "done", "", "2026-10-30T00:00:00Z"))
    await store.db.execute("UPDATE home SET payload=? WHERE id=1", (json.dumps(old),))
    await store.db.execute("PRAGMA user_version=1")
    await store.db.commit()
    await store.close()
    return old


async def test_v1_database_upgrade_backup_and_restart_are_lossless(tmp_path):
    old = await seed_v1(tmp_path)
    runtime = HomeRuntime(tmp_path, Gateway(), Clock())
    await runtime.start(background=False)
    try:
        state = runtime.state
        assert state.schema_version == 2 and state.character.location == "window"
        assert state.settings.provider_id == "test-model"
        assert not state.settings.autonomous_enabled
        assert state.settings.room_asset == old["settings"]["room_asset"]
        assert state.settings.character_style == "portrait"
        assert all(i.position is None for i in state.instances)
        assert [i.quantity for i in state.instances] == [i["quantity"] for i in old["instances"]]
        assert state.definitions[-1].name == "老相册"
        assert (await runtime.store.rows("messages"))[0]["text"] == "以前的聊天"
        assert (await runtime.store.rows("memories"))[0]["text"] == "喜欢月光"
        assert any(e["text"] == "曾经的日记" for e in await runtime.store.rows("events"))
        assert (await runtime.snapshot())["usage"]["chat"] == 1
        backup, = list((tmp_path / "backups").glob("before-v2-*.sqlite3"))
        with sqlite3.connect(backup) as db:
            assert db.execute("PRAGMA user_version").fetchone()[0] == 1
            assert json.loads(db.execute("SELECT payload FROM home").fetchone()[0]) == old
        archive = json.loads(await runtime.export_archive())
        assert old["settings"]["room_asset"] in archive["assets"]
        saved = state.model_dump_json()
    finally:
        await runtime.close()
    await runtime.start(background=False)
    try:
        assert runtime.state.model_dump_json() == saved
        assert len(list((tmp_path / "backups").glob("before-v2-*.sqlite3"))) == 1
        cursor = await runtime.store.db.execute("SELECT fingerprint FROM requests")
        assert (await cursor.fetchone())["fingerprint"] == "kept-fingerprint"
    finally:
        await runtime.close()


async def test_failed_migration_rolls_back_database_and_keeps_backup(tmp_path, monkeypatch):
    old = await seed_v1(tmp_path)
    async def fail_save(self, state):
        raise RuntimeError("injected migration failure")
    monkeypatch.setattr(Store, "save", fail_save)
    with pytest.raises(RuntimeError, match="injected"):
        await Store(tmp_path).open()
    with sqlite3.connect(tmp_path / "home.sqlite3") as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert json.loads(db.execute("SELECT payload FROM home").fetchone()[0]) == old
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
    assert list((tmp_path / "backups").glob("before-v2-*.sqlite3"))


async def test_v1_archive_migrates_images_inventory_and_history(runtime):
    old = legacy_state()
    asset_id = runtime.assets.import_image(image_bytes())
    old["settings"]["room_asset"] = asset_id
    archive = {"format": "whale-home", "schema_version": 1, "exported_at": runtime.now(),
               "state": old, "events": [], "messages": [], "memories": [],
               "assets": {asset_id: base64.b64encode(runtime.assets.read(asset_id)).decode()}}
    await runtime.import_archive(json.dumps(archive).encode())
    assert runtime.state.schema_version == 2
    assert all(i.position is None for i in runtime.state.instances)
    assert runtime.state.settings.room_asset == asset_id
    assert not runtime.state.settings.autonomous_enabled
    assert json.loads(await runtime.export_archive())["schema_version"] == 2


@pytest.mark.parametrize("malformed", [[], None, 3, {"schema_version": 2, "state": []},
                                       {"schema_version": 2, "state": {"schema_version": 1}}])
async def test_malformed_archive_root_is_rejected_without_writes(runtime, malformed):
    before = runtime.state.model_dump_json()
    with pytest.raises(HomeError, match="存档格式"):
        await runtime.import_archive(json.dumps(malformed).encode())
    assert runtime.state.model_dump_json() == before


@pytest.mark.parametrize("kind", ["bounds", "overlap", "definition", "future", "path"])
def test_legacy_validation_happens_before_discarding_layout(kind):
    data = legacy_state()
    if kind == "bounds":
        data["instances"][0]["position"] = {"x": 15, "y": 9}
    elif kind == "overlap":
        data["instances"][1]["position"] = data["instances"][0]["position"]
    elif kind == "definition":
        data["definitions"][0]["name"] = "tampered"
    elif kind == "future":
        data["schema_version"] = 3
    else:
        data["character"]["position"] = {"x": 1, "y": 1}
    with pytest.raises((ValueError, HomeError)):
        load_state(data)
