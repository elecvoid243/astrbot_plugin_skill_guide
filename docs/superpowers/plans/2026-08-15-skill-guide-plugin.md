# Skill Guide Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `astrbot_plugin_skill_guide` — an AstrBot plugin whose webapi lists the skills effective in the current session and, on user click, queues a one-shot guidance nudge injected into the *next* LLM request's `extra_user_content_parts`.

**Architecture:** Standalone plugin repo at `F:\github\astrbot_plugin_skill_guide` (never touch the AstrBot main repo). Core logic is split into small pure modules (`guide_state`, `guidance`, `skill_resolver`, `injector`) that import nothing from `astrbot` at module scope so they are unit-testable standalone; `main.py` + `webapi.py` are thin glue with lazy `astrbot` imports. Injection goes through `@filter.on_llm_request()` → `req.extra_user_content_parts.append(TextPart(...).mark_as_temp())`, one-shot via a per-umo drain queue.

**Tech Stack:** Python 3.10+ (no third-party runtime deps), pytest (dev only), AstrBot 4.x star API (`register`, `Star`, `filter.on_llm_request`, `context.register_web_api`), `astrbot.core.agent.message.TextPart` (lazy import), `astrbot.core.skills.skill_manager.SkillManager` (lazy import), `astrbot.core.star.star.star_registry` (lazy import).

## Global Constraints

- Plugin lives in its own repo `F:\github\astrbot_plugin_skill_guide`; **never modify the AstrBot main repo** (`F:\github\Astrbot`).
- No third-party runtime dependencies (`requirements.txt` stays empty; `pytest` goes in `requirements-dev.txt`).
- Python 3.10+ compatible; comments and logs in **English**; Google-style docstrings.
- Author tag: `elecvoid243`; commits use conventional messages (`feat:`, `test:`, `docs:`, `chore:`).
- Injection targets `req.extra_user_content_parts` only — never `system_prompt`, never `set_skill_active`, never persona mutation.
- **One-shot semantics**: queue → drained (consumed) on the first `on_llm_request` for that umo.
- Route prefix `/skill-guide/*` (global route matching across all plugins).
- All webapi responses use the envelope `{"status": "ok", "data": {...}}` / `{"status": "error", "message": "..."}` with HTTP 200 (matches spcode convention).
- Skill resolution mirrors `astr_main_agent._ensure_persona_and_skills` exactly (runtime + `plugin_set` filter + persona `skills` whitelist); workspace skills are out of scope for v1 (documented limitation).

---

### Task 1: Repo scaffold + `GuideState` (TDD)

**Files:**
- Create: `.gitignore`
- Create: `requirements.txt`
- Create: `requirements-dev.txt`
- Create: `core/__init__.py`
- Create: `core/guide_state.py`
- Create: `tests/test_guide_state.py`

**Interfaces:**
- Consumes: nothing (repo is empty besides the design doc).
- Produces: `GuideState` with `queue(umo, skill_name) -> bool`, `drain(umo) -> list[str]`, `clear(umo) -> list[str]`, `peek(umo) -> list[str]`, `clear_all() -> None`.

- [ ] **Step 1: Create scaffold files**

`.gitignore`:

```gitignore
__pycache__/
*.py[cod]
.pytest_cache/
.venv/
dist/
build/
*.egg-info/
```

`requirements.txt`:

```text
# No third-party runtime dependencies for this plugin.
```

`requirements-dev.txt`:

```text
pytest>=7.0
```

`core/__init__.py`:

```python
"""Skill Guide plugin core package."""
```

- [ ] **Step 2: Write the failing test**

`tests/test_guide_state.py`:

```python
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
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_guide_state.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.guide_state'` (or `core`), collection error.

- [ ] **Step 4: Write minimal implementation**

`core/guide_state.py`:

```python
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
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_guide_state.py -v`
Expected: PASS (6 passed)

- [ ] **Step 6: Commit**

