from __future__ import annotations

import asyncio

from astrbot.api.event import MessageChain
from astrbot.api.provider import LLMResponse, ProviderRequest
import pytest

from data.plugins.astrbot_plugin_vtuber_buddy.main import Main as PluginMain
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.bridge import (
    AstrBotMainChainBackend,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.platform import (
    BUDDY_PLATFORM_NAME,
    BuddyPlatformAdapter,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.queue_mgr import (
    BuddyQueueManager,
)


@pytest.mark.asyncio
async def test_adapter_submits_main_chain_event():
    event_queue: asyncio.Queue = asyncio.Queue()
    adapter = BuddyPlatformAdapter(
        platform_config={"id": BUDDY_PLATFORM_NAME},
        event_queue=event_queue,
        queue_mgr=BuddyQueueManager(),
    )

    adapter.submit_user_message(
        session_id="browser-session",
        text="你好",
        request_id="req-1",
        selected_provider="provider-1",
        extras={"buddy_prompt_context": {"system_prompt": "buddy prompt"}},
    )

    event = await event_queue.get()
    assert event.get_platform_name() == BUDDY_PLATFORM_NAME
    assert event.message_str == "你好"
    assert event.get_extra("selected_provider") == "provider-1"
    assert event.get_extra("enable_streaming") is False
    assert event.get_extra("buddy_prompt_context")["system_prompt"] == "buddy prompt"


@pytest.mark.asyncio
async def test_main_chain_backend_round_trip():
    event_queue: asyncio.Queue = asyncio.Queue()
    queue_mgr = BuddyQueueManager()
    adapter = BuddyPlatformAdapter(
        platform_config={"id": BUDDY_PLATFORM_NAME},
        event_queue=event_queue,
        queue_mgr=queue_mgr,
    )
    backend = AstrBotMainChainBackend(
        adapter=adapter,
        configured_provider_id="provider-1",
        request_timeout_seconds=2,
    )

    plugin = object.__new__(PluginMain)
    plugin.config = {}

    async def worker() -> None:
        event = await event_queue.get()
        req = ProviderRequest(prompt=event.message_str, system_prompt="base prompt")
        await PluginMain.decorate_buddy_request(plugin, event, req)
        assert req.func_tool is None
        assert "buddy prompt" in req.system_prompt

        resp = LLMResponse(
            role="assistant",
            completion_text='{"reply":"收到，我记住了。","emotion":"happy","motion":"wave","memory":"你在写插件"}',
        )
        await PluginMain.capture_buddy_response(plugin, event, resp)
        await event.send(MessageChain().message(resp.completion_text))
        await event.send(None)

    worker_task = asyncio.create_task(worker())
    result = await backend.request_reply(
        session_id="browser-session",
        user_message="我在写插件",
        prompt_context={"system_prompt": "buddy prompt"},
    )
    await worker_task

    assert result.reply_text == "收到，我记住了。"
    assert result.structured["memory"] == "你在写插件"
