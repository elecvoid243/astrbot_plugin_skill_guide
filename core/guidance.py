"""Guidance prompt builder.

Produces a short English nudge (aligned with ``build_skills_prompt``
style: name + description + file path) that tells the LLM to use the
given skill for the current request.
"""

from __future__ import annotations

from typing import Any


def build_guidance(skill: Any) -> str:
    """Build the one-shot guidance text for a skill.

    Args:
        skill: Object exposing ``name``, ``description`` and ``path``
            attributes (duck-typed; ``SkillInfo`` works).

    Returns:
        English guidance paragraph instructing the LLM to use the skill.
    """
    name = str(getattr(skill, "name", "") or "")
    description = str(getattr(skill, "description", "") or "").strip()
    if not description:
        description = "No description"
    path = str(getattr(skill, "path", "") or "") or "<skill_path>"
    return (
        "[User skill request]\n"
        "The user explicitly asks you to use the following skill for this request:\n"
        f"- **{name}**: {description}\n"
        f"  File: `{path}`\n"
        "Read and follow its SKILL.md instructions before acting. Do not skip it."
    )
