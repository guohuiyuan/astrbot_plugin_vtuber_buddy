from __future__ import annotations

import asyncio
import json
import sqlite3
from pathlib import Path

from .models import BuddySession

SCHEMA_VERSION = 2


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
