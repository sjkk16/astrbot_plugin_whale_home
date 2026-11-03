from .models import HomeState, ItemDefinition, ItemInstance


def builtins() -> list[ItemDefinition]:
    rows = [
        ("rice", "一碗白饭", "热乎乎的白饭，是鲸鱼娘的小小幸福。", "food", "eat", 1, 1, "utensils"),
        ("tea", "清香热茶", "慢慢喝，不着急。", "drink", "drink", 1, 1, "cup-soda"),
        ("cookie", "黄油饼干", "装在小罐子里的酥脆点心。", "food", "eat", 1, 1, "cookie"),
        ("book", "海边的故事", "一本关于远方、海风和日常的书。", "book", "read", 1, 1, "book-open"),
        ("game", "掌上游戏机", "偶尔也要给聪明的大脑放个假。", "toy", "play", 1, 1, "gamepad-2"),
        ("pillow", "柔软抱枕", "适合抱着发呆。", "toy", "rest", 1, 1, "cloud"),
        ("plant", "窗边绿植", "有新叶子在慢慢长大。", "decoration", "decorate", 1, 1, "sprout"),
        ("table", "白色书桌", "留给书本、笔记和小小的灵感。", "furniture", "decorate", 3, 2, "table-2"),
        ("chair", "浅绿椅子", "坐下来歇一会儿。", "furniture", "rest", 1, 1, "armchair"),
        ("bed", "云朵小床", "被子晒过太阳，今晚会有好梦。", "furniture", "rest", 3, 3, "bed-double"),
        ("lamp", "阅读台灯", "傍晚留一盏小灯。", "decoration", "decorate", 1, 1, "lamp-desk"),
        ("rug", "条纹地毯", "赤脚走上去也很舒服。", "decoration", "decorate", 4, 3, "rectangle-horizontal"),
    ]
    return [
        ItemDefinition(
            id=id_,
            name=name,
            description=description,
            category=category,
            usage=usage,
            width=width,
            height=height,
            blocks_movement=id_ != "rug",
            consumable=usage in ("eat", "drink"),
            builtin=True,
            icon=icon,
        )
        for id_, name, description, category, usage, width, height, icon in rows
    ]


def initial_state() -> HomeState:
    starting_items = ("bed", "table", "chair", "plant", "rug", "book", "rice", "tea", "pillow", "lamp")
    state = HomeState(definitions=builtins())
    state.instances = [
        ItemInstance(
            id=f"initial-{id_}",
            definition_id=id_,
            quantity=5 if id_ in ("rice", "tea") else 1,
            position=None,
        )
        for id_ in starting_items
    ]
    return state

