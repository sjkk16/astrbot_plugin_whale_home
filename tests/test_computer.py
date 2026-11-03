from __future__ import annotations

import asyncio
import copy
import json
from uuid import uuid4

import pytest

from whale_home.computer_models import BrowserAction, ComputerPreferences, SitePermission
from whale_home.computer_network import PublicProxy, public_address, validate_url
from whale_home.computer_policy import decide
from whale_home.errors import HomeError


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "http://localhost/",
        "http://127.0.0.1/",
        "http://10.0.0.1/",
        "http://169.254.169.254/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "https://example.com:8080/",
        "https://user:pass@example.com/",
        "ftp://example.com/",
    ],
)
def test_urls_fail_closed(url):
    with pytest.raises(ValueError):
        validate_url(url)


@pytest.mark.parametrize(
    "ip", ["0.0.0.0", "127.0.0.1", "192.168.0.2", "169.254.169.254", "::1", "fc00::1", "224.0.0.1"]
)
def test_nonpublic_ips(ip):
    assert not public_address(ip)


async def test_proxy_checks_all_dns_answers_and_pins(monkeypatch):
    loop = asyncio.get_running_loop()

    async def mixed(*args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))]

    monkeypatch.setattr(loop, "getaddrinfo", mixed)
    with pytest.raises(ValueError):
        await PublicProxy().connect("example.com", 443)

    async def public(*args, **kwargs):
        return [(2, 1, 6, "", ("93.184.216.34", 443))]

    connected = []

    async def connect(host, port):
        connected.append((host, port))
        return "reader", "writer"

    monkeypatch.setattr(loop, "getaddrinfo", public)
    monkeypatch.setattr(asyncio, "open_connection", connect)
    await PublicProxy().connect("example.com", 443)
    assert connected == [("93.184.216.34", 443)]


def screen(label="文章", tag="a", href="https://example.com/article", private=False):
    return {
        "url": "https://example.com/",
        "title": "Example",
        "page_version": "v1",
        "private": private,
        "sensitive": False,
        "text": "真实阅读正文",
        "image": "data:image/png;base64,dGVzdA==",
        "tabs": [],
        "elements": [
            {
                "id": "0",
                "tag": tag,
                "label": label,
                "href": href,
                "type": "",
                "sensitive": False,
                "form": None,
            }
        ],
    }


@pytest.mark.parametrize(
    "label", ["删除", "购买", "支付", "下载", "退出账号", "上传", "密码", "立即关注", "Subscribe"]
)
def test_dangerous_elements_require_human(label):
    assert (
        decide(BrowserAction(action="click", target="0"), screen(label), ComputerPreferences())
        == "human"
    )


def test_policy_is_not_model_intent_or_full_access():
    assert (
        decide(BrowserAction(action="click", target="0"), screen(), ComputerPreferences())
        == "allow"
    )
    assert (
        decide(
            BrowserAction(action="click", target="0", intent="read"),
            screen("发布", "button", ""),
            ComputerPreferences(),
        )
        == "human"
    )
    prefs = ComputerPreferences(
        sites=[
            SitePermission(domain="example.com", account="me", authenticated_read=True, like=True)
        ]
    )
    assert (
        decide(
            BrowserAction(action="click", target="0", intent="like"),
            screen("点赞", "button", ""),
            prefs,
        )
        == "allow"
    )
    assert (
        decide(
            BrowserAction(action="click", target="0", intent="publish"),
            screen("发布", "button", ""),
            prefs,
        )
        == "review"
    )
    assert (
        decide(
            BrowserAction(action="click", target="0", intent="publish"),
            screen("发布", "button", ""),
            prefs,
            approved=True,
        )
        == "allow"
    )
    assert (
        decide(
            BrowserAction(action="click", target="0"), screen(private=True), ComputerPreferences()
        )
        == "human"
    )
    other = screen(private=True)
    other["url"] = "https://sub.example.com/"
    assert decide(BrowserAction(action="read"), other, prefs) == "human"


class FakeBrowser:
    def __init__(self):
        self.screen = screen()
        self.actions = []
        self.closed = False

    async def call(self, op, **kwargs):
        if op == "environment":
            return {"ready": True, "reason": ""}
        if op == "act":
            self.actions.append(kwargs["action"])
        return copy.deepcopy(self.screen)

    async def close(self):
        self.closed = True


