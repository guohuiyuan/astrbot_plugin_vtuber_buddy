from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from astrbot.api.star import Context
    from astrbot.core.provider.provider import Provider


class BuddyModelClient(Protocol):
    async def generate_reply(
        self,
        *,
        system_prompt: str,
        contexts: list[dict],
        user_message: str,
        session_id: str,
    ) -> str: ...

    def describe(self) -> str: ...


class AstrBotModelClient:
    """Bridge the buddy chat flow to AstrBot's configured chat provider."""

    def __init__(
        self,
        *,
        context: Context,
        provider: Provider,
        configured_provider_id: str,
        inherit_default_persona: bool,
    ) -> None:
        self.context = context
        self.provider = provider
        self.configured_provider_id = configured_provider_id
        self.inherit_default_persona = inherit_default_persona

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        contexts: list[dict],
        user_message: str,
        session_id: str,
    ) -> str:
        full_system_prompt = system_prompt
        if self.inherit_default_persona:
            default_persona = await self.context.persona_manager.get_default_persona_v3()
            base_prompt = default_persona.get("prompt", "").strip()
            if base_prompt:
                full_system_prompt = f"{base_prompt}\n\n{system_prompt}"

        response = await self.provider.text_chat(
            prompt=user_message,
            session_id=session_id,
            contexts=contexts,
            system_prompt=full_system_prompt,
        )
        return response.completion_text.strip()

    def describe(self) -> str:
        return f"AstrBot Provider: {self.configured_provider_id}"


class FallbackModelClient:
    """Rule-based fallback when no chat provider is configured."""

    async def generate_reply(
        self,
        *,
        system_prompt: str,
        contexts: list[dict],
        user_message: str,
        session_id: str,
    ) -> str:
        del system_prompt, contexts, session_id
        user_message = user_message.strip()
        if not user_message:
            return '{"reply":"我在听。","emotion":"neutral","motion":"idle","memory":""}'
        return (
            '{"reply":"先把 AstrBot 的聊天模型配置好，我就能认真陪你聊了。",'
            '"emotion":"concerned","motion":"nod","memory":""}'
        )

    def describe(self) -> str:
        return "Rule-based fallback"
