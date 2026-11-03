"""Direct interaction and opt-in visible-page companionship. Never part of v2 archives."""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import Field

from .errors import HomeError
from .llm import make_reaction_prompt, parse_reaction
from .models import (
    DEFAULT_PERSONA,
    Action,
    CharacterInteractRequest,
    CompanionPreferences,
    CompanionPreferencesRequest,
    HomeState,
    Model,
    PresenceRequest,
)
from .rules import apply_action, definitions_by_id, validate_state
from .scene import SPOTS

if TYPE_CHECKING:
    from .runtime import HomeRuntime

PRESENCE_TTL_SECONDS = 45
INTERACTION_INTERVAL_SECONDS = 5
INTERACTION_DAILY_LIMIT = 60
POSE_SECONDS = 8
SPEECH_SECONDS = 20


class LocalCompanionState(Model):
    preferences: CompanionPreferences = Field(default_factory=CompanionPreferences)
    last_interaction_call: datetime | None = None
    last_proactive_call: datetime | None = None
    last_spoken: datetime | None = None
    awaiting_reply: bool = False


@dataclass
class PagePresence:
    seen_at: datetime
    active_at: datetime


def pose_for_action(state: HomeState, action: Action) -> str:
    """Show props only when their built-in identity matches the actual action."""
    if action.spot_id:
        return {"bookshelf": "read", "bed": "rest"}.get(action.spot_id, "neutral")
    item = next((item for item in state.instances if item.id == action.target_id), None)
    if item is None:
        return "neutral"
    definition = definitions_by_id(state)[item.definition_id]
    if not definition.builtin:
        return "neutral"
    return {("rice", "eat"): "eat", ("tea", "drink"): "drink", ("book", "read"): "read",
            ("game", "play"): "play", ("pillow", "rest"): "rest", ("chair", "rest"): "rest",
            ("bed", "rest"): "rest"}.get((definition.id, action.type), "neutral")


def direct_action(state: HomeState, request: CharacterInteractRequest) -> tuple[str, dict, str, str]:
    """Only authoritative rules consume inventory; model reactions cannot execute this."""
    character = state.character
    n = state.version
    if request.kind == "pet":
        character.mood = min(100, character.mood + 1)
        character.bond = min(100, character.bond + .05)
        text, details, pose = "轻轻摸了摸她的头。", {"action": "pet", "kind": "pet"}, "pet"
        lines = ("嗯？今天是给鲸鱼充电的环节吗。", "发型乱了——算了，这次不跟你计较。", "收到，脑袋上的小乌云暂时散开了。")
        if character.energy < 25:
            lines = ("轻一点，我的大脑正在省电模式。", "嗯……这个可以，先让我缓缓。")
    elif request.kind == "scene":
        spot = SPOTS[request.spot_id]
        action = Action(type=spot["action"], spot_id=request.spot_id)
        text, details = apply_action(state, action)
        details["kind"] = "scene"
        pose = pose_for_action(state, action)
        lines = {
            "bookshelf": ("好，挑一本。先说好，不许剧透。", "给大脑换个频道，一起看两页。"),
            "desk": ("电脑时间到。今天不当卷王。", "放松一下，手速不够就靠气势补。"),
            "window": ("月亮今晚挺努力，我们负责欣赏。", "来窗边透口气，烦心事先排队。"),
            "bed": ("站这儿歇会儿，给脑袋按个暂停。", "今天的努力先存档，歇一下。"),
        }[request.spot_id]
    else:
        instance = next((item for item in state.instances if item.id == request.instance_id), None)
        if instance is None or instance.quantity == 0:
            raise HomeError("这件物品已经用完或不在收纳里了。")
        definition = definitions_by_id(state)[instance.definition_id]
        if definition.usage == "decorate":
            if request.mode != "gift":
                raise HomeError("装饰物可以作为礼物递给她。")
            character.mood = min(100, character.mood + 3)
            character.bond = min(100, character.bond + .2)
            text = f"收到了作为礼物的「{definition.name}」。"
            details = {"action": "gift", "target_id": instance.id, "target_name": definition.name}
            pose = "accept"
            lines = (f"「{definition.name}」？你的眼光有点东西。", f"收下啦，「{definition.name}」今天加入小家名册。")
        else:
            action = Action(type=definition.usage, target_id=instance.id)
            text, details = apply_action(state, action)
            pose = pose_for_action(state, action)
            lines = {
                "eat": (f"「{definition.name}」来得正好，能量补给上线。", f"先尝一口「{definition.name}」，评价等我吃完再说。"),
                "drink": (f"喝点「{definition.name}」，让大脑别冒烟。", f"「{definition.name}」收到。慢慢喝，今天不赶进度。"),
                "read": (f"翻开「{definition.name}」——让我看看谁在书里摸鱼。", "先看两页，后面的剧情我们再慢慢聊。"),
                "play": (f"「{definition.name}」准备好了，快乐不需要绩效。", "来，给认真的脑袋放个小假。"),
                "rest": ("暂时切换成省电模式，不接加班任务。", "歇一下。摆烂和休息，我分得很清楚。"),
            }[definition.usage]
        details.update(kind="item", definition_id=definition.id, mode=request.mode)
    return text, details, pose, lines[n % len(lines)]


