"""Conservative DOM-bound policy; model intent never grants permission."""

from __future__ import annotations

import re

from .computer_models import BrowserAction, ComputerPreferences, domain_of
from .computer_network import validate_url

FORBIDDEN = re.compile(
    r"取消|unlike|unfavorite|unbookmark|购买|支付|下单|结算|删除|注销|退出|密码|验证码|上传|下载|订阅|打赏|转账|关注|buy|purchase|checkout|pay\b|delete|remove|logout|sign.?out|password|captcha|upload|download|subscribe|follow",
    re.I,
)
WRITE = {
    "like": r"^(赞|点赞|喜欢|like)(\s|$|\d)",
    "favorite": r"收藏|bookmark|favorite",
    "comment": r"评论|回复|comment|reply",
    "publish": r"发布|发表|post|publish",
    "message": r"私信|发送|send|message",
}
SEARCH = re.compile(r"搜索|搜尋|search|^q$|query", re.I)


def decide(
    action: BrowserAction, screen: dict, prefs: ComputerPreferences, *, approved=False
) -> str:
    """Return allow/review/human. Only allow/review may reach the AI executor."""
    host = domain_of(screen.get("url", ""))
    permission = next((site for site in prefs.sites if site.domain == host), None)
    if screen.get("sensitive"):
        return "human"
    if screen.get("private") and not (
        permission and permission.authenticated_read and permission.account
    ):
        return "human"
    if action.action in ("open", "search"):
        if action.action == "open":
            validate_url(action.target)
            if FORBIDDEN.search(action.target):
                return "human"
        return "allow"
    if action.action in ("read", "scroll", "back", "tab", "close_tab", "finish", "ask_user"):
        return "allow"
    element = next((e for e in screen.get("elements", []) if e["id"] == action.target), None)
    if not element or element.get("sensitive"):
        return "human"
    label = element.get("label", "")
    descriptor = label + " " + element.get("href", "") + " " + element.get("type", "")
    if FORBIDDEN.search(descriptor):
        return "human"
    if action.intent != "read":
        if not re.search(WRITE[action.intent], label, re.I):
            return "human"
        if not permission or not permission.account:
            return "human"
        if action.intent in ("like", "favorite"):
            return (
                "allow"
                if getattr(permission, action.intent)
                and action.action == "click"
                and not element.get("pressed")
                else "human"
            )
        return "allow" if approved else "review"
    if any(re.search(pattern, label, re.I) for pattern in WRITE.values()):
        return "human"
    if action.action == "click" and element.get("tag") == "a" and element.get("href"):
        validate_url(element["href"])
        # Navigation links can still have site-defined effects; stay conservative.
        if re.search(r"[?&](action|do|delete|token|confirm)=", element["href"], re.I):
            return "human"
        return "allow"
    if (
        action.action == "click"
        and element.get("tag") == "button"
        and re.fullmatch(
            r"下一页|上一页|next page|previous page|next|previous|展开全文|阅读更多",
            label.strip(),
            re.I,
        )
    ):
        if not element.get("form") or element["form"].get("method", "").lower() == "get":
            return "allow"
    if SEARCH.search(label):
        if (
            action.action == "fill"
            and element.get("tag") == "input"
            and element.get("type") in ("", "text", "search")
        ):
            return "allow"
        if action.action == "click" and element.get("tag") in ("button", "input"):
            form = element.get("form")
            if form and form.get("method", "").lower() == "get":
                return "allow"
    return "human"
