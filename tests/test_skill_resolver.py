"""Tests for core.skill_resolver pure filters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.skill_resolver import filter_by_persona, filter_plugin_skills


def _skill(name: str, source_type: str = "local", plugin_name: str = "") -> SimpleNamespace:
    return SimpleNamespace(name=name, source_type=source_type, plugin_name=plugin_name)


def _plugin_meta(root_dir: str, *, activated: bool = True, reserved: bool = False, name: str = "") -> SimpleNamespace:
    return SimpleNamespace(root_dir_name=root_dir, activated=activated, reserved=reserved, name=name)


@pytest.mark.parametrize(
    ("persona_skills", "expected"),
    [
        (None, ["a", "b", "c"]),          # unset -> all
        ([], []),                          # empty -> none
        (["a"], ["a"]),                    # whitelist
        (["a", "missing"], ["a"]),         # whitelist ignores unknown
    ],
)
def test_filter_by_persona(persona_skills, expected) -> None:
    skills = [_skill("a"), _skill("b"), _skill("c")]
    assert [s.name for s in filter_by_persona(skills, persona_skills)] == expected


def test_filter_plugin_skills_passes_non_plugin() -> None:
    skills = [_skill("local-one", "local"), _skill("workspace-one", "workspace")]
    assert filter_plugin_skills(skills, ["*"], []) == skills


def test_filter_plugin_skills_plugin_set_star() -> None:
    skills = [_skill("p1", "plugin", "plugin_a")]
    registry = [_plugin_meta("plugin_a", name="plugin_a")]
    assert filter_plugin_skills(skills, ["*"], registry) == skills


def test_filter_plugin_skills_plugin_set_named() -> None:
    skills = [_skill("p1", "plugin", "plugin_a"), _skill("p2", "plugin", "plugin_b")]
    registry = [
        _plugin_meta("plugin_a", name="plugin_a"),
        _plugin_meta("plugin_b", name="plugin_b"),
    ]
    result = filter_plugin_skills(skills, ["plugin_a"], registry)
    assert [s.name for s in result] == ["p1"]


def test_filter_plugin_skills_drops_inactive_plugin() -> None:
    skills = [_skill("p1", "plugin", "plugin_a")]
    registry = [_plugin_meta("plugin_a", activated=False, name="plugin_a")]
    assert filter_plugin_skills(skills, ["*"], registry) == []


def test_filter_plugin_skills_unknown_plugin_root_dropped() -> None:
    skills = [_skill("p1", "plugin", "no_such_root")]
    assert filter_plugin_skills(skills, ["*"], []) == []


def test_filter_plugin_skills_reserved_plugin_always_passes() -> None:
    skills = [_skill("p1", "plugin", "builtin_a")]
    registry = [_plugin_meta("builtin_a", reserved=True, name="builtin_a")]
    result = filter_plugin_skills(skills, ["some_other"], registry)
    assert [s.name for s in result] == ["p1"]
