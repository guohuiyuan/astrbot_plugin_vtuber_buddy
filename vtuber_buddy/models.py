from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from .live2d_constants import DEFAULT_LIVE2D_SELECTION_KEY


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def clamp(value: float, minimum: float = 0.0, maximum: float = 100.0) -> float:
    return max(minimum, min(maximum, value))


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
            weight=int(data.get("weight", 1)),
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
    satiety: float = 72.0
    mood: float = 78.0
    affection: float = 18.0
    updated_at: str = field(default_factory=utc_now)
    last_interaction_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict | None) -> BuddyStats:
        data = data or {}
        return cls(
            satiety=clamp(float(data.get("satiety", 72.0))),
            mood=clamp(float(data.get("mood", 78.0))),
            affection=clamp(float(data.get("affection", 18.0))),
            updated_at=str(data.get("updated_at", utc_now())),
            last_interaction_at=str(data.get("last_interaction_at", utc_now())),
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
    current_emotion: str = "neutral"
    current_motion: str = "idle"
    speech: str = "你好，我已经在这里了。"
    history: list[ChatTurn] = field(default_factory=list)
    memories: list[MemoryFact] = field(default_factory=list)
    created_at: str = field(default_factory=utc_now)
    updated_at: str = field(default_factory=utc_now)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "settings": self.settings.to_dict(),
            "stats": self.stats.to_dict(),
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
            current_emotion=str(data.get("current_emotion", "neutral")),
            current_motion=str(data.get("current_motion", "idle")),
            speech=str(data.get("speech", "你好，我已经在这里了。")),
            history=[
                ChatTurn.from_dict(item) for item in list(data.get("history", []))
            ],
            memories=[
                MemoryFact.from_dict(item) for item in list(data.get("memories", []))
            ],
            created_at=str(data.get("created_at", utc_now())),
            updated_at=str(data.get("updated_at", utc_now())),
        )
