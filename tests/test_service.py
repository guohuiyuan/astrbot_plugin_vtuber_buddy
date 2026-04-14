from __future__ import annotations

from datetime import UTC, datetime, timedelta

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


def build_service(tmp_path, **runtime_config):
    live2d_service, selection_key = build_live2d_service(tmp_path)
    service = BuddyConversationService(
        store=BuddyStore(tmp_path / "buddy_state.sqlite3"),
        chat_backend=StubChatBackend(
            reply_text="记住了。",
            structured={
                "reply": "记住了。",
                "emotion": "happy",
                "motion": "wave",
                "memory": "你喜欢抹茶",
            },
        ),
        plugin_data_dir=tmp_path,
        runtime_config=runtime_config,
        live2d_service=live2d_service,
    )
    return service, selection_key


@pytest.mark.asyncio
async def test_state_decay_feed_clean_and_sqlite_persistence(tmp_path):
    service, _ = build_service(
        tmp_path,
        satiety_decay_per_hour=240,
        cleanliness_decay_per_hour=220,
        mood_decay_per_hour=12,
    )
    await service.initialize()

    session = await service.store.load_session("pet")
    session.stats.coins = 50
    session.stats.satiety = 600
    session.stats.cleanliness = 700
    session.stats.illness = 35
    session.stats.updated_at = (
        datetime.now(UTC) - timedelta(hours=2)
    ).isoformat(timespec="seconds")
    await service.store.save_session(session)

    decayed = await service.get_state("pet")
    assert decayed["stats"]["satiety"] < 15
    assert decayed["stats"]["cleanliness"] < 10
    assert decayed["stats"]["illness"] >= 30
    assert decayed["live2d"]["available"] is True

    fed = await service.feed("pet")
    assert "收到" in fed["speech"]
    assert fed["stats"]["coins"] == decayed["stats"]["coins"] - 12
    assert fed["stats"]["satiety"] > decayed["stats"]["satiety"]

    cleaned = await service.clean("pet")
    assert "洗香香" in cleaned["speech"]
    assert cleaned["stats"]["coins"] == fed["stats"]["coins"] - 10
    assert cleaned["stats"]["cleanliness"] > fed["stats"]["cleanliness"]
    assert cleaned["stats"]["illness"] < decayed["stats"]["illness"]

    reloaded = await service.store.load_session("pet")
    assert reloaded.stats.coins == cleaned["stats"]["coins"]
    assert reloaded.speech == cleaned["speech"]
    assert (tmp_path / "buddy_state.sqlite3").read_bytes()[:16] == b"SQLite format 3\x00"


@pytest.mark.asyncio
async def test_work_cycle_settles_reward_and_costs(tmp_path):
    service, _ = build_service(tmp_path, work_duration_minutes=15)
    await service.initialize()

    started = await service.work("worker")
    assert started["work"]["status"] == "working"
    assert "分钟后回来" in started["speech"]
    spent_energy = started["stats"]["energy"]

    session = await service.store.load_session("worker")
    reward_coins = session.work.reward_coins
    reward_exp = session.work.reward_experience
    session.work.finish_at = (datetime.now(UTC) - timedelta(minutes=1)).isoformat(
        timespec="seconds"
    )
    await service.store.save_session(session)

    settled = await service.work("worker")
    assert settled["work"]["status"] == "idle"
    assert settled["stats"]["coins"] >= 120 + reward_coins
    assert settled["stats"]["experience"] >= reward_exp
    assert "收工" in settled["speech"]
    assert spent_energy < 78


@pytest.mark.asyncio
async def test_chat_can_store_memory_without_duplicates(tmp_path):
    service, _ = build_service(tmp_path, memory_limit=8)
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
        store=BuddyStore(tmp_path / "buddy_state.sqlite3"),
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
    service, selection_key = build_service(tmp_path)
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
