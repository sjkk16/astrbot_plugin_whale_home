"""Read-only diagnostics for the interpreter actually hosting the plugin."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import os
import shlex
import sys
from pathlib import Path


def installation_commands(executable=None, windows=None):
    executable = executable or sys.executable
    windows = os.name == "nt" if windows is None else windows
    quoted = "& '" + executable.replace("'", "''") + "'" if windows else shlex.quote(executable)
    commands = [f'{quoted} -m pip install "playwright>=1.58,<2"']
    directory = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    if directory:
        if windows:
            directory = directory.replace("'", "''")
            commands.append(
                "& { $previous = $env:PLAYWRIGHT_BROWSERS_PATH; try { "
                f"$env:PLAYWRIGHT_BROWSERS_PATH = '{directory}'; {quoted} -m playwright install chromium"
                " } finally { $env:PLAYWRIGHT_BROWSERS_PATH = $previous } }"
            )
        else:
            commands.append(
                f"PLAYWRIGHT_BROWSERS_PATH={shlex.quote(directory)} {quoted} -m playwright install chromium"
            )
    else:
        commands.append(f"{quoted} -m playwright install chromium")
    return commands


async def diagnose(*, probe=True):
    result = {
        "ready": False,
        "stage": "package",
        "code": "playwright_missing",
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "playwright_version": None,
        "chromium_path": None,
        "browser_source": "downloaded",
        "download_available": False,
        "browser_directory": os.environ.get("PLAYWRIGHT_BROWSERS_PATH"),
        "launch_mode": "独立 Chromium（官方 Headless Shell · 按需下载）",
        "commands": installation_commands(),
        "reason": "",
        "detail": "",
    }
    try:
        if importlib.util.find_spec("playwright") is None:
            result["reason"] = (
                "AstrBot 当前 Python 未安装 Playwright，请先安装本插件 requirements.txt，再点击下载 Chromium。"
            )
            return result
        result["code"] = "playwright_import_failed"
        from playwright.async_api import async_playwright

        result["playwright_version"] = importlib.metadata.version("playwright")
        result.update(stage="browser", code="chromium_missing", download_available=True)
        async with async_playwright() as pw:
            result["chromium_path"] = pw.chromium.executable_path
            if not Path(pw.chromium.executable_path).is_file():
                result["reason"] = "尚未安装对应 Chromium，请点击“下载 Chromium”。"
                return result
            if probe:
                result.update(stage="launch", code="chromium_launch_failed")
                browser = await pw.chromium.launch(
                    headless=True,
                    chromium_sandbox=True,
                    timeout=15000,
                    args=["--disable-background-networking", "--disable-component-update"],
                )
                await browser.close()
        result.update(ready=True, stage="ready", code="", reason="浏览器环境可用")
    except Exception as exc:
        reasons = {
            "playwright_import_failed": "Playwright 或其依赖导入失败，请先修复 Python 依赖。",
            "chromium_missing": "浏览器驱动检查失败。",
            "chromium_launch_failed": "Chromium 文件已找到，但启动失败；可重新下载检查，系统依赖或沙箱问题仍需修复宿主环境。",
        }
        result["reason"] = reasons.get(result["code"], "浏览器环境检测失败。")
        result["detail"] = f"{type(exc).__name__}: {exc}"[:1500]
    return result
