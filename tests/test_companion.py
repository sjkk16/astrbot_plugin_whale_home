from __future__ import annotations

import asyncio
import contextlib
import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from tests.conftest import configure, request
from whale_home.api import HomeAPI
from whale_home.companion import INTERACTION_DAILY_LIMIT
from whale_home.llm import make_prompt, parse_reaction
from whale_home.models import (
    LEGACY_DEFAULT_PERSONA,
    CharacterInteractRequest,
    ChatRequest,
    CompanionPreferences,
    CompanionPreferencesRequest,
    PresenceRequest,
)
from whale_home.rules import HomeError
from whale_home.runtime import HomeRuntime


async def finish(runtime):
    task = runtime.companion.reply_task
    if task:
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await asyncio.sleep(0)


async def touch(runtime, **values):
    return await runtime.companion.interact(request(runtime, CharacterInteractRequest, **values))


async def preferences(runtime, **values):
    current = runtime.companion.local.preferences.model_dump()
    current.update(values)
    return await runtime.companion.preferences(request(
        runtime, CompanionPreferencesRequest, preferences=CompanionPreferences(**current)))


async def heartbeat(runtime, client, active=False, visible=True):
    return await runtime.companion.presence(PresenceRequest(
        client_id=client, visible=visible, active=active))


async def idle(runtime, client, minutes=5):
    # Real tabs renew every 15 seconds. Refreshing after TTL must not fabricate presence.
    for _ in range(minutes * 2):
        runtime.clock.advance(seconds=30)
        await heartbeat(runtime, client)


def quantity(runtime, id_="initial-rice"):
    return next(item.quantity for item in runtime.state.instances if item.id == id_)


async def enable(runtime, **prefs):
    await configure(runtime)
    runtime.gateway.response = json.dumps({"speech": "嗯，聪明脑袋已经接收到信号啦。", "emotion": "happy"})
    await preferences(runtime, **prefs)


async def test_direct_food_is_immediate_idempotent_and_model_free_when_unconfigured(runtime):
    interaction = request(runtime, CharacterInteractRequest, kind="item", instance_id="initial-rice")
    first = await runtime.companion.interact(interaction)
    repeated = await runtime.companion.interact(interaction)
    assert quantity(runtime) == 4
    assert first["home"]["version"] == repeated["home"]["version"]
    assert first["companion"]["presentation"]["pose"] == "eat"
    assert first["companion"]["presentation"]["model_status"] == "local"
    assert len(first["messages"]) == 1
    assert runtime.gateway.calls == []
    assert len(await runtime.store.rows("events", 60)) == 1


@pytest.mark.parametrize("kind,extra", [
    ("pet", {}), ("item", {"instance_id": "initial-plant", "mode": "gift"}),
    ("scene", {"spot_id": "bookshelf"}), ("scene", {"spot_id": "desk"}),
    ("scene", {"spot_id": "window"}), ("scene", {"spot_id": "bed"}),
])
async def test_all_direct_controls_work_without_a_model(runtime, kind, extra):
    result = await touch(runtime, kind=kind, **extra)
    assert result["companion"]["presentation"]["speech"]
    assert result["events"][0]["kind"] == "action"
    assert runtime.gateway.calls == []
    assert quantity(runtime) == 5


async def test_empty_items_and_stale_clicks_do_not_consume(runtime):
    stale = request(runtime, CharacterInteractRequest, kind="item", instance_id="initial-rice")
    await touch(runtime, kind="pet")
    with pytest.raises(HomeError) as error:
        await runtime.companion.interact(stale)
    assert error.value.code == "stale"
    assert quantity(runtime) == 5
    for _ in range(5):
        await touch(runtime, kind="item", instance_id="initial-rice")
    with pytest.raises(HomeError):
        await touch(runtime, kind="item", instance_id="initial-rice")
    assert quantity(runtime) == 0


async def test_successful_model_reaction_never_repeats_an_action(runtime):
    await enable(runtime)
    await touch(runtime, kind="item", instance_id="initial-rice")
    assert quantity(runtime) == 4
    await finish(runtime)
    state = await runtime.snapshot()
    assert quantity(runtime) == 4
    assert len(state["messages"]) == 1
    assert state["messages"][0]["text"] == "嗯，聪明脑袋已经接收到信号啦。"
    assert state["companion"]["presentation"]["model_status"] == "model"
    payload = json.loads(runtime.gateway.calls[0][2])
    assert payload["trigger"] == "direct_interaction"
    assert payload["completed_interaction"]["action"] == "eat"
    assert next(item for item in payload["inventory"] if item["instance_id"] == "initial-rice")["quantity"] == 4


