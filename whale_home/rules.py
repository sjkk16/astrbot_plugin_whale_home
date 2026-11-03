from __future__ import annotations

from uuid import uuid4

from .catalog import builtins
from .errors import HomeError
from .models import Action, HomeState, ItemDefinition
from .scene import SPOTS, path_between


def definitions_by_id(state: HomeState) -> dict[str, ItemDefinition]:
    return {definition.id: definition for definition in state.definitions}


def validate_state(state: HomeState) -> None:
    definitions = definitions_by_id(state)
    expected = {definition.id: definition for definition in builtins()}
    if any(definitions.get(key) != value for key, value in expected.items()) or any(
        definition.builtin and definition.id not in expected
        for definition in state.definitions
    ):
        raise HomeError("内置物品定义不正确，不能覆盖现有小家。")
    if any(item.position is not None for item in state.instances):
        raise HomeError("当前房间不支持自由布置，物品应保存在收纳中。")
    path = state.character.last_path
    if path and (path[-1] != state.character.location or path != path_between(path[0], path[-1])):
        raise HomeError("角色活动路径不正确。")


EFFECTS = {
    "eat": {"satiety": 22, "energy": 3, "mood": 3},
    "drink": {"energy": 7, "mood": 4},
    "read": {"energy": -3, "mood": 6},
    "play": {"energy": -5, "mood": 10},
    "rest": {"energy": 22, "mood": 3},
}
VERBS = {"eat": "吃了", "drink": "喝了", "read": "读起了", "play": "玩起了"}
SCENE_TEXT = {
    "bookshelf": "从书架选了一本书，在书桌前读了一会儿。",
    "desk": "在书桌前玩了一会儿电脑。",
    "window": "走到窗边，看了一会儿月色和飘雪。",
    "bed": "在床边休息了一会儿。",
}
ITEM_LOCATION = {"eat": "window", "drink": "window", "read": "desk",
                 "play": "desk", "rest": "bedside"}


def apply_action(state: HomeState, action: Action) -> tuple[str, dict]:
    character = state.character
    if action.type == "idle":
        character.activity = "idle"
        character.activity_target = ""
        character.last_path = []
        character.movement_id = uuid4().hex
        return "在小屋里安静地待了一会儿。", {"action": "idle"}
    if action.spot_id is not None:
        spot = SPOTS[action.spot_id]
        if action.type != spot["action"]:
            raise HomeError("这个位置不能执行该动作。")
        location, target_name, text = spot["location"], spot["name"], SCENE_TEXT[action.spot_id]
    else:
        instance = next((item for item in state.instances if item.id == action.target_id), None)
        if instance is None or instance.quantity == 0:
            raise HomeError("这件物品已经不在了，或已经用完。")
        definition = definitions_by_id(state)[instance.definition_id]
        if definition.usage != action.type:
            raise HomeError("这件物品不能这样使用。")
        location, target_name = ITEM_LOCATION[action.type], definition.name
        text = (f"在床边用「{target_name}」休息了一会儿。" if action.type == "rest"
                else f"{VERBS[action.type]}「{target_name}」。")
        if definition.consumable:
            instance.quantity -= 1
    for field, delta in EFFECTS.get(action.type, {}).items():
        setattr(character, field, min(100, max(0, getattr(character, field) + delta)))
    if action.type in EFFECTS:
        character.bond = min(100, character.bond + 0.2)
    path = path_between(character.location, location)
    character.location = location
    character.last_path = path
    character.movement_id = uuid4().hex
    character.activity = action.type
    character.activity_target = target_name
    return text, {"action": action.type, "target_id": action.target_id,
                  "spot_id": action.spot_id, "target_name": target_name, "path": path}


def advance_needs(state: HomeState, minutes: float) -> None:
    # The scheduler supplies only time elapsed while running, never offline time.
    minutes = min(5.0, max(0.0, minutes))
    character = state.character
    character.satiety = max(0, character.satiety - minutes * 0.15)
    character.energy = max(0, character.energy - minutes * 0.10)
    if character.satiety < 20:
        character.mood = max(15, character.mood - minutes * 0.10)