```bash
cd F:\github\astrbot_plugin_skill_guide
git add .
git commit -m "feat: add one-shot GuideState queue with tests"
```

---

### Task 2: Guidance text builder (TDD)

**Files:**
- Create: `core/guidance.py`
- Create: `tests/test_guidance.py`

**Interfaces:**
- Consumes: nothing (duck-typed `skill` with `.name` / `.description` / `.path` attributes — real `SkillInfo` satisfies this).
- Produces: `build_guidance(skill) -> str`.

- [ ] **Step 1: Write the failing test**

`tests/test_guidance.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_guidance.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.guidance'`

- [ ] **Step 3: Write minimal implementation**

`core/guidance.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_guidance.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add guidance prompt builder with tests"
```

---

### Task 3: Skill resolver — pure filters (TDD)

**Files:**
- Create: `core/skill_resolver.py`
- Create: `tests/test_skill_resolver.py`

**Interfaces:**
- Consumes: nothing astrbot-specific (all inputs duck-typed).
- Produces:
  - `filter_by_persona(skills: list, persona_skills: Any) -> list`
  - `filter_plugin_skills(skills: list, plugin_set: Any, star_registry: Iterable) -> list`

- [ ] **Step 1: Write the failing test**

`tests/test_skill_resolver.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_resolver.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.skill_resolver'`

- [ ] **Step 3: Write minimal implementation**

`core/skill_resolver.py`:

```python
"""Skill resolution for the current session.

Mirrors the skill-selection steps of ``astr_main_agent._ensure_persona_and_skills``
(runtime active skills -> plugin_set filter -> persona skills whitelist).
Only the pure filters live here; the async glue lives in
:func:`resolve_active_skills` (same module, lazy astrbot imports).
"""

from __future__ import annotations

from typing import Any, Iterable


def filter_by_persona(skills: list[Any], persona_skills: Any) -> list[Any]:
    """Apply the persona ``skills`` whitelist.

    Args:
        skills: Skill objects with a ``name`` attribute.
        persona_skills: ``None`` = all skills; ``[]`` = no skills;
            ``["a", ...]`` = only named skills.

    Returns:
        Filtered skill list.
    """
    if persona_skills is None:
        return list(skills)
    if not persona_skills:
        return []
    allowed = set(persona_skills)
    return [skill for skill in skills if skill.name in allowed]


def filter_plugin_skills(
    skills: list[Any],
    plugin_set: Any,
    star_registry: Iterable[Any],
) -> list[Any]:
    """Drop plugin-provided skills whose plugin is disabled or filtered.

    Local re-implementation of ``astr_main_agent._filter_skills_for_current_config``
    (avoids importing the whole main-agent module). ``star_registry`` is
    any iterable of plugin metadata objects exposing ``root_dir_name``,
    ``activated``, ``reserved`` and ``name``.

    Args:
        skills: Skill objects with ``source_type`` and ``plugin_name``.
        plugin_set: ``["*"]``/missing = allow all; else allowed plugin names.
        star_registry: Iterable of plugin metadata (pass ``star_registry``
            from ``astrbot.core.star.star`` at call site).

    Returns:
        Filtered skill list.
    """
    allowed_plugins: set[str] | None = None
    if isinstance(plugin_set, list) and "*" not in plugin_set:
        allowed_plugins = {str(name) for name in plugin_set}

    plugin_by_root_dir = {
        meta.root_dir_name: meta for meta in star_registry if getattr(meta, "root_dir_name", None)
    }

    filtered: list[Any] = []
    for skill in skills:
        if getattr(skill, "source_type", None) != "plugin":
            filtered.append(skill)
            continue
        plugin = plugin_by_root_dir.get(getattr(skill, "plugin_name", None))
        if not plugin or not plugin.activated:
            continue
        if plugin.reserved or allowed_plugins is None:
            filtered.append(skill)
            continue
        if plugin.name is not None and plugin.name in allowed_plugins:
            filtered.append(skill)
    return filtered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_resolver.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add persona and plugin_set skill filters with tests"
```