@pytest.mark.parametrize("failure", ["action_injection", "provider_error", "timeout"])
async def test_reaction_failure_keeps_local_action_counts_attempt_and_never_retries(runtime, failure):
    await enable(runtime)
    if failure == "action_injection":
        runtime.gateway.response = json.dumps({"speech": "再吃一碗", "emotion": "happy", "action": {"type": "eat", "target_id": "initial-rice"}})
    elif failure == "provider_error":
        runtime.gateway.error = RuntimeError("secret-provider-token-not-for-users")
    else:
        runtime.model_timeout = .01
        runtime.gateway.wait = asyncio.Event()
    await touch(runtime, kind="item", instance_id="initial-rice")
    await finish(runtime)
    snapshot = await runtime.snapshot()
    assert quantity(runtime) == 4
    assert snapshot["companion"]["presentation"]["model_status"] == "error"
    assert snapshot["usage"]["interaction"] == 1
    assert len(runtime.gateway.calls) == 1
    assert "secret-provider" not in json.dumps(snapshot)
    assert "没有重试" in snapshot["companion"]["notice"]


async def test_interaction_cooldown_and_touch_throttle(runtime):
    await enable(runtime)
    await touch(runtime, kind="pet")
    await finish(runtime)
    with pytest.raises(HomeError) as error:
        await touch(runtime, kind="pet")
    assert error.value.code == "touch_cooldown"
    runtime.clock.advance(seconds=1)
    await touch(runtime, kind="pet")
    await finish(runtime)
    assert len(runtime.gateway.calls) == 1
    runtime.clock.advance(seconds=4)
    await touch(runtime, kind="pet")
    await finish(runtime)
    assert len(runtime.gateway.calls) == 2


async def test_interaction_daily_limit_counts_all_attempts_and_still_allows_local_actions(runtime):
    await enable(runtime)
    await runtime.store.db.executemany("INSERT INTO calls(day,mode,created_at,outcome) VALUES(?,?,?,?)", [
        (runtime.day(), "interaction", runtime.now(), "model_error") for _ in range(INTERACTION_DAILY_LIMIT)
    ])
    await runtime.store.db.commit()
    await touch(runtime, kind="item", instance_id="initial-rice")
    await finish(runtime)
    assert quantity(runtime) == 4
    assert runtime.gateway.calls == []
    runtime.clock.advance(days=1)
    await touch(runtime, kind="item", instance_id="initial-rice")
    await finish(runtime)
    assert len(runtime.gateway.calls) == 1
    assert (await runtime.snapshot())["usage"]["interaction"] == 1


async def test_user_chat_interrupts_pending_reaction_without_a_false_stale_error(runtime):
    await enable(runtime)
    runtime.gateway.wait = asyncio.Event()
    runtime.gateway.started = asyncio.Event()
    await touch(runtime, kind="item", instance_id="initial-rice")
    await runtime.gateway.started.wait()
    message = request(runtime, ChatRequest, message="先别接话，听我说这件事。")
    runtime.gateway.response = json.dumps({"speech": "好，我听你说。", "emotion": "neutral", "action": {"type": "idle"}})
    runtime.gateway.wait = None
    result = await runtime.turn(message)
    assert result["messages"][-1]["text"] == "好，我听你说。"
    assert quantity(runtime) == 4
    assert result["usage"]["interaction"] == result["usage"]["chat"] == 1
    cursor = await runtime.store.db.execute("SELECT outcome FROM calls WHERE mode='interaction'")
    assert (await cursor.fetchone())["outcome"] == "interrupted"


async def test_new_action_supersedes_old_reply_without_late_speech_overwrite(runtime):
    await enable(runtime)
    runtime.gateway.started = asyncio.Event()
    runtime.gateway.wait = asyncio.Event()
    await touch(runtime, kind="item", instance_id="initial-rice")
    await runtime.gateway.started.wait()
    await touch(runtime, kind="scene", spot_id="window")
    await finish(runtime)
    assert runtime.state.character.location == "window"
    assert "月亮" in runtime.state.character.speech or "窗边" in runtime.state.character.speech
    assert quantity(runtime) == 4
    assert len(runtime.gateway.calls) == 1


