from __future__ import annotations

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.astr_main_agent_resources import (
    TOOL_CALL_PROMPT,
    TOOL_CALL_PROMPT_SKILLS_LIKE_MODE,
)
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .vtuber_buddy.bridge import AstrBotMainChainBackend
from .vtuber_buddy.live2d_service import BuddyLive2DService
from .vtuber_buddy.platform import BUDDY_PLATFORM_NAME, BuddyPlatformAdapter
from .vtuber_buddy.queue_mgr import BuddyQueueManager
from .vtuber_buddy.service import (
    BuddyConversationService,
    buddy_reply_to_payload,
    coerce_buddy_reply,
)
from .vtuber_buddy.store import BuddyStore
from .vtuber_buddy.web import BuddyWebServer


class Main(Star):
    """VTuber Buddy plugin entry."""

    def __init__(self, context: Context, config=None) -> None:
        super().__init__(context)
        self.context = context
        self.config = config or {}

        plugin_data_dir = (
            Path(get_astrbot_plugin_data_path()) / "astrbot_plugin_vtuber_buddy"
        )
        plugin_root = Path(__file__).resolve().parent

        self.queue_mgr = BuddyQueueManager()
        self.platform_adapter = BuddyPlatformAdapter(
            platform_config={
                "type": BUDDY_PLATFORM_NAME,
                "enable": True,
                "id": BUDDY_PLATFORM_NAME,
            },
            event_queue=self.context.platform_manager.event_queue,
            queue_mgr=self.queue_mgr,
        )

        store = BuddyStore(plugin_data_dir / "sessions.json")
        chat_backend = AstrBotMainChainBackend(
            adapter=self.platform_adapter,
            configured_provider_id=str(self.config.get("chat_provider_id", "")).strip(),
            request_timeout_seconds=float(
                self.config.get("request_timeout_seconds", 60)
            ),
        )
        self.live2d_service = BuddyLive2DService(
            workspace_root=plugin_data_dir / "live2d_models",
            builtin_root=plugin_root / "vtuber_buddy" / "builtin_live2d",
        )

        self.service = BuddyConversationService(
            store=store,
            chat_backend=chat_backend,
            plugin_data_dir=plugin_data_dir,
            runtime_config=self.config,
            live2d_service=self.live2d_service,
        )
        self.web_server = BuddyWebServer(
            service=self.service,
            live2d_service=self.live2d_service,
            host=str(self.config.get("web_host", "127.0.0.1")),
            port=int(self.config.get("web_port", 6230)),
            template_dir=plugin_root / "vtuber_buddy" / "templates",
            static_dir=plugin_root / "vtuber_buddy" / "static",
        )

    async def initialize(self) -> None:
        await self.service.initialize()
        self._register_platform_instance()
        await self.web_server.start()

    async def terminate(self) -> None:
        await self.web_server.stop()
        await self.platform_adapter.terminate()
        self._remove_platform_instance()

    def _register_platform_instance(self) -> None:
        for platform in self.context.platform_manager.platform_insts:
            if platform.meta().id == self.platform_adapter.meta().id:
                return
        self.context.platform_manager.platform_insts.append(self.platform_adapter)
        self.platform_adapter.status = self.platform_adapter.status.__class__.RUNNING
        logger.info("VTuber Buddy platform adapter registered into platform_insts")

    def _remove_platform_instance(self) -> None:
        self.context.platform_manager.platform_insts = [
            platform
            for platform in self.context.platform_manager.platform_insts
            if platform is not self.platform_adapter
        ]

    @filter.on_llm_request()
    async def decorate_buddy_request(
        self,
        event: AstrMessageEvent,
        req: ProviderRequest,
    ) -> None:
        if event.get_platform_name() != BUDDY_PLATFORM_NAME:
            return

        prompt_context = event.get_extra("buddy_prompt_context", {})
        if not isinstance(prompt_context, dict):
            prompt_context = {}

        system_prompt = str(prompt_context.get("system_prompt", "")).strip()
        if system_prompt:
            req.system_prompt = "\n\n".join(
                part for part in [req.system_prompt.strip(), system_prompt] if part
            )

        for tool_prompt in (TOOL_CALL_PROMPT, TOOL_CALL_PROMPT_SKILLS_LIKE_MODE):
            req.system_prompt = req.system_prompt.replace(tool_prompt, "").strip()

        req.func_tool = None

    @filter.on_llm_response()
    async def capture_buddy_response(
        self,
        event: AstrMessageEvent,
        resp: LLMResponse,
    ) -> None:
        if event.get_platform_name() != BUDDY_PLATFORM_NAME:
            return

        parsed = coerce_buddy_reply(resp.completion_text or "")
        event.set_extra("buddy_structured_reply", buddy_reply_to_payload(parsed))
        resp.completion_text = parsed.reply

    @filter.command("buddy", alias={"vtuber_buddy", "伙伴"})
    async def buddy_entry(self, event: AstrMessageEvent):
        """Return the local VTuber Buddy URL."""
        yield event.plain_result(
            f"VTuber Buddy 已启动：{self.web_server.public_url}\n在浏览器中打开即可使用。"
        )

    @filter.command("buddy_status", alias={"伙伴状态"})
    async def buddy_status(self, event: AstrMessageEvent):
        """Show the current web service status."""
        server_status = "running" if self.web_server.is_running else "stopped"
        provider_label = self.service.chat_backend.describe()
        yield event.plain_result(
            f"VTuber Buddy 服务状态：{server_status}\n"
            f"地址：{self.web_server.public_url}\n"
            f"链路：{provider_label}"
        )
