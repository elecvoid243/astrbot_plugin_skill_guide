"""WebAPI endpoints for the Skill Guide plugin.

Routes (namespace ``/skill-guide/*`` to avoid global route collisions):

- GET  ``/skill-guide/active`` -- active skills for a session
- POST ``/skill-guide/load``   -- queue a one-shot skill nudge
- POST ``/skill-guide/clear``  -- drop queued nudges for a session

Handlers are adapted to the framework ``view_handler`` interface by
:func:`_wrap` (reads query/body from ``astrbot.api.web.request``),
mirroring the spcode plugin's webapi pattern.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

try:  # imported as a package module (AstrBot plugin runtime)
    from .core.guide_state import GuideState
    from .core.skill_resolver import resolve_active_skills
except ImportError:  # imported standalone as a top-level module (tests)
    from core.guide_state import GuideState
    from core.skill_resolver import resolve_active_skills


def build_active_payload(skills: list[Any], persona: Any | None) -> dict:
    """Build the ``data`` payload for GET /skill-guide/active.

    Args:
        skills: Resolved skill objects (``name``/``description``/``path``/``source_type``).
        persona: Resolved persona dict or None.

    Returns:
        Payload with ``persona`` and serialized ``skills`` list.
    """
    return {
        "persona": (
            {"id": persona.get("persona_id"), "name": persona.get("name")}
            if persona
            else None
        ),
        "skills": [
            {
                "name": skill.name,
                "description": skill.description,
                "path": skill.path,
                "source_type": skill.source_type,
            }
            for skill in skills
        ],
    }


def validate_load_skill(active_skills: list[Any], skill_name: str) -> str | None:
    """Validate a skill-load request against the session-active skills.

    Args:
        active_skills: Skills effective for the session.
        skill_name: Requested skill name.

    Returns:
        Error message string, or None when valid.
    """
    name = (skill_name or "").strip()
    if not name:
        return "missing skill_name"
    if not any(s.name == name for s in active_skills):
        return f"skill not found or not active in this session: {name}"
    return None


def _wrap(handler: Callable, plugin: Any) -> Callable:
    """Adapt ``handler(plugin, *, umo=..., body=...)`` to the view interface."""
    sig = inspect.signature(handler)
    accepts = set(sig.parameters) - {"plugin"}

    async def view(*_args: Any, **_kwargs: Any) -> Any:
        from astrbot.api import web

        is_post = web.request.method == "POST"
        body: dict = {}
        if is_post and (accepts & {"umo", "body"}):
            body = (await web.request.json(default={})) or {}

        call_kwargs: dict[str, Any] = {}
        if "umo" in accepts:
            if is_post:
                call_kwargs["umo"] = body.get("umo")
            else:
                call_kwargs["umo"] = web.request.query.get("umo") or None
        if "body" in accepts:
            call_kwargs["body"] = body
        return await handler(plugin, **call_kwargs)

    return view


def _error(message: str) -> dict:
    return {"status": "error", "message": message}


def _ok(data: dict) -> dict:
    return {"status": "ok", "data": data}


async def _handle_active(plugin: Any, *, umo: str | None = None) -> dict:
    if not umo:
        return _error("missing umo")
    try:
        skills, persona = await resolve_active_skills(plugin, umo)
        return _ok(build_active_payload(skills, persona))
    except Exception as exc:  # noqa: BLE001 - never crash the API
        return _error(f"resolve failed: {exc}")


async def _handle_load(
    plugin: Any, *, umo: str | None = None, body: dict | None = None
) -> dict:
    if not umo:
        return _error("missing umo")
    body = body or {}
    skill_name = str(body.get("skill_name") or "").strip()
    if not skill_name:
        return _error("missing skill_name")
    try:
        skills, _ = await resolve_active_skills(plugin, umo)
    except Exception as exc:  # noqa: BLE001
        return _error(f"resolve failed: {exc}")
    err = validate_load_skill(skills, skill_name)
    if err:
        return _error(err)
    state: GuideState = plugin._state
    state.queue(umo, skill_name)
    return _ok({"skill_name": skill_name, "queued": True})


async def _handle_clear(
    plugin: Any, *, umo: str | None = None, body: dict | None = None
) -> dict:
    if not umo:
        return _error("missing umo")
    cleared = plugin._state.clear(umo)
    return _ok({"cleared": cleared})


ROUTES: list[tuple[str, list[str], Callable, str]] = [
    (
        "/skill-guide/active",
        ["GET"],
        _handle_active,
        "获取当前会话生效的 skill 列表(供前端渲染)",
    ),
    (
        "/skill-guide/load",
        ["POST"],
        _handle_load,
        "为当前会话排队一次性 skill 引导注入",
    ),
    ("/skill-guide/clear", ["POST"], _handle_clear, "清空当前会话未消费的引导队列"),
]


def register_routes(plugin: Any) -> None:
    """Register all ``/skill-guide/*`` routes on ``plugin.context``.

    Args:
        plugin: The Star instance (must expose ``context`` and ``_state``).
    """
    for route, methods, handler, desc in ROUTES:
        plugin.context.register_web_api(
            route=route,
            view_handler=_wrap(handler, plugin),
            methods=methods,
            desc=desc,
        )