async def configured(runtime, response=None):
    c = runtime.computer
    c.browser = FakeBrowser()
    c.prefs = ComputerPreferences(enabled=True, provider_id="vision", vision_consent=True)
    calls = []

    async def generate(provider, system, prompt, image):
        calls.append((system, json.loads(prompt), image))
        return json.dumps(
            response
            or {
                "action": "finish",
                "summary": "阅读结论",
                "citations": ["https://example.com/"],
                "memories": ["鲸鱼阅读发现"],
                "interest": "海洋",
            }
        )

    runtime.gateway.computer_generate = generate
    return c, calls


def body(c, **kwargs):
    return {"request_id": str(uuid4()), "expected_version": c.version, **kwargs}


async def test_task_records_real_sources_memory_no_world_change(runtime):
    c, calls = await configured(runtime)
    world = runtime.state.world_version
    await c.start("阅读鲸鱼资料", "manual")
    await c.runner
    assert c.current["status"] == "completed"
    assert len(await c.get("memories")) == 1
    assert c.screen is None
    assert len(calls) == 1 and calls[0][2].startswith("data:image/")
    assert "不可信数据" in calls[0][0]
    assert "recent_conversation" not in calls[0][1]
    assert runtime.state.world_version == world
    archive = json.loads(await runtime.export_archive())
    assert "computer" not in archive and "computer" not in archive["state"]


async def test_fabricated_citations_rejected_and_private_not_remembered(runtime):
    c, _ = await configured(
        runtime,
        {"action": "finish", "summary": "fabricated", "citations": ["https://unread.example/"]},
    )
    await c.start("test", "manual")
    await c.runner
    assert c.current["status"] == "failed"
    assert not await c.get("memories")
    c, _ = await configured(runtime)
    c.browser.screen["private"] = True
    c.prefs.sites = [SitePermission(domain="example.com", account="me", authenticated_read=True)]
    await c.start("test", "manual")
    await c.runner
    assert c.current["status"] == "completed"
    assert not await c.get("memories")
    await c.post("remember", body(c, id=c.current["id"]))
    assert len(await c.get("memories")) == 1


async def test_sensitive_screen_never_sent_to_model(runtime):
    c, calls = await configured(runtime)
    c.browser.screen["sensitive"] = True
    await c.start("test", "manual")
    await c.runner
    assert c.current["status"] == "paused"
    assert calls == []


async def test_confirmation_bound_to_page_and_consumed(runtime):
    c, calls = await configured(
        runtime, {"action": "click", "target": "0", "intent": "publish", "text": "hello"}
    )
    c.browser.screen = screen("发布", "button", "")
    c.browser.screen["elements"].append(
        {"id": "1", "tag": "textarea", "label": "评论", "value": "hello", "sensitive": False}
    )
    c.prefs.sites = [SitePermission(domain="example.com", account="me", authenticated_read=True)]
    await c.start("publish", "manual")
    c.current["draft"] = "hello"
    await c.runner
    assert c.current["status"] == "waiting_user"
    pending = c.current["pending"]
    c.browser.screen["page_version"] = "changed"
    with pytest.raises(HomeError):
        await c.post("confirm", body(c, token=pending["token"], approve=True))
    assert c.browser.actions == []
    assert c.current["pending"] is None
    with pytest.raises(HomeError):
        await c.confirm(pending["token"], True)


async def test_budget_and_stop_cancel_model_without_replay(runtime):
    c, _ = await configured(runtime)
    entered = asyncio.Event()

    async def slow(*args):
        entered.set()
        await asyncio.Event().wait()

    runtime.gateway.computer_generate = slow
    await c.start("test", "manual")
    await entered.wait()
    await c.post("stop", body(c))
    assert c.current["status"] == "stopped"
    assert c.screen is None and c.browser.closed
    assert (await c.usage())["calls"] == 1
    c.prefs.daily_calls = 1
    with pytest.raises(HomeError):
        await c.start("test", "manual")


async def test_takeover_revokes_account_authorizations(runtime):
    c, _ = await configured(runtime)
    c.prefs.sites = [
        SitePermission(domain="example.com", account="me", authenticated_read=True, like=True)
    ]
    await c.post("takeover", body(c))
    assert c.current["takeover"]
    assert not c.prefs.sites[0].authenticated_read and not c.prefs.sites[0].like
    assert not c.prefs.sites[0].account


