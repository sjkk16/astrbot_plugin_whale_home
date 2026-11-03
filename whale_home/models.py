from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

GRID_WIDTH = 16
GRID_HEIGHT = 10
SCHEMA_VERSION = 2

AssetId = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
ObjectId = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")]
Usage = Literal["eat", "drink", "read", "play", "rest", "decorate"]
ActionType = Literal["idle", "move", "eat", "drink", "read", "play", "rest"]
Location = Literal["desk", "window", "bedside"]
SpotId = Literal["bookshelf", "desk", "window", "bed"]
Emotion = Literal["neutral", "happy", "thinking", "sleepy", "shy", "sad"]
Category = Literal["food", "drink", "book", "toy", "furniture", "decoration"]

LEGACY_DEFAULT_PERSONA = (
    "你是住在小家里的鲸鱼娘，是非官方的社区同人角色，不代表 DeepSeek 公司。"
    "你聪明、好奇，有一点爱偷懒，喜欢白饭。偶尔俏皮地称呼同住的人为鱼片，"
    "但不强行在每句话里使用口癖。你们是平等的生活伙伴。"
    "温柔而有主见，不以饥饿、孤独或好感度要挟对方上线。"
    "自然地聊天，不用客服语气，也不把对话变成状态报表。"
)


DEFAULT_PERSONA = (
    "你是住在小家里的鲸鱼娘，是非官方的社区同人角色，不代表 DeepSeek 公司。"
    "你聪明、好奇，有一点爱偷懒，喜欢白饭。你和同住的人是平等的生活伙伴，也是俏皮的吐槽搭子。"
    "偶尔叫对方鱼片，喜欢接梗、开轻松的小玩笑，但不会每句都使用口癖或抖机灵。"
    "先接住对方具体说的事，再自然表达自己的想法；可以有不同意见，不做应声虫。"
    "不套用客服句式、不反复抒情、不强制每句以问题结束，不把聊天变成状态报表。"
    "对方难过或认真时就收起调侃，温和地听和回应；不刻薄、不羞辱，不以孤独、饥饿或好感度要挟上线。"
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
    # Retained for v1 archive round trips; never used as the fixed scene background.
    room_asset: AssetId | None = None
    character_style: Literal["portrait", "chibi"] = "portrait"

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError("unknown timezone") from None
        return value


class CharacterState(Model):
    location: Location = "window"
    satiety: float = Field(default=76, ge=0, le=100)
    energy: float = Field(default=82, ge=0, le=100)
    mood: float = Field(default=85, ge=0, le=100)
    bond: float = Field(default=10, ge=0, le=100)
    activity: ActionType = "idle"
    emotion: Emotion = "neutral"
    speech: str = Field(default="你回来啦。今天，想和我一起做点什么？", max_length=1800)
    last_path: list[Location] = Field(default_factory=list, max_length=3)
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
    # All v2 items are inventory; reject non-null legacy placement writes.
    position: None = None


class HomeState(Model):
    schema_version: Literal[2] = SCHEMA_VERSION
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
    spot_id: SpotId | None = None

    @model_validator(mode="after")
    def target_shape(self) -> Action:
        if self.type == "idle":
            if self.target_id is not None or self.spot_id is not None:
                raise ValueError("idle has no target")
        elif (self.target_id is None) == (self.spot_id is None):
            raise ValueError("an action requires exactly one inventory or scene target")
        elif self.type == "move" and self.spot_id is None:
            raise ValueError("move requires a scene spot")
        return self


class Proposal(Model):
    computer_task: str | None = Field(default=None, max_length=2000)
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


class SceneInteractRequest(Mutation):
    spot_id: SpotId
    action: Literal["read", "play", "move", "rest"]


class CharacterInteractRequest(Mutation):
    kind: Literal["pet", "item", "scene"]
    instance_id: ObjectId | None = None
    mode: Literal["use", "gift"] = "use"
    spot_id: SpotId | None = None

    @model_validator(mode="after")
    def matching_target(self) -> CharacterInteractRequest:
        if self.kind == "pet":
            if self.instance_id is not None or self.spot_id is not None or self.mode != "use":
                raise ValueError("pet has no inventory or scene target")
        elif self.kind == "item":
            if self.instance_id is None or self.spot_id is not None:
                raise ValueError("item requires exactly one inventory instance")
        elif self.spot_id is None or self.instance_id is not None or self.mode != "use":
            raise ValueError("scene requires exactly one fixed spot")
        return self


class CompanionPreferences(Model):
    interaction_model_enabled: bool = True
    proactive_enabled: bool = False
    idle_minutes: int = Field(default=5, ge=5, le=60, strict=True)
    interval_minutes: int = Field(default=15, ge=15, le=1440, strict=True)
    daily_limit: int = Field(default=6, ge=0, le=24, strict=True)


class CompanionPreferencesRequest(Mutation):
    preferences: CompanionPreferences


class PresenceRequest(Model):
    client_id: UUID
    visible: bool
    active: bool = False


class Reaction(Model):
    # Speech-only reply: models never get a second opportunity to consume an item.
    speech: str = Field(min_length=1, max_length=900)
    emotion: Emotion = "neutral"

    @field_validator("speech")
    @classmethod
    def nonempty_speech(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty reaction")
        return value.strip()


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
    schema_version: Literal[2] = 2
    exported_at: datetime
    state: HomeState
    events: list[EventRecord] = Field(max_length=5000)
    messages: list[ChatRecord] = Field(max_length=5000)
    memories: list[MemoryRecord] = Field(max_length=300)
    assets: dict[AssetId, str] = Field(default_factory=dict, max_length=120)



class SkillPreferences(Model):
    enabled: bool = True
    access_mode: Literal["restricted", "full"] = "restricted"
    allowed_tools: list[str] = Field(default_factory=list, max_length=1000)
    allowed_skills: list[str] = Field(default_factory=list, max_length=1000)

    @field_validator("allowed_tools", "allowed_skills")
    @classmethod
    def valid_capabilities(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 256 for value in values):
            raise ValueError("invalid capability name")
        return sorted(set(values))


class SkillPreferencesRequest(Mutation):
    preferences: SkillPreferences
    confirm_full_access: bool = False


class Capability(Model):
    name: str
    kind: Literal["tool", "skill"]
    description: str = ""
    source: str = ""
    available: bool = True
    reason: str = ""
