from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .models import BuddyLongTermMemory, BuddySession

SCHEMA_VERSION = 3


class BuddyStore:
    """Persist VTuber Buddy sessions in SQLite."""

    def __init__(self, path: Path, *, legacy_json_path: Path | None = None) -> None:
        self.path = path
        self.legacy_json_path = legacy_json_path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._lock:
            await asyncio.to_thread(self._initialize_sync)

    async def load_session(self, session_id: str) -> BuddySession:
        async with self._lock:
            return await asyncio.to_thread(self._load_session_sync, session_id)

    async def save_session(self, session: BuddySession) -> None:
        async with self._lock:
            await asyncio.to_thread(self._save_session_sync, session)

    async def list_long_term_memories(
        self,
        session_id: str,
        *,
        limit: int | None = None,
    ) -> list[BuddyLongTermMemory]:
        async with self._lock:
            return await asyncio.to_thread(
                self._list_long_term_memories_sync,
                session_id,
                limit,
            )

    async def upsert_long_term_memory(
        self,
        session_id: str,
        memory: BuddyLongTermMemory,
    ) -> BuddyLongTermMemory:
        async with self._lock:
            return await asyncio.to_thread(
                self._upsert_long_term_memory_sync,
                session_id,
                memory,
            )

    async def trim_long_term_memories(self, session_id: str, limit: int) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._trim_long_term_memories_sync,
                session_id,
                limit,
            )

    async def record_memory_recall(
        self,
        session_id: str,
        memory_ids: list[int],
        *,
        recalled_at: str,
    ) -> None:
        async with self._lock:
            await asyncio.to_thread(
                self._record_memory_recall_sync,
                session_id,
                memory_ids,
                recalled_at,
            )

    def _initialize_sync(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and not self._is_sqlite_file(self.path):
            payload = self._read_legacy_payload(self.path)
            if payload is not None:
                self.path.rename(self.path.with_suffix(f"{self.path.suffix}.legacy"))
                self._write_database(payload)
                return

        with self._connect() as conn:
            self._create_schema(conn)
            self._migrate_legacy_json_if_needed(conn)

    def _load_session_sync(self, session_id: str) -> BuddySession:
        if not self.path.exists():
            return BuddySession(session_id=session_id)

        with self._connect() as conn:
            self._create_schema(conn)
            row = conn.execute(
                """
                SELECT settings_json, stats_json, work_json, current_emotion,
                       current_motion, speech, created_at, updated_at
                FROM sessions
                WHERE session_id = ?
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return BuddySession(session_id=session_id)

            history = conn.execute(
                """
                SELECT role, text, emotion, motion, timestamp
                FROM history
                WHERE session_id = ?
                ORDER BY idx ASC
                """,
                (session_id,),
            ).fetchall()
            memories = conn.execute(
                """
                SELECT content, source, created_at, weight
                FROM memories
                WHERE session_id = ?
                ORDER BY idx ASC
                """,
                (session_id,),
            ).fetchall()

        return BuddySession.from_dict(
            session_id,
            {
                "settings": self._loads(row["settings_json"]),
                "stats": self._loads(row["stats_json"]),
                "work": self._loads(row["work_json"]),
                "current_emotion": row["current_emotion"],
                "current_motion": row["current_motion"],
                "speech": row["speech"],
                "history": [
                    {
                        "role": item["role"],
                        "text": item["text"],
                        "emotion": item["emotion"],
                        "motion": item["motion"],
                        "timestamp": item["timestamp"],
                    }
                    for item in history
                ],
                "memories": [
                    {
                        "content": item["content"],
                        "source": item["source"],
                        "created_at": item["created_at"],
                        "weight": item["weight"],
                    }
                    for item in memories
                ],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
            },
        )

    def _save_session_sync(self, session: BuddySession) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            self._create_schema(conn)
            with conn:
                conn.execute(
                    """
                    INSERT INTO sessions (
                        session_id,
                        settings_json,
                        stats_json,
                        work_json,
                        current_emotion,
                        current_motion,
                        speech,
                        created_at,
                        updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id) DO UPDATE SET
                        settings_json = excluded.settings_json,
                        stats_json = excluded.stats_json,
                        work_json = excluded.work_json,
                        current_emotion = excluded.current_emotion,
                        current_motion = excluded.current_motion,
                        speech = excluded.speech,
                        created_at = excluded.created_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        session.session_id,
                        self._dumps(session.settings.to_dict()),
                        self._dumps(session.stats.to_dict()),
                        self._dumps(session.work.to_dict()),
                        session.current_emotion,
                        session.current_motion,
                        session.speech,
                        session.created_at,
                        session.updated_at,
                    ),
                )
                conn.execute(
                    "DELETE FROM history WHERE session_id = ?",
                    (session.session_id,),
                )
                conn.execute(
                    "DELETE FROM memories WHERE session_id = ?",
                    (session.session_id,),
                )
                conn.executemany(
                    """
                    INSERT INTO history (
                        session_id, idx, role, text, emotion, motion, timestamp
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session.session_id,
                            index,
                            item.role,
                            item.text,
                            item.emotion,
                            item.motion,
                            item.timestamp,
                        )
                        for index, item in enumerate(session.history)
                    ],
                )
                conn.executemany(
                    """
                    INSERT INTO memories (
                        session_id, idx, content, source, created_at, weight
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            session.session_id,
                            index,
                            item.content,
                            item.source,
                            item.created_at,
                            item.weight,
                        )
                        for index, item in enumerate(session.memories)
                    ],
                )

    def _list_long_term_memories_sync(
        self,
        session_id: str,
        limit: int | None = None,
    ) -> list[BuddyLongTermMemory]:
        if not self.path.exists():
            return []

        with self._connect() as conn:
            self._create_schema(conn)
            if limit is None:
                rows = conn.execute(
                    """
                    SELECT memory_id, category, content, summary, source, weight,
                           salience, confidence, keywords_json, created_at,
                           updated_at, last_recalled_at, recall_count
                    FROM long_term_memories
                    WHERE session_id = ?
                    ORDER BY updated_at DESC, salience DESC, weight DESC, memory_id DESC
                    """,
                    (session_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT memory_id, category, content, summary, source, weight,
                           salience, confidence, keywords_json, created_at,
                           updated_at, last_recalled_at, recall_count
                    FROM long_term_memories
                    WHERE session_id = ?
                    ORDER BY updated_at DESC, salience DESC, weight DESC, memory_id DESC
                    LIMIT ?
                    """,
                    (session_id, max(1, int(limit))),
                ).fetchall()
        return [self._long_term_memory_from_row(row) for row in rows]

    def _upsert_long_term_memory_sync(
        self,
        session_id: str,
        memory: BuddyLongTermMemory,
    ) -> BuddyLongTermMemory:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        normalized_content = self._normalize_memory_key(memory.content)
        if not normalized_content:
            return memory

        prepared = BuddyLongTermMemory.from_dict(memory.to_dict())
        prepared.content = prepared.content.strip()
        prepared.summary = prepared.summary.strip() or prepared.content
        prepared.category = prepared.category.strip() or "recent_update"
        prepared.source = prepared.source.strip() or "chat"
        prepared.keywords = self._normalize_keywords(prepared.keywords)
        prepared.weight = max(1, int(prepared.weight))
        prepared.salience = max(0.0, min(2.0, float(prepared.salience)))
        prepared.confidence = max(0.0, min(1.0, float(prepared.confidence)))
        prepared.created_at = prepared.created_at or prepared.updated_at
        prepared.updated_at = prepared.updated_at or prepared.created_at

        with self._connect() as conn:
            self._create_schema(conn)
            with conn:
                existing_row = conn.execute(
                    """
                    SELECT memory_id, category, content, summary, source, weight,
                           salience, confidence, keywords_json, created_at,
                           updated_at, last_recalled_at, recall_count
                    FROM long_term_memories
                    WHERE session_id = ? AND category = ? AND normalized_content = ?
                    """,
                    (
                        session_id,
                        prepared.category,
                        normalized_content,
                    ),
                ).fetchone()

                if existing_row is None:
                    cursor = conn.execute(
                        """
                        INSERT INTO long_term_memories (
                            session_id,
                            category,
                            content,
                            normalized_content,
                            summary,
                            source,
                            weight,
                            salience,
                            confidence,
                            keywords_json,
                            created_at,
                            updated_at,
                            last_recalled_at,
                            recall_count
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            session_id,
                            prepared.category,
                            prepared.content,
                            normalized_content,
                            prepared.summary,
                            prepared.source,
                            prepared.weight,
                            prepared.salience,
                            prepared.confidence,
                            self._dumps_list(prepared.keywords),
                            prepared.created_at,
                            prepared.updated_at,
                            prepared.last_recalled_at,
                            prepared.recall_count,
                        ),
                    )
                    prepared.memory_id = int(cursor.lastrowid)
                    return prepared

                existing = self._long_term_memory_from_row(existing_row)
                merged_keywords = self._normalize_keywords(
                    existing.keywords + prepared.keywords
                )
                merged = BuddyLongTermMemory(
                    memory_id=existing.memory_id,
                    content=prepared.content or existing.content,
                    category=existing.category,
                    summary=prepared.summary or existing.summary or prepared.content,
                    source=prepared.source or existing.source,
                    weight=max(1, existing.weight + prepared.weight),
                    salience=max(existing.salience, prepared.salience),
                    confidence=max(existing.confidence, prepared.confidence),
                    keywords=merged_keywords,
                    created_at=existing.created_at,
                    updated_at=prepared.updated_at,
                    last_recalled_at=existing.last_recalled_at,
                    recall_count=existing.recall_count,
                )
                conn.execute(
                    """
                    UPDATE long_term_memories
                    SET content = ?,
                        summary = ?,
                        source = ?,
                        weight = ?,
                        salience = ?,
                        confidence = ?,
                        keywords_json = ?,
                        updated_at = ?
                    WHERE memory_id = ?
                    """,
                    (
                        merged.content,
                        merged.summary,
                        merged.source,
                        merged.weight,
                        merged.salience,
                        merged.confidence,
                        self._dumps_list(merged.keywords),
                        merged.updated_at,
                        merged.memory_id,
                    ),
                )
                return merged

    def _trim_long_term_memories_sync(self, session_id: str, limit: int) -> None:
        safe_limit = max(1, int(limit))
        if not self.path.exists():
            return

        with self._connect() as conn:
            self._create_schema(conn)
            with conn:
                conn.execute(
                    """
                    DELETE FROM long_term_memories
                    WHERE memory_id IN (
                        SELECT memory_id
                        FROM long_term_memories
                        WHERE session_id = ?
                        ORDER BY salience DESC, weight DESC, updated_at DESC, memory_id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (session_id, safe_limit),
                )

    def _record_memory_recall_sync(
        self,
        session_id: str,
        memory_ids: list[int],
        recalled_at: str,
    ) -> None:
        ids: list[int] = []
        for item in memory_ids:
            if item is None:
                continue
            value = int(item)
            if value > 0:
                ids.append(value)
        if not ids or not self.path.exists():
            return

        placeholders = ",".join("?" for _ in ids)
        with self._connect() as conn:
            self._create_schema(conn)
            with conn:
                conn.execute(
                    f"""
                    UPDATE long_term_memories
                    SET last_recalled_at = ?,
                        recall_count = recall_count + 1
                    WHERE session_id = ?
                      AND memory_id IN ({placeholders})
                    """,
                    (recalled_at, session_id, *ids),
                )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def _create_schema(self, conn: sqlite3.Connection) -> None:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    settings_json TEXT NOT NULL,
                    stats_json TEXT NOT NULL,
                    work_json TEXT NOT NULL,
                    current_emotion TEXT NOT NULL,
                    current_motion TEXT NOT NULL,
                    speech TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS history (
                    session_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    emotion TEXT NOT NULL,
                    motion TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    PRIMARY KEY (session_id, idx),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS memories (
                    session_id TEXT NOT NULL,
                    idx INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    weight INTEGER NOT NULL,
                    PRIMARY KEY (session_id, idx),
                    FOREIGN KEY (session_id) REFERENCES sessions(session_id)
                        ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS long_term_memories (
                    memory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    content TEXT NOT NULL,
                    normalized_content TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    source TEXT NOT NULL,
                    weight INTEGER NOT NULL,
                    salience REAL NOT NULL,
                    confidence REAL NOT NULL,
                    keywords_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_recalled_at TEXT NOT NULL,
                    recall_count INTEGER NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_long_term_memories_unique
                ON long_term_memories (session_id, category, normalized_content)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_long_term_memories_lookup
                ON long_term_memories (session_id, updated_at DESC, salience DESC, weight DESC)
                """
            )
            conn.execute(
                """
                INSERT INTO meta(key, value) VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(SCHEMA_VERSION),),
            )

    def _migrate_legacy_json_if_needed(self, conn: sqlite3.Connection) -> None:
        legacy_path = self.legacy_json_path
        if legacy_path is None or not legacy_path.exists():
            return
        if self._is_sqlite_file(legacy_path):
            return
        existing = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        if existing:
            return

        payload = self._read_legacy_payload(legacy_path)
        if payload is None:
            return

        sessions = payload.get("sessions", {})
        with conn:
            for session_id, session_payload in sessions.items():
                session = BuddySession.from_dict(str(session_id), session_payload)
                self._save_session_with_connection(conn, session)

    def _save_session_with_connection(
        self, conn: sqlite3.Connection, session: BuddySession
    ) -> None:
        conn.execute(
            """
            INSERT INTO sessions (
                session_id,
                settings_json,
                stats_json,
                work_json,
                current_emotion,
                current_motion,
                speech,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                settings_json = excluded.settings_json,
                stats_json = excluded.stats_json,
                work_json = excluded.work_json,
                current_emotion = excluded.current_emotion,
                current_motion = excluded.current_motion,
                speech = excluded.speech,
                created_at = excluded.created_at,
                updated_at = excluded.updated_at
            """,
            (
                session.session_id,
                self._dumps(session.settings.to_dict()),
                self._dumps(session.stats.to_dict()),
                self._dumps(session.work.to_dict()),
                session.current_emotion,
                session.current_motion,
                session.speech,
                session.created_at,
                session.updated_at,
            ),
        )
        conn.executemany(
            """
            INSERT INTO history (
                session_id, idx, role, text, emotion, motion, timestamp
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session.session_id,
                    index,
                    item.role,
                    item.text,
                    item.emotion,
                    item.motion,
                    item.timestamp,
                )
                for index, item in enumerate(session.history)
            ],
        )
        conn.executemany(
            """
            INSERT INTO memories (
                session_id, idx, content, source, created_at, weight
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    session.session_id,
                    index,
                    item.content,
                    item.source,
                    item.created_at,
                    item.weight,
                )
                for index, item in enumerate(session.memories)
            ],
        )

    def _write_database(self, payload: dict) -> None:
        with self._connect() as conn:
            self._create_schema(conn)
            sessions = payload.get("sessions", {})
            with conn:
                for session_id, session_payload in sessions.items():
                    session = BuddySession.from_dict(str(session_id), session_payload)
                    self._save_session_with_connection(conn, session)

    @staticmethod
    def _is_sqlite_file(path: Path) -> bool:
        try:
            return path.read_bytes()[:16] == b"SQLite format 3\x00"
        except OSError:
            return False

    @staticmethod
    def _read_legacy_payload(path: Path) -> dict | None:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        payload.setdefault("sessions", {})
        return payload

    @staticmethod
    def _loads(text: str) -> dict:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return {}
        return payload if isinstance(payload, dict) else {}

    @staticmethod
    def _dumps(payload: dict) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _dumps_list(payload: list[str]) -> str:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _loads_list(text: str) -> list[str]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return []
        if not isinstance(payload, list):
            return []
        return [str(item).strip() for item in payload if str(item).strip()]

    @staticmethod
    def _normalize_memory_key(text: str) -> str:
        return "".join(str(text or "").casefold().split())

    @staticmethod
    def _normalize_keywords(values: list[str]) -> list[str]:
        seen: set[str] = set()
        keywords: list[str] = []
        for raw_value in values:
            value = str(raw_value or "").strip()
            if not value or value in seen:
                continue
            seen.add(value)
            keywords.append(value)
        return keywords[:24]

    def _long_term_memory_from_row(self, row: sqlite3.Row) -> BuddyLongTermMemory:
        return BuddyLongTermMemory(
            memory_id=int(row["memory_id"]),
            category=str(row["category"]),
            content=str(row["content"]),
            summary=str(row["summary"]),
            source=str(row["source"]),
            weight=max(1, int(row["weight"])),
            salience=float(row["salience"]),
            confidence=float(row["confidence"]),
            keywords=self._loads_list(str(row["keywords_json"])),
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
            last_recalled_at=str(row["last_recalled_at"]),
            recall_count=max(0, int(row["recall_count"])),
        )
