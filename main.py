from __future__ import annotations

import json
from pathlib import Path

from astrbot.api import logger
from astrbot.api.star import Context, Star
from astrbot.api.web import (
    PluginUploadFile,
    error_response,
    json_response,
    request,
    stream_response,
)
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .whale_home.api import COMPUTER_GET, COMPUTER_POST, MUTATIONS, HomeAPI
from .whale_home.assets import MAX_ARCHIVE_BYTES, MAX_IMAGE_BYTES
from .whale_home.astrbot_skills import AstrBotGateway
from .whale_home.rules import HomeError
from .whale_home.runtime import HomeRuntime

PLUGIN_NAME = "astrbot_plugin_whale_home"


class WhaleHomePlugin(Star):
    def __init__(self, context: Context):
        super().__init__(context)
        self.runtime: HomeRuntime | None = None
        self.api: HomeAPI | None = None
        for endpoint in ("state", "providers", "events/history", "messages", "memories", "companion/preferences", "skills/catalog", "skills/preferences", "skills/calls", *COMPUTER_GET):
            context.register_web_api(
                f"/{PLUGIN_NAME}/{endpoint}", self._get_handler(endpoint), ["GET"], endpoint
            )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/<asset_id>", self.read_asset, ["GET"], "Read a local image"
        )
        for endpoint in ("chat", "companion/presence", "skills/preferences", "skills/stop", *COMPUTER_POST, *MUTATIONS):
            context.register_web_api(
                f"/{PLUGIN_NAME}/{endpoint}", self._post_handler(endpoint), ["POST"], endpoint
            )
        for endpoint in ("assets/upload", "archives/import"):
            context.register_web_api(
                f"/{PLUGIN_NAME}/{endpoint}", self._upload_handler(endpoint), ["POST"], endpoint
            )
        context.register_web_api(
            f"/{PLUGIN_NAME}/events", self.stream_events, ["GET"], "Home event stream"
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/archives/export", self.export_archive, ["GET"], "Export home"
        )

    async def initialize(self):
        directory = Path(get_astrbot_plugin_data_path()) / PLUGIN_NAME
        self.runtime = HomeRuntime(directory, AstrBotGateway(self.context))
        await self.runtime.start()
        self.api = HomeAPI(self.runtime)
        logger.info("Whale Home initialized; settings and data remain in the plugin data directory.")

    async def terminate(self):
        self.api = None
        if self.runtime is not None:
            await self.runtime.close()
            self.runtime = None

    async def _guard(self, operation):
        if self.api is None:
            return error_response("小家还未就绪，或插件已停用。", status_code=503)
        try:
            return await operation()
        except HomeError as error:
            return error_response(error.message, status_code=error.status, data={"code": error.code})
        except Exception as error:
            # Provider exceptions can contain credentials or request payloads.
            logger.error("Whale Home request failed (%s).", type(error).__name__)
            return error_response("小家暂时无法完成这次操作。", status_code=500)

    def _get_handler(self, endpoint: str):
        async def handler():
            async def operation():
                assert self.api is not None
                params = {key: request.query.get(key) for key in ("before", "limit")}
                params = {key: value for key, value in params.items() if value is not None}
                return json_response(await self.api.get(endpoint, params))
            return await self._guard(operation)
        return handler

    def _post_handler(self, endpoint: str):
        async def handler():
            async def operation():
                assert self.api is not None
                if len(await request.body()) > 128 * 1024:
                    raise HomeError("提交的内容过大。", 413)
                body = await request.json(default=None)
                if not isinstance(body, dict):
                    raise HomeError("需要有效的 JSON 对象。")
                return json_response(await self.api.post(endpoint, body))
            return await self._guard(operation)
        return handler

    def _upload_handler(self, endpoint: str):
        async def handler():
            async def operation():
                assert self.api is not None
                upload = (await request.files()).get("file")
                if not isinstance(upload, PluginUploadFile):
                    raise HomeError("没有收到文件。")
                limit = MAX_ARCHIVE_BYTES if endpoint == "archives/import" else MAX_IMAGE_BYTES
                content = await upload.read(limit + 1)
                if len(content) > limit:
                    raise HomeError("文件过大。", 413)
                return json_response(await self.api.upload(endpoint, content))
            return await self._guard(operation)
        return handler

    async def read_asset(self, asset_id: str):
        async def operation():
            assert self.api is not None
            return json_response(await self.api.get(f"assets/{asset_id}"))
        return await self._guard(operation)

    async def export_archive(self):
        async def operation():
            assert self.runtime is not None
            content = await self.runtime.export_archive()
            return stream_response(
                iter((content,)),
                content_type="application/json",
                headers={"Content-Disposition": 'attachment; filename="whale-home-v2.json"'},
            )
        return await self._guard(operation)

    async def stream_events(self):
        async def operation():
            assert self.runtime is not None
            runtime = self.runtime

            async def stream():
                async for event in runtime.events():
                    yield f"data: {json.dumps(event)}\n\n"

            return stream_response(stream(), headers={"X-Accel-Buffering": "no"})
        return await self._guard(operation)

