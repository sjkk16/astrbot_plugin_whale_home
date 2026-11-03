"""Loopback-only preview using the real simulation and a clearly labeled local demo model."""

from __future__ import annotations

import argparse
import json
import sys
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.demo_gateway import DemoGateway  # noqa: E402
from whale_home.api import HomeAPI  # noqa: E402
from whale_home.assets import MAX_ARCHIVE_BYTES, MAX_IMAGE_BYTES  # noqa: E402
from whale_home.rules import HomeError  # noqa: E402
from whale_home.runtime import HomeRuntime  # noqa: E402


def create_app(data_directory: Path, static_directory: Path | None = None,
               *, interactive_preview: bool = False) -> FastAPI:
    static_directory = (static_directory or ROOT / "views/home").resolve()
    if not static_directory.is_relative_to(ROOT):
        raise ValueError("Static preview must stay inside the workspace")
    new_home = not (data_directory / "home.sqlite3").exists()
    runtime = HomeRuntime(data_directory, DemoGateway())
    api = HomeAPI(runtime)

    @asynccontextmanager
    async def lifespan(app):
        await runtime.start()
        if interactive_preview and new_home:
            # Seed only a brand-new, explicitly chosen preview. Never change existing saves.
            async with runtime.lock:
                state = runtime.state.model_copy(deep=True)
                state.settings.provider_id = "local-demo"
                await runtime.commit(state)
        yield
        await runtime.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.runtime = runtime

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        host = request.headers.get("host", "").split(":")[0]
        if host not in ("127.0.0.1", "localhost", "testserver"):
            return JSONResponse({"message": "Local preview only"}, status_code=403)
        origin = request.headers.get("origin")
        if origin and origin != f"http://{request.headers.get('host')}":
            return JSONResponse({"message": "Cross-origin request denied"}, status_code=403)
        return await call_next(request)

    @app.exception_handler(HomeError)
    async def home_error(request, error):
        return JSONResponse(
            {"status": "error", "message": error.message, "code": error.code},
            status_code=error.status,
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "mode": "local-demo", "interaction_preview": interactive_preview}

    @app.get("/api/events")
    async def events():
        async def stream():
            async for event in runtime.events():
                yield f"data: {json.dumps(event)}\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/archives/export")
    async def export():
        return Response(
            await runtime.export_archive(), media_type="application/json",
            headers={"Content-Disposition": 'attachment; filename="whale-home-v2.json"'},
        )

    @app.post("/api/assets/upload")
    @app.post("/api/archives/import")
    async def upload(request: Request, file: UploadFile):
        endpoint = request.url.path.removeprefix("/api/")
        limit = MAX_ARCHIVE_BYTES if endpoint == "archives/import" else MAX_IMAGE_BYTES
        content = await file.read(limit + 1)
        if len(content) > limit:
            raise HomeError("文件过大。", 413)
        return await api.upload(endpoint, content)

    @app.get("/api/{endpoint:path}")
    async def get_api(endpoint: str, request: Request):
        return await api.get(endpoint, dict(request.query_params))

    @app.post("/api/{endpoint:path}")
    async def post_api(endpoint: str, request: Request):
        if len(await request.body()) > 128 * 1024:
            raise HomeError("内容过大。", 413)
        try:
            body = await request.json()
        except ValueError:
            raise HomeError("需要 JSON 对象。") from None
        return await api.post(endpoint, body)

    @app.get("/")
    async def index():
        path = static_directory / "index.html"
        if not path.is_file():
            raise HTTPException(503, "Build the frontend first")
        html = path.read_text(encoding="utf-8")
        return HTMLResponse(html.replace("<head>", '<head><script src="/dev-bridge.js"></script>'))

    @app.get("/dev-bridge.js")
    async def bridge():
        return Response((ROOT / "tools" / "dev-bridge.js").read_text(encoding="utf-8"),
                        media_type="text/javascript")

    app.mount("/", StaticFiles(directory=static_directory, check_dir=False), name="static")
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=18761)
    parser.add_argument("--data-dir", type=Path, default=ROOT / ".local" / "preview-data")
    parser.add_argument("--static-dir", type=Path, default=ROOT / "views/home")
    parser.add_argument("--interaction-preview", action="store_true",
                        help="Select offline demo model only for a new isolated preview home")
    args = parser.parse_args()
    uvicorn.run(create_app(args.data_dir, args.static_dir, interactive_preview=args.interaction_preview), host="127.0.0.1", port=args.port, log_level="warning")

