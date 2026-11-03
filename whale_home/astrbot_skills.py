"""AstrBot 4.29 SDK adapter. No host configuration or real chat identity is changed."""
from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path

import jsonschema
import mcp.types
from astrbot.core.agent.handoff import HandoffTool
from astrbot.core.agent.hooks import BaseAgentRunHooks
from astrbot.core.agent.mcp_client import MCPTool
from astrbot.core.agent.runners.tool_loop_agent_runner import ToolLoopAgentRunner
from astrbot.core.agent.tool import FunctionTool, ToolSet
from astrbot.core.astr_agent_context import AgentContextWrapper, AstrAgentContext
from astrbot.core.astr_agent_tool_exec import FunctionToolExecutor
from astrbot.core.message.components import Plain
from astrbot.core.platform.astr_message_event import AstrMessageEvent, event_context
from astrbot.core.platform.astrbot_message import AstrBotMessage, MessageMember
from astrbot.core.platform.message_type import MessageType
from astrbot.core.platform.platform_metadata import PlatformMetadata
from astrbot.core.provider.entities import ProviderRequest
from astrbot.core.skills.skill_manager import SkillManager
from astrbot.core.tools.computer_tools import FileReadTool, LocalExecuteShellTool, ShellSessionTool
from astrbot.core.tools.registry import get_builtin_tool_config_statuses, iter_builtin_tool_classes

from .errors import HomeError
from .models import Capability
from .skills import SkillExecution

READ_SKILL = "whale_home_read_skill"
HOME_UMO = "whale_home:OtherMessage:home"


class HomeMessageEvent(AstrMessageEvent):
    def __init__(self, execution: SkillExecution, prompt: str):
        message = AstrBotMessage()
        message.type = MessageType.OTHER_MESSAGE
        message.self_id = "whale_home"
        message.session_id = "home"
        message.message_id = execution.run_id
        message.sender = MessageMember(user_id="whale_home_owner", nickname="小家用户")
        message.message = [Plain(prompt)]
        message.message_str = prompt
        message.raw_message = None
        super().__init__(prompt, message, PlatformMetadata(
            name="whale_home", description="Isolated Whale Home session", id="whale_home",
        ), "home")
        self.execution = execution
        # The SDK's default member role is intentionally retained.

    async def send(self, message):
        text = "".join(item.text for item in message.chain if isinstance(item, Plain))
        if text:
            await self.execution.emit(text)
        elif message.chain:
            await self.execution.emit("[工具返回了非文本内容，本预览不直接展示附件]")

    async def send_streaming(self, generator, **kwargs):
        async for message in generator:
            await self.send(message)

    async def get_group(self, group_id=None, **kwargs):
        raise HomeError("小家没有真实群聊身份。", 400, "incompatible_context")