---

### Task 4: Skill resolver — async glue `resolve_active_skills` (TDD)

**Files:**
- Modify: `core/skill_resolver.py` (append `resolve_active_skills`)
- Modify: `tests/test_skill_resolver.py` (append glue tests)

**Interfaces:**
- Consumes: `filter_plugin_skills` / `filter_by_persona` (Task 3); fakes for `plugin.context`.
- Produces: `async def resolve_active_skills(plugin, umo: str, *, skill_manager=None, star_registry=None) -> tuple[list, Any | None]` — returns `(skills, persona)`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_skill_resolver.py`:

```python
import pytest

from core.skill_resolver import resolve_active_skills


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

    async def resolve_selected_persona(self, **kwargs):
        return (None, self._persona, None, False)


class _FakeSkillManager:
    def __init__(self, skills: list) -> None:
        self._skills = skills

    def list_skills(self, *, active_only: bool, runtime: str) -> list:
        assert active_only is True
        assert runtime == "local"
        return self._skills


class _FakeContext:
    def __init__(self, *, prov_settings: dict, conversation_manager, persona_manager) -> None:
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
        plugin, "webchat:FriendMessage:webchat!astrbot!x",
        skill_manager=_FakeSkillManager(skills),
        star_registry=[],
    )
    # The glue must have resolved conversation persona -> persona whitelist applied
    assert [s.name for s in result] == ["a"]
```

Note: `pytest-asyncio` is required for `@pytest.mark.asyncio`.

- [ ] **Step 1b: Add the dev dependency**

Update `requirements-dev.txt`:

```text
pytest>=7.0
pytest-asyncio>=0.23
```

Then install:

```bash
python -m pip install -r requirements-dev.txt
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skill_resolver.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_active_skills'`

- [ ] **Step 3: Write minimal implementation**

Append to `core/skill_resolver.py`:

