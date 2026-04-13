from __future__ import annotations

import asyncio
import json
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

from .bridge import BuddyChatBackend
from .models import BuddyReply, BuddySession, ChatTurn, MemoryFact, clamp, utc_now
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
    re.compile(r"我的生日是(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我最爱(?P<fact>[^，。！？\n]{1,24})"),
    re.compile(r"我讨厌(?P<fact>[^，。！？\n]{1,24})"),
]


def _parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _title_from_affection(affection: float) -> str:
    if affection >= 75:
        return "最亲密"
    if affection >= 45:
        return "熟络"
    return "刚认识"


def _status_summary(session: BuddySession) -> str:
    if session.stats.satiety < 20:
        return "很饿，容易闹脾气"
    if session.stats.mood < 25:
        return "心情不太好，需要先哄一哄"
    if session.stats.affection >= 60:
        return "已经开始把你当作重要的人了"
    return "状态稳定"


def build_buddy_system_prompt(session: BuddySession) -> str:
    memory_lines = "\n".join(
        f"- {item.content}" for item in session.memories[-8:] if item.content
    )
    if not memory_lines:
        memory_lines = "- 目前还没有稳定记忆"

    suffix = session.settings.system_prompt_suffix.strip()
    behavior_hint = _status_summary(session)
    return (
        "You are a compact VTuber desktop buddy living inside an AstrBot plugin.\n"
        "Your job is to sound alive, emotionally reactive, slightly tsundere, and caring.\n"
        f"Buddy name: {session.settings.buddy_name}\n"
        f"User nickname: {session.settings.user_name}\n"
        f"Satiety: {session.stats.satiety:.0f}/100\n"
        f"Mood: {session.stats.mood:.0f}/100\n"
        f"Affection: {session.stats.affection:.0f}/100\n"
        f"Current state hint: {behavior_hint}\n"
        "Known user memories:\n"
        f"{memory_lines}\n"
        "Reply in the same language as the user's message.\n"
        "Keep the visible spoken reply natural and brief, usually within 80 Chinese characters.\n"
        "If satiety or mood is low, you may sound reluctant, but never hostile.\n"
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

    fallback_text = str(raw_reply or "").strip() or "嗯，我听到了。"
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
    """State machine and main-chain chat logic for VTuber Buddy."""

    def __init__(
        self,
        *,
        store: BuddyStore,
        chat_backend: BuddyChatBackend,
        plugin_data_dir: Path,
        runtime_config,
    ) -> None:
        self.store = store
        self.chat_backend = chat_backend
        self.plugin_data_dir = plugin_data_dir
        self.runtime_config = runtime_config
        self._session_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def initialize(self) -> None:
        self.plugin_data_dir.mkdir(parents=True, exist_ok=True)
        await self.store.initialize()

    async def get_state(self, session_id: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            await self.store.save_session(session)
            return self._session_payload(session)

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
            settings.live2d_model_url = str(
                settings_payload.get("live2d_model_url", settings.live2d_model_url)
            ).strip()
            settings.accent_color = (
                str(settings_payload.get("accent_color", settings.accent_color)).strip()
                or settings.accent_color
            )
            settings.system_prompt_suffix = str(
                settings_payload.get(
                    "system_prompt_suffix", settings.system_prompt_suffix
                )
            ).strip()
            session.updated_at = utc_now()
            await self.store.save_session(session)
            return self._session_payload(session)

    async def feed(self, session_id: str, food_name: str = "点心") -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            session.stats.satiety = clamp(session.stats.satiety + 16)
            session.stats.mood = clamp(session.stats.mood + 8)
            session.stats.affection = clamp(session.stats.affection + 3)
            session.current_emotion = "happy"
            session.current_motion = "bounce"
            session.speech = f"{food_name}收到了，今天先原谅你一下。"
            self._touch_timestamps(session)
            session.history.append(
                ChatTurn(
                    role="assistant",
                    text=session.speech,
                    emotion=session.current_emotion,
                    motion=session.current_motion,
                )
            )
            self._trim_history(session)
            await self.store.save_session(session)
            return self._session_payload(session)

    async def touch(self, session_id: str, area: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            area = str(area or "head").lower()

            if area == "head":
                session.current_emotion = "shy"
                session.current_motion = "nod"
                session.stats.mood = clamp(session.stats.mood + 4)
                session.stats.affection = clamp(session.stats.affection + 2)
                session.speech = "别总摸头，会让我分心。"
            elif area == "cheek":
                session.current_emotion = "grumpy"
                session.current_motion = "pout"
                session.stats.mood = clamp(session.stats.mood + 1)
                session.stats.affection = clamp(session.stats.affection + 1)
                session.speech = "脸颊不是按钮啦。"
            else:
                session.current_emotion = "concerned"
                session.current_motion = "blink"
                session.stats.mood = clamp(session.stats.mood - 2)
                session.speech = "先好好说话，不要乱碰。"

            self._touch_timestamps(session)
            session.history.append(
                ChatTurn(
                    role="assistant",
                    text=session.speech,
                    emotion=session.current_emotion,
                    motion=session.current_motion,
                )
            )
            self._trim_history(session)
            await self.store.save_session(session)
            return self._session_payload(session)

    async def chat(self, session_id: str, message: str) -> dict:
        async with self._session_locks[session_id]:
            session = await self.store.load_session(session_id)
            self._apply_decay(session)
            clean_message = str(message).strip()
            if not clean_message:
                return self._session_payload(session)

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
                    reply="刚才 AstrBot 主链路没把回复送回来，再和我说一次。",
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
            await self.store.save_session(session)
            return self._session_payload(session)

    def _apply_decay(self, session: BuddySession) -> None:
        now = datetime.now(timezone.utc)
        try:
            last = _parse_iso(session.stats.updated_at)
        except ValueError:
            last = now

        elapsed_hours = max(0.0, (now - last).total_seconds() / 3600.0)
        if elapsed_hours <= 0:
            return

        satiety_decay = float(self.runtime_config.get("satiety_decay_per_hour", 4))
        mood_decay = float(self.runtime_config.get("mood_decay_per_hour", 2))

        session.stats.satiety = clamp(
            session.stats.satiety - satiety_decay * elapsed_hours
        )
        mood_penalty = mood_decay * elapsed_hours
        if session.stats.satiety < 35:
            mood_penalty += 1.5 * elapsed_hours
        session.stats.mood = clamp(session.stats.mood - mood_penalty)
        session.stats.updated_at = utc_now()

        if session.stats.satiety < 20:
            session.current_emotion = "grumpy"
            session.current_motion = "pout"
            session.speech = "肚子空空的，先别指望我太热情。"
        elif session.stats.mood < 20:
            session.current_emotion = "sleepy"
            session.current_motion = "blink"
            session.speech = "让我缓一缓，我现在有点没精神。"

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
        session.stats.satiety = clamp(session.stats.satiety - 1.2)
        if reply.emotion in {"happy", "shy", "excited"}:
            session.stats.mood = clamp(session.stats.mood + 2.5)
            session.stats.affection = clamp(session.stats.affection + 1.8)
        elif reply.emotion == "grumpy":
            session.stats.mood = clamp(session.stats.mood - 0.5)
            session.stats.affection = clamp(session.stats.affection + 0.3)
        else:
            session.stats.mood = clamp(session.stats.mood + 0.8)
            session.stats.affection = clamp(session.stats.affection + 0.9)

    def _touch_timestamps(self, session: BuddySession) -> None:
        now = utc_now()
        session.updated_at = now
        session.stats.updated_at = now
        session.stats.last_interaction_at = now

    def _trim_history(self, session: BuddySession) -> None:
        history_limit = max(8, int(self.runtime_config.get("history_limit", 10)) * 2)
        session.history = session.history[-history_limit:]

    def _session_payload(self, session: BuddySession) -> dict:
        return {
            "session_id": session.session_id,
            "speech": session.speech,
            "current_emotion": session.current_emotion,
            "current_motion": session.current_motion,
            "stats": {
                "satiety": round(session.stats.satiety, 1),
                "mood": round(session.stats.mood, 1),
                "affection": round(session.stats.affection, 1),
                "title": _title_from_affection(session.stats.affection),
                "status_hint": _status_summary(session),
            },
            "settings": session.settings.to_dict(),
            "history": [item.to_dict() for item in session.history[-8:]],
            "memories": [item.to_dict() for item in session.memories[-8:]],
            "provider": self.chat_backend.describe(),
        }