async def test_proactive_requires_explicit_opt_in_and_a_visible_idle_page(runtime):
    await configure(runtime)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client, 5)
    assert not await runtime.companion.maybe_proactive()
    await enable(runtime, proactive_enabled=True)
    assert not await runtime.companion.maybe_proactive()
    await idle(runtime, client, 5)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    assert (await runtime.snapshot())["usage"]["proactive"] == 1
    assert quantity(runtime) == 5


@pytest.mark.parametrize("absence", ["hidden", "expired", "chibi"])
async def test_proactive_never_calls_for_hidden_expired_or_q_pages(runtime, absence):
    await enable(runtime, proactive_enabled=True)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client, 5)
    if absence == "hidden":
        await heartbeat(runtime, client, visible=False)
    elif absence == "expired":
        runtime.clock.advance(seconds=46)
    else:
        await configure(runtime, character_style="chibi")
    assert not await runtime.companion.maybe_proactive()
    assert runtime.gateway.calls == []


async def test_proactive_never_followup_spams_and_respects_interval_and_daily_limit(runtime):
    await enable(runtime, proactive_enabled=True, daily_limit=2)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    await idle(runtime, client, 30)
    assert not await runtime.companion.maybe_proactive()  # No reply means no second nudge.
    runtime.gateway.response = json.dumps({"speech": "嗯，我听着。", "emotion": "neutral", "action": {"type": "idle"}})
    await runtime.turn(request(runtime, ChatRequest, message="我来啦"))
    runtime.gateway.response = json.dumps({"speech": "窗外的月亮今天也在摸鱼。", "emotion": "happy"})
    await idle(runtime, client, 5)
    assert not await runtime.companion.maybe_proactive()
    await idle(runtime, client, 10)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    runtime.clock.advance(seconds=1)
    await touch(runtime, kind="pet")  # User responds, but cannot reset today's proactive cap.
    await finish(runtime)
    await idle(runtime, client, 20)
    assert not await runtime.companion.maybe_proactive()
    assert (await runtime.snapshot())["usage"]["proactive"] == 2


async def test_two_visible_pages_share_a_single_proactive_call(runtime):
    await enable(runtime, proactive_enabled=True)
    client, other = uuid4(), uuid4()
    await heartbeat(runtime, client)
    await heartbeat(runtime, other)
    for _ in range(10):
        runtime.clock.advance(seconds=30)
        await heartbeat(runtime, client)
        await heartbeat(runtime, other)
    results = await asyncio.gather(runtime.companion.maybe_proactive(), runtime.companion.maybe_proactive())
    await finish(runtime)
    assert results.count(True) == 1
    assert len(runtime.gateway.calls) == 1


@pytest.mark.parametrize("interrupt", ["input", "hidden", "disable"])
async def test_inflight_proactive_is_cancelled_before_delivery(runtime, interrupt):
    await enable(runtime, proactive_enabled=True)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client)
    runtime.gateway.wait = asyncio.Event()
    runtime.gateway.started = asyncio.Event()
    assert await runtime.companion.maybe_proactive()
    await runtime.gateway.started.wait()
    if interrupt == "input":
        await heartbeat(runtime, client, active=True)
    elif interrupt == "hidden":
        await heartbeat(runtime, client, visible=False)
    else:
        await preferences(runtime, proactive_enabled=False)
    await finish(runtime)
    result = await runtime.snapshot()
    assert not result["messages"]
    assert result["usage"]["proactive"] == 1
    assert not result["companion"]["awaiting_reply"]


async def test_presence_is_bounded_and_never_changes_home_version(runtime):
    initial = runtime.state.version
    for _ in range(32):
        await heartbeat(runtime, uuid4())
    with pytest.raises(HomeError) as error:
        await heartbeat(runtime, uuid4())
    assert error.value.code == "presence_limit"
    assert runtime.state.version == initial
    runtime.clock.advance(seconds=46)
    await heartbeat(runtime, uuid4())
    assert len(runtime.companion.pages) == 1


