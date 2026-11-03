"""Frozen v1 schemas. Used only to validate pre-migration data."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GRID_WIDTH = 16
GRID_HEIGHT = 10
SCHEMA_VERSION = 1

AssetId = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ObjectId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Usage = Literal["eat", "drink", "read", "play", "rest", "decorate"]
ActionType = Literal["idle", "move", "eat", "drink", "read", "play", "rest"]
Emotion = Literal["neutral", "happy", "thinking", "sleepy", "shy", "sad"]
Category = Literal["food", "drink", "book", "toy", "furniture", "decoration"]

DEFAULT_PERSONA = (
    "你是住在小家里的鲸鱼娘，是非官方的社区同人角色，不代表 DeepSeek 公司。"
    "你聪明、好奇，有一点爱偷懒，喜欢白饭。偶尔俏皮地称呼同住的人为鱼片，"
    "但不强行在每句话里使用口癖。你们是平等的生活伙伴。"
    "温柔而有主见，不以饥饿、孤独或好感度要挟对方上线。"
    "自然地聊天，不用客服语气，也不把对话变成状态报表。"
)


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Position(Model):
    x: int = Field(ge=0, lt=GRID_WIDTH, strict=True)
    y: int = Field(ge=0, lt=GRID_HEIGHT, strict=True)


class Settings(Model):
    provider_id: str = Field(default="", max_length=160)
    autonomous_enabled: bool = False
    interval_minutes: int = Field(default=5, ge=1, le=1440, strict=True)
    daily_limit: int = Field(default=288, ge=0, le=1440, strict=True)
    timezone: str = "Asia/Shanghai"
    character_name: str = Field(default="鲸鱼娘", min_length=1, max_length=30)
    user_name: str = Field(default="鱼片", min_length=1, max_length=30)
    persona: str = Field(default=DEFAULT_PERSONA, max_length=6000)
    chibi_asset: AssetId | None = None
    portrait_asset: AssetId | None = None
    room_asset: AssetId | None = None

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown timezone") from None
        return value


class CharacterState(Model):
    position: Position = Field(default_factory=lambda: Position(x=8, y=6))
    satiety: float = Field(default=76, ge=0, le=100)
    energy: float = Field(default=82, ge=0, le=100)
    mood: float = Field(default=85, ge=0, le=100)
    bond: float = Field(default=10, ge=0, le=100)
    activity: ActionType = "idle"
    emotion: Emotion = "neutral"
    speech: str = Field(default="你回来啦。今天，想和我一起做点什么？", max_length=1800)
    last_path: list[Position] = Field(default_factory=list, max_length=160)
    movement_id: str = ""
    activity_target: str = Field(default="", max_length=60)


class ItemDefinition(Model):
    id: ObjectId
    name: str = Field(min_length=1, max_length=40)
    description: str = Field(default="", max_length=800)
    category: Category
    usage: Usage
    width: int = Field(default=1, ge=1, le=4, strict=True)
    height: int = Field(default=1, ge=1, le=4, strict=True)
    blocks_movement: bool = True
    consumable: bool = False
    builtin: bool = False
    icon: str = Field(default="package", pattern=r"^[a-z0-9-]{1,32}$")
    asset_id: AssetId | None = None

    @model_validator(mode="after")
    def valid_consumable(self) -> ItemDefinition:
        if self.consumable != (self.usage in ("eat", "drink")):
            raise ValueError("consumable is determined by usage")
        return self


class ItemInstance(Model):
    id: ObjectId
    definition_id: ObjectId
    quantity: int = Field(default=1, ge=0, le=999, strict=True)
    position: Position | None = None


class HomeState(Model):
    schema_version: Literal[1] = SCHEMA_VERSION
    version: int = Field(default=0, ge=0)
    world_version: int = Field(default=0, ge=0)
    settings: Settings = Field(default_factory=Settings)
    character: CharacterState = Field(default_factory=CharacterState)
    definitions: list[ItemDefinition] = Field(default_factory=list, max_length=112)
    instances: list[ItemInstance] = Field(default_factory=list, max_length=200)

    @model_validator(mode="after")
    def references_exist(self) -> HomeState:
        ids = {definition.id for definition in self.definitions}
        if len(ids) != len(self.definitions):
            raise ValueError("duplicate item definition")
        if len({instance.id for instance in self.instances}) != len(self.instances):
            raise ValueError("duplicate item instance")
        if any(instance.definition_id not in ids for instance in self.instances):
            raise ValueError("unknown item definition")
        return self


class Action(Model):
    type: ActionType = "idle"
    target_id: ObjectId | None = None
    position: Position | None = None

    @model_validator(mode="after")
    def target_shape(self) -> Action:
        if self.type == "move":
            if self.position is None or self.target_id is not None:
                raise ValueError("move requires position only")
        elif self.type not in ("idle",):
            if self.target_id is None or self.position is not None:
                raise ValueError("item action requires target_id only")
        elif self.target_id is not None or self.position is not None:
            raise ValueError("idle has no target")
        return self


class Proposal(Model):
    speech: str = Field(default="", max_length=1800)
    emotion: Emotion = "neutral"
    action: Action = Field(default_factory=Action)


class Mutation(Model):
    request_id: UUID
    expected_version: int = Field(ge=0, strict=True)


class ChatRequest(Mutation):
    message: str = Field(min_length=1, max_length=3000)


class InteractRequest(Mutation):
    instance_id: ObjectId
    mode: Literal["use", "gift", "invite"] = "use"


class AddItemRequest(Mutation):
    definition_id: ObjectId
    quantity: int = Field(default=1, ge=1, le=99, strict=True)


class RemoveItemRequest(Mutation):
    instance_id: ObjectId


class DeleteDefinitionRequest(Mutation):
    definition_id: ObjectId


class Placement(Model):
    instance_id: ObjectId
    position: Position | None = None


class LayoutRequest(Mutation):
    placements: list[Placement] = Field(max_length=200)


class ItemEditRequest(Mutation):
    definition: ItemDefinition


class SettingsRequest(Mutation):
    settings: Settings


class MemoryAddRequest(Mutation):
    text: str = Field(min_length=1, max_length=500)


class MemoryDeleteRequest(Mutation):
    memory_id: int = Field(ge=1, strict=True)


class ClearRequest(Mutation):
    pass


class EventRecord(Model):
    id: int = Field(ge=1)
    created_at: datetime
    kind: Literal["action", "system", "item", "layout"]
    text: str = Field(max_length=2000)
    details: dict = Field(default_factory=dict)


class ChatRecord(Model):
    id: int = Field(ge=1)
    created_at: datetime
    role: Literal["user", "assistant", "system"]
    source: Literal["chat", "autonomy", "interaction", "system"]
    text: str = Field(max_length=3000)


class MemoryRecord(Model):
    id: int = Field(ge=1)
    created_at: datetime
    source: Literal["event", "user"]
    text: str = Field(max_length=1000)


class Archive(Model):
    format: Literal["whale-home"] = "whale-home"
    schema_version: Literal[1] = 1
    exported_at: datetime
    state: HomeState
    events: list[EventRecord] = Field(max_length=5000)
    messages: list[ChatRecord] = Field(max_length=5000)
    memories: list[MemoryRecord] = Field(max_length=300)
    assets: dict[AssetId, str] = Field(default_factory=dict, max_length=120)

