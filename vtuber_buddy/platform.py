from __future__ import annotations

import asyncio
import logging
import traceback
from collections.abc import Coroutine
from typing import Any

from astrbot.api.message_components import Plain
from astrbot.core.message.message_event_result import MessageChain
from astrbot.core.platform import (
    AstrBotMessage,
    MessageMember,
    MessageType,
    Platform,
    PlatformMetadata,
)
from astrbot.core.platform.astr_message_event import MessageSesion
from astrbot.core.platform.register import register_platform_adapter

try:
    from astrbot.api import logger
except ModuleNotFoundError:
    logger = logging.getLogger("vtuber_buddy")

from .event import BuddyPlatformEvent, message_chain_to_text
from .queue_mgr import BuddyQueueManager

BUDDY_PLATFORM_NAME = "vtuber_buddy"


@register_platform_adapter(
    adapter_name=BUDDY_PLATFORM_NAME,
    desc="VTuber Buddy browser platform adapter.",
    default_config_tmpl={
        "type": BUDDY_PLATFORM_NAME,
        "enable": True,
        "id": BUDDY_PLATFORM_NAME,
    },
    adapter_display_name="VTuber Buddy",
    support_streaming_message=False,
)
class BuddyPlatformAdapter(Platform):
    def __init__(
        self,
        platform_config: dict,
        event_queue: asyncio.Queue,
        *,
        queue_mgr: BuddyQueueManager | None = None,
    ) -> None:
        super().__init__(platform_config, event_queue)
        self.config = platform_config
        self.queue_mgr = queue_mgr or BuddyQueueManager()
        self.metadata = PlatformMetadata(
            name=BUDDY_PLATFORM_NAME,
            description="VTuber Buddy browser platform adapter.",
            id=str(platform_config.get("id", BUDDY_PLATFORM_NAME)),
            support_streaming_message=False,
            support_proactive_message=False,
        )
        self._shutdown_event = asyncio.Event()

    def meta(self) -> PlatformMetadata:
        return self.metadata

    def run(self) -> Coroutine[Any, Any, None]:
        self.status = self.status.__class__.RUNNING
        return self._shutdown_event.wait()

    async def terminate(self) -> None:
        self._shutdown_event.set()
        self.status = self.status.__class__.STOPPED

    def create_request(self, session_id: str) -> tuple[str, asyncio.Queue]:
        return self.queue_mgr.create_request(session_id)

    def finish_request(self, request_id: str) -> None:
        self.queue_mgr.remove_back_queue(request_id)

    def submit_user_message(
        self,
        *,
        session_id: str,
        text: str,
        request_id: str,
        sender_id: str = "browser_user",
        sender_name: str = "浏览器用户",
        selected_provider: str | None = None,
        selected_model: str | None = None,
        extras: dict | None = None,
    ) -> None:
        clean_text = str(text).strip()
        if not clean_text:
            raise ValueError("message cannot be empty")

        abm = AstrBotMessage()
        abm.self_id = self.metadata.id
        abm.sender = MessageMember(str(sender_id), str(sender_name))
        abm.type = MessageType.FRIEND_MESSAGE
        abm.session_id = session_id
        abm.message_id = request_id
        abm.message = [Plain(clean_text)]
        abm.message_str = clean_text
        abm.raw_message = {"source": "vtuber_buddy_web", "request_id": request_id}

        event = BuddyPlatformEvent(
            message_str=clean_text,
            message_obj=abm,
            platform_meta=self.metadata,
            session_id=session_id,
            queue_mgr=self.queue_mgr,
            request_id=request_id,
        )
        event.set_extra("enable_streaming", False)
        event.set_extra("request_id", request_id)

        if selected_provider:
            event.set_extra("selected_provider", selected_provider)
        if selected_model:
            event.set_extra("selected_model", selected_model)
        if extras:
            for key, value in extras.items():
                event.set_extra(key, value)

        self.commit_event(event)

    async def send_by_session(
        self,
        session: MessageSesion,
        message_chain: MessageChain,
    ) -> None:
        request_id = self.queue_mgr.get_latest_request_id(session.session_id)
        if request_id:
            queue = self.queue_mgr.get_or_create_back_queue(
                request_id, session.session_id
            )
            await queue.put(
                {
                    "type": "message",
                    "request_id": request_id,
                    "session_id": session.session_id,
                    "text": message_chain_to_text(message_chain),
                    "payload": None,
                    "streaming": False,
                }
            )
        else:
            logger.debug(
                "VTuber Buddy dropped proactive message for inactive session %s",
                session.session_id,
            )
        await super().send_by_session(session, message_chain)

    def handle_error(self, request_id: str, session_id: str, error: Exception) -> None:
        queue = self.queue_mgr.get_or_create_back_queue(request_id, session_id)
        queue.put_nowait(
            {
                "type": "error",
                "request_id": request_id,
                "session_id": session_id,
                "message": str(error),
                "traceback": traceback.format_exc(),
            }
        )