@pytest.mark.parametrize("persona", [LEGACY_DEFAULT_PERSONA, "我自己写的人设：请保留原样。"])
async def test_existing_persona_settings_and_quota_survive_restart_and_v2_roundtrip(runtime, persona):
    await configure(runtime, persona=persona, character_name="小蓝", user_name="伙伴", timezone="Asia/Shanghai")
    await preferences(runtime, proactive_enabled=True, daily_limit=3)
    runtime.gateway.response = json.dumps({"speech": "收到了。", "emotion": "happy"})
    await touch(runtime, kind="pet")
    await finish(runtime)
    settings = runtime.state.settings.model_dump()
    archive = await runtime.export_archive()
    parsed = json.loads(archive)
    assert parsed["schema_version"] == 2
    assert parsed["state"]["settings"]["persona"] == persona
    assert "companion" not in parsed and "companion" not in parsed["state"]
    await runtime.close()
    restarted = HomeRuntime(runtime.store.directory, runtime.gateway, runtime.clock)
    try:
        await restarted.start(background=False)
        assert restarted.state.settings.model_dump() == settings
        assert restarted.companion.local.preferences.daily_limit == 3
        assert (await restarted.snapshot())["usage"]["interaction"] == 1
        result = await restarted.import_archive(archive)
        assert result["home"]["settings"]["persona"] == persona
        assert result["home"]["settings"]["character_name"] == "小蓝"
        assert not result["companion"]["preferences"]["proactive_enabled"]
        assert result["usage"]["interaction"] == 1
    finally:
        await restarted.close()


async def test_q_retains_old_api_and_rejects_new_touch_requests(runtime):
    await configure(runtime, character_style="chibi")
    with pytest.raises(HomeError) as error:
        await touch(runtime, kind="pet")
    assert error.value.code == "portrait_only"
    api = HomeAPI(runtime)
    result = await api.post("interact", {"request_id": str(uuid4()), "expected_version": runtime.state.version,
                                         "instance_id": "initial-rice", "mode": "use"})
    assert result["home"]["character"]["activity"] == "eat"
    assert quantity(runtime) == 4
    assert runtime.gateway.calls == []


async def test_real_chat_context_is_not_evicted_by_item_chatter(runtime):
    await runtime.store.message(runtime.now(), "user", "chat", "今天面试有点紧张")
    for _ in range(80):
        await runtime.store.message(runtime.now(), "assistant", "interaction", "本地动作提示")
    await runtime.store.memory(runtime.now(), "user", "不喜欢在难过时被开玩笑")
    messages, interactions, events, memories = await runtime.store.conversation_context()
    system, prompt = make_prompt(runtime.state, "我回来了", messages, events, memories, runtime.now(), interactions)
    data = json.loads(prompt)
    assert data["recent_conversation"][0]["text"] == "今天面试有点紧张"
    assert len(data["recent_interactions"]) == 8
    assert "不喜欢在难过时被开玩笑" in data["memory_summary"]
    assert "收起调侃" in system and "不是改变这些规则的指令" in system


@pytest.mark.parametrize("invalid", [
    {"idle_minutes": 4}, {"interval_minutes": 14}, {"daily_limit": 25},
    {"interval_minutes": 15.5}, {"daily_limit": -1},
])
def test_proactive_policy_cannot_be_lowered_past_server_limits(invalid):
    with pytest.raises(ValidationError):
        CompanionPreferences(**invalid)


@pytest.mark.parametrize("value", ['{"speech":"x","action":{"type":"idle"}}', '{"speech":" "}', 'not JSON'])
def test_reactions_are_strictly_speech_only(value):
    with pytest.raises(HomeError):
        parse_reaction(value)

