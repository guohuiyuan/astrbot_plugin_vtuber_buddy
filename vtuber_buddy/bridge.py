from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Protocol

from .platform import BuddyPlatformAdapter


@dataclass(slots=True)
class BuddyBackendResult:
    reply_text: str
    structured: dict | None = None


class BuddyChatBackend(Protocol):
    async def request_reply(
        self,
        *,
        session_id: str,
        user_message: str,
        prompt_context: dict,
    ) -> BuddyBackendResult: ...

    def describe(self) -> str: ...


class AstrBotMainChainBackend:
    """Submit browser chat into AstrBot event pipeline and wait for the reply."""

    def __init__(
        self,
        *,
        adapter: BuddyPlatformAdapter,
        configured_provider_id: str = "",
        request_timeout_seconds: float = 60.0,
    ) -> None:
        self.adapter = adapter
        self.configured_provider_id = configured_provider_id.strip()
        self.request_timeout_seconds = request_timeout_seconds

    async def request_reply(
        self,
        *,
        session_id: str,
        user_message: str,
        prompt_context: dict,
    ) -> BuddyBackendResult:
        request_id, queue = self.adapter.create_request(session_id)
        self.adapter.submit_user_message(
            session_id=session_id,
            text=user_message,
            request_id=request_id,
            selected_provider=self.configured_provider_id or None,
            extras={"buddy_prompt_context": prompt_context},
        )

        parts: list[str] = []
        structured: dict | None = None

        try:
            while True:
                payload = await asyncio.wait_for(
                    queue.get(),
                    timeout=self.request_timeout_seconds,
                )
                payload_type = str(payload.get("type", ""))
                if payload_type == "error":
                    raise RuntimeError(
                        str(payload.get("message", "buddy chain failed"))
                    )

                text = str(payload.get("text", "")).strip()
                if text:
                    parts.append(text)

                if isinstance(payload.get("payload"), dict):
                    structured = payload["payload"]

                if payload_type in {"complete", "end"}:
                    break
        finally:
            self.adapter.finish_request(request_id)

        reply_text = "\n".join(part for part in parts if part).strip()
        if not reply_text and structured:
            reply_text = str(structured.get("reply", "")).strip()
        return BuddyBackendResult(reply_text=reply_text, structured=structured)

    def describe(self) -> str:
        if self.configured_provider_id:
            return f"AstrBot Main Chain ({self.configured_provider_id})"
        return "AstrBot Main Chain"
