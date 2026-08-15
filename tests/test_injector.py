"""Tests for core.injector.inject_pending (one-shot extra-content injection)."""

from __future__ import annotations

from types import SimpleNamespace

from core.guide_state import GuideState
from core import injector


class _FakeReq:
    def __init__(self) -> None:
        self.extra_user_content_parts: list[str] = []


def _skill(name: str) -> SimpleNamespace:
    return SimpleNamespace(name=name, description=f"desc-{name}", path=f"C:/s/{name}/SKILL.md")


def test_inject_pending_drains_and_appends(monkeypatch) -> None:
    state = GuideState()
    state.queue("umo-a", "brainstorming")
    state.queue("umo-a", "pdf")
    req = _FakeReq()
    by_name = {"brainstorming": _skill("brainstorming"), "pdf": _skill("pdf")}
    monkeypatch.setattr(injector, "make_text_part", lambda text: f"[part:{text}]")

    injected = injector.inject_pending(state, "umo-a", req, skills_by_name=by_name)

    assert injected == ["brainstorming", "pdf"]
    assert len(req.extra_user_content_parts) == 2
    assert all(p.startswith("[part:") for p in req.extra_user_content_parts)
    assert "brainstorming" in req.extra_user_content_parts[0]
    # one-shot: second call is a no-op
    assert injector.inject_pending(state, "umo-a", req) == []
    assert len(req.extra_user_content_parts) == 2


def test_inject_pending_unresolvable_skill_dropped() -> None:
    state = GuideState()
    state.queue("umo-a", "gone-skill")
    req = _FakeReq()
    # skill no longer active -> not in map -> silently dropped, still drained
    assert injector.inject_pending(state, "umo-a", req, skills_by_name={}) == []
    assert req.extra_user_content_parts == []
    assert state.peek("umo-a") == []


def test_inject_pending_empty_queue_noop() -> None:
    state = GuideState()
    req = _FakeReq()
    assert injector.inject_pending(state, "unknown-umo", req) == []
    assert req.extra_user_content_parts == []
