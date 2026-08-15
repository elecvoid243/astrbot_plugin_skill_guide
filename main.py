"""astrbot_plugin_skill_guide — 手动"加载"skill 的引导注入插件。

前端通过 webapi 获取当前会话生效的 skill 列表并让用户点击；插件将
一段引导提示词注入到该会话下一次 LLM 请求的 extra_user_content_parts，
鼓励 LLM 使用该 skill（一次性语义，不改 persona / skill active 状态）。

Author: elecvoid243, 2026-08-15
"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import register

from .core import GuideState, inject_pending, resolve_active_skills
from .webapi import register_routes


@register(
    "astrbot_plugin_skill_guide",
    "elecvoid243",
    "Skill Guide — 前端点击 skill 后，向下一次 LLM 请求注入引导提示词，鼓励 LLM 使用该 skill（一次性）。",
    "1.0.0",
)
class SkillGuidePlugin(star.Star):
    """Skill Guide 插件主类。"""

    def __init__(
        self, context: star.Context, config: dict[str, Any] | None = None
    ) -> None:
        super().__init__(context)
        self.context = context
        self._state = GuideState()

    async def initialize(self) -> None:
        """插件激活后注册 webapi 路由。"""
        register_routes(self)

    @filter.on_llm_request()
    async def _inject_pending_guidance(
        self,
        event: Any,
        req: ProviderRequest,
    ) -> None:
        """一次性注入：drain 队列 → 把每个 skill 的引导追加到 req.extra_user_content_parts。

        Args:
            event: AstrBot 消息事件（取 unified_msg_origin）。
            req: 即将发送给 Provider 的请求对象，直接修改其字段。
        """
        try:
            umo = event.unified_msg_origin
            if not self._state.peek(umo):
                return
            skills, _ = await resolve_active_skills(self, umo)
            by_name = {skill.name: skill for skill in skills}
            inject_pending(self._state, umo, req, skills_by_name=by_name)
        except Exception as exc:  # noqa: BLE001 - never block the request
            logger.error(f"[skill_guide] injection failed: {exc}")

    async def terminate(self) -> None:
        """插件卸载时清空队列。"""
        self._state.clear_all()