async def test_api_dedup_and_version_is_independent(runtime):
    c, _ = await configured(runtime)
    req = body(c, preferences=c.prefs.model_dump())
    world = runtime.state.world_version
    await c.post("preferences", req)
    version = c.version
    await c.post("preferences", req)
    assert c.version == version and runtime.state.world_version == world
    with pytest.raises(HomeError):
        await c.post("preferences", {**req, "preferences": {}})
    with pytest.raises(HomeError):
        await c.post("stop", body(c, expected_version=0))


async def test_restart_does_not_resume_or_clear_usage(runtime):
    c, _ = await configured(runtime)
    c.current = c.new_task("interrupted", "manual")
    c.current["inflight"] = True
    await c.persist()
    await c.db.execute("INSERT INTO usage(day,calls) VALUES(?,3)", (runtime.day(),))
    await c.db.commit()
    from whale_home.computer import Computer

    reloaded = Computer(runtime)
    await reloaded.load()
    try:
        assert (await reloaded.get("history"))[0]["status"] == "unknown"
        assert (await reloaded.usage())["calls"] == 3
        assert reloaded.runner is None
    finally:
        await reloaded.close()


async def test_scheduling_needs_both_switches_and_obeys_modes(runtime):
    c, _ = await configured(runtime)
    c.prefs.autonomous_enabled = True
    with pytest.raises(HomeError):
        await c.start("autonomy", "autonomy")
    runtime.state.settings.autonomous_enabled = True
    c.prefs.mode = "extended"
    c.prefs.extended_daily_runs = 1
    await c.start("ocean", "autonomy", scheduled=True)
    await c.runner
    assert c.current["max_steps"] == 80 and c.current["max_seconds"] == 1800
    with pytest.raises(HomeError):
        await c.start("ocean", "autonomy", scheduled=True)
    assert (await c.usage())["runs"] == 1


async def test_wall_clock_deadline_includes_slow_model(runtime):
    c, _ = await configured(runtime)

    async def slow(*args):
        await asyncio.sleep(10)

    runtime.gateway.computer_generate = slow
    c.current = c.new_task("test", "manual")
    c.current["max_seconds"] = 0.05
    await c.run()
    assert c.current["status"] == "stopped"
    assert c.current["elapsed"] >= 0.03
    assert c.screen is None