```python
async def resolve_active_skills(
    plugin: Any,
    umo: str,
    *,
    skill_manager: Any = None,
    star_registry: Iterable[Any] | None = None,
) -> tuple[list[Any], Any | None]:
    """Resolve the skills effective for ``umo`` (mirrors the main agent).

    Steps:
    1. provider settings from ``plugin.context.get_config(umo)``
    2. ``SkillManager().list_skills(active_only=True, runtime=runtime)``
    3. ``filter_plugin_skills`` with ``cfg.plugin_set``
    4. conversation-level ``persona_id`` via ``conversation_manager``
    5. ``persona_manager.resolve_selected_persona(...)``
    6. ``filter_by_persona`` with the resolved persona's ``skills``

    Args:
        plugin: The Star instance (exposes ``context``).
        umo: Unified message origin of the session.
        skill_manager: Optional injected skill manager (defaults to
            ``SkillManager()`` via lazy import).
        star_registry: Optional injected registry (defaults to
            ``astrbot.core.star.star.star_registry`` via lazy import).

    Returns:
        Tuple of ``(skills, persona)``; ``persona`` is None when the
        session resolves to no persona (webchat default included).
    """
    if skill_manager is None:
        from astrbot.core.skills.skill_manager import SkillManager

        skill_manager = SkillManager()
    if star_registry is None:
        from astrbot.core.star.star import star_registry

    cfg_obj = plugin.context.get_config(umo=umo)
    prov_settings = cfg_obj.get("provider_settings", {}) or {}
    runtime = prov_settings.get("computer_use_runtime", "local")

    skills = skill_manager.list_skills(active_only=True, runtime=runtime)
    skills = filter_plugin_skills(
        skills,
        prov_settings.get("plugin_set", ["*"]),
        star_registry,
    )

    conversation_persona_id: str | None = None
    try:
        conv_mgr = plugin.context.conversation_manager
        cid = await conv_mgr.get_curr_conversation_id(umo)
        if cid:
            conv = await conv_mgr.get_conversation(umo, cid)
            conversation_persona_id = getattr(conv, "persona_id", None) or None
    except Exception:  # noqa: BLE001 - persona lookup must never break the API
        conversation_persona_id = None

    platform_name = (umo.split(":", 1)[0] if umo else "") or "webchat"
    _, persona, _, _ = await plugin.context.persona_manager.resolve_selected_persona(
        umo=umo,
        conversation_persona_id=conversation_persona_id,
        platform_name=platform_name,
        provider_settings=prov_settings,
    )
    persona_skills = persona.get("skills") if persona else None
    skills = filter_by_persona(skills, persona_skills)
    return skills, persona
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skill_resolver.py -v`
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add session skill resolution glue with tests"
```

---

### Task 5: One-shot injector (TDD)

**Files:**
- Create: `core/injector.py`
- Create: `tests/test_injector.py`

**Interfaces:**
- Consumes: `GuideState.drain` (Task 1), `build_guidance` (Task 2).
- Produces: `make_text_part(text: str) -> Any` (lazy `TextPart` factory, monkeypatchable), `inject_pending(state, umo: str, req, *, skills_by_name: dict | None = None) -> list[str]` — drains the queue, resolves each pending name via `skills_by_name`, appends one `TextPart` per resolvable skill, returns the injected names.

- [ ] **Step 1: Write the failing test**

`tests/test_injector.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_injector.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'core.injector'`

- [ ] **Step 3: Write minimal implementation**

`core/injector.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_injector.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add one-shot guidance injector with tests"
```

---

### Task 6: WebAPI routes + pure payload helpers (TDD for pure parts)

**Files:**
- Create: `webapi.py`
- Create: `tests/test_webapi_helpers.py`

**Interfaces:**
- Consumes: `resolve_active_skills` (Task 4), `GuideState` (Task 1).
- Produces:
  - `build_active_payload(skills, persona) -> dict`
  - `validate_load_skill(active_skills, skill_name) -> str | None` (error message or None)
  - `register_routes(plugin) -> None`

- [ ] **Step 1: Write the failing test**

`tests/test_webapi_helpers.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_webapi_helpers.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'webapi'`

- [ ] **Step 3: Write minimal implementation**

`webapi.py`:

```python
"""WebAPI endpoints for the Skill Guide plugin.

Routes (namespace ``/skill-guide/*`` to avoid global route collisions):

- GET  ``/skill-guide/active`` — active skills for a session
- POST ``/skill-guide/load``   — queue a one-shot skill nudge
- POST ``/skill-guide/clear``  — drop queued nudges for a session

Handlers are adapted to the framework ``view_handler`` interface by
:func:`_wrap` (reads query/body from ``astrbot.api.web.request``),
mirroring the spcode plugin's webapi pattern.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from .core.guide_state import GuideState
from .core.skill_resolver import resolve_active_skills


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


async def _handle_load(plugin: Any, *, umo: str | None = None, body: dict | None = None) -> dict:
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


async def _handle_clear(plugin: Any, *, umo: str | None = None, body: dict | None = None) -> dict:
    if not umo:
        return _error("missing umo")
    cleared = plugin._state.clear(umo)
    return _ok({"cleared": cleared})


ROUTES: list[tuple[str, list[str], Callable, str]] = [
    ("/skill-guide/active", ["GET"], _handle_active, "获取当前会话生效的 skill 列表(供前端渲染)"),
    ("/skill-guide/load", ["POST"], _handle_load, "为当前会话排队一次性 skill 引导注入"),
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_webapi_helpers.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add .
git commit -m "feat: add skill-guide webapi routes with pure helper tests"
```

---

### Task 7: Plugin entry (`main.py`) + metadata + README + final checks

**Files:**
- Create: `main.py`
- Create: `metadata.yaml`
- Create: `README.md`
- Modify: `core/__init__.py` (export public symbols)

**Interfaces:**
- Consumes: `GuideState`, `resolve_active_skills`, `inject_pending`, `register_routes`, `build_guidance`.
- Produces: loadable AstrBot plugin (`@register` Star).

- [ ] **Step 1: Write the implementation**

`core/__init__.py` (replace):

```python
"""Skill Guide plugin core package."""

from .guide_state import GuideState
from .guidance import build_guidance
from .injector import inject_pending
from .skill_resolver import resolve_active_skills

__all__ = [
    "GuideState",
    "build_guidance",
    "inject_pending",
    "resolve_active_skills",
]
```

`main.py`:

```python
"""astrbot_plugin_skill_guide — 手动"加载"skill 的引导注入插件。

