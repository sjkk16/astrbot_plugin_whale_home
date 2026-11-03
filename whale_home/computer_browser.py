"""Async IPC client. No external HTTP control port or background shell is exposed."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
from pathlib import Path

from .errors import HomeError


class BrowserClient:
    def __init__(self, directory: Path, browsers_path: Path | None = None):
        self.directory = directory
        self.browsers_path = browsers_path
        self.process = None
        self.lock = asyncio.Lock()
        self.active_task = None
        self.active_op = None

    async def call(self, op: str, **payload):
        async with self.lock:
            self.active_task = asyncio.current_task()
            self.active_op = op
            try:
                if self.process is None or self.process.returncode is not None:
                    kwargs = (
                        {"creationflags": subprocess.CREATE_NO_WINDOW}
                        if os.name == "nt"
                        else {"start_new_session": True}
                    )
                    env = dict(os.environ)
                    if self.browsers_path is not None:
                        env["PLAYWRIGHT_BROWSERS_PATH"] = str(self.browsers_path)
                    self.process = await asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "whale_home.computer_worker",
                        str(self.directory),
                        cwd=str(Path(__file__).resolve().parents[1]),
                        env=env,
                        stdin=asyncio.subprocess.PIPE,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.DEVNULL,
                        limit=8 * 1024 * 1024,
                        **kwargs,
                    )
                self.process.stdin.write((json.dumps({"op": op, **payload}) + "\n").encode())
                await self.process.stdin.drain()
                reply = await asyncio.wait_for(self.process.stdout.readline(), 40)
                result = json.loads(reply)
                if not result["ok"]:
                    messages = {
                        "navigation_denied": "网页或安全出口拒绝访问；请检查地址或接管，不会自动重试。",
                        "navigation_failed": "网页返回错误，未读取成功；请检查地址或接管。",
                        "stale_frame": "画面已变化，请查看新截图后重新操作。",
                        "stale_page": "网页已变化，请重新查看后继续。",
                        "authenticated_site_not_authorized": "当前账号网站未获授权，请接管并检查网站权限。",
                    }
                    raise HomeError(
                        messages.get(result["error"], "浏览器操作未完成；请检查环境或接管页面。"),
                        409,
                        result["error"],
                    )
                return result["result"]
            except HomeError:
                raise
            except BaseException:
                # Never reuse a stream after a timed-out/cancelled request (stale response).
                await self._kill()
                raise
            finally:
                self.active_task = None
                self.active_op = None

    def interrupt(self):
        task = self.active_task
        if task and task is not asyncio.current_task() and not task.done():
            task.cancel()

    async def _kill(self):
        if self.process:
            if self.process.returncode is None:
                # Close the input first so the worker can release its own Chromium.
                if self.process.stdin:
                    self.process.stdin.close()
                try:
                    await asyncio.wait_for(self.process.wait(), 2)
                except TimeoutError:
                    if os.name == "nt":
                        killer = await asyncio.create_subprocess_exec(
                            "taskkill",
                            "/PID",
                            str(self.process.pid),
                            "/T",
                            "/F",
                            stdout=asyncio.subprocess.DEVNULL,
                            stderr=asyncio.subprocess.DEVNULL,
                            creationflags=subprocess.CREATE_NO_WINDOW,
                        )
                        await killer.wait()
                    else:
                        import signal

                        # The subprocess was created as the leader of its own session.
                        if os.getpgid(self.process.pid) == self.process.pid:
                            os.killpg(self.process.pid, signal.SIGKILL)
                    if self.process.returncode is None:
                        with contextlib.suppress(ProcessLookupError):
                            self.process.kill()
            with contextlib.suppress(Exception):
                await self.process.wait()
            self.process = None

    async def close(self):
        async with self.lock:
            if self.process and self.process.returncode is None:
                try:
                    self.process.stdin.close()
                    await asyncio.wait_for(self.process.wait(), 5)
                except (TimeoutError, Exception):
                    await self._kill()
            self.process = None