class GuardedExecutor:
    def __init__(self, gateway: AstrBotGateway, execution: SkillExecution):
        self.gateway = gateway
        self.execution = execution

    async def execute(self, tool, run_context, **tool_args):
        if tool.name == READ_SKILL:
            name = tool_args.get("name", "")
            if not isinstance(name, str) or set(tool_args) != {"name"}:
                raise HomeError("技能读取只接受技能名称。", 400, "invalid_skill")
            result = await self.execution.invoke(
                "skill", name, lambda: self.gateway.read_skill(name, run_context),
            )
        else:
            async def operation():
                # Re-resolve the SDK permission wrapper, never call its raw handler.
                tools, _, entries = self.gateway.inventory()
                entry = next((item for item in entries if item.kind == "tool" and item.name == tool.name), None)
                if not entry or not entry.available or tool.name not in tools:
                    raise HomeError("宿主能力已停用。", 403, "host_disabled")
                current = tools[tool.name]
                args = dict(tool_args)
                jsonschema.validate(args, current.parameters)
                raw = getattr(current, "_wrapped", current)
                if isinstance(raw, MCPTool):
                    # The host MCP helper reconnects and replays on ClosedResourceError.
                    # Retain its permission check but send this request exactly once.
                    manager = self.gateway.context.get_llm_tool_manager()
                    denied = await manager._check_tool_permission(current.name, run_context)
                    if denied:
                        return mcp.types.CallToolResult(isError=True, content=[
                            mcp.types.TextContent(type="text", text="error: Host permission denied")])
                    session = raw.mcp_client.session
                    if session is None:
                        raise HomeError("MCP 服务未连接，请在宿主中重连后重新发起任务。", 503, "mcp_unavailable")
                    return await session.call_tool(name=raw.mcp_tool.name, arguments=args,
                        read_timeout_seconds=timedelta(seconds=run_context.tool_call_timeout))
                if args.get("background") is True:
                    raise HomeError("首版不允许脱离本轮的后台工具任务。", 400, "detached_task")
                if current.name == "astrbot_execute_shell":
                    # Keep native managed processes bounded by this request's lifetime.
                    args["timeout"] = min(int(args.get("timeout") or 60), 60)
                result = None
                async for item in FunctionToolExecutor.execute(current, run_context, **args):
                    if isinstance(item, mcp.types.CallToolResult):
                        result = item
                    elif getattr(item, "chain", None):
                        await run_context.context.event.send(item)
                result = result or mcp.types.CallToolResult(content=[])
                if current.name == "astrbot_execute_shell":
                    result = await self.gateway.finish_shell(result, run_context, self.execution)
                return result
            result = await self.execution.invoke("tool", tool.name, operation)
        if isinstance(result, str):
            result = mcp.types.CallToolResult(content=[mcp.types.TextContent(type="text", text=result)])
        # Tool outputs are untrusted data and are not copied to the audit database.
        for content in result.content:
            if isinstance(content, mcp.types.TextContent):
                content.text = content.text[:32000]
        yield result


