"""Dedicated Chromium process, controlled only by a finite JSON-lines protocol."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote
from uuid import uuid4

from .computer_network import PublicProxy, validate_url

# Fixed application code, never model-supplied JavaScript.
ELEMENT_INFO = """e => ({rect:[e.getBoundingClientRect().x,e.getBoundingClientRect().y,e.getBoundingClientRect().width,e.getBoundingClientRect().height],tag:e.tagName.toLowerCase(),role:e.getAttribute('role')||'',
 label:(e.getAttribute('aria-label')||e.innerText||e.getAttribute('placeholder')||e.getAttribute('name')||'').slice(0,180),
 href:e.tagName==='A'?e.href:'',type:e.getAttribute('type')||'',
 editable:e.isContentEditable,pressed:e.getAttribute('aria-pressed')==='true',value:(e.type==='password'?'':(e.value||(e.isContentEditable?e.innerText:''))).slice(0,8001),form:e.form?{method:e.form.method,action:e.form.action}:null,
 sensitive:e.type==='password'||/password|otp|captcha|验证码|密码|autocomplete="username"|one-time-code/i.test(e.outerHTML.slice(0,400))})"""
LOCATOR = "a,button,input,textarea,select,[role=button],[contenteditable=true]"


class BrowserWorker:
    def __init__(self, profile: Path):
        self.profile = profile
        self.playwright = None
        self.context = None
        self.proxy = PublicProxy()
        self.pages = {}
        self.selected = ""
        self.next_id = 0
        self.handles = {}
        self.session_id = uuid4().hex
        self.ledger = profile.parent / "private-domains.json"
        try:
            self.private_domains = set(json.loads(self.ledger.read_text()))
        except (FileNotFoundError, ValueError):
            self.private_domains = set()
        self.manual = False
        self.auth_policy: dict = {}
        self.ai_mode = False
        self.navigation_domains = []
        self.blocked_domain = ""

    async def launch(self):
        if self.context:
            return
        from playwright.async_api import async_playwright

        self.playwright = await async_playwright().start()
        try:
            if not Path(self.playwright.chromium.executable_path).is_file():
                raise RuntimeError("browser_missing")
            port = await self.proxy.start()
            self.profile.mkdir(parents=True, exist_ok=True)
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(self.profile),
                headless=True,
                chromium_sandbox=True,
                viewport={"width": 1100, "height": 760},
                accept_downloads=False,
                service_workers="block",
                proxy={"server": f"http://127.0.0.1:{port}", "bypass": "<-loopback>"},
                args=[
                    "--disable-quic",
                    "--disable-extensions",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--disable-component-update",
                    "--disable-features=WebRtcHideLocalIpsWithMdns",
                    "--force-webrtc-ip-handling-policy=disable_non_proxied_udp",
                    "--proxy-bypass-list=<-loopback>",
                ],
            )
            self.context.on("page", self.register)
            await self.context.route("**/*", self.guard_route)
            if hasattr(self.context, "route_web_socket"):
                await self.context.route_web_socket("**/*", lambda ws: ws.close())
            for page in self.context.pages:
                self.register(page)
            if not self.pages:
                self.register(await self.context.new_page())
        except BaseException:
            with contextlib.suppress(Exception):
                await self.close()
            raise

    def register(self, page):
        if page in self.pages.values():
            return
        self.next_id += 1
        self.pages[str(self.next_id)] = page
        self.selected = str(self.next_id)
        page.set_default_timeout(8000)
        page.on("download", lambda download: asyncio.create_task(download.cancel()))
        page.on("dialog", lambda dialog: asyncio.create_task(dialog.dismiss()))

    async def guard_route(self, route):
        from .computer_models import domain_of

        try:
            validate_url(route.request.url)
            if self.manual:
                host = domain_of(route.request.url)
                if host not in self.private_domains:
                    self.private_domains.add(host)
                    self.ledger.write_text(
                        json.dumps(sorted(self.private_domains)), encoding="utf-8"
                    )
            if self.ai_mode and route.request.is_navigation_request():
                host = domain_of(route.request.url)
                if (
                    self.navigation_domains
                    and host not in self.navigation_domains
                    and host not in ("www.bing.com", "bing.com", "duckduckgo.com")
                ):
                    self.blocked_domain = host
                    await route.abort("blockedbyclient")
                    return
                if host in self.private_domains and not self.auth_policy.get(host):
                    self.blocked_domain = host
                    await route.abort("blockedbyclient")
                    return
            await route.continue_()
        except Exception:
            await route.abort("blockedbyclient")

    def page(self):
        self.pages = {key: page for key, page in self.pages.items() if not page.is_closed()}
        if self.selected not in self.pages:
            self.selected = next(iter(self.pages), "")
        if not self.selected:
            raise RuntimeError("no_page")
        return self.pages[self.selected]

    async def observe(self, *, bind_handles=True):
        page = self.page()
        from .computer_models import domain_of

        host = domain_of(page.url)
        if (
            bind_handles
            and self.ai_mode
            and host in self.private_domains
            and not self.auth_policy.get(host)
        ):
            raise RuntimeError("authenticated_site_not_authorized")
        visible, elements = [], []
        all_handles = await page.locator(LOCATOR).element_handles()
        previous = list(self.handles.values())
        try:
            for handle in all_handles:
                if await handle.is_visible():
                    info = await handle.evaluate(ELEMENT_INFO)
                    info["id"] = str(len(visible))
                    visible.append(handle)
                    elements.append(info)
                if len(visible) >= 160:
                    break
            if bind_handles:
                self.handles = {str(i): handle for i, handle in enumerate(visible)}
        finally:
            # UI sampling must not accumulate remote DOM references or dispose AI-owned handles.
            retained = set(self.handles.values())
            for handle in set(all_handles + previous) - retained:
                with contextlib.suppress(Exception):
                    await handle.dispose()
        sensitive = any(element["sensitive"] for element in elements)
        body = (
            (await page.locator("body").inner_text(timeout=4000))[:18000]
            if await page.locator("body").count()
            else ""
        )
        viewport = await page.evaluate(
            "() => ({x:scrollX,y:scrollY,width:innerWidth,height:innerHeight})"
        )
        digest = hashlib.sha256(
            json.dumps(
                [self.session_id, self.selected, page.url, elements, body, viewport],
                ensure_ascii=False,
            ).encode()
        ).hexdigest()
        image = await page.screenshot(type="jpeg", quality=65)
        title = (await page.title())[:300]
        tabs = [{"id": key, "url": p.url} for key, p in self.pages.items()]
        frame_id = hashlib.sha256(
            digest.encode() + image + json.dumps([title, tabs]).encode()
        ).hexdigest()
        return {
            "frame_id": frame_id,
            "session_id": self.session_id,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "viewport": viewport,
            "page_version": digest,
            "url": page.url,
            "title": title,
            "tab": self.selected,
            "tabs": tabs,
            "text": body,
            "elements": elements,
            "sensitive": sensitive,
            "private": host in self.private_domains,
            "blocked_domain": self.blocked_domain,
            "image": "data:image/jpeg;base64," + base64.b64encode(image).decode(),
            "width": 1100,
            "height": 760,
        }

    async def command(self, data):
        op = data.get("op")
        if op == "environment":
            from .computer_environment import diagnose

            return await diagnose()
        if op == "display":
            # A UI read must never change the authorization mode or the AI handle table.
            if self.context is None:
                return None
            return await self.observe(bind_handles=False)
        if op == "close":
            await self.close()
            return {}
        await self.launch()
        self.ai_mode = bool(data.get("ai", False))
        self.private_domains.update(data.get("private_domains", []))
        self.manual = bool(data.get("manual", False))
        self.auth_policy = data.get("auth_policy", {})
        self.navigation_domains = data.get("navigation_domains", [])
        self.blocked_domain = ""
        if self.manual:
            from .computer_models import domain_of

            host = domain_of(self.page().url)
            if host:
                self.private_domains.add(host)
                self.ledger.write_text(json.dumps(sorted(self.private_domains)), encoding="utf-8")
        if op == "observe":
            return await self.observe()
        if op == "clear":
            await self.context.clear_cookies()
            for page in self.pages.values():
                with contextlib.suppress(Exception):
                    await page.goto("about:blank")
            return {}
        if op != "act":
            raise ValueError("unknown_operation")
        action = data["action"]
        if action.get("action", "").startswith("manual_"):
            expected = data.get("frame")
            if not expected:
                raise ValueError("stale_frame")
            actual = await self.observe(bind_handles=False)
            if any(
                actual.get(key) != expected.get(key)
                for key in ("session_id", "tab", "page_version", "viewport")
            ) or (
                action.get("action") == "manual_click"
                and actual["frame_id"] != expected.get("frame_id")
            ):
                raise ValueError("stale_frame")

        name = action["action"]
        target, text = action.get("target", ""), action.get("text", "")
        page = self.page()
        if data.get("page_version"):
            observed = await self.observe()
            if observed["page_version"] != data["page_version"]:
                raise RuntimeError("stale_page")
        if name in ("open", "search"):
            url = (
                target
                if name == "open"
                else (
                    "https://www.bing.com/search?q="
                    if data.get("search_engine") != "duckduckgo"
                    else "https://duckduckgo.com/?q="
                )
                + quote(text)
            )
            validate_url(url)
            if action.get("new_tab"):
                if len(self.pages) >= 6:
                    raise RuntimeError("tab_limit")
                page = await self.context.new_page()
                self.register(page)
            response = await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self.check_navigation(response)
        elif name in ("click", "fill"):
            if target not in self.handles:
                raise ValueError("stale_element")
            handle = self.handles[target]
            if name == "click":
                await handle.click(timeout=8000, no_wait_after=True)
            else:
                await handle.fill(text, timeout=8000)
        elif name == "scroll":
            await page.mouse.wheel(0, -570 if target == "up" else 570)
        elif name == "back":
            response = await page.go_back(wait_until="domcontentloaded", timeout=20000)
            self.check_navigation(response)
        elif name in ("forward", "reload") and not self.ai_mode:
            method = page.go_forward if name == "forward" else page.reload
            response = await method(wait_until="domcontentloaded", timeout=20000)
            self.check_navigation(response)
        elif name == "tab":
            if target not in self.pages:
                raise ValueError("unknown_tab")
            self.selected = target
        elif name == "close_tab":
            if target not in self.pages or len(self.pages) < 2:
                raise ValueError("invalid_tab")
            await self.pages[target].close()
        elif name == "manual_click" and not self.ai_mode:
            x, y = float(action["x"]), float(action["y"])
            if not (0 <= x < 1100 and 0 <= y < 760):
                raise ValueError("invalid_coordinates")
            await page.mouse.click(x, y)
        elif name == "manual_text" and not self.ai_mode:
            if len(text) > 8000:
                raise ValueError("input_too_large")
            await page.keyboard.insert_text(text)
        elif name == "manual_key" and not self.ai_mode:
            if target not in ("Enter", "Tab", "Backspace", "Escape", "ArrowDown", "ArrowUp"):
                raise ValueError("invalid_key")
            await page.keyboard.press(target)
        elif name != "read":
            raise ValueError("unsupported_action")
        await page.wait_for_timeout(200)
        try:
            return await self.observe()
        except Exception as exc:
            if not self.ai_mode:
                return {"operation_applied": True, "capture_error": type(exc).__name__}
            raise

    @staticmethod
    def check_navigation(response):
        if response and response.status >= 400:
            raise RuntimeError(
                "navigation_denied" if response.status in (401, 403) else "navigation_failed"
            )

    async def close(self):
        if self.context:
            await self.context.close()
            self.context = None
        await self.proxy.close()
        if self.playwright:
            await self.playwright.stop()
            self.playwright = None


async def main():
    worker = BrowserWorker(Path(sys.argv[1]).resolve())
    try:
        while line := await asyncio.to_thread(sys.stdin.buffer.readline):
            try:
                if len(line) > 131072:
                    raise ValueError("request_too_large")
                result = await worker.command(json.loads(line))
                output = {"ok": True, "result": result}
            except Exception as error:
                # Do not leak browser exception URLs, input values or process output.
                code = (
                    str(error)
                    if str(error)
                    in (
                        "browser_missing",
                        "stale_page",
                        "stale_element",
                        "stale_frame",
                        "navigation_denied",
                        "navigation_failed",
                        "authenticated_site_not_authorized",
                    )
                    else type(error).__name__
                )
                output = {"ok": False, "error": code}
            sys.stdout.write(json.dumps(output, ensure_ascii=True) + "\n")
            sys.stdout.flush()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
