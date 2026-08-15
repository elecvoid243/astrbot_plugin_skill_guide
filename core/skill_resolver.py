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
