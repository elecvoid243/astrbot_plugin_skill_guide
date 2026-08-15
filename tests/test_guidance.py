"""Tests for core.guidance.build_guidance."""

from __future__ import annotations

from types import SimpleNamespace

from core.guidance import build_guidance


def _skill(**kwargs) -> SimpleNamespace:
    defaults = {
        "name": "brainstorming",
        "description": "Explores user intent before implementation.",
        "path": "C:/data/skills/brainstorming/SKILL.md",
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_renders_name_description_path() -> None:
    text = build_guidance(_skill())
    assert "brainstorming" in text
    assert "Explores user intent before implementation." in text
    assert "C:/data/skills/brainstorming/SKILL.md" in text


def test_empty_description_falls_back() -> None:
    text = build_guidance(_skill(description=""))
    assert "No description" in text


def test_empty_path_placeholder() -> None:
    text = build_guidance(_skill(path=""))
    assert "<skill_path>" in text
