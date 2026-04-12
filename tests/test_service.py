from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from vtuber_buddy.service import BuddyConversationService
from vtuber_buddy.store import BuddyStore


class StubModelClient:
    def __init__(self, raw_reply: str) -> None:
        self.raw_reply = raw_reply

    async def generate_reply(self, **kwargs) -> str:
        del kwargs
        return self.raw_reply

    def describe(self) -> str:
        return "stub-model"


@pytest.mark.asyncio
async def test_state_decay_and_feed_cycle(tmp_path):
    store = BuddyStore(tmp_path / "sessions.json")
    service = BuddyConversationService(
        store=store,
        model_client=StubModelClient(
            '{"reply":"好的。","emotion":"neutral","motion":"idle","memory":""}'
        ),
        plugin_data_dir=tmp_path,
        runtime_config={"satiety_decay_per_hour": 5, "mood_decay_per_hour": 3},
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

    fed = await service.feed("test-session", "布丁")
    assert fed["speech"].startswith("布丁收到了")
    assert fed["stats"]["satiety"] > decayed["stats"]["satiety"]


@pytest.mark.asyncio
async def test_chat_can_store_memory_without_duplicates(tmp_path):
    store = BuddyStore(tmp_path / "sessions.json")
    service = BuddyConversationService(
        store=store,
        model_client=StubModelClient(
            '{"reply":"抹茶我记住了。","emotion":"happy","motion":"wave","memory":"你喜欢抹茶"}'
        ),
        plugin_data_dir=tmp_path,
        runtime_config={"memory_limit": 8},
    )
    await service.initialize()

    result = await service.chat("memory-session", "我喜欢抹茶")
    assert result["memories"][0]["content"] == "你喜欢抹茶"

    result = await service.chat("memory-session", "我还是喜欢抹茶")
    assert len(result["memories"]) == 1
    assert result["stats"]["affection"] > 18
