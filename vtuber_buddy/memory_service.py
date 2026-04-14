from __future__ import annotations

import re
from datetime import UTC, datetime

from .models import BuddyLongTermMemory, BuddySession, utc_now
from .store import BuddyStore

TIME_HINTS = (
    "今天",
    "今晚",
    "明天",
    "后天",
    "周末",
    "下周",
    "下个月",
    "月底",
    "待会",
    "稍后",
)

SCHEDULE_HINTS = (
    "计划",
    "安排",
    "准备",
    "打算",
    "约了",
    "开会",
    "考试",
    "上课",
    "出门",
    "旅行",
    "见面",
)

TODO_HINTS = (
    "待办",
    "要做",
    "得做",
    "记得",
    "提醒",
    "需要",
    "要去",
)

RELATION_HINTS = (
    "朋友",
    "同事",
    "室友",
    "同学",
    "妈妈",
    "爸爸",
    "家人",
    "女朋友",
    "男朋友",
    "对象",
)

STOPWORDS = {
    "用户",
    "主人",
    "我",
    "你",
    "他",
    "她",
    "它",
    "这个",
    "那个",
    "最近",
    "还是",
    "就是",
    "一下",
    "已经",
}


def _parse_iso(value: str) -> datetime:
    if not value:
        return datetime.now(UTC)
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _normalize_text(text: str) -> str:
    return "".join(str(text or "").casefold().split())


def _trim_fact(text: str, *, maximum: int = 32) -> str:
    value = str(text or "").strip()
    value = value.strip("，。！？,.!?；;：:~ ")
    value = re.sub(r"^(还是|也|都|一直|总是|经常|通常|可能|应该|大概)", "", value)
    value = re.sub(r"(吧|呀|啊|呢|啦|嘛)$", "", value)
    return value[:maximum].strip()


def _build_keywords(text: str) -> list[str]:
    normalized = re.sub(r"[^\w\u4e00-\u9fff]+", " ", str(text or "").casefold())
    chunks = re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]+", normalized)
    keywords: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        token = chunk.strip()
        if not token or token in STOPWORDS:
            continue
        if token.isascii():
            if len(token) < 2:
                continue
            if token not in seen:
                seen.add(token)
                keywords.append(token)
            continue

        compact = token.replace(" ", "")
        if len(compact) <= 4:
            if compact not in seen:
                seen.add(compact)
                keywords.append(compact)
            continue

        if compact not in seen:
            seen.add(compact)
            keywords.append(compact)

        for size in (2, 3, 4):
            for index in range(0, len(compact) - size + 1):
                gram = compact[index : index + size]
                if gram in STOPWORDS or gram in seen:
                    continue
                seen.add(gram)
                keywords.append(gram)
                if len(keywords) >= 24:
                    return keywords
    return keywords[:24]


def _canonicalize_statement(text: str) -> str:
    value = _trim_fact(text, maximum=48)
    if not value:
        return ""
    value = re.sub(r"^(你|主人|用户)", "用户", value, count=1)
    if value.startswith("我"):
        value = f"用户{value[1:]}"
    if not value.startswith("用户"):
        value = f"用户{value}"
    return value[:48]