class Companion:
    def __init__(self, runtime: HomeRuntime):
        self.runtime = runtime
        self.local = LocalCompanionState()
        self.pages: dict[str, PagePresence] = {}
        self.last_user_activity = runtime.clock()
        self.last_pet_at: datetime | None = None
        self.epoch = 0
        self.presentation: dict | None = None
        self.reply_task: asyncio.Task | None = None
        self.reply_kind = ""
        self.notice = ""

    async def load(self) -> None:
        self.local = LocalCompanionState.model_validate(await self.runtime.store.load_companion())
        self.pages.clear()
        self.last_user_activity = self.runtime.clock()
        self.presentation = None

    @property
    def pending(self) -> bool:
        return self.reply_task is not None and not self.reply_task.done()

    def visible(self) -> bool:
        now = self.runtime.clock()
        self.pages = {key: page for key, page in self.pages.items()
                      if 0 <= (now - page.seen_at).total_seconds() < PRESENCE_TTL_SECONDS}
        return bool(self.pages) and self.runtime.state.settings.character_style == "portrait"

    def view(self, usage: dict) -> dict:
        presentation = self.presentation
        if presentation and not self.pending and self.runtime.clock() >= datetime.fromisoformat(presentation["speech_until"]):
            presentation = None
        return {
            "preferences": self.local.preferences.model_dump(),
            "presentation": presentation,
            "notice": self.notice,
            "reply_interruptible": self.pending,
            "awaiting_reply": self.local.awaiting_reply,
            "visible": self.visible(),
            "usage": {"interaction": usage.get("interaction", 0), "proactive": usage.get("proactive", 0)},
            "limits": {"interaction_interval_seconds": INTERACTION_INTERVAL_SECONDS,
                       "interaction_daily_limit": INTERACTION_DAILY_LIMIT,
                       "presence_ttl_seconds": PRESENCE_TTL_SECONDS},
            "touch_available_at": (self.last_pet_at + timedelta(seconds=1)).isoformat() if self.last_pet_at else None,
            "persona_preset": DEFAULT_PERSONA,
        }

    def invalidate(self, clear: bool = True) -> None:
        self.epoch += 1
        if self.pending:
            self.reply_task.cancel()
        if clear:
            self.presentation = None
        self.notice = ""

    def user_activity(self, clear: bool = True) -> None:
        self.invalidate(clear)
        self.last_user_activity = self.runtime.clock()
        self.local.awaiting_reply = False

    async def cancel_pending(self) -> None:
        task = self.reply_task
        self.invalidate()
        if task and task is not asyncio.current_task():
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def presence(self, request: PresenceRequest) -> dict:
        runtime = self.runtime
        async with runtime.lock:
            if runtime.closed:
                raise HomeError("小家正在关闭。", 503)
            self.visible()  # Prune expired tabs before enforcing the bound.
            key, now = str(request.client_id), runtime.clock()
            if not request.visible or runtime.state.settings.character_style != "portrait":
                self.pages.pop(key, None)
                if self.pending and self.reply_kind == "proactive" and not self.visible():
                    self.invalidate()
            else:
                old = self.pages.get(key)
                if old is None and len(self.pages) >= 32:
                    raise HomeError("打开的小家页面太多，请关闭不用的页面。", 429, "presence_limit")
                active_at = now if old is None or request.active else old.active_at
                self.pages[key] = PagePresence(now, active_at)
                if old is None or request.active:
                    self.last_user_activity = now
                    if self.pending and self.reply_kind == "proactive":
                        self.invalidate()
            return {"visible": self.visible(), "ttl_seconds": PRESENCE_TTL_SECONDS,
                    "server_time": runtime.now()}

    async def preferences(self, request: CompanionPreferencesRequest) -> dict:
        runtime = self.runtime
        async with runtime.lock:
            if runtime.closed:
                raise HomeError("小家正在关闭。", 503)
            if await runtime.check_request("companion/preferences", request):
                return await runtime._snapshot()
            if request.preferences.proactive_enabled and not runtime.state.settings.provider_id:
                raise HomeError("先选择聊天模型，再开启偶尔搭话。", 400, "no_model")
            previous = self.local.model_copy(deep=True)
            try:
                self.user_activity()
                self.local.preferences = request.preferences.model_copy(deep=True)
                await runtime.register_request("companion/preferences", request)
                await runtime.commit(runtime.state.model_copy(deep=True))
                return await runtime._snapshot()
            except BaseException:
                self.local = previous
                await runtime.store.db.rollback()
                raise

    def present(self, id_: str, pose: str, speech: str, source: str,
                model_status: str = "local", emotion: str = "happy") -> None:
        now = self.runtime.clock()
        self.presentation = {
            "id": id_, "pose": pose, "speech": speech, "emotion": emotion,
            "source": source, "model_status": model_status,
            "created_at": now.isoformat(),
            "pose_until": (now + timedelta(seconds=POSE_SECONDS)).isoformat(),
            "speech_until": (now + timedelta(seconds=SPEECH_SECONDS)).isoformat(),
        }

    def interaction_policy(self, usage: dict) -> tuple[bool, str]:
        if not self.local.preferences.interaction_model_enabled:
            return False, "直接互动的模型回应已关闭，当前使用本地回应。"
        if not self.runtime.state.settings.provider_id:
            return False, "动作已完成；选好聊天模型后，她可以结合聊天接话。"
        if usage.get("interaction", 0) >= INTERACTION_DAILY_LIMIT:
            return False, "今日互动模型次数已用完，仍可继续本地互动。"
        last = self.local.last_interaction_call
        if last and (self.runtime.clock() - last).total_seconds() < INTERACTION_INTERVAL_SECONDS:
            return False, "连点保护：这次先用本地回应，不追加模型调用。"
        if self.runtime.model_lock.locked() or self.pending:
            return False, "动作已完成；她还在想上一句话，这次先用本地回应。"
        return True, ""

    async def interact(self, request: CharacterInteractRequest) -> dict:
        runtime = self.runtime
        async with runtime.lock:
            if runtime.closed:
                raise HomeError("小家正在关闭。", 503)
            if await runtime.check_request("character/interact", request):
                return await runtime._snapshot()
            if runtime.state.settings.character_style != "portrait":
                raise HomeError("直接触碰仅用于正常比例角色，Q 版保持原有操作。", 400, "portrait_only")
            now = runtime.clock()
            if request.kind == "pet" and self.last_pet_at and (now - self.last_pet_at).total_seconds() < 1:
                raise HomeError("轻一点，让她缓一下再摸。", 429, "touch_cooldown")
            updated = runtime.state.model_copy(deep=True)
            previous = self.local.model_copy(deep=True)
            try:
                text, details, pose, speech = direct_action(updated, request)
                validate_state(updated)
                updated.character.speech, updated.character.emotion = speech, "happy"
                self.user_activity(clear=False)
                await runtime.store.event(runtime.now(), "action", text, details)
                if request.kind != "pet":
                    await runtime.store.memory(runtime.now(), "event", text)
                message_id = await runtime.store.message(runtime.now(), "assistant", "interaction", speech)
                allowed, self.notice = self.interaction_policy(await runtime.store.usage(runtime.day()))
                self.present(str(request.request_id), pose, speech, "interaction", "pending" if allowed else "local")
                await runtime.register_request("character/interact", request)
                await runtime.commit(updated)
                if request.kind == "pet":
                    self.last_pet_at = now
                if allowed:
                    self._spawn(str(request.request_id), self.epoch, updated.world_version,
                                "interaction", details, message_id)
                return await runtime._snapshot()
            except BaseException:
                self.local = previous
                await runtime.store.db.rollback()
                raise

    def _proactive_due(self, usage: dict, ignore_pending: bool = False) -> bool:
        runtime, now, prefs = self.runtime, self.runtime.clock(), self.local.preferences
        if not prefs.proactive_enabled or not runtime.state.settings.provider_id or not self.visible():
            return False
        if self.local.awaiting_reply or (self.pending and not ignore_pending):
            return False
        if usage.get("proactive", 0) >= prefs.daily_limit:
            return False
        if (now - self.last_user_activity).total_seconds() < prefs.idle_minutes * 60:
            return False
        recent = [t for t in (self.local.last_proactive_call, self.local.last_spoken) if t]
        return not recent or (now - max(recent)).total_seconds() >= prefs.interval_minutes * 60

    async def maybe_proactive(self) -> bool:
        runtime = self.runtime
        async with runtime.lock:
            if runtime.closed or runtime.model_lock.locked() or not self._proactive_due(await runtime.store.usage(runtime.day())):
                return False
            id_ = uuid4().hex
            self.present(id_, "neutral", "", "proactive", "pending", "thinking")
            self._spawn(id_, self.epoch, runtime.state.world_version, "proactive", {}, None)
            runtime.notify()
            return True

    def suppresses_autonomy(self) -> bool:
        if self.pending:
            return True
        if self.runtime.state.settings.character_style != "portrait":
            return False
        if self.local.preferences.proactive_enabled and self.visible():
            return self.local.awaiting_reply or (
                self.runtime.clock() - self.last_user_activity).total_seconds() < self.local.preferences.idle_minutes * 60 or (
                self.local.last_spoken is not None and (self.runtime.clock() - self.local.last_spoken).total_seconds() < self.local.preferences.interval_minutes * 60)
        return False

    def _spawn(self, id_: str, epoch: int, world_version: int, kind: str,
               completed: dict, message_id: int | None) -> None:
        task = asyncio.create_task(self._reply(id_, epoch, world_version, kind, completed, message_id),
                                   name=f"whale-home-{kind}-reply")
        self.reply_task, self.reply_kind = task, kind
        self.runtime.generation_tasks.add(task)
        def done(finished: asyncio.Task) -> None:
            self.runtime.generation_tasks.discard(finished)
            if self.reply_task is finished:
                self.reply_task, self.reply_kind = None, ""
            if not finished.cancelled():
                # Retrieve exceptions; only a sanitized notice ever reaches the UI.
                if finished.exception() is not None:
                    self.notice = "这次回应没有完成，已保留现有动作与数据。"
            self.runtime.notify()
        task.add_done_callback(done)

    def _current(self, id_: str, epoch: int, world_version: int) -> bool:
        return (not self.runtime.closed and self.epoch == epoch and self.presentation is not None
                and self.presentation["id"] == id_ and self.runtime.state.world_version == world_version
                and self.runtime.state.settings.character_style == "portrait")

    async def _reply(self, id_: str, epoch: int, world_version: int, kind: str,
                     completed: dict, message_id: int | None) -> None:
        runtime, call_id = self.runtime, None
        try:
            # Never queue behind another model call; direct actions already succeeded.
            if runtime.model_lock.locked():
                async with runtime.lock:
                    if self._current(id_, epoch, world_version):
                        self.presentation["model_status"] = "local"
                        self.notice = "她正在想别的事情，这次保留本地回应。"
                return
            async with runtime.model_lock:
                async with runtime.lock:
                    if not self._current(id_, epoch, world_version):
                        return
                    usage = await runtime.store.usage(runtime.day())
                    if kind == "proactive" and not self._proactive_due(usage, ignore_pending=True):
                        self.presentation = None
                        return
                    if kind == "interaction" and (not self.local.preferences.interaction_model_enabled
                            or usage["interaction"] >= INTERACTION_DAILY_LIMIT
                            or (self.local.last_interaction_call and (runtime.clock() - self.local.last_interaction_call).total_seconds() < INTERACTION_INTERVAL_SECONDS)):
                        self.presentation["model_status"] = "local"
                        self.notice = "已触发调用保护，本次保留本地回应。"
                        return
                    state = runtime.state.model_copy(deep=True)
                    messages, interactions, events, memories = await runtime.store.conversation_context()
                    system, prompt = make_reaction_prompt(
                        state, "direct_interaction" if kind == "interaction" else "proactive_greeting",
                        completed, messages, events, memories, runtime.now(), interactions)
                    cursor = await runtime.store.db.execute(
                        "INSERT INTO calls(day,mode,created_at) VALUES(?,?,?)", (runtime.day(), kind, runtime.now()))
                    call_id = cursor.lastrowid
                    if kind == "interaction":
                        self.local.last_interaction_call = runtime.clock()
                    else:
                        self.local.last_proactive_call = runtime.clock()
                    await runtime.commit(runtime.state.model_copy(deep=True), world_changed=False)
                answer = await asyncio.wait_for(runtime.skills.generate(state.settings.provider_id, system, prompt, kind,
                                            lambda: self._current(id_, epoch, world_version)),
                                                timeout=runtime.model_timeout)
                reaction = parse_reaction(answer)
                async with runtime.lock:
                    if (not self._current(id_, epoch, world_version)
                            or (kind == "proactive" and (not self.visible() or not self.local.preferences.proactive_enabled))):
                        await runtime.store.db.execute("UPDATE calls SET outcome='superseded' WHERE id=?", (call_id,))
                        await runtime.commit(runtime.state.model_copy(deep=True), world_changed=False)
                        return
                    updated = runtime.state.model_copy(deep=True)
                    updated.character.speech, updated.character.emotion = reaction.speech, reaction.emotion
                    if kind == "interaction":
                        await runtime.store.db.execute("UPDATE messages SET text=? WHERE id=? AND source='interaction'",
                                                       (reaction.speech, message_id))
                    else:
                        # Existing archive enum stays unchanged; local calls distinguish proactive.
                        await runtime.store.message(runtime.now(), "assistant", "autonomy", reaction.speech)
                        self.local.awaiting_reply = True
                    self.local.last_spoken = runtime.clock()
                    self.presentation.update(speech=reaction.speech, emotion=reaction.emotion, model_status="model",
                                             speech_until=(runtime.clock() + timedelta(seconds=SPEECH_SECONDS)).isoformat())
                    self.notice = ""
                    await runtime.store.db.execute("UPDATE calls SET outcome='ok' WHERE id=?", (call_id,))
                    await runtime.commit(updated, world_changed=False)
        except BaseException as error:
            if call_id is not None:
                async with runtime.lock:
                    await runtime.store.db.rollback()
                    cursor = await runtime.store.db.execute("SELECT outcome FROM calls WHERE id=?", (call_id,))
                    row = await cursor.fetchone()
                    if row and row["outcome"] != "ok":
                        code = "interrupted" if isinstance(error, asyncio.CancelledError) else "model_timeout" if isinstance(error, TimeoutError) else "model_error"
                        await runtime.store.db.execute("UPDATE calls SET outcome=? WHERE id=?", (code, call_id))
                        if self._current(id_, epoch, world_version):
                            if kind == "interaction":
                                self.presentation["model_status"] = "error"
                                self.notice = "动作已完成；模型回应暂时不可用，已保留本地回应，没有重试或重复消耗物品。"
                            else:
                                self.presentation = None
                                self.notice = "这次主动搭话没有完成，没有自动重试。"
                        await runtime.commit(runtime.state.model_copy(deep=True), world_changed=False)
            if isinstance(error, asyncio.CancelledError):
                raise
            # Never expose arbitrary provider errors (which can include credentials).
        finally:
            runtime.notify()

    def show_chat(self, state: HomeState, action: Action, speech: str, emotion: str, autonomous: bool) -> None:
        if state.settings.character_style != "portrait":
            return
        self.present(uuid4().hex, pose_for_action(state, action), speech, "autonomy" if autonomous else "chat", "model", emotion)
        self.local.last_spoken = self.runtime.clock()
        if autonomous and self.local.preferences.proactive_enabled and self.visible() and speech:
            self.local.awaiting_reply = True
