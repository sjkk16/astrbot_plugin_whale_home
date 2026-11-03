"""One scene manifest supplies both authoritative activities and aligned UI geometry."""

SCENE = {
    "id": "night-bedroom-v1",
    "title": "月光小夜曲",
    "background": "./art/night-room.webp",
    "width": 1672,
    "height": 941,
    "locations": {
        "desk": {"x": 0.35, "y": 0.93, "height": 0.65, "light": "warm"},
        "window": {"x": 0.54, "y": 0.93, "height": 0.64, "light": "cool"},
        "bedside": {"x": 0.73, "y": 0.93, "height": 0.65, "light": "warm"},
    },
    "spots": [
        {"id": "bookshelf", "name": "书架", "label": "读一会儿书", "action": "read",
         "location": "desk", "description": "从书架挑一本书，在书桌前读一会儿。",
         "rect": [0.085, 0.13, 0.20, 0.29], "marker": [0.185, 0.28]},
        {"id": "desk", "name": "书桌", "label": "玩一会儿电脑", "action": "play",
         "location": "desk", "description": "去书桌前，用电脑放松一下。",
         "rect": [0.012, 0.42, 0.235, 0.25], "marker": [0.085, 0.52]},
        {"id": "window", "name": "窗边", "label": "一起看夜景", "action": "move",
         "location": "window", "description": "走到窗前，看看月亮和缓缓落下的雪。",
         "rect": [0.36, 0.14, 0.29, 0.32], "marker": [0.525, 0.26]},
        {"id": "bed", "name": "床边", "label": "在床边休息", "action": "rest",
         "location": "bedside", "description": "到温暖的床边歇一会儿。当前使用站立形象。",
         "rect": [0.80, 0.51, 0.195, 0.37], "marker": [0.895, 0.65]},
    ],
}
SPOTS = {spot["id"]: spot for spot in SCENE["spots"]}
LOCATION_ORDER = ("desk", "window", "bedside")


def path_between(start: str, end: str) -> list[str]:
    first, last = LOCATION_ORDER.index(start), LOCATION_ORDER.index(end)
    step = 1 if last >= first else -1
    return [LOCATION_ORDER[i] for i in range(first, last + step, step)]
