"""Explicit-user-only Chromium installation. No model tools or arbitrary command input."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import re
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .errors import HomeError

ACTIVE = {"preparing", "downloading", "verifying", "cancelling"}
TIMEOUT_SECONDS = 20 * 60


def clean_output(text: str) -> str:
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", "", text)
    text = re.sub(r"(https?://)[^\s/@]+:[^\s/@]+@", r"\1[redacted]@", text)
    text = re.sub(r"(https?://[^\s?#]+)[?#][^\s]*", r"\1?[redacted]", text)
    return text.strip()[:350]


class ChromiumDownload:
    def __init__(self, directory: Path, notify, verify, prepare):
        self.directory = directory
        self.browsers = directory / "browsers"
        self.record = directory / "download-status.json"
        self.notify = notify
        self.verify = verify
        self.prepare = prepare
        self.task = None
        self.process = None
        self.lock = asyncio.Lock()
        self.closed = False
        self.last_notice = 0.0
        self.state = {
            "id": None,
            "version": 0,
            "status": "idle",
            "message": "浏览器未随插件打包，可按需下载。",
            "lines": [],
            "progress": None,
        }

    @property
    def active(self):
        return self.state["status"] in ACTIVE

    def load(self):
        try:
            saved = json.loads(self.record.read_text(encoding="utf-8"))
            if isinstance(saved, dict) and isinstance(saved.get("version"), int):
                self.state.update({key: saved[key] for key in self.state if key in saved})
                if self.active:
                    self.update(
                        status="interrupted",
                        message="服务已重启，上次下载中断；不会自动续跑。请重新检测或再次确认下载。",
                        progress=None,
                    )
        except (OSError, ValueError, TypeError):
            pass

    def snapshot(self):
        return json.loads(json.dumps(self.state))

    def update(self, **changes):
        self.state.update(changes)
        self.state["version"] += 1
        self.state["updated_at"] = datetime.now(timezone.utc).isoformat()
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            temporary = self.record.with_suffix(".tmp")
            temporary.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
            temporary.replace(self.record)
        except OSError:
            # Disk-full/read-only errors must not leave an immortal active task.
            self.state["persistence_error"] = "无法保存下载状态，请检查插件数据目录权限和磁盘空间。"
        self.notify()

    async def start(self, *, confirmed: bool):
        if confirmed is not True:
            raise HomeError("下载前请确认将在 AstrBot 所在机器下载并安装官方 Chromium。", 400)
        async with self.lock:
            if self.closed:
                raise HomeError("插件正在关闭。", 409)
            if self.active or self.task and not self.task.done():
                raise HomeError("Chromium 正在安装，请勿重复启动。", 409, "download_busy")
            self.update(
                id=str(uuid4()),
                status="preparing",
                message="准备下载，正在检查 Python 依赖…",
                lines=[],
                progress=None,
            )
            self.task = asyncio.create_task(self.run())

    async def consume(self):
        pending = ""
        while chunk := await self.process.stdout.read(2048):
            pending += chunk.decode("utf-8", errors="replace")
            parts = re.split(r"[\r\n]", pending)
            pending = parts.pop()[-4000:]
            for part in parts:
                line = clean_output(part)
                if not line:
                    continue
                self.state["lines"] = (self.state["lines"] + [line])[-15:]
                match = re.search(r"\b(\d{1,3})%", line)
                if match:
                    self.state["progress"] = min(100, int(match[1]))
                # Broadcast at most once per second; percentages describe one component, not all.
                if time.monotonic() - self.last_notice >= 1:
                    self.last_notice = time.monotonic()
                    self.update()
        if pending.strip():
            self.state["lines"] = (self.state["lines"] + [clean_output(pending)])[-15:]

    async def run(self):
        try:
            async with asyncio.timeout(TIMEOUT_SECONDS):
                await self.prepare()
                diagnostic = await self.verify()
                if not diagnostic.get("download_available"):
                    self.update(
                        status="failed",
                        message=diagnostic.get("reason", "请先安装 Playwright Python 依赖。"),
                        progress=None,
                    )
                    return
                self.browsers.mkdir(parents=True, exist_ok=True)
                env = dict(os.environ)
                env["PLAYWRIGHT_BROWSERS_PATH"] = str(self.browsers)
                env["PYTHONIOENCODING"] = "utf-8"
                env["CI"] = "1"
                # A UI cannot select a download server, browser, executable, path or shell flags.
                for name in (
                    "PLAYWRIGHT_DOWNLOAD_HOST",
                    "PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST",
                    "NODE_OPTIONS",
                ):
                    env.pop(name, None)
                flags = (
                    {"creationflags": subprocess.CREATE_NO_WINDOW}
                    if os.name == "nt"
                    else {"start_new_session": True}
                )
                self.update(
                    status="downloading",
                    message="正在下载官方 Chromium；进度为当前组件，可能需要数分钟。",
                )
                spawn = asyncio.create_task(
                    asyncio.create_subprocess_exec(
                        sys.executable,
                        "-m",
                        "playwright",
                        "install",
                        "chromium",
                        cwd=str(self.directory),
                        env=env,
                        stdin=asyncio.subprocess.DEVNULL,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.STDOUT,
                        **flags,
                    )
                )
                try:
                    self.process = await asyncio.shield(spawn)
                except asyncio.CancelledError:
                    # Do not orphan a downloader if cancellation races process creation.
                    self.process = await spawn
                    raise
                await self.consume()
                code = await self.process.wait()
                if code != 0:
                    self.update(
                        status="failed",
                        message=f"Chromium 下载/安装失败（退出码 {code}），请查看下方日志；不会自动重试。",
                        progress=None,
                    )
                    return
                self.update(
                    status="verifying",
                    message="下载程序已结束，正在真实启动 Chromium 验证…",
                    progress=None,
                )
                diagnostic = await self.verify()
                if diagnostic.get("ready"):
                    self.update(
                        status="completed",
                        message="Chromium 安装完成，真实启动验证通过。",
                        progress=100,
                    )
                else:
                    self.update(
                        status="failed",
                        message="下载已结束，但浏览器尚不可用："
                        + diagnostic.get("reason", "验证失败"),
                        progress=None,
                    )
        except asyncio.CancelledError:
            await self.kill()
            self.update(
                status="cancelled",
                message="下载已取消；不会自动重试。已下载文件保留，可重新检测。",
                progress=None,
            )
        except TimeoutError:
            await self.kill()
            self.update(
                status="failed",
                message="下载超过 20 分钟，已终止。请检查网络后手动重试。",
                progress=None,
            )
        except Exception as exc:
            await self.kill()
            self.update(
                status="failed",
                message="下载或验证失败：" + clean_output(f"{type(exc).__name__}: {exc}"),
                progress=None,
            )
        finally:
            self.process = None

    async def kill(self):
        process = self.process
        if process is None or process.returncode is not None:
            return
        if os.name == "nt":
            killer = await asyncio.create_subprocess_exec(
                "taskkill",
                "/PID",
                str(process.pid),
                "/T",
                "/F",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
            await killer.wait()
        else:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
        with contextlib.suppress(ProcessLookupError):
            if process.returncode is None:
                process.kill()
        await process.wait()

    async def cancel(self, download_id):
        async with self.lock:
            if not download_id or download_id != self.state["id"]:
                raise HomeError("下载任务已更换，请刷新状态。", 409, "download_changed")
            if self.task and not self.task.done() and self.state["status"] != "cancelling":
                self.update(status="cancelling", message="正在取消下载…")
                # A fresh task must enter its try/finally before cancellation is delivered.
                await asyncio.sleep(0)
                if not self.task.done():
                    self.task.cancel()

    async def close(self):
        self.closed = True
        if self.task and not self.task.done():
            await self.cancel(self.state["id"])
            with contextlib.suppress(asyncio.CancelledError):
                await self.task
