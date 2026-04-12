from __future__ import annotations

from pathlib import Path

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star
from astrbot.core.provider.provider import Provider
from astrbot.core.utils.astrbot_path import get_astrbot_plugin_data_path

from .vtuber_buddy.llm import AstrBotModelClient, FallbackModelClient
from .vtuber_buddy.service import BuddyConversationService
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

        store = BuddyStore(plugin_data_dir / "sessions.json")
        model_client = self._build_model_client()

        self.service = BuddyConversationService(
            store=store,
            model_client=model_client,
            plugin_data_dir=plugin_data_dir,
            runtime_config=self.config,
        )
        self.web_server = BuddyWebServer(
            service=self.service,
            host=str(self.config.get("web_host", "127.0.0.1")),
            port=int(self.config.get("web_port", 6230)),
            template_dir=plugin_root / "vtuber_buddy" / "templates",
            static_dir=plugin_root / "vtuber_buddy" / "static",
        )

    def _build_model_client(self):
        configured_provider_id = str(self.config.get("chat_provider_id", "")).strip()
        provider = None
        if configured_provider_id:
            provider = self.context.get_provider_by_id(configured_provider_id)
            if provider is None:
                logger.warning(
                    "VTuber Buddy provider %s not found, falling back to default provider.",
                    configured_provider_id,
                )

        if provider is None:
            provider = self.context.get_using_provider()

        if isinstance(provider, Provider):
            return AstrBotModelClient(
                context=self.context,
                provider=provider,
                configured_provider_id=configured_provider_id or provider.meta().id,
                inherit_default_persona=bool(
                    self.config.get("inherit_default_persona", True)
                ),
            )

        logger.warning(
            "VTuber Buddy cannot find an available AstrBot chat provider. Rule-based fallback is enabled."
        )
        return FallbackModelClient()

    async def initialize(self):
        await self.service.initialize()
        await self.web_server.start()

    async def terminate(self):
        await self.web_server.stop()

    @filter.command("buddy", alias={"vtuber_buddy", "伙伴"})
    async def buddy_entry(self, event: AstrMessageEvent):
        """Return the local VTuber Buddy URL."""
        yield event.plain_result(
            f"VTuber Buddy 已启动：{self.web_server.public_url}\n在浏览器打开即可使用。"
        )

    @filter.command("buddy_status", alias={"伙伴状态"})
    async def buddy_status(self, event: AstrMessageEvent):
        """Show the current web service status."""
        server_status = "running" if self.web_server.is_running else "stopped"
        provider_label = self.service.model_client.describe()
        yield event.plain_result(
            f"VTuber Buddy 服务状态：{server_status}\n"
            f"地址：{self.web_server.public_url}\n"
            f"模型来源：{provider_label}"
        )
