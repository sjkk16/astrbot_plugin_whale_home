import json

import pytest

from tools.demo_gateway import DemoGateway
from whale_home.catalog import initial_state
from whale_home.companion import pose_for_action
from whale_home.errors import HomeError
from whale_home.models import Action, Proposal, Reaction
from whale_home.scene import SCENE


def world(message="你好", **changes):
    value = {"trigger": "conversation", "user_message": message, "available_spots": SCENE["spots"],
             "inventory": [{"instance_id": "initial-rice", "name": "白饭", "usage": "eat", "quantity": 2},
                           {"instance_id": "demo-game", "name": "掌机", "usage": "play", "quantity": 1}]}
    value.update(changes)
    return value


@pytest.mark.parametrize("message,emotion", [
    ("你好", "happy"), ("你今天真可爱", "shy"), ("陪我想想周末做什么", "thinking"),
    ("我有点困了", "sleepy"), ("今天有点难过", "sad"), ("加班好累", "neutral"),
])
def test_every_demo_emotion_has_an_honest_idle_conversation(message, emotion):
    result = Proposal.model_validate(DemoGateway().conversation(world(message)))
    assert result.emotion == emotion
    assert result.speech
    assert result.action.type == "idle"


def test_demo_sadness_and_reflection_do_not_accidentally_consume_inventory():
    gateway = DemoGateway()
    for message in ("吃饭的时候觉得很难过", "想想要不要吃饭", "great", "这碗饭看着很不错"):
        assert gateway.conversation(world(message))["action"] == {"type": "idle"}
    assert gateway.conversation(world("我想吃饭"))["action"] == {"type": "eat", "target_id": "initial-rice"}
    empty = world("我想吃饭")
    empty["inventory"][0]["quantity"] = 0
    assert gateway.conversation(empty)["action"] == {"type": "idle"}


def test_demo_prefers_the_actual_computer_spot_not_a_handheld_prop():
    result = DemoGateway().conversation(world("一起玩电脑"))
    action = Action.model_validate(result["action"])
    assert action.spot_id == "desk"
    assert action.target_id is None
    assert pose_for_action(initial_state(), action) == "neutral"


def test_demo_can_use_fixed_read_and_rest_without_consuming_an_item():
    for message, spot, pose in (("一起读书", "bookshelf", "read"), ("去床边休息", "bed", "rest")):
        result = DemoGateway().conversation(world(message, inventory=[]))
        action = Action.model_validate(result["action"])
        assert action.spot_id == spot
        assert pose_for_action(initial_state(), action) == pose


def test_demo_rotates_per_topic_instead_of_repeating_due_to_interleaved_activity():
    gateway = DemoGateway()
    compliments = []
    for _ in range(3):
        compliments.append(gateway.conversation(world("你真可爱"))["speech"])
        gateway.conversation(world("你好"))
    assert len(set(compliments)) == 3


@pytest.mark.parametrize("trigger", ["direct_interaction", "proactive_greeting"])
def test_demo_reactions_are_speech_only_and_respect_latest_serious_context(trigger):
    gateway = DemoGateway()
    value = world(trigger=trigger, completed_interaction={"kind": "pet", "action": "pet"},
                  recent_conversation=[{"role": "user", "text": "我有点难过"}])
    result = Reaction.model_validate(gateway.reaction(value))
    assert result.emotion == "sad"
    assert "不用勉强" in result.speech
    value["recent_conversation"].append({"role": "user", "text": "现在好些了，你真可爱"})
    assert gateway.reaction(value)["emotion"] != "sad"
    assert set(gateway.reaction(value)) == {"speech", "emotion"}


async def test_offline_gateway_is_labeled_and_rejects_other_providers():
    gateway = DemoGateway()
    assert "不调用在线模型" in (await gateway.providers())[0]["name"]
    with pytest.raises(HomeError):
        await gateway.generate("some-remote-provider", "", json.dumps(world()))
    result = await gateway.generate("local-demo", "", json.dumps(world("你真可爱")))
    assert Proposal.model_validate_json(result).emotion == "shy"


@pytest.mark.parametrize("message", ["别逗我，认真说", "你很可爱，但别叫我鱼片", "不要开玩笑", "我不喜欢这样，别调侃我"])
def test_offline_conversation_respects_explicit_boundaries(message):
    result = DemoGateway().conversation(world(message))
    assert result["emotion"] == "neutral"
    assert result["action"] == {"type": "idle"}
    assert "尊重" in result["speech"]


@pytest.mark.parametrize("trigger", ["direct_interaction", "proactive_greeting"])
def test_offline_reaction_respects_latest_boundary(trigger):
    result = DemoGateway().reaction(world(trigger=trigger, completed_interaction={"action": "pet"},
                                         recent_conversation=[{"role": "user", "text": "先别开玩笑，认真一点"}]))
    assert set(result) == {"speech", "emotion"}
    assert result["emotion"] == "neutral"
    assert "边界" in result["speech"]


@pytest.mark.parametrize("message", ["不要吃饭", "我不想玩游戏", "先不去窗边看月亮", "不用喝茶"])
def test_offline_declining_an_action_cannot_spend_inventory(message):
    assert DemoGateway().conversation(world(message))["action"] == {"type": "idle"}
