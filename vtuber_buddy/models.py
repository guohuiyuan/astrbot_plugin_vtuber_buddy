from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .live2d_constants import DEFAULT_LIVE2D_SELECTION_KEY

MAX_LEVEL = 30
NEED_CAP_MAX = 6000.0
MOOD_MAX = 1000.0
ENERGY_MAX = 1000.0
HEALTH_MAX = 1000.0
AFFECTION_MAX = 1000.0
ILLNESS_MAX = 100.0


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


def need_capacity(level: int) -> float:
    safe_level = int(clamp(level, 1, MAX_LEVEL))
    return min(NEED_CAP_MAX, 3000.0 + safe_level * 100.0)


def experience_for_next_level(level: int) -> int:
    safe_level = int(clamp(level, 1, MAX_LEVEL))
    return 240 + (safe_level - 1) * 90


def to_percent(value: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    return clamp(value / maximum * 100.0)


@dataclass(slots=True)
class ChatTurn:
    role: str
    text: str
    emotion: str = "neutral"
    motion: str = "idle"
    timestamp: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> ChatTurn:
        data = data or {}
        return cls(
            role=str(data.get("role", "assistant")),
            text=str(data.get("text", "")),
            emotion=str(data.get("emotion", "neutral")),
            motion=str(data.get("motion", "idle")),
            timestamp=str(data.get("timestamp", utc_now())),
        )


@dataclass(slots=True)
class MemoryFact:
    content: str
    source: str = "chat"
    created_at: str = field(default_factory=utc_now)
    weight: int = 1

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> MemoryFact:
        data = data or {}
        return cls(
            content=str(data.get("content", "")).strip(),
            source=str(data.get("source", "chat")),
            created_at=str(data.get("created_at", utc_now())),
            weight=max(1, int(data.get("weight", 1))),
        )


@dataclass(slots=True)
class BuddyLongTermMemory:
    content: str
    category: str = "recent_update"
    summary: str = ""
    source: str = "chat"
    weight: int = 1
    salience: float = 0.5
    confidence: float = 0.5
    keywords: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)
    last_recalled_at: str = ""
    recall_count: int = 0
    memory_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BuddyLongTermMemory:
        data = data or {}
        keywords = data.get("keywords", [])
        if not isinstance(keywords, list):
            keywords = []
        return cls(
            content=str(data.get("content", "")).strip(),
            category=str(data.get("category", "recent_update")).strip()
            or "recent_update",
            summary=str(data.get("summary", "")).strip(),
            source=str(data.get("source", "chat")).strip() or "chat",
            weight=max(1, int(data.get("weight", 1))),
            salience=clamp(float(data.get("salience", 0.5)), 0.0, 2.0),
            confidence=clamp(float(data.get("confidence", 0.5)), 0.0, 1.0),
            keywords=[str(item).strip() for item in keywords if str(item).strip()],
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
            last_recalled_at=str(data.get("last_recalled_at", "")).strip(),
            recall_count=max(0, int(data.get("recall_count", 0))),
            memory_id=(
                None
                if data.get("memory_id") in {None, ""}
                else int(data.get("memory_id"))
            ),
        )


@dataclass(slots=True)
class BuddySettings:
    buddy_name: str = "Buddy"
    user_name: str = "主人"
    live2d_selection_key: str = DEFAULT_LIVE2D_SELECTION_KEY
    live2d_model_url: str = ""
    live2d_mouse_follow_enabled: bool = True
    accent_color: str = "#ff8a65"
    system_prompt_suffix: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BuddySettings:
        data = data or {}
        return cls(
            buddy_name=str(data.get("buddy_name", "Buddy")).strip() or "Buddy",
            user_name=str(data.get("user_name", "主人")).strip() or "主人",
            live2d_selection_key=(
                str(
                    data.get("live2d_selection_key", DEFAULT_LIVE2D_SELECTION_KEY)
                ).strip()
                or DEFAULT_LIVE2D_SELECTION_KEY
            ),
            live2d_model_url=str(data.get("live2d_model_url", "")).strip(),
            live2d_mouse_follow_enabled=bool(
                data.get("live2d_mouse_follow_enabled", True)
            ),
            accent_color=str(data.get("accent_color", "#ff8a65")).strip() or "#ff8a65",
            system_prompt_suffix=str(data.get("system_prompt_suffix", "")).strip(),
        )


