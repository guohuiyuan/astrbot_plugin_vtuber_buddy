from __future__ import annotations

import asyncio
import json
from pathlib import Path

from .models import BuddySession


class BuddyStore:
    """Persist VTuber Buddy sessions as JSON."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = asyncio.Lock()

    async def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            await self._write_payload({"schema_version": 1, "sessions": {}})

    async def load_session(self, session_id: str) -> BuddySession:
        payload = await self._read_payload()
        session_data = payload.get("sessions", {}).get(session_id)
        return BuddySession.from_dict(session_id, session_data)

    async def save_session(self, session: BuddySession) -> None:
        async with self._lock:
            payload = await self._read_payload(lock_held=True)
            payload.setdefault("sessions", {})[session.session_id] = session.to_dict()
            await self._write_payload(payload, lock_held=True)

    async def _read_payload(self, *, lock_held: bool = False) -> dict:
        if not lock_held:
            async with self._lock:
                return await self._read_payload(lock_held=True)

        if not self.path.exists():
            return {"schema_version": 1, "sessions": {}}

        text = self.path.read_text(encoding="utf-8").strip()
        if not text:
            return {"schema_version": 1, "sessions": {}}

        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            payload = {"schema_version": 1, "sessions": {}}

        if not isinstance(payload, dict):
            payload = {"schema_version": 1, "sessions": {}}

        payload.setdefault("schema_version", 1)
        payload.setdefault("sessions", {})
        return payload

    async def _write_payload(self, payload: dict, *, lock_held: bool = False) -> None:
        if not lock_held:
            async with self._lock:
                await self._write_payload(payload, lock_held=True)
                return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(".tmp")
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp_path.replace(self.path)