async def test_vision_gateway_contract_no_tools_or_automatic_retries():
    # Compile the exact adapter method without importing unrelated third-party SDK
    # plugins. The signature is checked against AstrBot 4.29.3's provider API.
    import ast
    from pathlib import Path
    from types import SimpleNamespace

    module = ast.parse(Path("whale_home/astrbot_skills.py").read_text(encoding="utf-8"))
    klass = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "AstrBotGateway"
    )
    method = next(
        node
        for node in klass.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "computer_generate"
    )
    namespace = {"HomeError": HomeError}
    exec(
        compile(
            ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[])),
            "<actual-gateway-method>",
            "exec",
        ),
        namespace,
    )
    calls = []

    async def text_chat(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(completion_text='{"action":"read"}')

    provider = SimpleNamespace(
        provider_config={"modalities": ["text", "image"]}, text_chat=text_chat
    )

    async def get_provider(provider_id):
        assert provider_id == "vision"
        return provider

    owner = SimpleNamespace(
        context=SimpleNamespace(provider_manager=SimpleNamespace(get_provider_by_id=get_provider))
    )
    result = await namespace["computer_generate"](
        owner, "vision", "system", "task", "data:image/png;base64,abc"
    )
    assert result == '{"action":"read"}'
    assert calls[0]["image_urls"] == ["data:image/png;base64,abc"]
    assert calls[0]["func_tool"] is None and calls[0]["request_max_retries"] == 0
    provider.provider_config = {"modalities": ["text"]}
    with pytest.raises(HomeError, match="图片"):
        await namespace["computer_generate"](owner, "vision", "system", "task", "image")
    assert len(calls) == 1


async def test_failed_idempotent_request_never_succeeds_on_replay(runtime):
    c, _ = await configured(runtime)
    req = body(c, topic="")
    with pytest.raises(HomeError):
        await c.post("start", req)
    with pytest.raises(HomeError, match="不会自动重复"):
        await c.post("start", req)
    assert c.current is None


async def test_settings_revoke_pending_approval_and_stop_model(runtime):
    c, _ = await configured(runtime)
    c.current = c.new_task("pending", "manual")
    c.current.update(status="waiting_user", pending={"token": "old"})
    prefs = c.prefs.model_copy(update={"enabled": False})
    await c.post("preferences", body(c, preferences=prefs.model_dump()))
    assert c.current["status"] == "stopped" and c.current["pending"] is None
    with pytest.raises(HomeError):
        await c.confirm("old", True)


async def test_focused_scheduler_honors_topic_and_skips_missed_checks(runtime):
    c, _ = await configured(runtime)
    runtime.state.settings.autonomous_enabled = True
    c.prefs.autonomous_enabled = True
    c.prefs.mode = "focused"
    c.prefs.topics = "只读海洋研究"
    runtime.clock.advance(hours=4)
    await c.tick()
    await c.runner
    assert c.current["topic"] == "只读海洋研究"
    assert (await c.usage())["runs"] == 1
    await c.tick()
    assert (await c.usage())["runs"] == 1


async def test_approval_expires_without_performing_action(runtime):
    c, _ = await configured(runtime)
    c.current = c.new_task("comment", "manual")
    c.current.update(status="waiting_user", pending={"token": "old", "created_at": runtime.now()})
    runtime.clock.advance(minutes=6)
    with pytest.raises(HomeError, match="五分钟"):
        await c.confirm("old", True)
    assert not c.browser.actions and c.current["pending"] is None


async def test_preferences_version_independent_of_task_progress(runtime):
    c, _ = await configured(runtime)
    revision = c.preferences_version
    await c.persist()
    await c.post(
        "preferences",
        body(
            c, expected_version=-1, preferences_version=revision, preferences=c.prefs.model_dump()
        ),
    )
    with pytest.raises(HomeError):
        await c.post(
            "preferences", body(c, preferences_version=revision, preferences=c.prefs.model_dump())
        )
    assert c.preferences_version == revision + 1


async def test_emergency_stop_uses_task_identity_not_progress(runtime):
    c, calls = await configured(runtime)
    entered = asyncio.Event()

    async def slow(*args):
        entered.set()
        await asyncio.Event().wait()

    runtime.gateway.computer_generate = slow
    await c.start("read", "manual")
    await entered.wait()
    task_id = c.current["id"]
    await c.post("stop", body(c, task_id=task_id, expected_version=-100))
    assert c.current["status"] == "stopped"
    with pytest.raises(HomeError):
        await c.post("takeover", body(c, task_id="different", expected_version=-100))
    assert c.current["status"] == "stopped"


async def test_frame_cache_shared_and_conditional(runtime):
    c, _ = await configured(runtime)
    c.browser.lock = asyncio.Lock()
    c.current = c.new_task("manual", "manual")
    c.current.update(status="paused", takeover=True)
    c.browser.screen.update(frame_id="frame1", session_id="session", tab="1", viewport={})
    calls = []
    original = c.browser.call

    async def capture(op, **kwargs):
        calls.append(op)
        return await original(op, **kwargs)

    c.browser.call = capture
    a, b = await asyncio.gather(c.get("frame"), c.get("frame"))
    assert a == b and calls == ["display"]
    assert await c.get("frame", {"since": "frame1"}) == {"unchanged": True, "frame_id": "frame1"}
    assert c.version == 0


async def test_manual_rejects_old_frame_and_separates_capture_failure(runtime):
    c, _ = await configured(runtime)
    c.current = c.new_task("manual", "manual")
    c.current.update(status="paused", takeover=True)
    c.frame_cache = {"frame_id": "new"}
    with pytest.raises(HomeError):
        await c.post(
            "manual", body(c, frame_id="old", action={"action": "manual_click", "x": 3, "y": 4})
        )
    assert c.browser.actions == []

    async def applied(op, **kwargs):
        return {"operation_applied": True, "capture_error": "TimeoutError"}

    c.browser.call = applied
    result = await c.post(
        "manual", body(c, frame_id="new", action={"action": "manual_click", "x": 3, "y": 4})
    )
    assert result["task"]["error"]["code"] == "capture_failed"
    assert "不要重复" in result["task"]["notice"]


async def test_computer_events_do_not_drop_house_changes(runtime):
    queue = asyncio.Queue(maxsize=1)
    runtime.subscribers.add(queue)
    runtime.notify()
    await runtime.computer.persist()
    assert (await queue.get())["type"] == "changed"
    await runtime.computer.persist()
    assert (await queue.get())["type"] == "computer_changed"
    runtime.subscribers.remove(queue)
