"""Real Chromium tests. Local site routing is injected only inside this test."""

from __future__ import annotations

import asyncio
import os

import pytest

from whale_home.computer_worker import BrowserWorker

HTML = b"""<!doctype html><html><head><title>Browser fixture</title></head><body>
<h1>Ocean research</h1><form method="get" action="/search"><input aria-label="search" name="q"><button>Search</button></form>
<a href="http://whale.test/article">Read article</a><button onclick="document.querySelector('h1').textContent='Dynamic page ready'">Dynamic</button>
<a href="http://127.0.0.1/private">Unsafe redirect</a>
<div style="height:1300px">Verified local reading source</div><p>Bottom</p></body></html>"""


@pytest.fixture
async def real_browser(tmp_path, monkeypatch):
    # Optional local Chromium-family binary for CI; production still requires its
    # dedicated Playwright Chromium. The actual sandboxed browser is not mocked.
    executable = os.environ.get("WHALE_TEST_CHROMIUM_EXECUTABLE")
    if executable:
        from playwright.async_api import BrowserType

        original = BrowserType.launch_persistent_context

        async def launch(browser_type, *args, **kwargs):
            kwargs["executable_path"] = executable
            return await original(browser_type, *args, **kwargs)

        monkeypatch.setattr(BrowserType, "launch_persistent_context", launch)
        monkeypatch.setattr(BrowserType, "executable_path", property(lambda self: executable))

    async def handle(reader, writer):
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(
                b"HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nConnection: close\r\nContent-Length: "
                + str(len(HTML)).encode()
                + b"\r\n\r\n"
                + HTML
            )
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    worker = BrowserWorker(tmp_path / "profile")

    async def test_site_only(host, target_port):
        if host not in ("whale.test", "www.bing.com"):
            raise ValueError("test forbids real Internet")
        return await asyncio.open_connection("127.0.0.1", port)

    worker.proxy.connect = test_site_only
    try:
        yield worker
    finally:
        await worker.close()
        server.close()
        await server.wait_closed()


async def test_real_search_read_dynamic_tabs_scroll_screenshot(real_browser):
    w = real_browser
    environment = await w.command({"op": "environment"})
    assert environment["ready"], environment["reason"]
    page = await w.command(
        {"op": "act", "ai": True, "action": {"action": "open", "target": "http://whale.test/"}}
    )
    assert page["image"].startswith("data:image/jpeg;base64,") and len(page["image"]) > 1000
    assert "Ocean research" in page["text"]
    dynamic = next(e for e in page["elements"] if e["label"] == "Dynamic")
    result = await w.command(
        {
            "op": "act",
            "ai": True,
            "page_version": page["page_version"],
            "action": {"action": "click", "target": dynamic["id"]},
        }
    )
    assert "Dynamic page ready" in result["text"]
    with pytest.raises(RuntimeError, match="stale_page"):
        await w.command(
            {
                "op": "act",
                "ai": True,
                "page_version": page["page_version"],
                "action": {"action": "click", "target": dynamic["id"]},
            }
        )
    result = await w.command(
        {
            "op": "act",
            "ai": True,
            "action": {"action": "open", "target": "http://whale.test/article", "new_tab": True},
        }
    )
    assert len(result["tabs"]) == 2
    await w.command({"op": "act", "ai": True, "action": {"action": "scroll", "target": "down"}})
    await w.command(
        {"op": "act", "ai": True, "action": {"action": "tab", "target": result["tabs"][0]["id"]}}
    )
    # A search input is genuinely filled in Chromium, not a fake model result.
    page = await w.command({"op": "observe", "ai": True})
    element = next(e for e in page["elements"] if e["tag"] == "input")
    await w.command(
        {
            "op": "act",
            "ai": True,
            "page_version": page["page_version"],
            "action": {"action": "fill", "target": element["id"], "text": "whale sleep"},
        }
    )
    assert await w.page().locator("input").input_value() == "whale sleep"


async def test_real_private_session_manual_input_and_network_denial(real_browser):
    w = real_browser
    page = await w.command(
        {"op": "act", "manual": True, "action": {"action": "open", "target": "http://whale.test/"}}
    )
    assert page["private"]
    with pytest.raises(RuntimeError, match="authenticated_site_not_authorized"):
        await w.command({"op": "observe", "ai": True})
    page = await w.command({"op": "observe", "ai": True, "auth_policy": {"whale.test": True}})
    assert page["text"]
    with pytest.raises(ValueError):
        await w.command(
            {"op": "act", "action": {"action": "open", "target": "http://127.0.0.1/private"}}
        )
    # Proxy refuses DNS names outside the injected test host, even on a redirect.
    with pytest.raises(Exception):
        await w.command(
            {"op": "act", "action": {"action": "open", "target": "http://internal.invalid/"}}
        )


async def test_display_preserves_ai_policy_and_element_handles(real_browser):
    w = real_browser
    await w.command(
        {
            "op": "act",
            "ai": True,
            "auth_policy": {"whale.test": True},
            "action": {"action": "open", "target": "http://whale.test/"},
        }
    )
    handles = w.handles
    policy = w.auth_policy.copy()
    page = await w.command({"op": "display"})
    assert page["frame_id"] and page["session_id"] and page["viewport"]["width"] == 1100
    assert w.handles is handles and w.ai_mode is True and w.auth_policy == policy


async def test_manual_click_rejects_stale_scroll_then_accepts_current_frame(real_browser):
    w = real_browser
    before = await w.command(
        {"op": "act", "manual": True, "action": {"action": "open", "target": "http://whale.test/"}}
    )
    await w.command({"op": "act", "manual": True, "action": {"action": "scroll", "target": "down"}})
    with pytest.raises(ValueError, match="stale_frame"):
        await w.command(
            {
                "op": "act",
                "manual": True,
                "frame": before,
                "action": {"action": "manual_click", "x": 15, "y": 30},
            }
        )
    await w.command({"op": "act", "manual": True, "action": {"action": "scroll", "target": "up"}})
    frame = await w.command({"op": "display"})
    button = next(e for e in frame["elements"] if e["label"] == "Dynamic")
    x, y, width, height = button["rect"]
    result = await w.command(
        {
            "op": "act",
            "manual": True,
            "frame": frame,
            "action": {"action": "manual_click", "x": x + width / 2, "y": y + height / 2},
        }
    )
    assert "Dynamic page ready" in result["text"]


async def test_manual_history_reload_and_unchanged_frame(real_browser):
    w = real_browser
    for target in ("http://whale.test/", "http://whale.test/article"):
        await w.command(
            {"op": "act", "manual": True, "action": {"action": "open", "target": target}}
        )
    back = await w.command({"op": "act", "manual": True, "action": {"action": "back"}})
    assert back["url"] == "http://whale.test/"
    forward = await w.command({"op": "act", "manual": True, "action": {"action": "forward"}})
    assert forward["url"] == "http://whale.test/article"
    reloaded = await w.command({"op": "act", "manual": True, "action": {"action": "reload"}})
    display = await w.command({"op": "display"})
    assert reloaded["frame_id"] == display["frame_id"]


async def test_manual_completed_action_reports_capture_failure_separately(
    real_browser, monkeypatch
):
    w = real_browser
    await w.launch()

    async def failing(**kwargs):
        raise RuntimeError("capture failed")

    monkeypatch.setattr(w, "observe", failing)
    result = await w.command(
        {"op": "act", "manual": True, "action": {"action": "open", "target": "http://whale.test/"}}
    )
    assert result["operation_applied"] is True
    assert w.page().url == "http://whale.test/"
