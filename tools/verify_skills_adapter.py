"""Exercise the real AstrBot SDK with in-process fake models/tools, without network."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
INSTANCE = ROOT / ".local" / f"skills-sdk-{uuid4().hex}"
INSTANCE.mkdir(parents=True)
os.environ["ASTRBOT_ROOT"] = str(INSTANCE)
sys.path.insert(0, str(ROOT / ".runtime/astrbot/AstrBot-4.29.3"))
sys.path.insert(0, str(ROOT))

import anyio  # noqa: E402
import mcp.types  # noqa: E402
from astrbot.core.agent.mcp_client import MCPTool  # noqa: E402
from astrbot.core.message.components import Plain  # noqa: E402
from astrbot.core.message.message_event_result import MessageChain  # noqa: E402
from astrbot.core.provider.entities import LLMResponse  # noqa: E402
from astrbot.core.provider.func_tool_manager import FunctionToolManager  # noqa: E402
from astrbot.core.star.context import Context  # noqa: E402
from astrbot.core.star.star import StarMetadata, star_registry  # noqa: E402
from astrbot.core.utils.astrbot_path import get_astrbot_skills_path  # noqa: E402

from whale_home.astrbot_skills import HOME_UMO, READ_SKILL, AstrBotGateway  # noqa: E402
from whale_home.errors import HomeError  # noqa: E402
from whale_home.models import ChatRequest, SkillPreferences, SkillPreferencesRequest  # noqa: E402
from whale_home.runtime import HomeRuntime  # noqa: E402


class ScriptedProvider:
    provider_config = {"id": "fixture", "max_context_tokens": 0}

    def __init__(self):
        self.steps = []
        self.seen_tools = []

    async def text_chat(self, **kwargs):
        self.seen_tools.append([tool.name for tool in kwargs["func_tool"]])
        if self.steps:
            name, args = self.steps.pop(0)
            return LLMResponse(role="tool", tools_call_name=[name], tools_call_args=[args],
                               tools_call_ids=[uuid4().hex])
        return LLMResponse(role="assistant", completion_text=json.dumps({
            "speech": "SDK 离线工具验证完成。", "emotion": "happy", "action": {"type": "idle"}}, ensure_ascii=False))


async def main():
    provider = ScriptedProvider()
    context = Context.__new__(Context)
    config = {"provider_settings": {"computer_use_runtime": "none"}, "plugin_set": ["*"]}
    context.get_config = lambda umo=None: config
    manager = FunctionToolManager()
    context.get_llm_tool_manager = lambda: manager
    async def get_provider(id):
        return provider
    context.provider_manager = SimpleNamespace(get_provider_by_id=get_provider)
    context.get_all_providers = lambda: []
    performed = []
    async def lookup(event, query):
        assert event.role == "member"
        assert event.unified_msg_origin == HOME_UMO
        assert event.get_group_id() == ""
        performed.append(query)
        await event.send(MessageChain(chain=[Plain("SDK 工具会话输出")]))
        return "fixture result"
    manager.add_func("fixture_lookup", [{"name": "query", "type": "string"}], "Offline lookup fixture", lookup)
    skills = Path(get_astrbot_skills_path()) / "fixture-guide"
    skills.mkdir(parents=True)
    (skills / "SKILL.md").write_text("---\nname: fixture-guide\ndescription: Offline test guide\n---\nUse fixture_lookup only if authorized.", encoding="utf-8")
    home = HomeRuntime(INSTANCE / "home", AstrBotGateway(context))
    await home.start(background=False)
    home.state.settings.provider_id = "fixture"
    try:
        catalog = await home.skills.catalog()
        assert any(item.name == "fixture_lookup" and item.available for item in catalog)
        assert any(item.name == "fixture-guide" and item.available for item in catalog)
        assert any(item.name == "astrbot_execute_shell" and not item.available for item in catalog)
        await home.skills.save_preferences(SkillPreferencesRequest(request_id=uuid4(), expected_version=home.state.version,
            preferences=SkillPreferences(allowed_tools=["fixture_lookup"], allowed_skills=["fixture-guide"])))
        provider.steps = [(READ_SKILL, {"name": "fixture-guide"}), ("fixture_lookup", {"query": "weather"})]
        await home.turn(ChatRequest(request_id=uuid4(), expected_version=home.state.version, message="test"))
        assert performed == ["weather"]
        rows = await home.store.rows("skill_calls")
        assert len(rows) == 2 and all(row["status"] == "succeeded" for row in rows)
        assert home.skills.output == "SDK 工具会话输出"
        assert all(set(names) == {READ_SKILL, "fixture_lookup"} for names in provider.seen_tools)
        print("PASS: real SDK loop, skill reader, plugin permission wrapper, isolated member event, tool output and audit")
        class Session:
            calls = 0
            fail = False
            async def call_tool(self, **kwargs):
                self.calls += 1
                if self.fail:
                    raise anyio.ClosedResourceError
                return mcp.types.CallToolResult(content=[mcp.types.TextContent(type="text", text="MCP fixture")])
        class Client:
            session = Session()
            async def call_tool_with_reconnect(self, **kwargs):
                raise AssertionError("MCP reconnect/replay helper must not be used")
        client = Client()
        manager.func_list.append(MCPTool(mcp.types.Tool(name="fixture_mcp", description="Offline MCP fixture",
            inputSchema={"type": "object", "properties": {}}), client, "fixture"))
        await home.skills.save_preferences(SkillPreferencesRequest(request_id=uuid4(), expected_version=home.state.version,
            preferences=SkillPreferences(allowed_tools=["fixture_mcp"])))
        provider.steps = [("fixture_mcp", {})]
        await home.turn(ChatRequest(request_id=uuid4(), expected_version=home.state.version, message="mcp"))
        assert client.session.calls == 1
        client.session.fail = True
        provider.steps = [("fixture_mcp", {})]
        try:
            await home.turn(ChatRequest(request_id=uuid4(), expected_version=home.state.version, message="disconnect"))
            raise AssertionError("Disconnected tool must fail")
        except HomeError:
            pass
        assert client.session.calls == 2
        assert (await home.store.rows("skill_calls"))[0]["status"] == "unknown"
        async def deny(tool_name, run_context):
            assert run_context.context.event.role == "member"
            return "error: Permission denied"
        manager._check_tool_permission = deny
        provider.steps = [("fixture_mcp", {})]
        try:
            await home.turn(ChatRequest(request_id=uuid4(), expected_version=home.state.version, message="permission"))
            raise AssertionError("Host permission denial must fail")
        except HomeError:
            pass
        assert client.session.calls == 2
        assert (await home.store.rows("skill_calls"))[0]["status"] == "failed"
        print("PASS: native MCP request sent once, disconnect not replayed, host permission denial retained")
        plugin_skill = INSTANCE / "data/plugins/fixture_plugin/skills/blocked-guide"
        plugin_skill.mkdir(parents=True)
        (plugin_skill / "SKILL.md").write_text("---\nname: blocked-guide\ndescription: Blocked fixture\n---\nFixture", encoding="utf-8")
        star_registry.append(StarMetadata(name="fixture_plugin", root_dir_name="fixture_plugin",
            module_path="data.plugins.fixture_plugin.main", activated=True))
        manager.add_func("fixture_plugin_tool", [], "Plugin config fixture", lookup)
        lookup.__module__ = "data.plugins.fixture_plugin.main"
        config["plugin_set"] = []
        catalogue = await home.skills.catalog()
        assert any(item.description == "Blocked fixture" and not item.available for item in catalogue)
        assert any(item.name == "fixture_plugin_tool" and not item.available for item in catalogue)
        print("PASS: disabled plugin profile blocks both tools and plugin Skills")
        class ShellFixture:
            calls = []
            async def call(self, run_context, **kwargs):
                self.calls.append((kwargs["action"], kwargs["session_id"]))
                return json.dumps({"session_closed": True, "exit_code": 0, "output": "later output"})
        shell_fixture = ShellFixture()
        context.get_llm_tool_manager = lambda: SimpleNamespace(get_builtin_tool=lambda cls: shell_fixture)
        first = mcp.types.CallToolResult(content=[mcp.types.TextContent(type="text", text=json.dumps({
            "session_id": "owned-session", "output": "initial output", "session_closed": False}))])
        result = await home.gateway.finish_shell(first, None, SimpleNamespace(check=lambda: None))
        assert "initial output" in result.content[0].text and "later output" in result.content[0].text
        assert shell_fixture.calls == [("poll", "owned-session"), ("terminate", "owned-session")]
        print("PASS: managed shell output retained and only the owned session cleaned up (no real shell)")
        print(f"Isolated evidence: {INSTANCE}")
    finally:
        await home.close()


if __name__ == "__main__":
    asyncio.run(main())
