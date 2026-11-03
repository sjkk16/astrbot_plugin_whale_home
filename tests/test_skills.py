from __future__ import annotations

import asyncio
import json
from uuid import uuid4

import pytest

from tests.conftest import Clock, configure, request
from tests.test_companion import finish, heartbeat, idle, preferences, touch
from whale_home.api import HomeAPI
from whale_home.errors import HomeError
from whale_home.models import ChatRequest, Mutation, SkillPreferences, SkillPreferencesRequest
from whale_home.runtime import HomeRuntime


class SkillGateway:
    def __init__(self):
        self.entries = [dict(name="lookup", kind="tool", source="fixture"),
                        dict(name="write", kind="tool", source="fixture"),
                        dict(name="guide", kind="skill", source="fixture")]
        self.steps = [("tool", "lookup")]
        self.performed = []
        self.generated = []
        self.started = asyncio.Event()
        self.release = None
        self.failure = None

    async def providers(self):
        return [{"id": "test-model", "name": "Offline fixture"}]

    async def capabilities(self):
        return self.entries

    async def generate(self, provider_id, system, prompt, *, execution=None):
        self.generated.append((system, execution))
        if execution:
            for kind, name in self.steps:
                async def operation():
                    self.performed.append(name)
                    self.started.set()
                    if self.release:
                        await self.release.wait()
                    if self.failure:
                        raise self.failure
                    return "SECRET tool output is never audited"
                await execution.invoke(kind, name, operation)
        world = json.loads(prompt)
        result = {"speech": "已完成本地演示。", "emotion": "happy"}
        if world["trigger"] in ("conversation", "autonomous_life"):
            result["action"] = {"type": "idle"}
        return json.dumps(result, ensure_ascii=False)


@pytest.fixture
async def skill_home(tmp_path):
    home = HomeRuntime(tmp_path, SkillGateway(), Clock())
    await home.start(background=False)
    await configure(home)
    yield home
    await home.close()


async def save(home, **values):
    prefs = home.skills.preferences.model_dump()
    prefs.update(values)
    return await home.skills.save_preferences(request(home, SkillPreferencesRequest,
        preferences=SkillPreferences(**prefs), confirm_full_access=True))


async def chat(home):
    return await home.turn(request(home, ChatRequest, message="请使用技能"))


async def test_default_empty_allowlist_keeps_plain_generation(skill_home):
    state = await chat(skill_home)
    assert state["skills"]["preferences"] == {"enabled": True, "access_mode": "restricted",
                                              "allowed_tools": [], "allowed_skills": []}
    assert skill_home.gateway.performed == []
    assert skill_home.gateway.generated[0][1] is None
    assert not state["skills"]["calls"]


async def test_full_access_requires_explicit_transition_confirmation(skill_home):
    req = request(skill_home, SkillPreferencesRequest,
                  preferences=SkillPreferences(access_mode="full"))
    with pytest.raises(HomeError, match="确认"):
        await skill_home.skills.save_preferences(req)
    assert skill_home.skills.preferences.access_mode == "restricted"
    await save(skill_home, access_mode="full")
    await chat(skill_home)
    assert skill_home.gateway.performed == ["lookup"]
    await save(skill_home, enabled=False)
    with pytest.raises(HomeError, match="确认"):
        await skill_home.skills.save_preferences(request(skill_home, SkillPreferencesRequest,
            preferences=SkillPreferences(access_mode="full")))


async def test_skill_does_not_grant_dependent_tools(skill_home):
    await save(skill_home, allowed_skills=["guide"])
    skill_home.gateway.steps = [("skill", "guide"), ("tool", "write")]
    with pytest.raises(HomeError):
        await chat(skill_home)
    assert skill_home.gateway.performed == ["guide"]
    rows = await skill_home.store.rows("skill_calls")
    assert [row["status"] for row in rows] == ["denied", "succeeded"]


