"""Per-umo one-shot pending skill queue.

Each queued skill is consumed (drained) by the *first* ``on_llm_request``
hook for that umo, matching the design decision D1 (one-shot injection).
"""

from __future__ import annotations

import threading


class GuideState:
    """Thread-safe per-umo queue of skill names waiting to be nudged."""

    def __init__(self) -> None:
        self._pending: dict[str, list[str]] = {}
        self._lock = threading.Lock()

    def queue(self, umo: str, skill_name: str) -> bool:
        """Queue ``skill_name`` for ``umo`` (deduplicated).

        Args:
            umo: Unified message origin of the session.
            skill_name: Skill name to nudge on the next request.

        Returns:
            True if newly queued, False if already pending.
        """
        with self._lock:
            pending = self._pending.setdefault(umo, [])
            if skill_name in pending:
                return False
            pending.append(skill_name)
            return True

    def drain(self, umo: str) -> list[str]:
        """Pop and clear all pending skills for ``umo`` (one-shot consumption).

        Args:
            umo: Unified message origin of the session.

        Returns:
            List of queued skill names (empty if none).
        """
        with self._lock:
            return self._pending.pop(umo, [])

    def clear(self, umo: str) -> list[str]:
        """Remove pending skills for ``umo`` without consuming them.

        Args:
            umo: Unified message origin of the session.

        Returns:
            List of removed skill names (empty if none).
        """
        with self._lock:
            return self._pending.pop(umo, [])

    def peek(self, umo: str) -> list[str]:
        """Return a copy of pending skills for ``umo`` without consuming.

        Args:
            umo: Unified message origin of the session.

        Returns:
            List of currently pending skill names.
        """
        with self._lock:
            return list(self._pending.get(umo, []))

    def clear_all(self) -> None:
        """Drop all pending queues (called on plugin terminate)."""
        with self._lock:
            self._pending.clear()
