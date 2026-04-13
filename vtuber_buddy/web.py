from __future__ import annotations

import logging
from pathlib import Path

from aiohttp import web

try:
    from astrbot.api import logger
except ModuleNotFoundError:
    logger = logging.getLogger("vtuber_buddy")

from .service import BuddyConversationService


class BuddyWebServer:
    """Standalone local web server for the VTuber Buddy UI."""

    def __init__(
        self,
        *,
        service: BuddyConversationService,
        host: str,
        port: int,
        template_dir: Path,
        static_dir: Path,
    ) -> None:
        self.service = service
        self.host = host
        self.port = port
        self.template_dir = template_dir
        self.static_dir = static_dir
        self.runner: web.AppRunner | None = None
        self.site: web.TCPSite | None = None
        self.public_url = f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return self.site is not None

    async def start(self) -> None:
        if self.site is not None:
            return

        app = web.Application(middlewares=[self._json_error_middleware])
        app.router.add_get("/", self.handle_index)
        app.router.add_get("/api/health", self.handle_health)
        app.router.add_get("/api/state", self.handle_state)
        app.router.add_post("/api/chat", self.handle_chat)
        app.router.add_post("/api/feed", self.handle_feed)
        app.router.add_post("/api/touch", self.handle_touch)
        app.router.add_post("/api/settings", self.handle_settings)
        app.router.add_static("/static/", str(self.static_dir))

        self.runner = web.AppRunner(app)
        await self.runner.setup()
        self.site = web.TCPSite(self.runner, self.host, self.port)
        await self.site.start()

        socket = getattr(self.site, "_server", None)
        if socket and socket.sockets:
            bound_port = socket.sockets[0].getsockname()[1]
            self.public_url = f"http://{self.host}:{bound_port}"

        logger.info("VTuber Buddy web app started at %s", self.public_url)

    async def stop(self) -> None:
        if self.runner is None:
            return
        await self.runner.cleanup()
        self.runner = None
        self.site = None

    @web.middleware
    async def _json_error_middleware(self, request: web.Request, handler):
        try:
            return await handler(request)
        except web.HTTPException:
            raise
        except Exception as exc:
            logger.error("VTuber Buddy request failed: %s", exc, exc_info=True)
            return web.json_response(
                {"status": "error", "message": str(exc)},
                status=500,
            )

    async def handle_index(self, request: web.Request) -> web.FileResponse:
        del request
        return web.FileResponse(self.template_dir / "index.html")

    async def handle_health(self, request: web.Request) -> web.Response:
        del request
        return web.json_response({"status": "ok", "data": {"url": self.public_url}})

    async def handle_state(self, request: web.Request) -> web.Response:
        session_id = self._session_id_from_request(request)
        payload = await self.service.get_state(session_id)
        return web.json_response({"status": "ok", "data": payload})

    async def handle_chat(self, request: web.Request) -> web.Response:
        session_id = self._session_id_from_request(request)
        payload = await request.json()
        result = await self.service.chat(session_id, str(payload.get("message", "")))
        return web.json_response({"status": "ok", "data": result})

    async def handle_feed(self, request: web.Request) -> web.Response:
        session_id = self._session_id_from_request(request)
        payload = await request.json()
        result = await self.service.feed(session_id, str(payload.get("food", "点心")))
        return web.json_response({"status": "ok", "data": result})

    async def handle_touch(self, request: web.Request) -> web.Response:
        session_id = self._session_id_from_request(request)
        payload = await request.json()
        result = await self.service.touch(session_id, str(payload.get("area", "head")))
        return web.json_response({"status": "ok", "data": result})

    async def handle_settings(self, request: web.Request) -> web.Response:
        session_id = self._session_id_from_request(request)
        payload = await request.json()
        result = await self.service.update_settings(session_id, payload)
        return web.json_response({"status": "ok", "data": result})

    def _session_id_from_request(self, request: web.Request) -> str:
        session_id = request.headers.get("X-Session-Id", "").strip()
        if not session_id:
            session_id = request.query.get("session_id", "").strip()
        if not session_id:
            session_id = "local-default"
        return session_id[:128]