class AstrBotGateway:
    def __init__(self, context):
        self.context = context

    async def providers(self) -> list[dict]:
        result = []
        for provider in self.context.get_all_providers():
            try:
                metadata = provider.meta()
                result.append({"id": metadata.id, "name": f"{metadata.id} · {metadata.model}"})
            except (ValueError, KeyError, AttributeError):
                continue
        return result

    async def computer_generate(self, provider_id: str, system: str, prompt: str, image: str) -> str:
        # No Skills, tools, provider fallbacks or plugin retries in the computer path.
        provider = await self.context.provider_manager.get_provider_by_id(provider_id)
        if provider is None:
            raise HomeError("上网模型不可用，请选择支持图片的模型。", 400, "no_vision_model")
        modalities = getattr(provider, "provider_config", {}).get("modalities")
        if modalities and "image" not in modalities:
            raise HomeError("所选模型在宿主中未启用图片输入。", 400, "no_vision_model")
        try:
            result = await provider.text_chat(prompt=prompt, system_prompt=system,
                                              image_urls=[image], contexts=[], func_tool=None, request_max_retries=0)
        except Exception:
            raise HomeError("图文模型请求失败，请检查模型是否支持图片及其连接。", 502, "vision_model_failed") from None
        if not result.completion_text:
            raise HomeError("图文模型未返回有效内容。", 502, "vision_model_empty")
        return result.completion_text

    def inventory(self):
        from astrbot.core.astr_main_agent import _filter_skills_for_current_config
        from astrbot.core.star.star import star_registry

        config = self.context.get_config(umo=HOME_UMO)
        settings = config.get("provider_settings", {})
        runtime = settings.get("computer_use_runtime", "none")
        manager = self.context.get_llm_tool_manager()
        tools = {tool.name: tool for tool in manager.get_full_tool_set()}
        builtin_names = set()
        for cls in iter_builtin_tool_classes():
            tool = manager.get_builtin_tool(cls)
            # Registered plugin/MCP names follow the SDK's precedence over builtins.
            if tool.name not in tools:
                tools[tool.name] = tool
                builtin_names.add(tool.name)
        if runtime == "local" and "astrbot_execute_shell" in builtin_names:
            tools["astrbot_execute_shell"] = LocalExecuteShellTool()
        entries = []
        for tool in tools.values():
            raw = getattr(tool, "_wrapped", tool)
            handler = getattr(raw, "handler", None)
            handler = getattr(handler, "func", handler)
            source = (getattr(raw, "handler_module_path", None)
                      or getattr(handler, "__module__", None) or type(raw).__module__)
            reason = ""
            metadata = next((item for item in star_registry if item.module_path and
                             (source == item.module_path or source.startswith(item.module_path + "."))), None)
            plugin_set = config.get("plugin_set", settings.get("plugin_set", ["*"]))
            if metadata and (not metadata.activated or (not metadata.reserved and
                    isinstance(plugin_set, list) and "*" not in plugin_set and metadata.name not in plugin_set)):
                reason = "所属插件未在当前宿主配置中启用"
            if isinstance(raw, MCPTool):
                source = "MCP · " + raw.mcp_server_name
            if not tool.active:
                reason = "已在 AstrBot 中停用"
            statuses = get_builtin_tool_config_statuses(tool.name, [{"config": config}]) if tool.name in builtin_names else []
            if statuses and not all(item["enabled"] for item in statuses):
                reason = "宿主未启用所需运行环境或功能"
            required = set(tool.parameters.get("required", []))
            if (isinstance(raw, HandoffTool) or getattr(raw, "is_background_task", False)
                    or tool.name == "astrbot_shell_session" or "cron" in source
                    or required.intersection({"group_id", "platform_id", "unified_msg_origin"})
                    or getattr(raw, "requires_real_event", False)):
                reason = "首版不支持真实平台身份、子代理或独立后台任务"
            if tool.name == READ_SKILL:
                reason = "名称与小家技能读取入口冲突"
            entries.append(Capability(name=tool.name, kind="tool", source=source,
                                      description=tool.description[:4000], available=not reason, reason=reason))
        skill_manager = SkillManager()
        skills = skill_manager.list_skills(active_only=False, runtime=runtime)
        skill_settings = {**settings, "plugin_set": config.get("plugin_set", settings.get("plugin_set", ["*"]))}
        active_plugins = {s.name for s in _filter_skills_for_current_config(skills, skill_settings)}
        skill_map = {}
        for skill in skills:
            reason = ""
            if not skill.active or skill.name not in active_plugins:
                reason = "技能或所属插件已在宿主中停用"
            elif skill.source_type == "sandbox_only" and runtime != "sandbox":
                reason = "技能仅存在于沙箱，当前未启用沙箱环境"
            elif skill.source_type != "sandbox_only" and not Path(skill.path).is_file():
                reason = "技能指引文件不可用"
            skill_map[skill.name] = skill
            entries.append(Capability(name=skill.name, kind="skill", description=skill.description[:4000],
                                      source=skill.source_label or skill.source_type,
                                      available=not reason, reason=reason))
        return tools, skill_map, entries

    async def capabilities(self) -> list[dict]:
        return [entry.model_dump() for entry in self.inventory()[2]]

    async def read_skill(self, name: str, run_context):
        _, skills, entries = self.inventory()
        entry = next((item for item in entries if item.kind == "skill" and item.name == name), None)
        if not entry or not entry.available or name not in skills:
            raise HomeError("技能已不可用。", 403, "host_disabled")
        skill = skills[name]
        if skill.source_type == "sandbox_only":
            # The name resolves to a host-owned path; model-supplied paths never reach the reader.
            tool = self.context.get_llm_tool_manager().get_builtin_tool(FileReadTool)
            return await tool.call(run_context, path=skill.path, limit=1000)
        path = Path(skill.path)
        root = path.parent.resolve()
        resolved = path.resolve(strict=True)
        if path.name != "SKILL.md" or not resolved.is_relative_to(root):
            raise HomeError("技能指引路径校验失败。", 400, "invalid_skill_path")
        def read():
            with resolved.open("rb") as stream:
                content = stream.read(65537)
            if len(content) > 65536:
                raise HomeError("技能指引超过 64 KiB，请在宿主中拆分指引。", 400, "skill_too_large")
            return content.decode("utf-8")
        return await asyncio.to_thread(read)

    async def finish_shell(self, result, run_context, execution):
        session_id = None
        output = ""
        for content in result.content:
            if isinstance(content, mcp.types.TextContent):
                output = (output + content.text + "\n")[-32000:]
                try:
                    data = json.loads(content.text)
                    if isinstance(data, dict) and not data.get("session_closed"):
                        session_id = data.get("session_id")
                except (ValueError, TypeError):
                    pass
        if not session_id:
            return result
        manager = self.context.get_llm_tool_manager().get_builtin_tool(ShellSessionTool)
        try:
            while True:
                execution.check()
                text = await manager.call(run_context, action="poll", session_id=session_id, yield_time_ms=1000)
                data = json.loads(text)
                output = (output + text + "\n")[-32000:]
                if data.get("session_closed"):
                    return mcp.types.CallToolResult(
                        isError=bool(data.get("error")) or data.get("exit_code") not in (None, 0),
                        content=[mcp.types.TextContent(type="text", text=output)])
        finally:
            # Only clean up the session returned by this invocation, never enumerate other sessions.
            try:
                await asyncio.wait_for(manager.call(run_context, action="terminate", session_id=session_id), 2)
            except Exception:
                pass

    async def generate(self, provider_id: str, system_prompt: str, prompt: str,
                       *, execution: SkillExecution | None = None) -> str:
        if execution is None:
            result = await self.context.llm_generate(chat_provider_id=provider_id,
                system_prompt=system_prompt, prompt=prompt, tools=None)
            return result.completion_text
        tools, _, catalog = self.inventory()
        allowed = [entry for entry in catalog if entry.available and execution.owner.allowed(entry)]
        toolset = ToolSet()
        for entry in allowed:
            if entry.kind == "tool":
                toolset.add_tool(tools[entry.name])
        skills = [entry for entry in allowed if entry.kind == "skill"]
        if skills:
            toolset.add_tool(FunctionTool(name=READ_SKILL,
                description="Read the complete SKILL.md for one authorized skill by its exact name. Read before following it. Does not grant dependent tools.",
                parameters={"type": "object", "properties": {"name": {"type": "string", "enum": [s.name for s in skills]}},
                            "required": ["name"], "additionalProperties": False}))
            system_prompt += "\n可用技能目录（必须先读取完整指引，依赖工具仍需单独授权）：\n" + json.dumps(
                [{"name": s.name, "description": s.description} for s in skills], ensure_ascii=False)
        event = HomeMessageEvent(execution, prompt)
        run_context = AgentContextWrapper(context=AstrAgentContext(context=self.context, event=event),
                                          tool_call_timeout=execution.owner.runtime.model_timeout)
        provider = await self.context.provider_manager.get_provider_by_id(provider_id)
        if provider is None:
            raise HomeError("所选模型不可用。", 400, "no_model")
        runner = ToolLoopAgentRunner()
        with event_context(event):
            await runner.reset(provider=provider, request=ProviderRequest(
                prompt=prompt, system_prompt=system_prompt, func_tool=toolset, contexts=[]),
                run_context=run_context, tool_executor=GuardedExecutor(self, execution),
                agent_hooks=BaseAgentRunHooks(), streaming=False, request_max_retries=0,
                fallback_providers=[], tool_schema_mode="full")
            # No plugin daily/step quota: the existing outer deadline and cancellation bound the run.
            while not runner.done():
                execution.check()
                async for _ in runner.step():
                    pass
            execution.check()
            response = runner.get_final_llm_resp()
            if response is None or not response.completion_text:
                raise HomeError("模型没有返回有效技能回应。", 502, "skill_model_error")
            return response.completion_text