async def test_host_activation_rechecked_for_every_tool(skill_home):
    await save(skill_home, access_mode="full")
    skill_home.gateway.release = asyncio.Event()
    skill_home.gateway.steps = [("tool", "lookup"), ("tool", "write")]
    task = asyncio.create_task(chat(skill_home))
    await skill_home.gateway.started.wait()
    skill_home.gateway.entries[1]["available"] = False
    skill_home.gateway.release.set()
    with pytest.raises(HomeError):
        await task
    assert skill_home.gateway.performed == ["lookup"]


async def test_no_daily_or_single_turn_tool_quota_and_metadata_only(skill_home):
    await save(skill_home, allowed_tools=["lookup"])
    skill_home.gateway.steps *= 65
    await chat(skill_home)
    assert len(skill_home.gateway.performed) == 65
    rows = await skill_home.store.rows("skill_calls", 100)
    assert len(rows) == 65 and all(row["status"] == "succeeded" for row in rows)
    assert "SECRET" not in json.dumps(rows)
    assert all("arguments" not in row and "output" not in row for row in rows)
    assert "只能通过本轮实际提供" in skill_home.gateway.generated[0][0]


@pytest.mark.parametrize("change", ["stop", "disable", "revoke", "mode"])
async def test_stop_and_revocation_cancel_without_waiting_for_room_lock(skill_home, change):
    await save(skill_home, allowed_tools=["lookup", "write"])
    skill_home.gateway.release = asyncio.Event()
    skill_home.gateway.steps = [("tool", "lookup"), ("tool", "write")]
    task = asyncio.create_task(chat(skill_home))
    await skill_home.gateway.started.wait()
    if change == "stop":
        req = request(skill_home, Mutation)
        await skill_home.skills.stop(req)
        await skill_home.skills.stop(req)
    elif change == "disable":
        await save(skill_home, enabled=False)
    elif change == "revoke":
        await save(skill_home, allowed_tools=[])
    else:
        await save(skill_home, access_mode="full")
    with pytest.raises(HomeError, match="停止"):
        await asyncio.wait_for(task, 2)
    assert skill_home.gateway.performed == ["lookup"]
    assert (await skill_home.store.rows("skill_calls"))[0]["status"] == "unknown"
    assert (await skill_home.snapshot())["skills"]["active"] is None


async def test_timeout_and_failed_request_are_not_replayed(skill_home):
    await save(skill_home, allowed_tools=["lookup"])
    skill_home.model_timeout = .08
    skill_home.gateway.release = asyncio.Event()
    req = request(skill_home, ChatRequest, message="慢查询")
    with pytest.raises(HomeError, match="超时"):
        await skill_home.turn(req)
    with pytest.raises(HomeError):
        await skill_home.turn(req)
    assert skill_home.gateway.performed == ["lookup"]
    assert (await skill_home.store.rows("skill_calls"))[0]["status"] == "unknown"


@pytest.mark.parametrize("failure", [RuntimeError("SECRET-sk-123"), HomeError("SECRET-sk-456")])
async def test_error_details_never_enter_audit_or_public_error(skill_home, failure):
    await save(skill_home, allowed_tools=["lookup"])
    skill_home.gateway.failure = failure
    with pytest.raises(HomeError) as raised:
        await chat(skill_home)
    assert "SECRET" not in str(raised.value)
    state = await skill_home.snapshot()
    assert "SECRET" not in json.dumps(state)
    assert state["skills"]["calls"][0]["status"] == "unknown"


async def test_successful_chat_and_preference_requests_are_idempotent(skill_home):
    req = request(skill_home, SkillPreferencesRequest,
        preferences=SkillPreferences(allowed_tools=["lookup"]))
    await skill_home.skills.save_preferences(req)
    await skill_home.skills.save_preferences(req)
    turn = request(skill_home, ChatRequest, message="查询")
    await skill_home.turn(turn)
    await skill_home.turn(turn)
    assert skill_home.gateway.performed == ["lookup"]


