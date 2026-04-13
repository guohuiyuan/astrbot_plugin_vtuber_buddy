from __future__ import annotations

import asyncio
import uuid


class BuddyQueueManager:
    """Track active browser chat requests and their response queues."""

    def __init__(self, back_queue_maxsize: int = 64) -> None:
        self.back_queues: dict[str, asyncio.Queue] = {}
        self._session_requests: dict[str, list[str]] = {}
        self.back_queue_maxsize = back_queue_maxsize

    def create_request(self, session_id: str) -> tuple[str, asyncio.Queue]:
        request_id = uuid.uuid4().hex
        return request_id, self.get_or_create_back_queue(request_id, session_id)

    def get_or_create_back_queue(
        self,
        request_id: str,
        session_id: str | None = None,
    ) -> asyncio.Queue:
        if request_id not in self.back_queues:
            self.back_queues[request_id] = asyncio.Queue(
                maxsize=self.back_queue_maxsize
            )

        if session_id:
            requests = self._session_requests.setdefault(session_id, [])
            if request_id not in requests:
                requests.append(request_id)

        return self.back_queues[request_id]

    def get_latest_request_id(self, session_id: str) -> str | None:
        requests = self._session_requests.get(session_id, [])
        return requests[-1] if requests else None

    def remove_back_queue(self, request_id: str) -> None:
        self.back_queues.pop(request_id, None)
        empty_sessions: list[str] = []
        for session_id, requests in self._session_requests.items():
            if request_id in requests:
                requests.remove(request_id)
            if not requests:
                empty_sessions.append(session_id)
        for session_id in empty_sessions:
            self._session_requests.pop(session_id, None)
