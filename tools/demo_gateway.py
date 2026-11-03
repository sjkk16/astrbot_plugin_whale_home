"""Explicit offline dialogue script for the local preview, not a language model."""
from __future__ import annotations

import asyncio
import json
import re

from whale_home.errors import HomeError

SERIOUS_WORDS = ("难过", "伤心", "不开心", "压力", "焦虑", "失落", "想哭")


BOUNDARY_WORDS = ("别开玩笑", "不要开玩笑", "不开玩笑", "别逗", "不要逗", "别调侃", "不要调侃",
                  "别叫我", "不要叫我", "认真说", "认真点", "认真一点", "别贫", "不喜欢这样")


class DemoGateway:
    def __init__(self):
        self.sequence = 0
        self.positions: dict[str, int] = {}

    def pick(self, topic: str, lines: tuple[str, ...]) -> str:
        index = self.positions.get(topic, 0)
        self.positions[topic] = index + 1
        return lines[index % len(lines)]

    async def providers(self):
        return [{"id": "local-demo", "name": "本地演示 · 不调用在线模型"}]

    async def capabilities(self):
        return [
            {"name": "demo_weather", "kind": "tool", "source": "本地模拟 · 不联网", "description": "返回固定的演示天气，不查询真实天气。"},
            {"name": "demo_slow", "kind": "tool", "source": "本地模拟 · 不联网", "description": "等待8秒的模拟工具，用来验证停止与多页面同步。"},
            {"name": "demo_companion", "kind": "skill", "source": "本地模拟 · 无脚本", "description": "演示先读取技能指引，再使用已授权的天气工具。"},
            {"name": "demo_detached", "kind": "tool", "source": "兼容性演示", "description": "独立后台任务（首版不支持）", "available": False, "reason": "首版不支持独立后台任务"},
        ]

    async def generate(self, provider_id: str, system_prompt: str, prompt: str, *, execution=None):
        if provider_id != "local-demo":
            raise HomeError("本地预览只提供离线演示模型。")
        await asyncio.sleep(.3)
        self.sequence += 1
        world = json.loads(prompt)
        if world.get("trigger") in ("direct_interaction", "proactive_greeting"):
            result = self.reaction(world)
        else:
            result = self.conversation(world)
        if execution is not None:
            text = world.get("user_message") or ""
            from whale_home.models import Capability
            available = [Capability.model_validate(item) for item in await self.capabilities()]
            names = {item.name for item in available if item.available and execution.owner.allowed(item)}
            async def instruction():
                return "模拟技能：可用时调用 demo_weather，必须明确说明是模拟天气。"
            async def weather():
                await asyncio.sleep(.15)
                return "模拟天气：晴，22℃。不是实时查询。"
            async def slow():
                await asyncio.sleep(8)
                return "模拟等待已结束，没有联网或修改文件。"
            if "demo_companion" in names and ("技能" in text or not text):
                await execution.invoke("skill", "demo_companion", instruction)
            name = "demo_slow" if "慢速" in text else "demo_weather"
            if name in names and (not text or any(word in text for word in ("天气", "技能", "慢速"))):
                output = await execution.invoke("tool", name, slow if name == "demo_slow" else weather)
                result["speech"] = "【本地模拟工具】" + output
        return json.dumps(result, ensure_ascii=False)

    def reaction(self, world: dict) -> dict:
        latest = next((row["text"] for row in reversed(world.get("recent_conversation", []))
                       if row["role"] == "user"), "")
        if any(word in latest for word in BOUNDARY_WORDS):
            return {"speech": self.pick("boundary-reaction", (
                "收到，我会尊重你刚才说的边界。这次不逗你，慢慢来。",
                "好，先收起玩笑。这件小事我收到了，你不必配合我的语气。",
            )), "emotion": "neutral"}
        if any(word in latest for word in SERIOUS_WORDS):
            return {"speech": self.pick("gentle-reaction", (
                "嗯，先不闹你。这点小事我收到了，你不用勉强自己马上开心。",
                "收到啦。今天不需要打起精神来配合我的玩笑，慢慢待着也可以。",
            )), "emotion": "sad"}
        completed = world.get("completed_interaction", {})
        name = completed.get("target_name", "这份心意")
        kind = "proactive" if world.get("trigger") == "proactive_greeting" else completed.get("action", "other")
        if completed.get("kind") == "pet":
            kind = "pet"
        lines = {
            "proactive": ("窗外的月亮今天也没交房租。算了，它负责照明，我们负责摸鱼。你忙你的。",
                          "突然想到，休息不需要先拿满分。今天的小家营业项目：慢慢来。",
                          "我宣布今晚的待办清单加一项：给自己留点空白。嗯，这项可以不打勾。"),
            "pet": ("哼，手法还行。这颗聪明脑袋暂时批准你摸一下。",
                    "你这是在给鲸鱼充电？好吧，电量加一格。",
                    "发型乱了——看在是你的份上，这次维修费免了。"),
            "eat": (f"「{name}」到位。别笑，聪明脑袋也是要靠饭供电的。", "这一口吃到了。你果然掌握了我的补给密码。"),
            "drink": (f"「{name}」收到，慢慢喝。今天不跟开水比谁更着急。", "饮品到位，今晚的配置有点豪华。"),
            "read": ("好，书翻开了。要是看到精彩的地方，别在我前面笑出声。", "脑袋换到阅读频道。先看两页，不立读完一本的旗。"),
            "play": ("快乐时间开始。输赢先放一边，嘴硬我肯定不会输。", "给大脑放个假，认真摸鱼也是一种态度。"),
            "rest": ("先歇一下。我没在偷懒，我是在给聪明才智安排冷却。", "站这儿缓缓也好，不用每一分钟都证明自己。"),
            "move": ("窗边已到站。月亮负责发光，我们负责不加班。", "来，给眼睛放个远一点的假。"),
            "gift": (f"「{name}」？眼光不错嘛。心意收好，我会认真喜欢它。", "收下啦。这次不吐槽，真的很喜欢。"),
        }.get(kind, ("收到。这份日常我记下了，嘴上不夸，心里给你加分。",))
        emotion = {"pet": "shy", "gift": "shy", "rest": "sleepy", "read": "thinking"}.get(kind, "happy")
        return {"speech": self.pick("reaction-" + kind, lines), "emotion": emotion}

    def conversation(self, world: dict) -> dict:
        message = world.get("user_message") or ""
        action = {"type": "idle"}
        emotion = "happy"
        if any(word in message for word in BOUNDARY_WORDS):
            emotion = "neutral"
            speech = self.pick("boundary", (
                "好，收起玩笑。我会尊重你的边界，接下来认真听你说。",
                "明白，这样的称呼或玩笑先停下。你不需要迁就我的语气。",
            ))
        elif any(word in message for word in SERIOUS_WORDS):
            emotion = "sad"
            speech = self.pick("sad", (
                "那先不逗你。今天已经够难了，不用再给自己加一道‘必须开心’的题。我在这儿，慢慢说也行。",
                "听到了。难过的时候不必急着交一份乐观报告，想说什么就按自己的速度说。",
                "嗯，今天的小玩笑先收起来。你不用把事情讲得很有条理，我会认真听。",
            ))
        elif any(word in message for word in ("可爱", "好看", "漂亮", "聪明", "喜欢你", "夸夸")):
            emotion = "shy"
            speech = self.pick("shy", (
                "突然夸这么认真，我差点没接住。咳，先收下了，不许说我偷笑。",
                "眼光不错嘛……这句本来想说得很镇定的，结果嘴角不太配合。",
                "这份夸奖我收好了。没有偷偷高兴，只是心情刚好往上蹦了一点。",
            ))
        elif any(word in message for word in ("想想", "想一想", "思考", "怎么选", "主意", "拿不定", "纠结")):
            emotion = "thinking"
            speech = self.pick("thinking", (
                "让我想想。先别一口气解决所有问题，把最在意的那一件挑出来，其他的暂时排队。",
                "聪明脑袋正在转弯。我们可以先列两个最像样的选择，不必把每条岔路都走一遍。",
                "嗯，先给这个问题一点空白。想法有时候像猫，追得太紧反而不肯出来。",
            ))
        elif "困" in message or "睡" in message:
            emotion = "sleepy"
            speech = self.pick("sleepy", (
                "眼皮都快发来辞职申请了？那就早点休息。今晚的月亮，我替你看一会儿。",
                "省电模式可以上线了。今天没做完的事不用现在补考，先照顾困困的脑袋。",
            ))
        else:
            action, activity = self.requested_action(world, message)
            if action["type"] != "idle":
                emotion = {"read": "thinking", "rest": "sleepy"}.get(action["type"], "happy")
                speech = self.pick("activity-" + action["type"], (
                    f"好，和「{activity}」待一会儿。今天不卷效率，快乐也不用写总结。",
                    f"「{activity}」安排上了。先把生活调到慢一点的频道。",
                ))
            elif "累" in message or "加班" in message:
                emotion = "neutral"
                speech = self.pick("tired", ("今天的脑袋已经认真营业过了，休息不算旷工。把肩膀放下来一点，先喘口气。",
                                           "这会儿不用再证明自己有多能干。先缓缓，今天已经够忙了。"))
            elif "摸鱼" in message:
                speech = self.pick("banter", ("批准。不过我得澄清一下：摸鱼不等于摸鲸鱼——后者要来找我单独申请。",
                                            "摸鱼小队收到。今天的考核项目是放松，不许偷偷卷这个。"))
            else:
                speech = self.pick("casual", ("我在呢，脑袋也没下班。今晚不用表演很厉害，轻松待着就好。",
                                            "听见啦。先别急着把人生整理成待办清单，留点地方给突发的快乐。",
                                            "嗯，你说的我接住了。虽然我偶尔偷懒，但陪聊这件事暂时没有外包。"))
        return {"speech": speech, "emotion": emotion, "action": action}

    @staticmethod
    def requested_action(world: dict, message: str) -> tuple[dict, str]:
        # Mentioning an action while declining it must not spend real inventory.
        if re.search(r"(?:不要|别|不想|不愿|不打算|不需要|不用|先不).{0,8}(?:吃|喝|玩|读|看|休息|歇)", message):
            return {"type": "idle"}, ""
        words = {"read": ("读书", "看书", "读一", "阅读", "翻书"), "eat": ("吃饭", "吃点", "吃一", "来碗饭"),
                 "drink": ("喝茶", "喝点", "喝一", "饮茶"), "play": ("玩游戏", "玩一", "玩会", "玩电脑", "玩掌机"),
                 "rest": ("休息", "歇一", "歇会"), "move": ("看夜景", "看月亮", "去窗边")}
        preferred = next((kind for kind, phrases in words.items() if any(word in message for word in phrases)
                          or re.search(r"\b" + kind + r"\b", message, re.I)), None)
        if world.get("trigger") == "autonomous_life" and not message:
            preferred = "read"
        if not preferred:
            return {"type": "idle"}, ""
        target = next((item for item in world.get("inventory", [])
                       if item["usage"] == preferred and item["quantity"] > 0), None)
        spot = next((spot for spot in world.get("available_spots", []) if spot["action"] == preferred), None)
        if spot and (not target or "电脑" in message or "床边" in message or "书架" in message):
            return {"type": preferred, "spot_id": spot["id"]}, spot["name"]
        if target:
            return {"type": preferred, "target_id": target["instance_id"]}, target["name"]
        return {"type": "idle"}, ""
