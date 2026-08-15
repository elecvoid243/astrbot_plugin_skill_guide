"""Tests for core.guide_state.GuideState (one-shot pending queue)."""

from __future__ import annotations

import threading

import pytest

from core.guide_state import GuideState


def test_queue_deduplicates_per_umo() -> None:
    state = GuideState()
    assert state.queue("umo-a", "brainstorming") is True
    assert state.queue("umo-a", "brainstorming") is False  # dedupe
    assert state.queue("umo-a", "pdf") is True
    assert state.peek("umo-a") == ["brainstorming", "pdf"]


def test_drain_is_one_shot() -> None:
    state = GuideState()
    state.queue("umo-a", "brainstorming")
    assert state.drain("umo-a") == ["brainstorming"]
    assert state.drain("umo-a") == []  # consumed
    assert state.peek("umo-a") == []


def test_drain_unknown_umo_returns_empty() -> None:
    assert GuideState().drain("nope") == []


def test_clear_returns_and_removes_pending() -> None:
    state = GuideState()
    state.queue("umo-a", "pdf")
    state.queue("umo-a", "spreadsheets")
    assert state.clear("umo-a") == ["pdf", "spreadsheets"]
    assert state.peek("umo-a") == []


def test_clear_all() -> None:
    state = GuideState()
    state.queue("umo-a", "pdf")
    state.queue("umo-b", "documents")
    state.clear_all()
    assert state.peek("umo-a") == []
    assert state.peek("umo-b") == []


def test_concurrent_queue_and_drain_are_thread_safe() -> None:
    state = GuideState()
    errors: list[Exception] = []
    barrier = threading.Barrier(4)

    def worker(name: str) -> None:
        try:
            barrier.wait()
            for i in range(100):
                state.queue("umo-a", f"{name}-{i}")
        except Exception as exc:  # pragma: no cover - defensive
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(f"w{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    # 4 workers x 100 unique names, deduped
    assert len(state.peek("umo-a")) == 400
    assert len(state.drain("umo-a")) == 400
