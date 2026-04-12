from __future__ import annotations

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer
import pytest

from vtuber_buddy.service import BuddyConversationService
from vtuber_buddy.store import BuddyStore
from vtuber_buddy.web import BuddyWebServer


class StubModelClient:
    async def generate_reply(self, **kwargs) -> str:
        del kwargs
        return (
            '{"reply":"收到，我会一直盯着你。","emotion":"excited",'
            '"motion":"bounce","memory":"你在写插件"}'
        )

    def describe(self) -> str:
        return "stub-web"


@pytest.mark.asyncio
async def test_web_routes_round_trip(tmp_path):
    service = BuddyConversationService(
        store=BuddyStore(tmp_path / "sessions.json"),
        model_client=StubModelClient(),
        plugin_data_dir=tmp_path,
        runtime_config={},
    )
    await service.initialize()

    server = BuddyWebServer(
        service=service,
        host="127.0.0.1",
        port=0,
        template_dir=tmp_path,
        static_dir=tmp_path,
    )

    app = web.Application(middlewares=[server._json_error_middleware])
    app.router.add_get("/api/health", server.handle_health)
    app.router.add_get("/api/state", server.handle_state)
    app.router.add_post("/api/chat", server.handle_chat)

    async with TestServer(app) as test_server:
        async with TestClient(test_server) as client:
            health = await client.get("/api/health")
            assert health.status == 200

            state = await client.get("/api/state", headers={"X-Session-Id": "webtest"})
            state_payload = await state.json()
            assert state_payload["status"] == "ok"

            chat = await client.post(
                "/api/chat",
                headers={"X-Session-Id": "webtest"},
                json={"message": "我在写插件"},
            )
            chat_payload = await chat.json()
            assert chat_payload["status"] == "ok"
            assert chat_payload["data"]["speech"] == "收到，我会一直盯着你。"
            assert chat_payload["data"]["memories"][0]["content"] == "你在写插件"