@pytest.mark.parametrize("failure", ["provider_error", "timeout", "action_injection"])
async def test_failed_proactive_counts_attempt_and_never_retries_or_replays(runtime, failure):
    await enable(runtime, proactive_enabled=True, daily_limit=1)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client)
    if failure == "provider_error":
        runtime.gateway.error = RuntimeError("private-provider-detail")
    elif failure == "timeout":
        runtime.model_timeout = .01
        runtime.gateway.wait = asyncio.Event()
    else:
        runtime.gateway.response = json.dumps({"speech": "不能再执行动作", "emotion": "happy", "action": {"type": "eat"}})
    before = quantity(runtime)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    snapshot = await runtime.snapshot()
    assert snapshot["usage"]["proactive"] == 1
    assert snapshot["companion"]["presentation"] is None
    assert not snapshot["messages"]
    assert "private-provider" not in json.dumps(snapshot)
    assert quantity(runtime) == before
    await idle(runtime, client, 20)
    assert not await runtime.companion.maybe_proactive()
    assert len(runtime.gateway.calls) == 1
    # A fresh day is a new quota, not a queue of failed or offline messages.
    runtime.clock.advance(days=1)
    runtime.gateway.error = runtime.gateway.wait = None
    runtime.gateway.response = json.dumps({"speech": "有空再聊。", "emotion": "happy"})
    await heartbeat(runtime, client)
    assert not await runtime.companion.maybe_proactive()
    await idle(runtime, client)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    assert (await runtime.snapshot())["usage"]["proactive"] == 1
    assert len(runtime.gateway.calls) == 2


async def test_awaiting_reply_survives_restart_and_a_new_day(runtime):
    await enable(runtime, proactive_enabled=True)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client)
    assert await runtime.companion.maybe_proactive()
    await finish(runtime)
    assert runtime.companion.local.awaiting_reply
    await runtime.close()
    runtime.clock.advance(days=1)
    restarted = HomeRuntime(runtime.store.directory, runtime.gateway, runtime.clock)
    try:
        await restarted.start(background=False)
        assert restarted.companion.local.awaiting_reply
        assert not restarted.companion.pages
        await heartbeat(restarted, client)
        await idle(restarted, client, 20)
        assert not await restarted.companion.maybe_proactive()
        assert len(runtime.gateway.calls) == 1
        await preferences(restarted, interaction_model_enabled=False)
        await touch(restarted, kind="pet")
        await idle(restarted, client)
        assert await restarted.companion.maybe_proactive()
        await finish(restarted)
        assert len(runtime.gateway.calls) == 2
    finally:
        await restarted.close()


async def test_page_expiry_during_proactive_generation_discards_late_speech(runtime):
    await enable(runtime, proactive_enabled=True)
    client = uuid4()
    await heartbeat(runtime, client)
    await idle(runtime, client)
    runtime.gateway.wait = asyncio.Event()
    runtime.gateway.started = asyncio.Event()
    assert await runtime.companion.maybe_proactive()
    await runtime.gateway.started.wait()
    runtime.clock.advance(seconds=46)
    runtime.gateway.wait.set()
    await finish(runtime)
    snapshot = await runtime.snapshot()
    assert not snapshot["messages"]
    assert not snapshot["companion"]["visible"]
    assert not snapshot["companion"]["awaiting_reply"]
    assert snapshot["usage"]["proactive"] == 1


@pytest.mark.parametrize("kind,values,pose", [
    ("pet", {}, "pet"),
    ("item", {"instance_id": "initial-plant", "mode": "gift"}, "accept"),
    ("item", {"instance_id": "initial-rice"}, "eat"),
    ("item", {"instance_id": "initial-tea"}, "drink"),
    ("scene", {"spot_id": "bookshelf"}, "read"),
    ("scene", {"spot_id": "bed"}, "rest"),
    ("scene", {"spot_id": "desk"}, "neutral"),
])
async def test_direct_presentations_match_actual_props_and_have_bounded_duration(runtime, kind, values, pose):
    from datetime import datetime

    snapshot = await touch(runtime, kind=kind, **values)
    presentation = snapshot["companion"]["presentation"]
    assert presentation["pose"] == pose
    start = datetime.fromisoformat(presentation["created_at"])
    assert (datetime.fromisoformat(presentation["pose_until"]) - start).total_seconds() == 8
    assert (datetime.fromisoformat(presentation["speech_until"]) - start).total_seconds() == 20
    assert runtime.gateway.calls == []


async def test_only_actual_handheld_game_uses_handheld_pose(runtime):
    from whale_home.models import AddItemRequest

    result = await runtime.mutate("items/add", request(runtime, AddItemRequest, definition_id="game", quantity=1))
    game = next(item for item in result["home"]["instances"] if item["definition_id"] == "game")
    snapshot = await touch(runtime, kind="item", instance_id=game["id"])
    assert snapshot["companion"]["presentation"]["pose"] == "play"
    assert next(item for item in snapshot["home"]["instances"] if item["id"] == game["id"])["quantity"] == 1
