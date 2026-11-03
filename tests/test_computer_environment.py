from types import SimpleNamespace

import pytest

from whale_home import computer_environment as env


def test_install_commands_quote_real_interpreter():
    command = env.installation_commands("C:/it's folder/python.exe", True)[0]
    assert command.startswith("& 'C:/it''s folder/python.exe'")
    assert env.installation_commands("/a b/python", False)[1].startswith("'/a b/python'")


async def test_missing_package(monkeypatch):
    monkeypatch.setattr(env.importlib.util, "find_spec", lambda name: None)
    result = await env.diagnose()
    assert result["code"] == "playwright_missing" and not result["ready"]
    assert result["python_executable"] and result["commands"]


async def test_broken_dependency(monkeypatch):
    import builtins

    original = builtins.__import__

    def broken(name, *args, **kwargs):
        if name == "playwright.async_api":
            raise ImportError("dependent module missing")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", broken)
    result = await env.diagnose()
    assert result["code"] == "playwright_import_failed"
    assert "dependent module" in result["detail"]


@pytest.mark.parametrize(
    "exists,launch_ok,expected",
    [
        (False, True, "chromium_missing"),
        (True, False, "chromium_launch_failed"),
        (True, True, ""),
    ],
)
async def test_browser_diagnostics(tmp_path, monkeypatch, exists, launch_ok, expected):
    import playwright.async_api

    binary = tmp_path / "browser.exe"
    if exists:
        binary.touch()
    calls = []

    async def close():
        calls.append("closed")

    async def launch(**kwargs):
        assert kwargs["chromium_sandbox"] is True
        if not launch_ok:
            raise RuntimeError("launch denied")
        calls.append("launched")
        return SimpleNamespace(close=close)

    class Manager:
        async def __aenter__(self):
            return SimpleNamespace(
                chromium=SimpleNamespace(executable_path=str(binary), launch=launch)
            )

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(playwright.async_api, "async_playwright", Manager)
    result = await env.diagnose()
    assert result["code"] == expected
    assert result["ready"] == (expected == "")
    if not expected:
        assert calls == ["launched", "closed"]


def test_manual_install_commands_scope_private_directory(monkeypatch):
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "C:/it's folder/browsers")
    command = env.installation_commands("C:/it's folder/python.exe", True)[1]
    assert "'C:/it''s folder/browsers'" in command
    assert "finally" in command and "$previous" in command
    monkeypatch.setenv("PLAYWRIGHT_BROWSERS_PATH", "/a b/browsers")
    assert env.installation_commands("/a b/python", False)[1].startswith(
        "PLAYWRIGHT_BROWSERS_PATH='/a b/browsers' '/a b/python'"
    )