class BuddyMemoryService:
    """Lightweight long-term memory router and retriever for VTuber Buddy."""

    def __init__(self, *, store: BuddyStore, runtime_config) -> None:
        self.store = store
        self.runtime_config = runtime_config

    async def remember(
        self,
        *,
        session: BuddySession,
        user_message: str,
        llm_memory: str = "",
    ) -> list[BuddyLongTermMemory]:
        candidates = self.extract_candidates(
            user_message=user_message,
            llm_memory=llm_memory,
        )
        if not candidates:
            return []

        stored: list[BuddyLongTermMemory] = []
        for candidate in candidates:
            stored.append(
                await self.store.upsert_long_term_memory(session.session_id, candidate)
            )

        limit = max(8, int(self.runtime_config.get("long_term_memory_limit", 40)))
        await self.store.trim_long_term_memories(session.session_id, limit)
        return stored

    async def recall(
        self,
        *,
        session_id: str,
        query: str,
        limit: int | None = None,
    ) -> list[BuddyLongTermMemory]:
        memories = await self.store.list_long_term_memories(session_id)
        if not memories:
            return []

        safe_limit = max(
            1,
            int(limit or self.runtime_config.get("memory_recall_limit", 4)),
        )
        ranked = self._rank_memories(query, memories)
        selected = ranked[:safe_limit]
        recalled_at = utc_now()
        memory_ids = [item.memory_id for item in selected if item.memory_id is not None]
        if memory_ids:
            await self.store.record_memory_recall(
                session_id,
                memory_ids,
                recalled_at=recalled_at,
            )
            for item in selected:
                item.last_recalled_at = recalled_at
                item.recall_count += 1
        return selected

    async def list_recent(
        self,
        *,
        session_id: str,
        limit: int | None = None,
    ) -> list[BuddyLongTermMemory]:
        safe_limit = limit
        if safe_limit is None:
            safe_limit = max(
                4,
                int(self.runtime_config.get("memory_panel_limit", 8)),
            )
        return await self.store.list_long_term_memories(session_id, limit=safe_limit)

    def extract_candidates(
        self,
        *,
        user_message: str,
        llm_memory: str = "",
    ) -> list[BuddyLongTermMemory]:
        candidates: list[BuddyLongTermMemory] = []
        seen: set[tuple[str, str]] = set()

        for raw_text, source in (
            (llm_memory, "llm_memory"),
            (user_message, "user_message"),
        ):
            candidate = self._candidate_from_text(raw_text, source=source)
            if candidate is None:
                continue
            key = (candidate.category, _normalize_text(candidate.content))
            if key in seen:
                continue
            seen.add(key)
            candidates.append(candidate)
        return candidates

    def _candidate_from_text(
        self,
        text: str,
        *,
        source: str,
    ) -> BuddyLongTermMemory | None:
        raw_text = _trim_fact(text, maximum=64)
        if len(raw_text) < 4:
            return None

        fact = self._extract_preference(raw_text, source=source)
        if fact is not None:
            return fact

        fact = self._extract_identity(raw_text, source=source)
        if fact is not None:
            return fact

        fact = self._extract_habit(raw_text, source=source)
        if fact is not None:
            return fact

        if (
            any(keyword in raw_text for keyword in RELATION_HINTS)
            and len(raw_text) <= 48
        ):
            return self._build_memory(
                content=f"用户提到关系：{raw_text}",
                category="relationship",
                source=source,
                salience=0.78,
                confidence=0.68 if source == "user_message" else 0.8,
            )

        if any(keyword in raw_text for keyword in TIME_HINTS) and any(
            keyword in raw_text for keyword in SCHEDULE_HINTS
        ):
            return self._build_memory(
                content=f"用户计划：{raw_text}",
                category="schedule",
                source=source,
                salience=0.9,
                confidence=0.74 if source == "user_message" else 0.84,
            )

        if any(keyword in raw_text for keyword in TODO_HINTS):
            return self._build_memory(
                content=f"用户待办：{raw_text}",
                category="todo",
                source=source,
                salience=0.72,
                confidence=0.66 if source == "user_message" else 0.8,
            )

        if source == "llm_memory":
            canonical = _canonicalize_statement(raw_text)
            if canonical:
                return self._build_memory(
                    content=canonical,
                    category=self._infer_category(canonical),
                    source=source,
                    salience=0.76,
                    confidence=0.82,
                )

        return None

    def _extract_preference(
        self,
        text: str,
        *,
        source: str,
    ) -> BuddyLongTermMemory | None:
        positive = re.search(
            r"(?:我|你|用户|主人)(?:还是|也|都|一直|最|真)?喜欢(?P<fact>[^，。！？\n]{1,24})",
            text,
        )
        if positive:
            fact = _trim_fact(positive.group("fact"), maximum=24)
            if fact:
                return self._build_memory(
                    content=f"用户喜欢{fact}",
                    category="preference",
                    source=source,
                    salience=0.96,
                    confidence=0.88,
                )

        negative = re.search(
            r"(?:我|你|用户|主人)(?:不喜欢|讨厌)(?P<fact>[^，。！？\n]{1,24})",
            text,
        )
        if negative:
            fact = _trim_fact(negative.group("fact"), maximum=24)
            if fact:
                return self._build_memory(
                    content=f"用户不喜欢{fact}",
                    category="preference",
                    source=source,
                    salience=0.96,
                    confidence=0.88,
                )
        return None

    def _extract_identity(
        self,
        text: str,
        *,
        source: str,
    ) -> BuddyLongTermMemory | None:
        patterns = (
            (r"(?:我|你|用户|主人)叫(?P<fact>[^，。！？\n]{1,16})", "用户叫{fact}"),
            (r"(?:我|你|用户|主人)是(?P<fact>[^，。！？\n]{1,24})", "用户是{fact}"),
            (r"(?:我|你|用户|主人)住在(?P<fact>[^，。！？\n]{1,24})", "用户住在{fact}"),
            (
                r"(?:我|你|用户|主人)在(?P<fact>[^，。！？\n]{1,24})(?:上班|工作)",
                "用户在{fact}工作",
            ),
            (
                r"(?:我|你|用户|主人)在(?P<fact>[^，。！？\n]{1,24})(?:上学|读书)",
                "用户在{fact}上学",
            ),
            (
                r"(?:我|你|用户|主人)的生日是(?P<fact>[^，。！？\n]{1,24})",
                "用户生日是{fact}",
            ),
        )
        for pattern, template in patterns:
            matched = re.search(pattern, text)
            if not matched:
                continue
            fact = _trim_fact(matched.group("fact"), maximum=24)
            if not fact:
                continue
            return self._build_memory(
                content=template.format(fact=fact),
                category="identity",
                source=source,
                salience=0.9,
                confidence=0.82,
            )
        return None

    def _extract_habit(
        self,
        text: str,
        *,
        source: str,
    ) -> BuddyLongTermMemory | None:
        matched = re.search(
            r"(?:我|你|用户|主人)(?P<prefix>经常|通常|总是|每天|每周|习惯)(?P<fact>[^，。！？\n]{2,30})",
            text,
        )
        if not matched:
            return None
        prefix = _trim_fact(matched.group("prefix"), maximum=8)
        fact = _trim_fact(matched.group("fact"), maximum=30)
        if not prefix or not fact:
            return None
        return self._build_memory(
            content=f"用户{prefix}{fact}",
            category="habit",
            source=source,
            salience=0.86,
            confidence=0.78,
        )

    def _build_memory(
        self,
        *,
        content: str,
        category: str,
        source: str,
        salience: float,
        confidence: float,
    ) -> BuddyLongTermMemory:
        text = _trim_fact(content, maximum=48)
        category_name = category.strip() or "recent_update"
        return BuddyLongTermMemory(
            content=text,
            category=category_name,
            summary=text,
            source=source,
            weight=1,
            salience=salience,
            confidence=confidence,
            keywords=_build_keywords(text),
            created_at=utc_now(),
            updated_at=utc_now(),
        )

    def _infer_category(self, content: str) -> str:
        if "喜欢" in content or "不喜欢" in content or "讨厌" in content:
            return "preference"
        if (
            "每天" in content
            or "每周" in content
            or "经常" in content
            or "习惯" in content
        ):
            return "habit"
        if (
            "计划" in content
            or "明天" in content
            or "今晚" in content
            or "下周" in content
        ):
            return "schedule"
        if "叫" in content or "住在" in content or "生日" in content or "是" in content:
            return "identity"
        return "recent_update"

    def _rank_memories(
        self,
        query: str,
        memories: list[BuddyLongTermMemory],
    ) -> list[BuddyLongTermMemory]:
        query_text = _normalize_text(query)
        query_keywords = set(_build_keywords(query))
        scored: list[tuple[float, float, BuddyLongTermMemory]] = []

        for memory in memories:
            candidate_text = _normalize_text(memory.summary or memory.content)
            memory_keywords = set(memory.keywords or _build_keywords(memory.content))
            overlap = len(query_keywords & memory_keywords)
            contains_query = 0.0
            if query_text and (
                query_text in candidate_text
                or any(
                    token in candidate_text
                    for token in query_keywords
                    if len(token) >= 2
                )
            ):
                contains_query = 1.4

            question_bonus = 0.0
            if "喜欢" in query and memory.category == "preference":
                question_bonus += 0.45
            if any(keyword in query for keyword in TIME_HINTS) and memory.category in {
                "schedule",
                "todo",
            }:
                question_bonus += 0.5
            if "工作" in query and memory.category == "identity":
                question_bonus += 0.28

            signal_score = overlap * 1.6 + contains_query + question_bonus
            updated_hours = max(
                0.0,
                (datetime.now(UTC) - _parse_iso(memory.updated_at)).total_seconds()
                / 3600.0,
            )
            recency_score = max(0.0, 1.0 - min(updated_hours, 240.0) / 240.0) * 0.5
            total_score = (
                signal_score
                + memory.salience * 1.2
                + min(memory.weight, 8) * 0.16
                + min(memory.recall_count, 8) * 0.08
                + recency_score
                + memory.confidence * 0.4
            )

            if signal_score > 0:
                scored.append((total_score, signal_score, memory))

        if not scored:
            return sorted(
                memories,
                key=lambda item: (
                    item.salience,
                    item.weight,
                    item.updated_at,
                    item.confidence,
                ),
                reverse=True,
            )

        scored.sort(
            key=lambda item: (
                item[1],
                item[0],
                item[2].updated_at,
            ),
            reverse=True,
        )
        return [item[2] for item in scored]
