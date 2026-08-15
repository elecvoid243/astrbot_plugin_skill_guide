"""Tests for core.skill_resolver pure filters."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.skill_resolver import (
    filter_by_persona,
    filter_plugin_skills,
    resolve_active_skills,
)


def _skill(
    name: str, source_type: str = "local", plugin_name: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(name=name, source_type=source_type, plugin_name=plugin_name)


def _plugin_meta(
    root_dir: str, *, activated: bool = True, reserved: bool = False, name: str = ""
) -> SimpleNamespace:
    return SimpleNamespace(
        root_dir_name=root_dir, activated=activated, reserved=reserved, name=name
    )


@pytest.mark.parametrize(
    ("persona_skills", "expected"),
    [
        (None, ["a", "b", "c"]),  # unset -> all
        ([], []),  # empty -> none
        (["a"], ["a"]),  # whitelist
        (["a", "missing"], ["a"]),  # whitelist ignores unknown
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


def test_filter_plugin_skills_plugin_set_none_allows_all() -> None:
    skills = [_skill("p1", "plugin", "plugin_a"), _skill("p2", "plugin", "plugin_b")]
    registry = [
        _plugin_meta("plugin_a", name="plugin_a"),
        _plugin_meta("plugin_b", name="plugin_b"),
    ]
    assert filter_plugin_skills(skills, None, registry) == skills


def test_filter_plugin_skills_plugin_name_none_dropped_under_named_set() -> None:
    skills = [_skill("p1", "plugin", "plugin_a")]
    registry = [_plugin_meta("plugin_a", name=None)]
    result = filter_plugin_skills(skills, ["plugin_a"], registry)
    assert result == []


class _FakeConversationManager:
    def __init__(self, persona_id: str | None) -> None:
        self._persona_id = persona_id

    async def get_curr_conversation_id(self, umo: str) -> str | None:
        return "conv-1" if umo else None

    async def get_conversation(self, umo: str, conversation_id: str):
        return SimpleNamespace(persona_id=self._persona_id)


class _FakePersonaManager:
    def __init__(self, persona: dict | None) -> None:
        self._persona = persona
        self.last_kwargs: dict | None = None

    async def resolve_selected_persona(self, **kwargs):
        self.last_kwargs = kwargs
        return (None, self._persona, None, False)


class _FakeSkillManager:
    def __init__(self, skills: list) -> None:
        self._skills = skills

    def list_skills(self, *, active_only: bool, runtime: str) -> list:
        assert active_only is True
        assert runtime == "local"
        return self._skills


class _FakeContext:
    def __init__(
        self, *, prov_settings: dict, conversation_manager, persona_manager
    ) -> None:
        self._prov = prov_settings
        self.conversation_manager = conversation_manager
        self.persona_manager = persona_manager

    def get_config(self, umo: str = None) -> dict:
        return {"provider_settings": self._prov}


class _FakePlugin:
    def __init__(self, context) -> None:
        self.context = context


@pytest.mark.asyncio
async def test_resolve_glue_applies_all_filters() -> None:
    skills = [
        _skill("local-a", "local"),
        _skill("plugin-b", "plugin", "plugin_b"),
        _skill("local-c", "local"),
    ]
    registry = [_plugin_meta("plugin_b", name="plugin_b")]
    ctx = _FakeContext(
        prov_settings={"computer_use_runtime": "local", "plugin_set": ["*"]},
        conversation_manager=_FakeConversationManager("p-default"),
        persona_manager=_FakePersonaManager({"skills": ["local-a"]}),
    )
    plugin = _FakePlugin(ctx)
    result, persona = await resolve_active_skills(
        plugin,
        "webchat:FriendMessage:webchat!astrbot!x",
        skill_manager=_FakeSkillManager(skills),
        star_registry=registry,
    )
    assert [s.name for s in result] == ["local-a"]
    assert persona == {"skills": ["local-a"]}


@pytest.mark.asyncio
async def test_resolve_glue_conversation_persona_id_passed() -> None:
    skills = [_skill("a", "local")]
    ctx = _FakeContext(
        prov_settings={},
        conversation_manager=_FakeConversationManager("conv-persona"),
        persona_manager=_FakePersonaManager({"skills": ["a"]}),
    )
    plugin = _FakePlugin(ctx)
    result, persona = await resolve_active_skills(
        plugin,
        "webchat:FriendMessage:webchat!astrbot!x",
        skill_manager=_FakeSkillManager(skills),
        star_registry=[],
    )
    # The glue must have resolved conversation persona -> persona whitelist applied
    assert [s.name for s in result] == ["a"]
    # And the conversation persona id must actually reach the persona manager
    assert ctx.persona_manager.last_kwargs is not None
    assert ctx.persona_manager.last_kwargs["conversation_persona_id"] == "conv-persona"