@dataclass(slots=True)
class BuddyStats:
    level: int = 1
    experience: int = 0
    coins: int = 120
    satiety: float = 2200.0
    cleanliness: float = 2150.0
    mood: float = 720.0
    energy: float = 780.0
    health: float = 920.0
    affection: float = 180.0
    illness: float = 0.0
    updated_at: str = field(default_factory=utc_now)
    last_interaction_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BuddyStats:
        data = data or {}
        level = int(clamp(float(data.get("level", 1)), 1, MAX_LEVEL))
        capacity = need_capacity(level)
        return cls(
            level=level,
            experience=max(0, int(data.get("experience", 0))),
            coins=max(0, int(data.get("coins", 120))),
            satiety=clamp(float(data.get("satiety", 2200.0)), 0.0, capacity),
            cleanliness=clamp(float(data.get("cleanliness", 2150.0)), 0.0, capacity),
            mood=clamp(float(data.get("mood", 720.0)), 0.0, MOOD_MAX),
            energy=clamp(float(data.get("energy", 780.0)), 0.0, ENERGY_MAX),
            health=clamp(float(data.get("health", 920.0)), 0.0, HEALTH_MAX),
            affection=clamp(float(data.get("affection", 180.0)), 0.0, AFFECTION_MAX),
            illness=clamp(float(data.get("illness", 0.0)), 0.0, ILLNESS_MAX),
            updated_at=str(data.get("updated_at", utc_now())),
            last_interaction_at=str(data.get("last_interaction_at", utc_now())),
        )


@dataclass(slots=True)
class BuddyWorkState:
    status: str = "idle"
    label: str = ""
    started_at: str = ""
    finish_at: str = ""
    duration_minutes: int = 0
    reward_coins: int = 0
    reward_experience: int = 0
    satiety_cost: float = 0.0
    cleanliness_cost: float = 0.0
    energy_cost: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BuddyWorkState:
        data = data or {}
        return cls(
            status=str(data.get("status", "idle")).strip() or "idle",
            label=str(data.get("label", "")).strip(),
            started_at=str(data.get("started_at", "")).strip(),
            finish_at=str(data.get("finish_at", "")).strip(),
            duration_minutes=max(0, int(data.get("duration_minutes", 0))),
            reward_coins=max(0, int(data.get("reward_coins", 0))),
            reward_experience=max(0, int(data.get("reward_experience", 0))),
            satiety_cost=max(0.0, float(data.get("satiety_cost", 0.0))),
            cleanliness_cost=max(0.0, float(data.get("cleanliness_cost", 0.0))),
            energy_cost=max(0.0, float(data.get("energy_cost", 0.0))),
        )


@dataclass(slots=True)
class BuddyReply:
    reply: str
    emotion: str = "neutral"
    motion: str = "idle"
    memory: str = ""


@dataclass(slots=True)
class BuddySession:
    session_id: str
    settings: BuddySettings = field(default_factory=BuddySettings)
    stats: BuddyStats = field(default_factory=BuddyStats)
    work: BuddyWorkState = field(default_factory=BuddyWorkState)
    current_emotion: str = "neutral"
    current_motion: str = "idle"
    speech: str = "我在这里，今天也会好好陪着你。"
    history: list[ChatTurn] = field(default_factory=list)
    memories: list[MemoryFact] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "settings": self.settings.to_dict(),
            "stats": self.stats.to_dict(),
            "work": self.work.to_dict(),
            "current_emotion": self.current_emotion,
            "current_motion": self.current_motion,
            "speech": self.speech,
            "history": [item.to_dict() for item in self.history],
            "memories": [item.to_dict() for item in self.memories],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, session_id: str, data: dict | None) -> BuddySession:
        data = data or {}
        return cls(
            session_id=session_id,
            settings=BuddySettings.from_dict(data.get("settings")),
            stats=BuddyStats.from_dict(data.get("stats")),
            work=BuddyWorkState.from_dict(data.get("work")),
            current_emotion=str(data.get("current_emotion", "neutral")),
            current_motion=str(data.get("current_motion", "idle")),
            speech=str(data.get("speech", "我在这里，今天也会好好陪着你。")),
            history=[
                ChatTurn.from_dict(item) for item in list(data.get("history", []))
            ],
            memories=[
                MemoryFact.from_dict(item) for item in list(data.get("memories", []))
            ],
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
        )
