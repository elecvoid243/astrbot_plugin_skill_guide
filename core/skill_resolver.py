"""Skill resolution for the current session.

Mirrors the skill-selection steps of ``astr_main_agent._ensure_persona_and_skills``
(runtime active skills -> plugin_set filter -> persona skills whitelist).
Only the pure filters live here; the async glue lives in
:func:`resolve_active_skills` (same module, lazy astrbot imports).
"""

from __future__ import annotations

from typing import Any, Iterable


def filter_by_persona(skills: list[Any], persona_skills: Any) -> list[Any]:
    """Apply the persona ``skills`` whitelist.

    Args:
        skills: Skill objects with a ``name`` attribute.
        persona_skills: ``None`` = all skills; ``[]`` = no skills;
            ``["a", ...]`` = only named skills.

    Returns:
        Filtered skill list.
    """
    if persona_skills is None:
        return list(skills)
    if not persona_skills:
        return []
    allowed = set(persona_skills)
    return [skill for skill in skills if skill.name in allowed]


def filter_plugin_skills(
    skills: list[Any],
    plugin_set: Any,
    star_registry: Iterable[Any],
) -> list[Any]:
    """Drop plugin-provided skills whose plugin is disabled or filtered.

    Local re-implementation of ``astr_main_agent._filter_skills_for_current_config``
    (avoids importing the whole main-agent module). ``star_registry`` is
    any iterable of plugin metadata objects exposing ``root_dir_name``,
    ``activated``, ``reserved`` and ``name``.

    Args:
        skills: Skill objects with ``source_type`` and ``plugin_name``.
        plugin_set: ``["*"]``/missing = allow all; else allowed plugin names.
        star_registry: Iterable of plugin metadata (pass ``star_registry``
            from ``astrbot.core.star.star`` at call site).

    Returns:
        Filtered skill list.
    """
    allowed_plugins: set[str] | None = None
    if isinstance(plugin_set, list) and "*" not in plugin_set:
        allowed_plugins = {str(name) for name in plugin_set}

    plugin_by_root_dir = {
        meta.root_dir_name: meta for meta in star_registry if getattr(meta, "root_dir_name", None)
    }

    filtered: list[Any] = []
    for skill in skills:
        if getattr(skill, "source_type", None) != "plugin":
            filtered.append(skill)
            continue
        plugin = plugin_by_root_dir.get(getattr(skill, "plugin_name", None))
        if not plugin or not plugin.activated:
            continue
        if plugin.reserved or allowed_plugins is None:
            filtered.append(skill)
            continue
        if plugin.name is not None and plugin.name in allowed_plugins:
            filtered.append(skill)
    return filtered


async def resolve_active_skills(
    plugin: Any,
    umo: str,
    *,
    skill_manager: Any = None,
    star_registry: Iterable[Any] | None = None,
) -> tuple[list[Any], Any | None]:
    """Resolve the skills effective for ``umo`` (mirrors the main agent).

    Steps:
    1. provider settings from ``plugin.context.get_config(umo)``
    2. ``SkillManager().list_skills(active_only=True, runtime=runtime)``
    3. ``filter_plugin_skills`` with ``cfg.plugin_set``
    4. conversation-level ``persona_id`` via ``conversation_manager``
    5. ``persona_manager.resolve_selected_persona(...)``
    6. ``filter_by_persona`` with the resolved persona's ``skills``

    Args:
        plugin: The Star instance (exposes ``context``).
        umo: Unified message origin of the session.
        skill_manager: Optional injected skill manager (defaults to
            ``SkillManager()`` via lazy import).
        star_registry: Optional injected registry (defaults to
            ``astrbot.core.star.star.star_registry`` via lazy import).

    Returns:
        Tuple of ``(skills, persona)``; ``persona`` is None when the
        session resolves to no persona (webchat default included).
    """
    if skill_manager is None:
        from astrbot.core.skills.skill_manager import SkillManager

        skill_manager = SkillManager()
    if star_registry is None:
        from astrbot.core.star.star import star_registry

    cfg_obj = plugin.context.get_config(umo=umo)
    prov_settings = cfg_obj.get("provider_settings", {}) or {}
    runtime = prov_settings.get("computer_use_runtime", "local")

    skills = skill_manager.list_skills(active_only=True, runtime=runtime)
    skills = filter_plugin_skills(
        skills,
        prov_settings.get("plugin_set", ["*"]),
        star_registry,
    )

    conversation_persona_id: str | None = None
    try:
        conv_mgr = plugin.context.conversation_manager
        cid = await conv_mgr.get_curr_conversation_id(umo)
        if cid:
            conv = await conv_mgr.get_conversation(umo, cid)
            conversation_persona_id = getattr(conv, "persona_id", None) or None
    except Exception:  # noqa: BLE001 - persona lookup must never break the API
        conversation_persona_id = None

    platform_name = (umo.split(":", 1)[0] if umo else "") or "webchat"
    _, persona, _, _ = await plugin.context.persona_manager.resolve_selected_persona(
        umo=umo,
        conversation_persona_id=conversation_persona_id,
        platform_name=platform_name,
        provider_settings=prov_settings,
    )
    persona_skills = persona.get("skills") if persona else None
    skills = filter_by_persona(skills, persona_skills)
    return skills, persona
