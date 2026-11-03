from __future__ import annotations

import asyncio
import base64

from pydantic import ValidationError

from .computer import GET_ENDPOINTS as COMPUTER_GET
from .computer import POST_ENDPOINTS as COMPUTER_POST
from .models import (
    AddItemRequest,
    CharacterInteractRequest,
    ChatRequest,
    ClearRequest,
    CompanionPreferencesRequest,
    DeleteDefinitionRequest,
    InteractRequest,
    ItemEditRequest,
    LayoutRequest,
    MemoryAddRequest,
    MemoryDeleteRequest,
    Mutation,
    PresenceRequest,
    RemoveItemRequest,
    SceneInteractRequest,
    SettingsRequest,
    SkillPreferencesRequest,
)
from .rules import HomeError
from .runtime import HomeRuntime

MUTATIONS = {
    "items/add": AddItemRequest,
    "items/remove": RemoveItemRequest,
    "items/edit": ItemEditRequest,
    "items/delete-definition": DeleteDefinitionRequest,
    "layout": LayoutRequest,
    "interact": InteractRequest,
    "character/interact": CharacterInteractRequest,
    "companion/preferences": CompanionPreferencesRequest,
    "scene/interact": SceneInteractRequest,
    "settings": SettingsRequest,
    "memories/add": MemoryAddRequest,
    "memories/delete": MemoryDeleteRequest,
    "memories/clear": ClearRequest,
    "messages/clear": ClearRequest,
}


class HomeAPI:
    def __init__(self, runtime: HomeRuntime):
        self.runtime = runtime

    async def get(self, endpoint: str, params: dict | None = None) -> dict | list:
        params = params or {}
        if endpoint in COMPUTER_GET:
            return await self.runtime.computer.get(endpoint.split("/", 1)[1], params)
        if endpoint == "state":
            return await self.runtime.snapshot()
        if endpoint == "skills/catalog":
            return [item.model_dump() for item in await self.runtime.skills.catalog()]
        if endpoint == "skills/preferences":
            async with self.runtime.lock:
                return self.runtime.skills.preferences.model_dump()
        if endpoint == "providers":
            return await self.runtime.gateway.providers()
        if endpoint == "companion/preferences":
            async with self.runtime.lock:
                return self.runtime.companion.local.preferences.model_dump()
        if endpoint in ("events/history", "messages", "memories", "skills/calls"):
            table = "events" if endpoint == "events/history" else "skill_calls" if endpoint == "skills/calls" else endpoint
            try:
                before = int(params["before"]) if params.get("before") else None
                limit = min(100, max(1, int(params.get("limit", 60))))
            except (TypeError, ValueError):
                raise HomeError("分页参数不正确。") from None
            async with self.runtime.lock:
                return {"items": await self.runtime.store.rows(table, limit, before)}
        if endpoint.startswith("assets/"):
            content = await asyncio.to_thread(self.runtime.assets.read, endpoint.split("/", 1)[1])
            return {"data_url": "data:image/webp;base64," + base64.b64encode(content).decode("ascii")}
        raise HomeError("接口不存在。", 404)

    async def post(self, endpoint: str, body: dict) -> dict:
        if endpoint in COMPUTER_POST:
            return await self.runtime.computer.post(endpoint.split("/", 1)[1], body)
        try:
            if endpoint == "layout":
                raise HomeError("当前房间不支持自由布置，物品可以直接从收纳中使用。", 400, "fixed_scene")
            if endpoint == "skills/preferences":
                return await self.runtime.skills.save_preferences(SkillPreferencesRequest.model_validate(body))
            if endpoint == "skills/stop":
                return await self.runtime.skills.stop(Mutation.model_validate(body))
            if endpoint == "chat":
                return await self.runtime.turn(ChatRequest.model_validate(body))
            if endpoint == "character/interact":
                return await self.runtime.companion.interact(CharacterInteractRequest.model_validate(body))
            if endpoint == "companion/preferences":
                return await self.runtime.companion.preferences(CompanionPreferencesRequest.model_validate(body))
            if endpoint == "companion/presence":
                return await self.runtime.companion.presence(PresenceRequest.model_validate(body))
            if endpoint in MUTATIONS:
                return await self.runtime.mutate(
                    endpoint, MUTATIONS[endpoint].model_validate(body)
                )
        except ValidationError:
            raise HomeError("输入格式不正确，请检查名称、数值和物品信息。") from None
        raise HomeError("接口不存在。", 404)

    async def upload(self, endpoint: str, content: bytes) -> dict:
        if endpoint == "assets/upload":
            asset_id = await asyncio.to_thread(self.runtime.assets.import_image, content)
            return {"asset_id": asset_id}
        if endpoint == "archives/import":
            return await self.runtime.import_archive(content)
        raise HomeError("上传接口不存在。", 404)

