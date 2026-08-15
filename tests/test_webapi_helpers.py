"""Tests for webapi pure helpers (envelope/payload builders)."""

from __future__ import annotations

from types import SimpleNamespace

from webapi import build_active_payload, validate_load_skill


def _skill(name: str) -> SimpleNamespace:
    return SimpleNamespace(
        name=name,
        description=f"desc-{name}",
        path=f"C:/skills/{name}/SKILL.md",
        source_type="local",
    )


def test_build_active_payload() -> None:
    persona = {"name": "default", "persona_id": "default"}
    payload = build_active_payload([_skill("a"), _skill("b")], persona)
    assert payload["persona"] == {"id": "default", "name": "default"}
    assert [s["name"] for s in payload["skills"]] == ["a", "b"]
    assert payload["skills"][0]["path"].endswith("SKILL.md")


def test_build_active_payload_no_persona() -> None:
    payload = build_active_payload([], None)
    assert payload["persona"] is None
    assert payload["skills"] == []


def test_validate_load_skill_ok() -> None:
    assert validate_load_skill([_skill("a")], "a") is None


def test_validate_load_skill_not_found() -> None:
    assert "not found" in validate_load_skill([_skill("a")], "zzz")


def test_validate_load_skill_missing_name() -> None:
    assert "missing" in validate_load_skill([_skill("a")], "")
