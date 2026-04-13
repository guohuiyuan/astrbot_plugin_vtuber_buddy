from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from data.plugins.astrbot_plugin_vtuber_buddy.tests.live2d_fixture import (
    create_sample_live2d_root,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.bridge import (
    BuddyBackendResult,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.live2d_service import (
    BuddyLive2DService,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.service import (
    BuddyConversationService,
)
from data.plugins.astrbot_plugin_vtuber_buddy.vtuber_buddy.store import BuddyStore


class StubChatBackend:
    def __init__(self, reply_text: str, structured: dict | None = None) -> None:
        self.reply_text = reply_text
        self.structured = structured

    async def request_reply(self, **kwargs) -> BuddyBackendResult:
        del kwargs
        return BuddyBackendResult(
            reply_text=self.reply_text,
            structured=self.structured,
        )

    def describe(self) -> str:
        return "stub-main-chain"


def build_live2d_service(tmp_path):
    builtin_root = tmp_path / "builtin_live2d"
    selection_key = create_sample_live2d_root(builtin_root)
    service = BuddyLive2DService(
        workspace_root=tmp_path / "workspace_live2d",
        builtin_root=builtin_root,
        default_selection_key=selection_key,
    )
    return service, selection_key


@pytest.mark.asyncio
async def test_state_decay_and_feed_cycle(tmp_path):
    live2d_service, _ = build_live2d_service(tmp_path)
    store = BuddyStore(tmp_path / "sessions.json")
    service = BuddyConversationService(
        store=store,
        chat_backend=StubChatBackend(
            reply_text="",
            structured={
                "reply": "好的。",
                "emotion": "neutral",
                "motion": "idle",
                "memory": "",
            },
        ),
        plugin_data_dir=tmp_path,
        runtime_config={"satiety_decay_per_hour": 5, "mood_decay_per_hour": 3},
        live2d_service=live2d_service,
    )
    await service.initialize()

    session = await store.load_session("test-session")
    session.stats.updated_at = (
        datetime.now(timezone.utc) - timedelta(hours=2)
    ).isoformat(timespec="seconds")
    await store.save_session(session)

    decayed = await service.get_state("test-session")
    assert decayed["stats"]["satiety"] <= 62.1
    assert decayed["stats"]["mood"] <= 72.1
    assert decayed["live2d"]["available"] is True

    fed = await service.feed("test-session", "布丁")
    assert fed["speech"].startswith("布丁收到了")
    assert fed["stats"]["satiety"] > decayed["stats"]["satiety"]
    assert fed["live2d"]["model_name"] == "sample"


@pytest.mark.asyncio
async def test_chat_can_store_memory_without_duplicates(tmp_path):
    live2d_service, _ = build_live2d_service(tmp_path)
    store = BuddyStore(tmp_path / "sessions.json")
    service = BuddyConversationService(
        store=store,
        chat_backend=StubChatBackend(
            reply_text="抹茶我记住了。",
            structured={
                "reply": "抹茶我记住了。",
                "emotion": "happy",
                "motion": "wave",
                "memory": "你喜欢抹茶",
            },
        ),
        plugin_data_dir=tmp_path,
        runtime_config={"memory_limit": 8},
        live2d_service=live2d_service,
    )
    await service.initialize()

    result = await service.chat("memory-session", "我喜欢抹茶")
    assert result["memories"][0]["content"] == "你喜欢抹茶"

    result = await service.chat("memory-session", "我还是喜欢抹茶")
    assert len(result["memories"]) == 1
    assert result["stats"]["affection"] > 18


@pytest.mark.asyncio
async def test_chat_falls_back_when_backend_fails(tmp_path):
    live2d_service, _ = build_live2d_service(tmp_path)

    class FailingBackend:
        async def request_reply(self, **kwargs):
            del kwargs
            raise RuntimeError("boom")

        def describe(self) -> str:
            return "broken"

    service = BuddyConversationService(
        store=BuddyStore(tmp_path / "sessions.json"),
        chat_backend=FailingBackend(),
        plugin_data_dir=tmp_path,
        runtime_config={},
        live2d_service=live2d_service,
    )
    await service.initialize()

    result = await service.chat("error-session", "你好")
    assert "AstrBot 主链路" in result["speech"]
    assert result["current_emotion"] == "concerned"


@pytest.mark.asyncio
async def test_update_settings_can_switch_live2d_mode(tmp_path):
    live2d_service, selection_key = build_live2d_service(tmp_path)
    service = BuddyConversationService(
        store=BuddyStore(tmp_path / "sessions.json"),
        chat_backend=StubChatBackend(reply_text="ok"),
        plugin_data_dir=tmp_path,
        runtime_config={},
        live2d_service=live2d_service,
    )
    await service.initialize()

    payload = await service.update_settings(
        "settings-session",
        {
            "buddy_name": "Mao",
            "live2d_selection_key": selection_key,
            "live2d_model_url": "https://example.com/custom.model3.json",
            "live2d_mouse_follow_enabled": False,
        },
    )

    assert payload["settings"]["buddy_name"] == "Mao"
    assert payload["live2d"]["is_custom_model"] is True
    assert payload["live2d"]["model_url"] == "https://example.com/custom.model3.json"
    assert payload["live2d"]["mouse_follow_enabled"] is False
