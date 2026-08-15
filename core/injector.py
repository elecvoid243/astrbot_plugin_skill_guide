"""One-shot guidance injection into the next LLM request."""

from __future__ import annotations

from typing import Any

from .guidance import build_guidance


def make_text_part(text: str) -> Any:
    """Build a provider-only ``TextPart`` (lazy import, monkeypatchable).

    Args:
        text: Guidance text.

    Returns:
        A ``TextPart`` marked ``_no_save`` so it never lands in history.
    """
    from astrbot.core.agent.message import TextPart

    return TextPart(text=text).mark_as_temp()


def inject_pending(
    state: Any,
    umo: str,
    req: Any,
    *,
    skills_by_name: dict[str, Any] | None = None,
) -> list[str]:
    """Drain the pending queue for ``umo`` and append guidance parts to ``req``.

    Pending names that cannot be resolved via ``skills_by_name`` (e.g. the
    skill became inactive meanwhile) are silently dropped; the queue is
    still drained (one-shot semantics).

    Args:
        state: ``GuideState`` instance.
        umo: Unified message origin of the session.
        req: ProviderRequest-like object exposing
            ``extra_user_content_parts`` list.
        skills_by_name: Map of skill name -> skill object (carries
            description/path for the guidance text).

    Returns:
        The list of skill names actually injected (empty when none).
    """
    pending = state.drain(umo)
    if not pending:
        return []
    by_name = skills_by_name or {}
    parts: list[Any] = []
    injected: list[str] = []
    for name in pending:
        skill = by_name.get(name)
        if skill is None:
            continue
        injected.append(name)
        parts.append(make_text_part(build_guidance(skill)))
    if parts:
        req.extra_user_content_parts.extend(parts)
    return injected
