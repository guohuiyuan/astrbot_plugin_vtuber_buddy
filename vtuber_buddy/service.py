from __future__ import annotations

import asyncio
import json
import math
import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .bridge import BuddyChatBackend
from .live2d_service import BuddyLive2DService
from .models import (
    AFFECTION_MAX,
    ENERGY_MAX,
    HEALTH_MAX,
    ILLNESS_MAX,
    MAX_LEVEL,
    MOOD_MAX,
    BuddyReply,
    BuddySession,
    BuddyWorkState,
    ChatTurn,
    MemoryFact,
    clamp,
    experience_for_next_level,
    need_capacity,
    to_percent,
    utc_now,
)
from .store import BuddyStore

EMOTIONS = {
    "neutral",
    "happy",
    "shy",
    "excited",
    "grumpy",
    "concerned",
    "sleepy",
}

MOTIONS = {"idle", "wave", "nod", "bounce", "pout", "blink"}

MEMORY_PATTERNS = [
    re.compile(r"我喜欢(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我最爱(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我的生日是(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我讨厌(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我经常(?P<fact>[^，。！？\n]{1,24})"),
]

JOB_LABELS = (
    "接陪伴通告",
    "帮你赚零花",
    "练习营业状态",
)


def _parse_iso(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _coerce_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _title_from_affection(affection: float) -> str:
    if affection >= 850:
        return "最亲密"
    if affection >= 600:
        return "很依赖你"
    if affection >= 350:
        return "越来越熟"
    if affection >= 150:
        return "刚熟起来"
    return "初次贴贴"


def _condition_label(session: BuddySession) -> str:
    stats = session.stats
    capacity = need_capacity(stats.level)
    satiety = to_percent(stats.satiety, capacity)
    cleanliness = to_percent(stats.cleanliness, capacity)

    if session.work.status == "working":
        return "工作中"
    if stats.health <= 280:
        return "危险"
    if stats.illness >= 30:
        return "生病"
    if satiety <= 12:
        return "很饿"
    if cleanliness <= 24:
        return "脏兮兮"
    if stats.energy <= 220:
        return "犯困"
    if stats.mood >= 850 and stats.energy >= 650:
        return "活力满满"
    return "稳定"


def _work_status_summary(session: BuddySession) -> str:
    if session.work.status != "working":
        return "空闲"

    finish_at = _parse_iso(session.work.finish_at)
    remaining_seconds = max(
        0,
        int((finish_at - datetime.now(UTC)).total_seconds()),
    )
    remaining_minutes = max(1, math.ceil(remaining_seconds / 60))
    return f"{session.work.label or '打工'}中，还要 {remaining_minutes} 分钟"


def _status_summary(session: BuddySession) -> str:
    stats = session.stats
    capacity = need_capacity(stats.level)
    satiety = to_percent(stats.satiety, capacity)
    cleanliness = to_percent(stats.cleanliness, capacity)

    if session.work.status == "working":
        return _work_status_summary(session)
    if stats.health <= 280:
        return "状态危险，先补状态再聊天。"
    if stats.illness >= 30:
        return "身体有点不舒服，清洁和休息优先。"
    if satiety <= 12:
        return "饱食度跌进危险线了，先喂食。"
    if cleanliness <= 24:
        return "清洁度太低，继续拖着会掉健康。"
    if stats.energy <= 220:
        return "精力偏低，互动收益会打折。"
    if stats.mood >= 850:
        return "心情很好，成长效率会有加成。"
    return "状态稳定，适合继续互动。"


def _recent_history_text(session: BuddySession) -> str:
    if not session.history:
        return "- 暂无对话记录"

    lines = []
    for item in session.history[-6:]:
        speaker = session.settings.buddy_name if item.role == "assistant" else "User"
        lines.append(f"- {speaker}: {item.text}")
    return "\n".join(lines)


def build_buddy_system_prompt(session: BuddySession) -> str:
    stats = session.stats
    capacity = need_capacity(stats.level)
    memory_lines = "\n".join(
        f"- {item.content}" for item in session.memories[-8:] if item.content
    )
    if not memory_lines:
        memory_lines = "- 目前还没有稳定记忆"

    suffix = session.settings.system_prompt_suffix.strip()
    history_lines = _recent_history_text(session)
    return (
        "You are a compact VTuber desktop pet living inside an AstrBot plugin.\n"
        "Stay lively, emotionally reactive, caring, and slightly tsundere.\n"
        f"Buddy name: {session.settings.buddy_name}\n"
        f"User nickname: {session.settings.user_name}\n"
        f"Level: {stats.level}\n"
        f"Coins: {stats.coins}\n"
        f"Satiety: {to_percent(stats.satiety, capacity):.0f}/100\n"
        f"Cleanliness: {to_percent(stats.cleanliness, capacity):.0f}/100\n"
        f"Mood: {stats.mood / 10:.0f}/100\n"
        f"Energy: {stats.energy / 10:.0f}/100\n"
        f"Health: {stats.health / 10:.0f}/100\n"
        f"Affection: {stats.affection / 10:.0f}/100\n"
        f"Condition: {_condition_label(session)}\n"
        f"Status hint: {_status_summary(session)}\n"
        f"Work state: {_work_status_summary(session)}\n"
        "Known user memories:\n"
        f"{memory_lines}\n"
        "Recent dialogue:\n"
        f"{history_lines}\n"
        "Reply in the same language as the user's message.\n"
        "Keep the visible spoken reply natural and brief, usually within 80 Chinese characters.\n"
        "If the buddy is hungry, dirty, sick, or tired, the tone can show it, but never become hostile.\n"
        "Return ONLY one JSON object with these keys:\n"
        '{"reply":"text","emotion":"neutral|happy|shy|excited|grumpy|concerned|sleepy","motion":"idle|wave|nod|bounce|pout|blink","memory":"short stable fact or empty string"}\n'
        "Only write a non-empty memory when the user reveals a stable preference, fact, or recurring habit worth remembering.\n"
        f"{suffix}"
    ).strip()


def parse_buddy_reply(raw_reply: str) -> BuddyReply:
    candidate = str(raw_reply or "").strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        candidate = candidate.removeprefix("json").strip()

    json_match = re.search(r"\{.*\}", candidate, re.S)
    if json_match:
        candidate = json_match.group(0)

    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        return BuddyReply(reply="")

    reply = str(payload.get("reply", "")).strip()
    emotion = str(payload.get("emotion", "neutral")).strip().lower()
    motion = str(payload.get("motion", "idle")).strip().lower()
    memory = str(payload.get("memory", "")).strip()

    if emotion not in EMOTIONS:
        emotion = "neutral"
    if motion not in MOTIONS:
        motion = "idle"

    return BuddyReply(
        reply=reply[:160],
        emotion=emotion,
        motion=motion,
        memory=memory[:64],
    )


def coerce_buddy_reply(raw_reply: str) -> BuddyReply:
    parsed = parse_buddy_reply(raw_reply)
    if parsed.reply:
        return parsed

    fallback_text = str(raw_reply or "").strip() or "嗯，我在听。"
    return BuddyReply(
        reply=fallback_text[:120],
        emotion="neutral",
        motion="idle",
    )


def buddy_reply_to_payload(reply: BuddyReply) -> dict:
    return {
        "reply": reply.reply,
        "emotion": reply.emotion,
        "motion": reply.motion,
        "memory": reply.memory,
    }


def buddy_reply_from_payload(
    payload: dict | None,
    fallback_text: str = "",
) -> BuddyReply:
    if not isinstance(payload, dict):
        return coerce_buddy_reply(fallback_text)

    reply = str(payload.get("reply", fallback_text)).strip()[:160]
    emotion = str(payload.get("emotion", "neutral")).strip().lower()
    motion = str(payload.get("motion", "idle")).strip().lower()
    memory = str(payload.get("memory", "")).strip()[:64]

    if emotion not in EMOTIONS:
        emotion = "neutral"
    if motion not in MOTIONS:
        motion = "idle"
    if not reply:
        reply = coerce_buddy_reply(fallback_text).reply

    return BuddyReply(reply=reply, emotion=emotion, motion=motion, memory=memory)


class BuddyConversationService:
    """State machine and AstrBot main-chain chat logic for VTuber Buddy."""

    def __init__(
        self,
        *,
        store: BuddyStore,
        chat_backend: BuddyChatBackend,
        plugin_data_dir: Path,
        runtime_config,
        live2d_service: BuddyLive2DService | None = None,
    ) -> None:
        self.store = store
        self.chat_backend = chat_backend
        self.plugin_data_dir = plugin_data_dir
        self.runtime_config = runtime_config
        self.live2d_service = live2d_service
        self._session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def initialize(self) -> None:
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        await self.store.initialize()

    async def get_state(self, session_id: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def get_live2d_config(self, session_id: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
        return await self._live2d_payload(session)

    async def update_settings(self, session_id: str, settings_payload: dict) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            settings = session.settings
            settings.buddy_name = (
                str(settings_payload.get("buddy_name", settings.buddy_name)).strip()
                or settings.buddy_name
            )
            settings.user_name = (
                str(settings_payload.get("user_name", settings.user_name)).strip()
                or settings.user_name
            )
            settings.live2d_selection_key = (
                str(
                    settings_payload.get(
                        "live2d_selection_key",
                        settings.live2d_selection_key,
                    )
                ).strip()
                or settings.live2d_selection_key
            )
            settings.live2d_model_url = str(
                settings_payload.get("live2d_model_url", settings.live2d_model_url)
            ).strip()
            settings.live2d_mouse_follow_enabled = _coerce_bool(
                settings_payload.get(
                    "live2d_mouse_follow_enabled",
                    settings.live2d_mouse_follow_enabled,
                ),
                settings.live2d_mouse_follow_enabled,
            )
            settings.accent_color = (
                str(settings_payload.get("accent_color", settings.accent_color)).strip()
                or settings.accent_color
            )
            settings.system_prompt_suffix = str(
                settings_payload.get(
                    "system_prompt_suffix",
                    settings.system_prompt_suffix,
                )
            ).strip()
            session.updated_at = utc_now()
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def feed(self, session_id: str, food_name: str = "营养餐") -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            stats = session.stats
            capacity = need_capacity(stats.level)
            satiety_percent = to_percent(stats.satiety, capacity)

            if session.work.status == "working":
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = f"我还在{session.work.label}，等我回来再认真吃。"
            elif satiety_percent >= 94:
                stats.mood = clamp(stats.mood - 18, 0.0, MOOD_MAX)
                session.current_emotion = "grumpy"
                session.current_motion = "pout"
                session.speech = "我现在一点都不饿，先把金币省下来。"
            elif stats.coins < 12:
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = "金币不够买饭啦，先让我去打个工。"
            else:
                stats.coins -= 12
                stats.satiety = clamp(
                    stats.satiety + (1180.0 if satiety_percent < 25 else 880.0),
                    0.0,
                    capacity,
                )
                stats.mood = clamp(stats.mood + 42, 0.0, MOOD_MAX)
                stats.health = clamp(stats.health + 10, 0.0, HEALTH_MAX)
                stats.affection = clamp(stats.affection + 16, 0.0, AFFECTION_MAX)
                stats.experience += 12
                session.current_emotion = "happy"
                session.current_motion = "bounce"
                session.speech = f"{food_name}收到，今天先原谅你一秒。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)
                self._apply_level_up(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def clean(self, session_id: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            stats = session.stats
            capacity = need_capacity(stats.level)
            cleanliness_percent = to_percent(stats.cleanliness, capacity)

            if session.work.status == "working":
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = f"我还在{session.work.label}，回来再洗香香。"
            elif cleanliness_percent >= 96:
                session.current_emotion = "shy"
                session.current_motion = "nod"
                session.speech = "已经很干净了，不用这么紧张。"
            elif stats.coins < 10:
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = "清洁用品不够啦，先去赚点金币。"
            else:
                stats.coins -= 10
                stats.cleanliness = clamp(stats.cleanliness + 980.0, 0.0, capacity)
                stats.mood = clamp(stats.mood + 34, 0.0, MOOD_MAX)
                stats.health = clamp(stats.health + 16, 0.0, HEALTH_MAX)
                stats.illness = clamp(stats.illness - 18, 0.0, ILLNESS_MAX)
                stats.affection = clamp(stats.affection + 12, 0.0, AFFECTION_MAX)
                stats.experience += 10
                session.current_emotion = "happy"
                session.current_motion = "wave"
                session.speech = "洗香香完成，抱起来会舒服很多。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)
                self._apply_level_up(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def work(self, session_id: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            advance = self._apply_decay(session)
            if advance["work_settled"]:
                await self.store.save_session(session)
                return await self._session_payload(session)

            stats = session.stats
            capacity = need_capacity(stats.level)
            satiety_percent = to_percent(stats.satiety, capacity)
            cleanliness_percent = to_percent(stats.cleanliness, capacity)

            if session.work.status == "working":
                session.current_emotion = "excited"
                session.current_motion = "wave"
                session.speech = f"我还在{session.work.label}，先等我收工。"
            elif satiety_percent < 28:
                session.current_emotion = "grumpy"
                session.current_motion = "pout"
                session.speech = "太饿了，先喂饱我再让我打工。"
            elif cleanliness_percent < 30:
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = "这副样子出门营业不太行，先帮我收拾一下。"
            elif stats.energy < 360:
                session.current_emotion = "sleepy"
                session.current_motion = "blink"
                session.speech = "我现在有点没电，先休息一会儿。"
            elif stats.health < 420 or stats.illness >= 65:
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.speech = "我这状态不适合打工，先把身体养回来。"
            else:
                duration_minutes = max(
                    15,
                    int(self.runtime_config.get("work_duration_minutes", 45)),
                )
                reward_coins = (
                    18
                    + stats.level * 5
                    + int(stats.mood / 120)
                    + int(stats.affection / 180)
                )
                reward_experience = 18 + stats.level * 3
                label = JOB_LABELS[(stats.level - 1) % len(JOB_LABELS)]
                now = datetime.now(UTC)

                session.work = BuddyWorkState(
                    status="working",
                    label=label,
                    started_at=now.isoformat(timespec="seconds"),
                    finish_at=(now + timedelta(minutes=duration_minutes)).isoformat(
                        timespec="seconds"
                    ),
                    duration_minutes=duration_minutes,
                    reward_coins=reward_coins,
                    reward_experience=reward_experience,
                    satiety_cost=260.0,
                    cleanliness_cost=320.0,
                    energy_cost=280.0,
                )
                stats.satiety = clamp(stats.satiety - 260.0, 0.0, capacity)
                stats.cleanliness = clamp(
                    stats.cleanliness - 320.0,
                    0.0,
                    capacity,
                )
                stats.energy = clamp(stats.energy - 280.0, 0.0, ENERGY_MAX)
                stats.mood = clamp(stats.mood - 18.0, 0.0, MOOD_MAX)
                session.current_emotion = "excited"
                session.current_motion = "wave"
                session.speech = f"我去{label}，大概 {duration_minutes} 分钟后回来。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def touch(self, session_id: str, area: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            stats = session.stats
            area = str(area or "head").lower()

            if session.work.status == "working":
                session.current_emotion = "excited"
                session.current_motion = "wave"
                session.speech = "先别戳啦，我还在工作模式里。"
            elif area == "head":
                stats.mood = clamp(stats.mood + 18, 0.0, MOOD_MAX)
                stats.affection = clamp(stats.affection + 16, 0.0, AFFECTION_MAX)
                session.current_emotion = "shy"
                session.current_motion = "nod"
                session.speech = "摸头可以，但别得寸进尺。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)
            elif area == "cheek":
                stats.mood = clamp(stats.mood + 8, 0.0, MOOD_MAX)
                stats.affection = clamp(stats.affection + 10, 0.0, AFFECTION_MAX)
                session.current_emotion = "shy"
                session.current_motion = "pout"
                session.speech = "捏脸会分心的……不过今天先算了。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)
            else:
                if stats.affection < 260:
                    stats.mood = clamp(stats.mood - 12, 0.0, MOOD_MAX)
                    session.current_emotion = "grumpy"
                    session.current_motion = "pout"
                    session.speech = "这里现在还不行，先慢慢熟起来。"
                else:
                    stats.mood = clamp(stats.mood + 20, 0.0, MOOD_MAX)
                    stats.affection = clamp(stats.affection + 18, 0.0, AFFECTION_MAX)
                    stats.health = clamp(stats.health + 4, 0.0, HEALTH_MAX)
                    session.current_emotion = "happy"
                    session.current_motion = "bounce"
                    session.speech = "今天给你抱一下，别到处说。"
                self._touch_timestamps(session)
                self._record_assistant_line(session)

            self._apply_level_up(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    async def chat(self, session_id: str, message: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            clean_message = str(message).strip()
            if not clean_message:
                return await self._session_payload(session)

            session.history.append(ChatTurn(role="user", text=clean_message))
            heuristic_memory = self._heuristic_memory(clean_message)

            try:
                backend_result = await self.chat_backend.request_reply(
                    session_id=session.session_id,
                    user_message=clean_message,
                    prompt_context={
                        "system_prompt": build_buddy_system_prompt(session),
                    },
                )
                reply = buddy_reply_from_payload(
                    backend_result.structured,
                    backend_result.reply_text,
                )
            except Exception:
                reply = BuddyReply(
                    reply="刚才 AstrBot 主链路没有把回复送回来，再和我说一次。",
                    emotion="concerned",
                    motion="blink",
                )

            session.current_emotion = reply.emotion
            session.current_motion = reply.motion
            session.speech = reply.reply
            session.history.append(
                ChatTurn(
                    role="assistant",
                    text=reply.reply,
                    emotion=reply.emotion,
                    motion=reply.motion,
                )
            )
            self._remember(session, reply.memory or heuristic_memory)
            self._after_chat(session, reply)
            self._trim_history(session)
            self._touch_timestamps(session)
            self._apply_level_up(session)
            await self.store.save_session(session)
        return await self._session_payload(session)

    def _apply_decay(self, session: BuddySession) -> dict[str, bool]:
        now = datetime.now(UTC)
        try:
            last = _parse_iso(session.stats.updated_at)
        except ValueError:
            last = now

        elapsed_hours = max(0.0, (now - last).total_seconds() / 3600.0)
        result = {"work_settled": False, "leveled_up": False}
        stats = session.stats
        capacity = need_capacity(stats.level)

        if elapsed_hours > 0:
            satiety_decay = float(
                self.runtime_config.get("satiety_decay_per_hour", 150)
            )
            cleanliness_decay = float(
                self.runtime_config.get("cleanliness_decay_per_hour", 130)
            )
            mood_decay = float(self.runtime_config.get("mood_decay_per_hour", 18))
            energy_recovery = float(
                self.runtime_config.get("energy_recovery_per_hour", 90)
            )
            growth_exp = float(self.runtime_config.get("growth_exp_per_hour", 100))
            affection_decay = float(
                self.runtime_config.get("affection_decay_per_hour", 2)
            )

            stats.satiety -= satiety_decay * elapsed_hours
            stats.cleanliness -= cleanliness_decay * elapsed_hours
            stats.mood -= mood_decay * elapsed_hours
            if session.work.status == "working":
                stats.energy -= 24 * elapsed_hours
            else:
                stats.energy += energy_recovery * elapsed_hours

            satiety_ratio = stats.satiety / capacity if capacity else 0.0
            cleanliness_ratio = stats.cleanliness / capacity if capacity else 0.0
            low_satiety = satiety_ratio < 0.12
            low_cleanliness = cleanliness_ratio < 0.24

            if low_satiety:
                stats.illness += 22 * elapsed_hours
                stats.health -= 58 * elapsed_hours
                stats.mood -= 36 * elapsed_hours
            if low_cleanliness:
                stats.illness += 16 * elapsed_hours
                stats.health -= 44 * elapsed_hours
                stats.mood -= 24 * elapsed_hours
            if not low_satiety and not low_cleanliness:
                stats.illness -= 8 * elapsed_hours
                if stats.energy > 450 and stats.mood > 650:
                    stats.health += 16 * elapsed_hours

            if stats.illness >= 30:
                stats.health -= stats.illness * 0.3 * elapsed_hours
                stats.mood -= 12 * elapsed_hours

            if stats.health < 400:
                stats.energy -= 20 * elapsed_hours
                stats.mood -= 14 * elapsed_hours

            if stats.energy < 180:
                stats.mood -= 18 * elapsed_hours

            try:
                last_interaction = _parse_iso(stats.last_interaction_at)
            except ValueError:
                last_interaction = now
            idle_hours = max(0.0, (now - last_interaction).total_seconds() / 3600.0)
            if idle_hours > 8:
                stats.affection -= affection_decay * elapsed_hours

            exp_gain = growth_exp * elapsed_hours
            if 900 <= stats.mood <= 1000:
                exp_gain *= 1.3
            elif stats.mood < 600:
                exp_gain *= 0.8
            if stats.illness >= 30:
                exp_gain *= 0.75
            if session.work.status == "working":
                exp_gain *= 0.85
            stats.experience += int(exp_gain)

        result["work_settled"] = self._settle_finished_work(session, now)
        result["leveled_up"] = self._apply_level_up(session)
        self._normalize_stats(session)
        self._refresh_idle_presence(session)

        timestamp = now.isoformat(timespec="seconds")
        session.updated_at = timestamp
        session.stats.updated_at = timestamp
        return result

    def _settle_finished_work(self, session: BuddySession, now: datetime) -> bool:
        if session.work.status != "working" or not session.work.finish_at:
            return False

        try:
            finish_at = _parse_iso(session.work.finish_at)
        except ValueError:
            finish_at = now

        if now < finish_at:
            return False

        stats = session.stats
        stats.coins += session.work.reward_coins
        stats.experience += session.work.reward_experience
        stats.mood = clamp(stats.mood + 36, 0.0, MOOD_MAX)
        stats.affection = clamp(stats.affection + 10, 0.0, AFFECTION_MAX)
        session.current_emotion = "happy"
        session.current_motion = "wave"
        session.speech = (
            f"我收工啦，这次赚了 {session.work.reward_coins} 金币，"
            f"还拿了 {session.work.reward_experience} 点成长。"
        )
        session.work = BuddyWorkState()
        self._touch_timestamps(session)
        self._record_assistant_line(session)
        return True

    def _normalize_stats(self, session: BuddySession) -> None:
        stats = session.stats
        capacity = need_capacity(stats.level)
        stats.satiety = clamp(stats.satiety, 0.0, capacity)
        stats.cleanliness = clamp(stats.cleanliness, 0.0, capacity)
        stats.mood = clamp(stats.mood, 0.0, MOOD_MAX)
        stats.energy = clamp(stats.energy, 0.0, ENERGY_MAX)
        stats.health = clamp(stats.health, 0.0, HEALTH_MAX)
        stats.affection = clamp(stats.affection, 0.0, AFFECTION_MAX)
        stats.illness = clamp(stats.illness, 0.0, ILLNESS_MAX)
        stats.level = int(clamp(stats.level, 1, MAX_LEVEL))
        stats.experience = max(0, int(stats.experience))
        stats.coins = max(0, int(stats.coins))

    def _apply_level_up(self, session: BuddySession) -> bool:
        leveled_up = False
        stats = session.stats
        while stats.level < MAX_LEVEL:
            need_exp = experience_for_next_level(stats.level)
            if stats.experience < need_exp:
                break
            stats.experience -= need_exp
            stats.level += 1
            leveled_up = True

        if not leveled_up:
            return False

        capacity = need_capacity(stats.level)
        stats.satiety = clamp(stats.satiety + 260.0, 0.0, capacity)
        stats.cleanliness = clamp(stats.cleanliness + 220.0, 0.0, capacity)
        stats.health = clamp(stats.health + 60.0, 0.0, HEALTH_MAX)
        stats.energy = clamp(stats.energy + 80.0, 0.0, ENERGY_MAX)
        session.current_emotion = "excited"
        session.current_motion = "bounce"
        session.speech = f"我升到 Lv.{stats.level} 了，之后会更会陪你。"
        self._touch_timestamps(session)
        self._record_assistant_line(session)
        return True

    def _heuristic_memory(self, message: str) -> str:
        for pattern in MEMORY_PATTERNS:
            matched = pattern.search(message)
            if matched:
                fact = matched.group("fact").strip()
                if 1 <= len(fact) <= 24:
                    return message[:48].strip()
        return ""

    def _remember(self, session: BuddySession, fact: str) -> None:
        fact = fact.strip()
        if not fact:
            return
        normalized = fact.casefold()
        for memory in session.memories:
            if memory.content.casefold() == normalized:
                memory.weight += 1
                return
        session.memories.append(MemoryFact(content=fact))
        memory_limit = int(self.runtime_config.get("memory_limit", 12))
        session.memories = session.memories[-memory_limit:]

    def _after_chat(self, session: BuddySession, reply: BuddyReply) -> None:
        stats = session.stats
        capacity = need_capacity(stats.level)
        stats.satiety = clamp(stats.satiety - 45.0, 0.0, capacity)
        stats.energy = clamp(stats.energy - 28.0, 0.0, ENERGY_MAX)
        stats.experience += 8
        if reply.emotion in {"happy", "shy", "excited"}:
            stats.mood = clamp(stats.mood + 20, 0.0, MOOD_MAX)
            stats.affection = clamp(stats.affection + 14, 0.0, AFFECTION_MAX)
        elif reply.emotion == "grumpy":
            stats.mood = clamp(stats.mood - 6, 0.0, MOOD_MAX)
            stats.affection = clamp(stats.affection + 4, 0.0, AFFECTION_MAX)
        else:
            stats.mood = clamp(stats.mood + 8, 0.0, MOOD_MAX)
            stats.affection = clamp(stats.affection + 9, 0.0, AFFECTION_MAX)

    def _touch_timestamps(self, session: BuddySession) -> None:
        now = utc_now()
        session.updated_at = now
        session.stats.updated_at = now
        session.stats.last_interaction_at = now

    def _record_assistant_line(self, session: BuddySession) -> None:
        session.history.append(
            ChatTurn(
                role="assistant",
                text=session.speech,
                emotion=session.current_emotion,
                motion=session.current_motion,
            )
        )
        self._trim_history(session)

    def _trim_history(self, session: BuddySession) -> None:
        history_limit = max(8, int(self.runtime_config.get("history_limit", 10)) * 2)
        session.history = session.history[-history_limit:]

    def _refresh_idle_presence(self, session: BuddySession) -> None:
        if session.work.status == "working":
            session.current_emotion = "excited"
            session.current_motion = "wave"
            session.speech = f"我在{session.work.label}，忙完就回来。"
            return

        stats = session.stats
        capacity = need_capacity(stats.level)
        satiety = to_percent(stats.satiety, capacity)
        cleanliness = to_percent(stats.cleanliness, capacity)

        if stats.health <= 280:
            session.current_emotion = "concerned"
            session.current_motion = "blink"
            session.speech = "我状态有点危险，先帮我把基础属性拉回来。"
        elif stats.illness >= 30:
            session.current_emotion = "concerned"
            session.current_motion = "blink"
            session.speech = "有点不舒服，清洁和休息先排前面。"
        elif satiety <= 12:
            session.current_emotion = "grumpy"
            session.current_motion = "pout"
            session.speech = "肚子空空的，先别指望我太热情。"
        elif cleanliness <= 24:
            session.current_emotion = "concerned"
            session.current_motion = "blink"
            session.speech = "我现在有点脏，继续拖着会掉健康。"
        elif stats.energy <= 220:
            session.current_emotion = "sleepy"
            session.current_motion = "blink"
            session.speech = "让我缓一缓，电量有点见底。"
        elif stats.mood >= 850:
            session.current_emotion = "happy"
            session.current_motion = "idle"
            session.speech = "今天状态很好，快来多陪我一会儿。"

    async def _live2d_payload(self, session: BuddySession) -> dict:
        if self.live2d_service is None:
            return {}
        return await self.live2d_service.build_config(
            selection_key=session.settings.live2d_selection_key,
            custom_model_url=session.settings.live2d_model_url,
            mouse_follow_enabled=session.settings.live2d_mouse_follow_enabled,
        )

    def _work_payload(self, session: BuddySession) -> dict:
        if session.work.status != "working":
            return {
                "status": "idle",
                "label": "空闲",
                "remaining_minutes": 0,
                "duration_minutes": 0,
                "reward_coins": 0,
                "reward_experience": 0,
            }

        finish_at = _parse_iso(session.work.finish_at)
        remaining_seconds = max(
            0,
            int((finish_at - datetime.now(UTC)).total_seconds()),
        )
        return {
            "status": "working",
            "label": session.work.label or "打工",
            "remaining_minutes": max(1, math.ceil(remaining_seconds / 60)),
            "duration_minutes": session.work.duration_minutes,
            "reward_coins": session.work.reward_coins,
            "reward_experience": session.work.reward_experience,
        }

    async def _session_payload(self, session: BuddySession) -> dict:
        stats = session.stats
        capacity = need_capacity(stats.level)
        return {
            "session_id": session.session_id,
            "speech": session.speech,
            "current_emotion": session.current_emotion,
            "current_motion": session.current_motion,
            "stats": {
                "level": stats.level,
                "experience": stats.experience,
                "next_level_experience": experience_for_next_level(stats.level),
                "coins": stats.coins,
                "satiety": round(to_percent(stats.satiety, capacity), 1),
                "cleanliness": round(to_percent(stats.cleanliness, capacity), 1),
                "mood": round(stats.mood / 10.0, 1),
                "energy": round(stats.energy / 10.0, 1),
                "health": round(stats.health / 10.0, 1),
                "affection": round(stats.affection / 10.0, 1),
                "illness": round(stats.illness, 1),
                "title": _title_from_affection(stats.affection),
                "condition": _condition_label(session),
                "status_hint": _status_summary(session),
            },
            "work": self._work_payload(session),
            "settings": session.settings.to_dict(),
            "history": [item.to_dict() for item in session.history[-8:]],
            "memories": [item.to_dict() for item in session.memories[-8:]],
            "provider": self.chat_backend.describe(),
            "live2d": await self._live2d_payload(session),
        }