async def test_all_four_model_triggers_and_no_duplicate_consumption(skill_home):
    await save(skill_home, allowed_tools=["lookup"])
    await chat(skill_home)
    await touch(skill_home, kind="item", instance_id="initial-rice")
    await finish(skill_home)
    assert next(item.quantity for item in skill_home.state.instances if item.id == "initial-rice") == 4
    await configure(skill_home, autonomous_enabled=True)
    await skill_home.turn()
    await preferences(skill_home, proactive_enabled=True, idle_minutes=5)
    client = uuid4()
    await heartbeat(skill_home, client, active=True)
    await idle(skill_home, client, minutes=16)
    assert await skill_home.companion.maybe_proactive()
    await finish(skill_home)
    rows = await skill_home.store.rows("skill_calls", 100)
    assert {row["trigger"] for row in rows} == {"chat", "interaction", "autonomy", "proactive"}


async def test_import_resets_permissions_but_preserves_audit(skill_home):
    await save(skill_home, access_mode="full")
    await chat(skill_home)
    archive = await skill_home.export_archive()
    assert "allowed_tools" not in archive.decode()
    await skill_home.import_archive(archive)
    assert skill_home.skills.preferences == SkillPreferences()
    assert len(await skill_home.store.rows("skill_calls")) == 1


async def test_restart_marks_unfinished_calls_unknown(tmp_path):
    home = HomeRuntime(tmp_path, SkillGateway(), Clock())
    await home.start(background=False)
    db = home.store.db
    await db.execute("INSERT INTO skill_calls(run_id,call_key,created_at,name,kind,source,trigger,status) "
                     "VALUES('run','call','now','lookup','tool','fixture','chat','running')")
    await db.commit()
    await home.close()
    restarted = HomeRuntime(tmp_path, SkillGateway(), Clock())
    await restarted.start(background=False)
    try:
        record = (await restarted.store.rows("skill_calls"))[0]
        assert record["status"] == "unknown" and record["error_code"] == "process_interrupted"
        assert restarted.gateway.performed == []
    finally:
        await restarted.close()


async def test_api_catalog_preferences_calls_and_snapshot(skill_home):
    api = HomeAPI(skill_home)
    assert len(await api.get("skills/catalog")) == 3
    assert (await api.get("skills/preferences"))["access_mode"] == "restricted"
    await save(skill_home, allowed_tools=["lookup"])
    await chat(skill_home)
    result = await api.get("skills/calls", {"limit": 1})
    assert len(result["items"]) == 1
    assert (await api.get("skills/calls", {"before": result["items"][0]["id"]}))["items"] == []
    req = request(skill_home, Mutation).model_dump(mode="json")
    assert "skills" in await api.post("skills/stop", req)


async def test_removed_host_capability_can_be_revoked(skill_home):
    await save(skill_home, allowed_tools=["lookup"])
    skill_home.gateway.entries = []
    catalog = await skill_home.skills.catalog()
    assert len(catalog) == 1 and catalog[0].name == "lookup" and not catalog[0].available
    await save(skill_home, allowed_tools=[])
    assert await skill_home.skills.catalog() == []


async def test_close_cancels_inflight_tools_without_replaying(skill_home):
    await save(skill_home, allowed_tools=["lookup"])
    skill_home.gateway.release = asyncio.Event()
    task = asyncio.create_task(chat(skill_home))
    await skill_home.gateway.started.wait()
    directory = skill_home.store.directory
    await skill_home.close()
    with pytest.raises(asyncio.CancelledError):
        await task
    restarted = HomeRuntime(directory, SkillGateway(), Clock())
    await restarted.start(background=False)
    try:
        assert (await restarted.store.rows("skill_calls"))[0]["status"] == "unknown"
        assert restarted.gateway.performed == []
    finally:
        await restarted.close()
