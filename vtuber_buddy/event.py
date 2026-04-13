from __future__ import annotations

from collections.abc import AsyncGenerator

from astrbot.api.event import MessageChain
from astrbot.core.platform.astr_message_event import AstrMessageEvent
from astrbot.core.platform.sources.webchat.webchat_event import WebChatMessageEvent

from .queue_mgr import BuddyQueueManager


def message_chain_to_text(message: MessageChain | None) -> str:
    if not message:
        return ""
    return message.get_plain_text(with_other_comps_mark=True).strip()


class BuddyPlatformEvent(WebChatMessageEvent):
    """Message event routed through AstrBot main pipeline for VTuber Buddy."""

    def __init__(
        self,
        message_str,
        message_obj,
        platform_meta,
        session_id: str,
        *,
        queue_mgr: BuddyQueueManager,
        request_id: str,
    ) -> None:
        AstrMessageEvent.__init__(
            self, message_str, message_obj, platform_meta, session_id
        )
        self.queue_mgr = queue_mgr
        self.request_id = request_id

    async def _enqueue(self, payload: dict) -> None:
        back_queue = self.queue_mgr.get_or_create_back_queue(
            self.request_id,
            self.session_id,
        )
        await back_queue.put(payload)

    def _reply_payload(self) -> dict | None:
        payload = self.get_extra("buddy_structured_reply")
        return payload if isinstance(payload, dict) else None

    async def send(self, message: MessageChain | None) -> None:
        if message is None:
            await self._enqueue(
                {
                    "type": "end",
                    "request_id": self.request_id,
                    "session_id": self.session_id,
                    "payload": self._reply_payload(),
                }
            )
            await AstrMessageEvent.send(self, MessageChain([]))
            return

        await self._enqueue(
            {
                "type": "message",
                "request_id": self.request_id,
                "session_id": self.session_id,
                "text": message_chain_to_text(message),
                "payload": self._reply_payload(),
                "streaming": False,
            }
        )
        await AstrMessageEvent.send(self, MessageChain([]))

    async def send_streaming(
        self,
        generator: AsyncGenerator[MessageChain, None],
        use_fallback: bool = False,
    ) -> None:
        final_text = ""
        async for chain in generator:
            chunk_text = message_chain_to_text(chain)
            if chunk_text:
                final_text += chunk_text
            await self._enqueue(
                {
                    "type": "message",
                    "request_id": self.request_id,
                    "session_id": self.session_id,
                    "text": chunk_text,
                    "payload": self._reply_payload(),
                    "streaming": True,
                }
            )

        await self._enqueue(
            {
                "type": "complete",
                "request_id": self.request_id,
                "session_id": self.session_id,
                "text": final_text,
                "payload": self._reply_payload(),
                "streaming": True,
            }
        )
        await AstrMessageEvent.send_streaming(self, generator, use_fallback)