前端通过 webapi 获取当前会话生效的 skill 列表并让用户点击；插件将
一段引导提示词注入到该会话下一次 LLM 请求的 extra_user_content_parts，
鼓励 LLM 使用该 skill（一次性语义，不改 persona / skill active 状态）。

Author: elecvoid243, 2026-08-15
"""

from __future__ import annotations

from typing import Any

from astrbot.api import logger, star
from astrbot.api.event import filter
from astrbot.api.provider import ProviderRequest
from astrbot.api.star import register

from .core import GuideState, inject_pending, resolve_active_skills
from .webapi import register_routes


@register(
    "astrbot_plugin_skill_guide",
    "elecvoid243",
    "Skill Guide — 前端点击 skill 后，向下一次 LLM 请求注入引导提示词，鼓励 LLM 使用该 skill（一次性）。",
    "1.0.0",
)
class SkillGuidePlugin(star.Star):
    """Skill Guide 插件主类。"""

    def __init__(self, context: star.Context, config: dict[str, Any] | None = None) -> None:
        super().__init__(context)
        self.context = context
        self._state = GuideState()

    async def initialize(self) -> None:
        """插件激活后注册 webapi 路由。"""
        register_routes(self)

    @filter.on_llm_request()
    async def _inject_pending_guidance(
        self,
        event: Any,
        req: ProviderRequest,
    ) -> None:
        """一次性注入：drain 队列 → 把每个 skill 的引导追加到 req.extra_user_content_parts。

        Args:
            event: AstrBot 消息事件（取 unified_msg_origin）。
            req: 即将发送给 Provider 的请求对象，直接修改其字段。
        """
        umo = event.unified_msg_origin
        if not self._state.peek(umo):
            return
        try:
            skills, _ = await resolve_active_skills(self, umo)
            by_name = {skill.name: skill for skill in skills}
            inject_pending(self._state, umo, req, skills_by_name=by_name)
        except Exception as exc:  # noqa: BLE001 - never block the request
            logger.error(f"[skill_guide] injection failed: {exc}")

    async def terminate(self) -> None:
        """插件卸载时清空队列。"""
        self._state.clear_all()
```

Note: the hook peeks first (cheap no-op when queue empty), resolves pending names → skill objects via `resolve_active_skills` (so guidance carries description/path), then calls `inject_pending`, which drains the queue and injects only the resolvable skills. If a skill became inactive between click and request, its name is silently dropped (still consumed).

`metadata.yaml`:

```yaml
name: astrbot_plugin_skill_guide
display_name: skill_guide
desc: 手动"加载"skill——前端点击后，向下一次 LLM 请求注入引导提示词，鼓励 LLM 使用该 skill（一次性，不改 persona/active 状态）。
version: v1.0.0
author: elecvoid243
repo: https://github.com/elecvoid243/astrbot_plugin_skill_guide
astrbot_version: ">=4.16,<5"
```

`README.md`:

```markdown
# astrbot_plugin_skill_guide

手动"加载"skill：前端列出当前会话生效的 skill，用户点击后，插件将一段引导提示词
注入到该会话**下一次** LLM 请求的 `extra_user_content_parts`，鼓励 LLM 使用该 skill。

- 一次性语义：注入后自动清除（下下次请求不再生效）
- 只注入引导，**不修改** persona、**不修改** skill 全局 active 状态
- 独立 webapi，供 Dashboard 前端调用（`pluginExtensionApi`）

## 安装

将本目录放入 AstrBot `data/plugins/` 后重启，或在插件商店安装。

## WebAPI 契约

| 方法 | 路径 | 参数 | 说明 |
|---|---|---|---|
| GET | `/skill-guide/active` | query `umo` | 当前会话生效的 skill 列表（含 persona） |
| POST | `/skill-guide/load` | body `{umo, skill_name}` | 排队一次性引导注入 |
| POST | `/skill-guide/clear` | body `{umo}` | 清空未消费队列 |

前端调用示例（axios，`pluginExtensionApi` 基址已配置好）：

```ts
// 获取活跃 skill
const res = await pluginExtensionApi.get('skill-guide/active', { params: { umo } });
// res.data.data = { persona: {id,name}|null, skills: [{name,description,path,source_type}] }

// 加载 skill
await pluginExtensionApi.post('skill-guide/load', { umo, skill_name: 'brainstorming' });
// res.data.data = { skill_name, queued: true }

// 撤销
await pluginExtensionApi.post('skill-guide/clear', { umo });
// res.data.data = { cleared: ['brainstorming'] }
```

错误响应统一为 `{ status: 'error', message }`（HTTP 200）。

## 前端建议

1. 会话挂载时调用 `/skill-guide/active` 渲染列表；会话切换后重新拉取
2. 点击 skill → `/skill-guide/load`，提示"将在下一条消息生效"
3. 可选"撤销"按钮 → `/skill-guide/clear`

## 限制（v1）

- 仅展示**当前会话生效**的 skill（全局 active + 人格白名单过滤结果）；
  不含 workspace skills
- 队列仅存内存，重启即清空（一次性语义下可接受）

## 开发

```bash
python -m pip install -r requirements-dev.txt   # pytest / pytest-asyncio
python -m pytest tests/ -v
```

## License

MIT
```

- [ ] **Step 2: Syntax/style check**

Run: `python -m compileall main.py webapi.py core tests`
Expected: no output (all compile)

Then run `ruff check .` and `ruff format .` if ruff is available in the environment (otherwise use the agent's `code_check`/`code_format` tools on each Python file).

- [ ] **Step 3: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: PASS (6 + 3 + 12 + 3 + 5 = 29 passed)

- [ ] **Step 4: Commit**

```bash
git add .
git commit -m "feat: wire plugin entry, metadata and README"
```

---

## Self-Review Notes

- **Spec coverage:** §4.1→Task 1 (GuideState); §4.3→Task 2 (guidance); §4.2 pure filters→Task 3, glue→Task 4; §4.5→Task 5 (injector); §4.4→Task 6 (webapi); plugin scaffold/metadata/README→Task 7. All design decisions D1–D7 are honored (one-shot drain; extra_user_content_parts only; `/skill-guide/*` prefix; no persona/active mutation; English guidance).
- **Type consistency:** `GuideState.queue/drain/clear/peek/clear_all` used identically across Tasks 1/5/6/7; `build_guidance` (Task 2) consumed by Task 5; `filter_plugin_skills`/`filter_by_persona` (Task 3) consumed by Task 4; `resolve_active_skills` returns `(skills, persona)` everywhere (Tasks 4/6/7); `inject_pending(state, umo, req, *, skills_by_name=...)` consistent between Task 5 (definition) and Task 7 (hook call).
- **Known deviation from spec §4.5 sketch:** the hook resolves pending *names* back to skill objects via `skills_by_name` before injection (so guidance carries description/path), and unresolvable names are silently dropped; one-shot semantics preserved (drain inside `inject_pending`). This is an implementation refinement, not a contract change.
